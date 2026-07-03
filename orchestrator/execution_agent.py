"""
execution_agent.py — Agentic Orchestrator Execution Wrapper
Thin wrapper around the unified ExecutionAgent (orchestrator/) that adds
dry-run support and routes all action types including patch_replicas.

Uses importlib to load the unified ExecutionAgent by absolute file path
to avoid circular-import issues (both files are named execution_agent.py).
"""
import importlib.util
import logging
import os
import subprocess
import time

import config

log = logging.getLogger("execution")

# ── Load unified ExecutionAgent by absolute path (avoids circular import) ──────
try:
    _unified_file = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "../orchestrator/execution_agent.py")
    )
    _spec = importlib.util.spec_from_file_location("_orchestrator_exec", _unified_file)
    _mod  = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _RealExecutionAgent = _mod.ExecutionAgent
    _HAS_REAL = True
    log.info(f"Loaded unified ExecutionAgent from {_unified_file}")
except Exception as _e:
    _HAS_REAL = False
    log.warning(f"Unified ExecutionAgent not found ({_e}) — using kubectl-exec fallback")


class ExecutionAgent:
    """
    Wraps the rule-based ExecutionAgent.
    dry_run=True: logs the tc command but does NOT apply it.
    """

    def __init__(self, dry_run: bool = False):
        self.dry_run   = dry_run
        self._real     = _RealExecutionAgent() if _HAS_REAL and not dry_run else None
        self._prev_rtt = 0.0
        log.info(f"[Executor] dry_run={dry_run}  real_agent={_HAS_REAL and not dry_run}")

    def execute(self, decision: dict, metrics: dict) -> dict:
        action         = decision.get("action", "no_action")
        self._prev_rtt = metrics.get("urllc_rtt_99", 0)

        if action == "no_action":
            return {"action_executed": False, "success": True, "error": None}

        if self.dry_run:
            log.info(f"[Executor] [DRY-RUN] Would execute: {action} | params={decision}")
            return {"action_executed": True, "success": True, "error": None}

        if self._real:
            # Route all action types through the unified ExecutionAgent
            # (throttle_embb, restore_embb, patch_replicas, etc.)
            return self._real.execute(decision, metrics)

        # ── Inline fallback: kubectl exec into UPF pod ──────────────────────
        # Mirrors the rule-based orchestrator's kubectl_exec_upf() approach.
        # The UPF pod runs hostNetwork=true so tc commands affect the host interface.
        return self._kubectl_exec_fallback(decision)

    def _kubectl_exec_fallback(self, decision: dict) -> dict:
        """Fallback tc execution via kubectl exec — used when unified agent unavailable."""
        action   = decision.get("action", "throttle_embb")
        new_rate = decision.get("new_rate", f"{config.EMBB_RATE_MAX}mbit")

        if action == "restore_embb":
            tc_cmd = f"tc qdisc del dev {config.EMBB_INTERFACE} root 2>/dev/null || true"
        else:
            tc_cmd = (
                f"tc qdisc del dev {config.EMBB_INTERFACE} root 2>/dev/null || true; "
                f"tc qdisc add dev {config.EMBB_INTERFACE} root tbf "
                f"rate {new_rate} burst 32kbit latency 400ms"
            )

        t0 = time.time()
        try:
            upf = subprocess.check_output(
                "kubectl get pod -n embb -l app=upf-embb "
                "--no-headers | awk '{print $1}' | head -1",
                shell=True, text=True, timeout=10
            ).strip()
            if not upf:
                return {"action_executed": True, "success": False,
                        "error": "No eMBB UPF pod found",
                        "exec_ms": round((time.time() - t0) * 1000, 1)}

            r = subprocess.run(
                ["kubectl", "exec", "-n", "embb", upf, "--", "bash", "-c", tc_cmd],
                capture_output=True, text=True, timeout=15
            )
            exec_ms = round((time.time() - t0) * 1000, 1)
            if r.returncode == 0:
                log.info(f"[Executor] ✅ {action} via kubectl exec ({exec_ms:.0f}ms)")
                return {"action_executed": True, "success": True,
                        "error": None, "exec_ms": exec_ms}
            else:
                err = r.stderr.strip() or r.stdout.strip()
                log.warning(f"[Executor] ❌ kubectl exec failed: {err}")
                return {"action_executed": True, "success": False,
                        "error": err, "exec_ms": exec_ms}
        except Exception as e:
            exec_ms = round((time.time() - t0) * 1000, 1)
            log.error(f"[Executor] kubectl exec exception: {e}")
            return {"action_executed": True, "success": False,
                    "error": str(e), "exec_ms": exec_ms}

    def evaluate_impact(self, metrics: dict) -> float:
        """RTT change since last action (for reflect node)."""
        current = metrics.get("urllc_rtt_99", 0)
        return round(current - self._prev_rtt, 2)
