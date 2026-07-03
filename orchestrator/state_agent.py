"""
state_agent.py — Agentic Orchestrator State Tracker
Maintains sliding window of RTT history, computes trend,
tracks violations and stability for the LLM context window.
Also tracks current pod replica counts for autoscaling context.
"""
import logging
import statistics
import subprocess
import time
from collections import deque

import config

log = logging.getLogger("state")


class StateAgent:
    """
    Maintains orchestrator state between LangGraph cycles.
    Provides trend, violation count, stability, and oscillation detection.
    """

    # Deployments to track for autoscaling context
    _TRACKED_DEPLOYMENTS = [
        ("urllc", "urllc-app"),
        ("embb",  "embb-app"),
        ("mmtc",  "mmtc-app"),
    ]

    def __init__(self):
        self._rtt_history:    deque = deque(maxlen=config.RTT_TREND_WINDOW)
        self._action_history: deque = deque(maxlen=10)
        self.current_embb_rate: int = config.EMBB_RATE_MAX
        self.violation_count:   int = 0
        self.stable_for:        float = 0.0
        self._last_action_time: float = 0.0
        self._last_action:      str = "none"
        self._stable_since:     float = time.time()
        # Replica tracking (cached, refreshed every N cycles)
        self._replicas:  dict = {"urllc_replicas": 1, "embb_replicas": 1, "mmtc_replicas": 1}
        self._replica_cycle: int = 0

    def update(self, metrics: dict) -> dict:
        """
        Process new metrics and return state snapshot for LLM context.
        Called every cycle BEFORE the think node.
        """
        rtt = metrics.get("urllc_rtt_99", 0.0)

        # Update RTT history (skip zero = session drop)
        if rtt > 0:
            self._rtt_history.append(rtt)

        # Compute trend
        trend = self._compute_trend()

        # Update violation / stability counters
        # violation_count = consecutive violations in the CURRENT congestion event.
        # Reset to 0 as soon as RTT drops back below the SLA threshold so the
        # LLM receives accurate situational context (not a 400+ all-time counter).
        if rtt > config.URLLC_RTT_SLA_MS:
            self.violation_count += 1
            self._stable_since    = time.time()
        elif rtt > 0:
            self.violation_count = 0   # ← clear on recovery

        self.stable_for = time.time() - self._stable_since

        # Oscillation detection: rapid throttle↔restore switches
        oscillating = self._detect_oscillation()

        # Refresh replica counts every 5 cycles to avoid hammering k8s API
        self._replica_cycle += 1
        if self._replica_cycle % 5 == 1:
            self._replicas = self._fetch_replicas()

        return {
            "rtt_trend":        trend,
            "violation_count":  self.violation_count,
            "stable_for":       self.stable_for,
            "oscillation":      oscillating,
            "current_embb_rate":self.current_embb_rate,
            "last_action":      self._last_action,
            "last_action_time": self._last_action_time,
            "metrics":          metrics,
            **self._replicas,
        }

    def record_action(self, action: str, new_rate: int,
                      namespace: str = "", deployment: str = "",
                      new_replicas: int = 0):
        """Call after a successful action execution."""
        self._last_action      = action
        self._last_action_time = time.time()
        self.current_embb_rate = new_rate
        self._action_history.append(action)

        # Update cached replica count immediately on patch_replicas
        if action == "patch_replicas" and namespace and deployment and new_replicas:
            key = f"{namespace}_replicas"
            if key in self._replicas:
                self._replicas[key] = new_replicas
            log.debug(f"[State] Replicas updated: {namespace}/{deployment} → {new_replicas}")

        if action in ("throttle_embb", "throttle_embb_mild",
                      "throttle_embb_moderate"):
            self._stable_since = time.time()  # reset stability on throttle

        log.debug(f"[State] Action recorded: {action} → {new_rate}Mbit")

    def reset_violations(self):
        self.violation_count = 0
        self._stable_since   = time.time()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _fetch_replicas(self) -> dict:
        """Query kubectl for current spec.replicas on each tracked deployment."""
        result = {}
        for ns, dep in self._TRACKED_DEPLOYMENTS:
            key = f"{ns}_replicas"
            try:
                out = subprocess.check_output(
                    ["kubectl", "get", "deployment", dep, "-n", ns,
                     "-o", "jsonpath={.spec.replicas}"],
                    text=True, timeout=5
                ).strip()
                result[key] = int(out) if out else 1
            except Exception:
                result[key] = self._replicas.get(key, 1)  # keep cached value on failure
        return result

    def _compute_trend(self) -> str:
        """Linear slope over RTT history window."""
        vals = list(self._rtt_history)
        if len(vals) < 3:
            return "stable"
        n      = len(vals)
        x_mean = (n - 1) / 2.0
        y_mean = statistics.mean(vals)
        num    = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(vals))
        den    = sum((i - x_mean) ** 2 for i in range(n))
        slope  = num / den if den else 0.0

        if slope > 0.5:
            return "rising"
        elif slope < -0.5:
            return "falling"
        return "stable"

    def _detect_oscillation(self) -> bool:
        """True if too many rapid action switches in recent history."""
        recent = list(self._action_history)[-6:]
        if len(recent) < 4:
            return False
        switches = sum(
            1 for i in range(1, len(recent))
            if recent[i] != recent[i - 1] and
               recent[i] != "no_action" and
               recent[i - 1] != "no_action"
        )
        return switches >= 3
