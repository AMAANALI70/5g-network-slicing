"""
Planning Agent — Reasons over state and decides optimal slice adjustments.
Assigns confidence scores based on severity, trend strength, and history.
"""

import time
from config import (
    URLLC_RTT_SLA_MS, EMBB_RATE_FLOOR, EMBB_RATE_MAX,
    EMBB_THROTTLE_STEP, EMBB_RESTORE_STEP,
    COOLDOWN_SEC, STABILITY_WINDOW_SEC,
)


class PlanningAgent:
    """Decision engine with confidence-weighted actions."""

    def decide(self, state: dict) -> dict:
        """
        Produce action decision based on current state.

        Returns:
            {
                "action": "throttle_embb"|"restore_embb"|"no_action",
                "new_rate": "<rate_value>",
                "confidence": 0.0–1.0,
                "reason": "<explanation>"
            }
        """
        metrics = state["metrics"]
        rtt = metrics.get("urllc_rtt_99", 0.0)
        rtt_trend = state["rtt_trend"]
        violations = state["violation_count"]
        stable_for = state["stable_for"]
        oscillating = state["oscillation"]
        current_rate = state["current_embb_rate"]
        last_action = state["last_action_time"]

        now = time.time()
        time_since_action = now - last_action

        # ── Cooldown check ────────────────────────────────────
        if time_since_action < COOLDOWN_SEC:
            return self._no_action(
                current_rate,
                f"Cooldown active ({COOLDOWN_SEC - time_since_action:.0f}s remaining)"
            )

        # ── Oscillation dampening ─────────────────────────────
        if oscillating:
            return self._no_action(
                current_rate,
                "Oscillation detected — suppressing actions to stabilize"
            )

        # ── THROTTLE logic ────────────────────────────────────
        if rtt > URLLC_RTT_SLA_MS and rtt_trend == "rising":
            return self._plan_throttle(
                current_rate, rtt, violations, rtt_trend
            )

        if rtt > URLLC_RTT_SLA_MS and violations > 2:
            return self._plan_throttle(
                current_rate, rtt, violations, rtt_trend,
                severe=True
            )

        # ── RESTORE logic ─────────────────────────────────────
        if (stable_for >= STABILITY_WINDOW_SEC
                and current_rate < EMBB_RATE_MAX
                and rtt <= URLLC_RTT_SLA_MS):
            return self._plan_restore(current_rate, stable_for)

        # ── Default: no action ────────────────────────────────
        return self._no_action(current_rate, "SLA within bounds")

    # ── Internal planning methods ─────────────────────────────

    def _plan_throttle(self, current_rate, rtt, violations,
                       trend, severe=False):
        """Plan eMBB throttle action."""
        step = EMBB_THROTTLE_STEP
        if severe or violations > 4:
            step = EMBB_THROTTLE_STEP * 1.5  # More aggressive

        new_rate = max(EMBB_RATE_FLOOR, current_rate - int(step))

        if new_rate >= current_rate:
            return self._no_action(
                current_rate,
                f"Already at rate floor ({EMBB_RATE_FLOOR}mbit)"
            )

        # Confidence based on severity
        confidence = self._compute_confidence(rtt, violations, trend)

        reason = (
            f"URLLC RTT {rtt:.1f}ms > SLA {URLLC_RTT_SLA_MS}ms, "
            f"trend={trend}, violations={violations}. "
            f"Throttle eMBB {current_rate}→{new_rate}mbit."
        )

        return {
            "action": "throttle_embb",
            "new_rate": f"{new_rate}mbit",
            "new_rate_int": new_rate,
            "confidence": confidence,
            "reason": reason,
        }

    def _plan_restore(self, current_rate, stable_for):
        """Plan eMBB bandwidth restoration."""
        new_rate = min(EMBB_RATE_MAX, current_rate + EMBB_RESTORE_STEP)

        confidence = min(0.9, 0.5 + (stable_for - STABILITY_WINDOW_SEC) / 120)

        reason = (
            f"Stable for {stable_for:.0f}s (>{STABILITY_WINDOW_SEC}s). "
            f"Restoring eMBB {current_rate}→{new_rate}mbit."
        )

        return {
            "action": "restore_embb",
            "new_rate": f"{new_rate}mbit",
            "new_rate_int": new_rate,
            "confidence": confidence,
            "reason": reason,
        }

    @staticmethod
    def _no_action(current_rate, reason):
        return {
            "action": "no_action",
            "new_rate": f"{current_rate}mbit",
            "new_rate_int": current_rate,
            "confidence": 1.0,
            "reason": reason,
        }

    @staticmethod
    def _compute_confidence(rtt, violations, trend):
        """
        Confidence = f(severity, trend, history).
        Higher when violation is severe and consistent.
        """
        severity = min(1.0, (rtt - URLLC_RTT_SLA_MS) / URLLC_RTT_SLA_MS)
        trend_weight = {"rising": 0.3, "stable": 0.1, "falling": 0.0}.get(trend, 0.1)
        history_weight = min(0.3, violations * 0.05)
        return round(min(1.0, 0.3 + severity + trend_weight + history_weight), 2)
