"""
State Agent — Maintains historical memory and detects patterns.
Does NOT execute actions.
"""

import time
from collections import deque
from config import (
    HISTORY_SIZE, URLLC_RTT_SLA_MS,
    OSCILLATION_WINDOW, OSCILLATION_THRESHOLD,
    STABILITY_WINDOW_SEC, LOOP_INTERVAL_SEC,
)


class StateAgent:
    """Stateful agent that tracks trends, violations, and oscillation."""

    def __init__(self):
        self.history = deque(maxlen=HISTORY_SIZE)
        self.action_history = deque(maxlen=20)
        self.violation_count = 0
        self.consecutive_stable = 0
        self.last_action_time = 0.0
        self.current_embb_rate = 100  # Mbit — start at max

    # ── Public API ────────────────────────────────────────────

    def update(self, metrics: dict) -> dict:
        """
        Ingest new metrics, update internal state, return state snapshot.
        """
        self.history.append(metrics)

        rtt = metrics.get("urllc_rtt_99", 0.0)
        rtt_trend = self._compute_rtt_trend()
        violating = rtt > URLLC_RTT_SLA_MS

        if violating:
            self.violation_count += 1
            self.consecutive_stable = 0
        else:
            self.consecutive_stable += 1

        stable_duration = self.consecutive_stable * LOOP_INTERVAL_SEC

        return {
            "rtt_trend": rtt_trend,
            "violation_count": self.violation_count,
            "stable_for": stable_duration,
            "oscillation": self._detect_oscillation(),
            "current_embb_rate": self.current_embb_rate,
            "last_action_time": self.last_action_time,
            "metrics": metrics,
        }

    def record_action(self, action: str, new_rate: int):
        """Record an executed action for oscillation detection."""
        self.action_history.append({
            "time": time.time(),
            "action": action,
            "rate": new_rate,
        })
        self.last_action_time = time.time()
        self.current_embb_rate = new_rate

    def record_outcome(self, outcome: dict):
        """Record execution outcome for feedback."""
        if outcome.get("success") and outcome.get("impact_rtt_change", 0) < 0:
            # Action helped — reset violation count partially
            self.violation_count = max(0, self.violation_count - 1)

    def reset_violations(self):
        """Reset after sustained stability."""
        self.violation_count = 0

    # ── Trend Detection ───────────────────────────────────────

    def _compute_rtt_trend(self) -> str:
        """Detect RTT trend: rising, stable, or falling."""
        if len(self.history) < 3:
            return "stable"

        recent = [m.get("urllc_rtt_99", 0) for m in list(self.history)[-5:]]
        if len(recent) < 3:
            return "stable"

        # Linear slope approximation
        diffs = [recent[i+1] - recent[i] for i in range(len(recent)-1)]
        avg_diff = sum(diffs) / len(diffs)

        if avg_diff > 0.2:
            return "rising"
        elif avg_diff < -0.2:
            return "falling"
        return "stable"

    # ── Oscillation Detection ─────────────────────────────────

    def _detect_oscillation(self) -> bool:
        """Detect rapid rate toggling (throttle/restore/throttle...)."""
        actions = list(self.action_history)[-OSCILLATION_WINDOW:]
        if len(actions) < OSCILLATION_WINDOW:
            return False

        direction_changes = 0
        for i in range(1, len(actions)):
            prev = actions[i-1]["action"]
            curr = actions[i]["action"]
            if prev != curr and curr != "no_action" and prev != "no_action":
                direction_changes += 1

        return direction_changes >= OSCILLATION_THRESHOLD
