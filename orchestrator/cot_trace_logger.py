"""
cot_trace_logger.py — Structured Chain-of-Thought Trace Logger
===============================================================
Appends one JSON line per LLM inference cycle to logs/cot_traces.jsonl.
Provides machine-readable audit trail for:
  - Wrong-Lever Avoidance validation
  - Behavioral audit (S1/S2/S3)
  - Decision latency analysis
  - Experiment record-keeping

Usage (from main.py):
    from cot_trace_logger import CoTTraceLogger
    trace_logger = CoTTraceLogger()
    trace_logger.log(cycle, metrics, state, decision, latency_components)
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("cot_trace")

# Traces written to logs/ next to this file
_LOG_DIR  = Path(__file__).parent / "logs"
_LOG_FILE = _LOG_DIR / "cot_traces.jsonl"


class CoTTraceLogger:
    """
    Appends one structured JSON line per LLM cycle.
    Thread-safe: uses an append-only file; no shared mutable state.
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path else _LOG_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)
        log.info(f"[CoTTrace] Writing traces to {self._path}")

    # ── Public API ────────────────────────────────────────────────────────────

    def log(
        self,
        cycle: int,
        metrics: dict,
        state: dict,
        decision: dict,
        latency: dict,
    ) -> None:
        """
        Write one trace record.

        Args:
            cycle:    LLM inference cycle number (1-indexed)
            metrics:  raw metrics dict from MonitoringAgent.collect()
            state:    state snapshot dict from StateAgent.update()
            decision: decision dict from LLMPlanningAgent.decide()
            latency:  {collect_ms, llm_ms, exec_ms, cycle_ms, recovery_latency_s}
        """
        record = self._build_record(cycle, metrics, state, decision, latency)
        try:
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            log.warning(f"[CoTTrace] Write failed: {e}")

    def load_all(self) -> list[dict]:
        """Return all records from the current trace file (for analysis)."""
        if not self._path.exists():
            return []
        records = []
        with open(self._path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return records

    def summarise(self) -> dict:
        """Quick summary stats over all logged cycles, including LLM usage and cost estimates."""
        records = self.load_all()
        if not records:
            return {"total_cycles": 0}

        wla_events   = [r for r in records if r.get("wrong_lever_event")]
        throttles    = [r for r in records if r.get("action") == "throttle_embb"]
        violations   = [r for r in records if r.get("sla_violated")]
        llm_used_recs = [r for r in records if r.get("llm_used")]

        llm_ms_vals  = [r.get("llm_ms", 0) for r in llm_used_recs if r.get("llm_ms", 0) > 0]
        lv_scores    = [r["lever_validity_score"] for r in records
                        if r.get("lever_validity_score") is not None]

        # Token totals
        total_prompt_tok  = sum(r.get("prompt_tokens", 0) for r in records)
        total_comp_tok    = sum(r.get("completion_tokens", 0) for r in records)
        total_tokens      = sum(r.get("total_tokens", 0) for r in records)
        tokens_per_dec    = total_tokens / max(len(llm_used_recs), 1)

        # LLM latency percentiles
        sorted_ms   = sorted(llm_ms_vals)
        p95_idx     = int(0.95 * len(sorted_ms))
        avg_llm_ms  = sum(sorted_ms) / len(sorted_ms) if sorted_ms else 0.0
        p95_llm_ms  = sorted_ms[p95_idx] if sorted_ms else 0.0
        max_llm_ms  = max(sorted_ms) if sorted_ms else 0.0

        # Memory coverage
        mem_with_history = sum(1 for r in records if r.get("memory_has_history", False))

        # Cost estimates (per-1M-token pricing, 2024 rates)
        # Using input/output split; Ollama is local ($0) but we estimate equivalent cost
        COSTS = {
            "gpt4_turbo":  {"in": 10.00, "out": 30.00},   # $/1M tokens
            "claude3_opus":{"in": 15.00, "out": 75.00},
            "groq_llama3": {"in":  0.59, "out":  0.79},
        }
        cost_estimates = {}
        for provider, rates in COSTS.items():
            cost = (total_prompt_tok * rates["in"] + total_comp_tok * rates["out"]) / 1_000_000
            cost_estimates[f"equiv_cost_{provider}_usd"] = round(cost, 4)

        summary = {
            "total_cycles":           len(records),
            "llm_calls":              len(llm_used_recs),
            "throttle_actions":       len(throttles),
            "restore_actions":        sum(1 for r in records if r.get("action")=="restore_embb"),
            "no_op_actions":          sum(1 for r in records if r.get("action")=="no_action"),
            "wla_events_caught":      len(wla_events),
            "wla_rate":               round(len(wla_events) / max(len(throttles), 1), 3),
            "sla_violations":         len(violations),
            # LLM latency
            "avg_llm_ms":             round(avg_llm_ms, 1),
            "p95_llm_ms":             round(p95_llm_ms, 1),
            "max_llm_ms":             round(max_llm_ms, 1),
            # Token metrics
            "total_prompt_tokens":    total_prompt_tok,
            "total_completion_tokens":total_comp_tok,
            "total_tokens":           total_tokens,
            "tokens_per_decision":    round(tokens_per_dec, 1),
            # Memory coverage
            "cycles_with_memory":     mem_with_history,
            "memory_coverage_pct":    round(100 * mem_with_history / max(len(records),1), 1),
            # WLA
            "avg_lever_validity":     round(sum(lv_scores)/len(lv_scores), 3) if lv_scores else None,
            # Timestamps
            "first_ts":               records[0].get("ts"),
            "last_ts":                records[-1].get("ts"),
        }
        summary.update(cost_estimates)
        return summary

    def rotate(self) -> Path:
        """Archive current file with timestamp suffix and start fresh."""
        if self._path.exists():
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            dst = self._path.with_suffix(f".{ts}.jsonl")
            self._path.rename(dst)
            log.info(f"[CoTTrace] Rotated: {dst}")
            return dst
        return self._path

    # ── Internals ─────────────────────────────────────────────────────────────

    def _build_record(
        self,
        cycle: int,
        metrics: dict,
        state: dict,
        decision: dict,
        latency: dict,
    ) -> dict:
        rtt     = metrics.get("urllc_rtt_99", 0.0)
        embb_lf = metrics.get("embb_load_fraction")

        raw_conf          = decision.get("confidence", 0.5)
        contradiction     = decision.get("contradiction", False)
        wrong_lever_event = bool(contradiction and decision.get("action") == "throttle_embb")
        lever_validity_score = round(raw_conf, 3)

        return {
            # ── Identity ──────────────────────────────────────────────────────
            "ts":                    datetime.now(timezone.utc).isoformat(),
            "cycle":                 cycle,

            # ── Network state ─────────────────────────────────────────────────
            "urllc_rtt_99":          rtt,
            "urllc_rtt_max":         metrics.get("urllc_rtt_max", rtt),
            "urllc_dead_tunnels":    metrics.get("urllc_dead_tunnels", 0),
            "urllc_loss_rate":       metrics.get("urllc_loss_rate", 0.0),
            "embb_load_fraction":    embb_lf,
            "embb_tp_mbps":          round(metrics.get("embb_tp_mbps", 0.0), 2),
            "embb_pkt_rate":         metrics.get("embb_pkt_rate", 0.0),
            "embb_pod_cpu_m":        metrics.get("embb_pod_cpu_m", 0.0),
            "embb_tc_rate_mbit":     state.get("current_embb_rate", 1000),
            "mmtc_pdr":              round(metrics.get("mmtc_pdr", 1.0), 4),
            "mmtc_msgs_total":       metrics.get("mmtc_msgs_total", 0),
            "sla_violated":          rtt > 20.0,

            # ── Orchestrator state ────────────────────────────────────────────
            "rtt_trend":             state.get("rtt_trend", "stable"),
            "violation_count":       state.get("violation_count", 0),
            "stable_for_s":          round(state.get("stable_for", 0.0), 1),
            "oscillating":           state.get("oscillation", False),
            "last_action":           state.get("last_action", "none"),

            # ── CoT reasoning fields ──────────────────────────────────────────
            "root_cause_assessment":  decision.get("root_cause_assessment", ""),
            "lever_validity_text":    decision.get("lever_validity", ""),
            "action":                 decision.get("action", "no_action"),
            "new_rate_mbit":          decision.get("new_rate_int", 1000),
            "confidence":             raw_conf,
            "llm_used":               decision.get("llm_used", True),
            "model_name":             decision.get("model_name", ""),   # B1

            # ── WLA scoring ───────────────────────────────────────────────────
            "wrong_lever_event":      wrong_lever_event,
            "lever_validity_score":   lever_validity_score,

            # ── Latency components (ms) ───────────────────────────────────────
            "collect_ms":            latency.get("collect_ms", 0.0),
            "llm_ms":                latency.get("llm_ms", 0.0),
            "exec_ms":               latency.get("exec_ms"),
            "cycle_ms":              latency.get("cycle_ms", 0.0),
            "recovery_latency_s":    latency.get("recovery_latency_s"),

            # ── Memory context (A3) ───────────────────────────────────────────
            "memory_context_summary": decision.get("memory_context_summary", ""),
            "memory_entry_count":      decision.get("memory_entry_count", 0),
            "memory_has_history":      decision.get("memory_has_history", False),

            # ── Token metrics (B2) ────────────────────────────────────────────
            "prompt_tokens":          decision.get("prompt_tokens", 0),
            "completion_tokens":      decision.get("completion_tokens", 0),
            "total_tokens":           decision.get("total_tokens", 0),
        }
