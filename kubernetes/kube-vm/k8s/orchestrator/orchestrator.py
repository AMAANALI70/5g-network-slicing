#!/usr/bin/env python3
"""
QoS Orchestrator — Main Control Loop
Wires Perception → State → Planning → Execution agents.
Exposes Prometheus metrics on port 9200.
"""

import time
import threading
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

from config import LOOP_INTERVAL_SEC, METRICS_PORT
from perception_agent import PerceptionAgent
from state_agent import StateAgent
from planning_agent import PlanningAgent
from execution_agent import ExecutionAgent

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("orchestrator")

# ── Prometheus metrics state (simple counters/gauges) ─────────
prom_state = {
    "embb_current_rate": 100,
    "urllc_rtt_99": 0.0,
    "embb_throughput": 0.0,
    "mmtc_pdr": 1.0,
    "violation_count": 0,
    "stability_score": 0,
    "oscillation": 0,
    "throttle_actions_total": 0,
    "restore_actions_total": 0,
    "last_action": "none",
    "last_confidence": 0.0,
    "last_reason": "",
    "cpu_usage": 0.0,
    "total_drops": 0,
    "loop_count": 0,
}
prom_lock = threading.Lock()


# ── Prometheus metrics HTTP handler ───────────────────────────
class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            with prom_lock:
                lines = []
                lines.append(f'orchestrator_embb_rate_mbit {prom_state["embb_current_rate"]}')
                lines.append(f'orchestrator_urllc_rtt_ms {prom_state["urllc_rtt_99"]:.2f}')
                lines.append(f'orchestrator_embb_throughput_bps {prom_state["embb_throughput"]:.0f}')
                lines.append(f'orchestrator_mmtc_pdr {prom_state["mmtc_pdr"]:.4f}')
                lines.append(f'orchestrator_violation_count {prom_state["violation_count"]}')
                lines.append(f'orchestrator_stability_seconds {prom_state["stability_score"]}')
                lines.append(f'orchestrator_oscillation {prom_state["oscillation"]}')
                lines.append(f'orchestrator_throttle_total {prom_state["throttle_actions_total"]}')
                lines.append(f'orchestrator_restore_total {prom_state["restore_actions_total"]}')
                lines.append(f'orchestrator_last_confidence {prom_state["last_confidence"]:.2f}')
                lines.append(f'orchestrator_cpu_usage {prom_state["cpu_usage"]:.1f}')
                lines.append(f'orchestrator_total_drops {prom_state["total_drops"]}')
                lines.append(f'orchestrator_loop_count {prom_state["loop_count"]}')
                body = "\n".join(lines) + "\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            self.wfile.write(body.encode())
        elif self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok\n")
        elif self.path == "/status":
            with prom_lock:
                body = json.dumps(prom_state, indent=2)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress request logs


def start_metrics_server():
    """Run Prometheus metrics endpoint in background thread."""
    server = HTTPServer(("0.0.0.0", METRICS_PORT), MetricsHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    log.info(f"Metrics server started on :{METRICS_PORT}")


# ── Main Control Loop ─────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("QoS Orchestrator starting")
    log.info("Agents: Perception → State → Planning → Execution")
    log.info(f"Loop interval: {LOOP_INTERVAL_SEC}s")
    log.info("=" * 60)

    # Initialize agents
    perception = PerceptionAgent()
    state = StateAgent()
    planner = PlanningAgent()
    executor = ExecutionAgent()

    # Start metrics endpoint
    start_metrics_server()

    loop_count = 0
    pending_impact_check = None  # (cycle_count, pre_metrics)

    while True:
        loop_count += 1
        cycle_start = time.time()

        try:
            # ── Step 1: Perception — gather metrics ───────────
            metrics = perception.collect()
            log.info(
                f"[Perception] RTT={metrics['urllc_rtt_99']:.1f}ms  "
                f"eMBB={metrics['embb_tp']/1_000_000:.2f}MB/s  "
                f"PDR={metrics['mmtc_pdr']:.4f}  "
                f"drops={metrics['drops']}"
            )

            # ── Step 2: State — update memory ─────────────────
            state_snapshot = state.update(metrics)
            log.info(
                f"[State    ] trend={state_snapshot['rtt_trend']}  "
                f"violations={state_snapshot['violation_count']}  "
                f"stable={state_snapshot['stable_for']:.0f}s  "
                f"oscillation={state_snapshot['oscillation']}  "
                f"rate={state_snapshot['current_embb_rate']}mbit"
            )

            # ── Step 3: Planning — reason & decide ────────────
            decision = planner.decide(state_snapshot)
            action = decision["action"]
            log.info(
                f"[Planning ] action={action}  "
                f"rate={decision['new_rate']}  "
                f"confidence={decision['confidence']:.2f}  "
                f"reason={decision['reason']}"
            )

            # ── Step 4: Execution — act & verify ──────────────
            outcome = executor.execute(decision, metrics)

            if outcome["action_executed"]:
                status = "✅" if outcome["success"] else "❌"
                log.info(
                    f"[Execution] {status} {action} → {decision['new_rate']}  "
                    f"error={outcome.get('error')}"
                )

                if outcome["success"]:
                    state.record_action(action, decision["new_rate_int"])
                    pending_impact_check = (loop_count + 2, metrics)

                    # Reset violations on sustained stability
                    if action == "restore_embb":
                        state.reset_violations()

            # ── Step 5: Evaluate impact (2 cycles after action)
            if (pending_impact_check
                    and loop_count >= pending_impact_check[0]):
                impact = executor.evaluate_impact(metrics)
                log.info(f"[Impact   ] RTT change: {impact:+.2f}ms")
                state.record_outcome({
                    "success": True,
                    "impact_rtt_change": impact,
                })
                pending_impact_check = None

            # ── Update Prometheus metrics ─────────────────────
            with prom_lock:
                prom_state["embb_current_rate"] = state.current_embb_rate
                prom_state["urllc_rtt_99"] = metrics["urllc_rtt_99"]
                prom_state["embb_throughput"] = metrics["embb_tp"]
                prom_state["mmtc_pdr"] = metrics["mmtc_pdr"]
                prom_state["violation_count"] = state.violation_count
                prom_state["stability_score"] = state_snapshot["stable_for"]
                prom_state["oscillation"] = int(state_snapshot["oscillation"])
                prom_state["last_action"] = action
                prom_state["last_confidence"] = decision["confidence"]
                prom_state["last_reason"] = decision["reason"]
                prom_state["cpu_usage"] = metrics["cpu"]
                prom_state["total_drops"] = metrics["drops"]
                prom_state["loop_count"] = loop_count
                if action == "throttle_embb" and outcome.get("success"):
                    prom_state["throttle_actions_total"] += 1
                elif action == "restore_embb" and outcome.get("success"):
                    prom_state["restore_actions_total"] += 1

        except Exception as e:
            log.error(f"[ERROR    ] Loop exception: {e}", exc_info=True)

        # Sleep for remainder of interval
        elapsed = time.time() - cycle_start
        sleep_time = max(0, LOOP_INTERVAL_SEC - elapsed)
        time.sleep(sleep_time)


if __name__ == "__main__":
    main()
