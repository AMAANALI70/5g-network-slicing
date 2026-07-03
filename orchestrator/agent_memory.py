"""
agent_memory.py — Sliding Window Decision Memory
Stores the last N orchestrator decisions + outcomes.
Fed into the LLM prompt as few-shot context so it learns from recent history.
"""
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import json


@dataclass
class MemoryEntry:
    timestamp:          str
    rtt_ms:             float
    embb_rate:          int
    action:             str
    reasoning:          str
    confidence:         float
    root_cause:         str   = ""    # Phase 1: root_cause_assessment from LLM
    lever_valid:        str   = ""    # Phase 1: lever_validity from LLM
    embb_load_fraction: Optional[float] = None  # ρ at decision time (WLA key metric)
    rtt_after:          Optional[float] = None  # filled by reflect node
    success:            Optional[bool]  = None  # did RTT improve?

    def to_prompt_line(self) -> str:
        outcome = ""
        if self.rtt_after is not None:
            delta   = self.rtt_after - self.rtt_ms
            symbol  = "✅" if (self.success) else "❌"
            outcome = f" → RTT_after={self.rtt_after:.1f}ms ({delta:+.1f}ms) {symbol}"
        lf_str = f" ρ={self.embb_load_fraction:.2f}" if self.embb_load_fraction is not None else ""
        cause  = f" | cause: {self.root_cause[:60]}" if self.root_cause else ""
        return (
            f"  [{self.timestamp}] RTT={self.rtt_ms:.1f}ms{lf_str}"
            f" rate={self.embb_rate}Mbit → {self.action}"
            f" (conf={self.confidence:.2f}){outcome}{cause}"
        )

    def to_dict(self) -> dict:
        return {
            "timestamp":          self.timestamp,
            "rtt_ms":             self.rtt_ms,
            "embb_rate":          self.embb_rate,
            "action":             self.action,
            "reasoning":          self.reasoning,
            "confidence":         self.confidence,
            "root_cause":         self.root_cause,
            "lever_valid":        self.lever_valid,
            "embb_load_fraction": self.embb_load_fraction,
            "rtt_after":          self.rtt_after,
            "success":            self.success,
        }


class AgentMemory:
    """Thread-safe sliding window of recent decisions."""

    def __init__(self, maxlen: int = 10):
        self._q: deque[MemoryEntry] = deque(maxlen=maxlen)

    def record(self, rtt: float, embb_rate: int,
               action: str, reasoning: str, confidence: float,
               root_cause: str = "", lever_valid: str = "",
               embb_load_fraction: Optional[float] = None) -> int:
        """Add new entry. Returns its index (for later update)."""
        entry = MemoryEntry(
            timestamp          = datetime.now().strftime("%H:%M:%S"),
            rtt_ms             = round(rtt, 2),
            embb_rate          = embb_rate,
            action             = action,
            reasoning          = reasoning,
            confidence         = confidence,
            root_cause         = root_cause,
            lever_valid        = lever_valid,
            embb_load_fraction = embb_load_fraction,
        )
        self._q.append(entry)
        return len(self._q) - 1

    def update_outcome(self, rtt_after: float):
        """Update the most recent entry with post-action RTT."""
        if self._q:
            last = self._q[-1]
            last.rtt_after = round(rtt_after, 2)
            last.success   = rtt_after < last.rtt_ms

    def get_recent(self, n: int = 5) -> list[MemoryEntry]:
        """Return last N entries, newest first."""
        entries = list(self._q)
        return list(reversed(entries[-n:]))

    def format_for_prompt(self, n: int = 5) -> str:
        """Format recent decisions as a readable block for LLM context."""
        recent = self.get_recent(n)
        if not recent:
            return "  (no previous decisions this session)"
        return "\n".join(e.to_prompt_line() for e in recent)

    def get_stats(self) -> dict:
        """Summary stats for Prometheus export."""
        entries = list(self._q)
        if not entries:
            return {"total": 0, "success_rate": 0.0, "avg_confidence": 0.0}
        decided = [e for e in entries if e.success is not None]
        return {
            "total":          len(entries),
            "success_rate":   sum(1 for e in decided if e.success) / max(len(decided), 1),
            "avg_confidence": sum(e.confidence for e in entries) / len(entries),
        }

    def clear(self):
        """Flush all stored decisions. Call at experiment start to prevent cross-run contamination."""
        self._q.clear()

    def export_json(self) -> list[dict]:
        return [e.to_dict() for e in self._q]
