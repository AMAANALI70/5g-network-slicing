"""
Execution Agent — Executes tc class change commands and verifies results.
Reports outcome back to the State Agent.
"""

import subprocess
import time
from config import EMBB_INTERFACE, EMBB_CLASSID, LOOP_INTERVAL_SEC


class ExecutionAgent:
    """Applies tc shaping changes and evaluates their impact."""

    def __init__(self):
        self.pre_action_rtt = None

    def execute(self, decision: dict, pre_metrics: dict) -> dict:
        """
        Execute the planned action and return outcome.

        Args:
            decision: Planning agent output with action/new_rate
            pre_metrics: Metrics snapshot before action

        Returns:
            {
                "action_executed": bool,
                "action": str,
                "new_rate": str,
                "impact_rtt_change": float,
                "success": bool,
                "error": str or None,
            }
        """
        action = decision.get("action", "no_action")

        if action == "no_action":
            return {
                "action_executed": False,
                "action": "no_action",
                "new_rate": decision.get("new_rate", ""),
                "impact_rtt_change": 0.0,
                "success": True,
                "error": None,
            }

        rate = decision.get("new_rate", "100mbit")
        self.pre_action_rtt = pre_metrics.get("urllc_rtt_99", 0.0)

        # Execute tc class change
        success, error = self._apply_tc_change(rate)

        if not success:
            return {
                "action_executed": True,
                "action": action,
                "new_rate": rate,
                "impact_rtt_change": 0.0,
                "success": False,
                "error": error,
            }

        # Verify application
        verified = self._verify_rate(rate)

        return {
            "action_executed": True,
            "action": action,
            "new_rate": rate,
            "impact_rtt_change": 0.0,  # Updated after post-check
            "success": verified,
            "error": None if verified else "Rate verification failed",
        }

    def evaluate_impact(self, post_metrics: dict) -> float:
        """
        Compare RTT before and after action.
        Negative = improvement. Call after 2 cycles.
        """
        if self.pre_action_rtt is None:
            return 0.0
        post_rtt = post_metrics.get("urllc_rtt_99", 0.0)
        delta = post_rtt - self.pre_action_rtt
        self.pre_action_rtt = None
        return round(delta, 2)

    # ── tc command execution ──────────────────────────────────

    @staticmethod
    def _apply_tc_change(rate: str) -> tuple:
        """
        Execute: tc class change dev ogstun-embb classid 1:1 htb rate <rate> ceil <rate>
        Returns (success: bool, error: str|None)
        """
        cmd = [
            "tc", "class", "change",
            "dev", EMBB_INTERFACE,
            "classid", EMBB_CLASSID,
            "htb",
            f"rate", rate,
            f"ceil", rate,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return False, result.stderr.strip()
            return True, None
        except subprocess.TimeoutExpired:
            return False, "tc command timed out"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _verify_rate(expected_rate: str) -> bool:
        """Verify tc class was updated correctly."""
        try:
            out = subprocess.check_output(
                ["tc", "class", "show", "dev", EMBB_INTERFACE],
                text=True, timeout=5,
            )
            # Check if the expected rate appears in output
            rate_num = expected_rate.replace("mbit", "").replace("Mbit", "")
            return f"rate {rate_num}Mbit" in out or f"rate {rate_num}mbit" in out.lower()
        except Exception:
            return False
