"""
main.py — Agentic 5G QoS Orchestrator Entry Point
==================================================
Architecture: Decoupled monitoring + LLM inference.

  Thread A — Fast Monitor (every 3s):
    MonitoringAgent.collect() → StateAgent.update()
    → writes metrics_cache (for LLM)
    → updates prom_state (for Prometheus, stays fresh)

  Thread B — LLM Inference (continuous, no sleep):
    observe_node reads metrics_cache
    think(LLM ~11–15s) → validate → act → reflect
    → LangGraph: observe→think→validate→act→reflect

  Thread C — Metrics HTTP Server (daemon):
    Serves prom_state on :9200/metrics

Usage:
  python3 main.py                 # normal run
  python3 main.py --dry-run       # LLM reasons; no tc commands applied
  python3 main.py --loops 3       # stop after N LLM cycles (testing)
  python3 main.py --fresh         # flush memory before starting
"""

import argparse
import logging
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

from monitoring_agent import MonitoringAgent
from state_agent      import StateAgent
from execution_agent  import ExecutionAgent
from cot_trace_logger import CoTTraceLogger

import config
from agent_memory import AgentMemory
from graph        import build_graph

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt= "%H:%M:%S",
)
log = logging.getLogger("main")

# ── Shared state ──────────────────────────────────────────────────────────────

# metrics_cache: updated by fast monitor thread, read by LangGraph observe_node
metrics_cache: dict = {}
metrics_cache_lock  = threading.Lock()

# prom_state: updated by both threads; served to Prometheus
prom_state = {
    "rtt_ms":              0.0,
    "embb_rate_mbit":      config.EMBB_RATE_MAX,
    "embb_mbps":           0.0,
    "mmtc_pdr":            1.0,
    "sla_violated":        0,
    "action":              "none",
    "confidence":          0.0,
    "llm_latency_ms":      0.0,
    "llm_used":            1,
    "safety_overrides":    0,
    "loop_count":          0,
    "memory_success_rate": 0.0,
    "orchestrator_state":  0,
    "violation_count":     0,
    "recovery_streak":     0,
    "embb_mbps":           0.0,
    "mmtc_msgs_total":     0,
    "throttle_total":      0,
    "restore_total":       0,
    "urllc_replicas":      1,
    "embb_replicas":       1,
    "mmtc_replicas":       1,
    # Monitoring freshness
    "monitor_age_s":       0.0,
    # Phase 1 additions
    "embb_load_fraction":  0.0,
    "wla_total":           0,
    "wla_score":           0,        # per-cycle: 1 if WLA event this cycle
    "lever_validity_score": 0.0,
    "collect_ms":          0.0,
    "exec_ms":             0.0,
    "cycle_ms":            0.0,
    "recovery_latency_s":  0.0,      # 0 = no active recovery
}
prom_lock = threading.Lock()


# ── Prometheus HTTP server ────────────────────────────────────────────────────

class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200); self.end_headers()
            self.wfile.write(b"ok"); return

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        with prom_lock:
            lines = [
                f"orchestrator_urllc_rtt_ms {prom_state['rtt_ms']:.2f}",
                f"orchestrator_embb_rate_mbit {prom_state['embb_rate_mbit']}",
                f"orchestrator_embb_mbps {prom_state['embb_mbps']:.2f}",
                f"orchestrator_mmtc_pdr {prom_state['mmtc_pdr']:.4f}",
                f"orchestrator_mmtc_msgs_total {prom_state['mmtc_msgs_total']}",
                f"orchestrator_state {prom_state['orchestrator_state']}",
                f"orchestrator_violation_count {prom_state['violation_count']}",
                f"orchestrator_recovery_streak {prom_state['recovery_streak']}",
                f"orchestrator_llm_latency_ms {prom_state['llm_latency_ms']:.1f}",
                f"orchestrator_llm_confidence {prom_state['confidence']:.2f}",
                f"orchestrator_llm_used {prom_state['llm_used']}",
                f"orchestrator_safety_overrides_total {prom_state['safety_overrides']}",
                f"orchestrator_loop_count {prom_state['loop_count']}",
                f"orchestrator_memory_success_rate {prom_state['memory_success_rate']:.3f}",
                f"orchestrator_agentic_mode 1",
                f"orchestrator_throttle_total {prom_state['throttle_total']}",
                f"orchestrator_restore_total {prom_state['restore_total']}",
                f"orchestrator_urllc_replicas {prom_state['urllc_replicas']}",
                f"orchestrator_embb_replicas {prom_state['embb_replicas']}",
                f"orchestrator_mmtc_replicas {prom_state['mmtc_replicas']}",
                f"orchestrator_monitor_age_s {prom_state['monitor_age_s']:.1f}",
                # Phase 1: WLA + latency metrics
                f"orchestrator_embb_load_fraction {prom_state['embb_load_fraction']:.3f}",
                f"orchestrator_wla_total {prom_state['wla_total']}",
                f"orchestrator_wla_score {prom_state['wla_score']}",
                f"orchestrator_lever_validity_score {prom_state['lever_validity_score']:.3f}",
                f"orchestrator_collect_ms {prom_state['collect_ms']:.1f}",
                f"orchestrator_exec_ms {prom_state['exec_ms']:.1f}",
                f"orchestrator_cycle_ms {prom_state['cycle_ms']:.1f}",
                f"orchestrator_recovery_latency_s {prom_state['recovery_latency_s']:.1f}",
            ]
        self.wfile.write("\n".join(lines).encode())

    def log_message(self, *_): pass


def start_metrics_server():
    server = HTTPServer(("", config.METRICS_PORT), MetricsHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    log.info(f"[Metrics ] HTTP server on :{config.METRICS_PORT}/metrics")


# ── Fast monitor thread (Thread A) ───────────────────────────────────────────

_MONITOR_INTERVAL = 3   # seconds — independent of LLM cycle rate

def fast_monitor_loop(monitor: MonitoringAgent, state_agent: StateAgent):
    """
    Runs every 3s regardless of LLM inference speed.
    Writes to metrics_cache (read by observe_node) and prom_state (read by Prometheus).
    state_agent is updated here so trend/violation tracking runs at monitoring rate.
    """
    log.info("[Monitor ] Fast monitor thread started (3s interval)")
    while True:
        t0 = time.time()
        try:
            metrics        = monitor.collect()
            state_snapshot = state_agent.update(metrics)
            now            = time.time()

            with metrics_cache_lock:
                metrics_cache["metrics"]        = metrics
                metrics_cache["state_snapshot"] = state_snapshot
                metrics_cache["ts"]             = now

            # Update Prometheus with fresh monitoring data (independent of LLM cycle)
            with prom_lock:
                prom_state["rtt_ms"]         = metrics.get("urllc_rtt_99", 0.0)
                prom_state["embb_mbps"]      = metrics.get("embb_tp_mbps",
                                               metrics.get("embb_tp", 0) / 1e6)
                prom_state["mmtc_pdr"]       = metrics.get("mmtc_pdr", 1.0)
                prom_state["mmtc_msgs_total"]= metrics.get("mmtc_msgs_total", 0)
                prom_state["violation_count"]= state_snapshot.get("violation_count", 0)
                prom_state["recovery_streak"]= state_snapshot.get("stable_for", 0)
                prom_state["sla_violated"]   = (
                    1 if metrics.get("urllc_rtt_99", 0) > config.URLLC_RTT_SLA_MS else 0)
                prom_state["monitor_age_s"]  = 0.0

            log.info(
                f"[Monitor ] RTT={metrics.get('urllc_rtt_99',0):.1f}ms  "
                f"eMBB={metrics.get('embb_tp_mbps',0):.1f}Mbps  "
                f"dead={metrics.get('urllc_dead_tunnels',0)}  "
                f"trend={state_snapshot.get('rtt_trend','?')}"
            )

        except Exception as e:
            log.error(f"[Monitor ] Collection error: {e}")

        # Update monitor staleness counter for Prometheus
        elapsed = time.time() - t0
        time.sleep(max(0, _MONITOR_INTERVAL - elapsed))

        # Tick monitor_age after sleep
        with prom_lock:
            prom_state["monitor_age_s"] = time.time() - metrics_cache.get("ts", time.time())


# ── LangGraph graph wiring (observe reads cache) ──────────────────────────────

def _observe_from_cache(state: dict, memory, state_agent) -> dict:
    """
    observe_node replacement: reads from metrics_cache instead of calling
    monitor.collect() directly. Falls back to in-state values if cache is empty.
    Also handles the outcome-update flag set by the previous reflect node.
    """
    # Update previous decision's outcome with current (post-action) RTT
    if state.get("_needs_outcome_update", False):
        with metrics_cache_lock:
            prev_metrics = metrics_cache.get("metrics", {})
        prev_rtt = prev_metrics.get("urllc_rtt_99", 0)
        if prev_rtt > 0:
            memory.update_outcome(prev_rtt)

    # Read latest snapshot from fast monitor thread
    with metrics_cache_lock:
        metrics        = metrics_cache.get("metrics",        state.get("metrics", {}))
        state_snapshot = metrics_cache.get("state_snapshot", state.get("state_snapshot", {}))
        cache_age      = time.time() - metrics_cache.get("ts", 0)

    if cache_age > 15:
        log.warning(f"[Observe ] Metrics cache stale ({cache_age:.0f}s) — using last known values")

    return {
        **state,
        "metrics":             metrics,
        "state_snapshot":      state_snapshot,
        "_needs_outcome_update": False,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Agentic 5G QoS Orchestrator")
    parser.add_argument("--dry-run", action="store_true",
                        help="LLM reasons but no tc commands applied")
    parser.add_argument("--loops", type=int, default=0,
                        help="Stop after N LLM cycles (0=infinite)")
    parser.add_argument("--fresh", action="store_true",
                        help="Flush agent memory before starting (use between experiment runs)")
    args = parser.parse_args()

    if args.dry_run:
        log.info("[Main    ] DRY-RUN mode — tc commands will be skipped")

    # ── Boot ──────────────────────────────────────────────────────────────────
    start_metrics_server()

    monitor     = MonitoringAgent()
    state_agent = StateAgent()
    executor    = ExecutionAgent(dry_run=args.dry_run)
    memory      = AgentMemory(maxlen=config.MEMORY_SIZE)

    # ── Sync initial tc rate from worker (avoids stale-rate mismatch) ─────────
    # If a previous orchestrator left a non-default tc rate, read it now so that
    # state_agent and Prometheus both reflect the live hardware state from cycle 1.
    try:
        import subprocess as _sp
        _tc_raw = _sp.run(
            ["ssh", "-i", config.WORKER_SSH_KEY,
             "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=4",
             f"{config.WORKER_SSH_USER}@{config.WORKER_SSH_HOST}",
             f"tc qdisc show dev {config.EMBB_INTERFACE} 2>/dev/null"],
            capture_output=True, text=True, timeout=8
        ).stdout
        import re as _re
        _m = _re.search(r'\brate\s+(\d+)Mbit\b', _tc_raw, _re.IGNORECASE)
        if _m:
            _live_rate = int(_m.group(1))
            state_agent.current_embb_rate = _live_rate
            with prom_lock:
                prom_state["embb_rate_mbit"] = _live_rate
            log.info(f"[Main    ] Synced live tc rate from worker: {_live_rate}Mbit")
        else:
            log.info(f"[Main    ] No tc qdisc on {config.EMBB_INTERFACE} — using default {config.EMBB_RATE_MAX}Mbit")
    except Exception as _e:
        log.warning(f"[Main    ] Could not read live tc rate: {_e} — using default")

    if args.fresh:
        memory.clear()
        log.info("[Main    ] Agent memory flushed (--fresh flag)")

    # ── CoT trace logger ──────────────────────────────────────────────────────
    trace_logger = CoTTraceLogger()
    if args.fresh:
        trace_logger.rotate()
        log.info("[Main    ] CoT trace file rotated (--fresh flag)")

    # ── Start fast monitor thread ─────────────────────────────────────────────
    monitor_thread = threading.Thread(
        target=fast_monitor_loop,
        args=(monitor, state_agent),
        daemon=True,
        name="FastMonitor",
    )
    monitor_thread.start()

    # Seed cache: wait up to 8s for first monitor collection
    log.info("[Main    ] Waiting for initial metrics collection...")
    deadline = time.time() + 8
    while time.time() < deadline:
        with metrics_cache_lock:
            if metrics_cache.get("metrics"):
                break
        time.sleep(0.2)
    else:
        log.warning("[Main    ] Initial metrics not ready — proceeding with empty state")

    # ── Build LangGraph with cache-aware observe node ─────────────────────────
    # Override observe_node to read from metrics_cache instead of calling collect()
    from graph import build_graph as _build_graph
    import graph as _graph_module

    # Monkey-patch observe_node in the graph closure
    _orig_observe = _graph_module.observe_node

    def _patched_observe(state):
        return _observe_from_cache(state, memory, state_agent)

    _graph_module.observe_node = _patched_observe   # patch before build_graph
    agentic_graph, llm_agent = _build_graph(monitor, state_agent, memory, None, executor)
    _graph_module.observe_node = _orig_observe       # restore for clean module state

    log.info("=" * 60)
    log.info("Agentic 5G QoS Orchestrator — STARTING")
    log.info(f"Backend:  Ollama  model={config.OLLAMA_MODEL}")
    log.info(f"SLA:      RTT < {config.URLLC_RTT_SLA_MS}ms")
    log.info(f"eMBB:     {config.EMBB_RATE_FLOOR}–{config.EMBB_RATE_MAX}Mbit")
    log.info(f"Loop:     inference-rate (no sleep)  Memory: {config.MEMORY_SIZE} entries")
    log.info(f"Monitor:  {_MONITOR_INTERVAL}s independent thread")
    log.info(f"Dry-run:  {args.dry_run}")
    log.info("=" * 60)

    loop_count       = 0
    safety_overrides = 0
    throttle_total   = 0
    restore_total    = 0
    wla_total        = 0
    prev_action      = "no_action"
    # Recovery latency tracking: t_breach is set when RTT first crosses SLA,
    # cleared when RTT recovers. recovery_latency_s is the duration.
    _breach_time:   float = 0.0   # 0 = not in violation
    _last_cycle_ms: float = 0.0

    agent_state: dict = {
        "metrics": {}, "state_snapshot": {},
        "action": "none", "new_rate_int": config.EMBB_RATE_MAX,
        "reason": "", "confidence": 0.0, "llm_used": True,
        "decision_latency_ms": 0.0,
        "safe": True, "safety_reason": "OK",
        "executed": False, "exec_success": False, "exec_error": None,
        "rtt_after": None, "_needs_outcome_update": False,
    }

    while True:
        loop_count += 1
        cycle_start = time.time()

        try:
            cycle_start = time.time()

            # ── Full LangGraph cycle (observe reads cache, think=LLM) ─────────
            agent_state = agentic_graph.invoke(agent_state)

            cycle_ms = round((time.time() - cycle_start) * 1000, 1)

            if not agent_state.get("safe", True):
                safety_overrides += 1

            cur_action = agent_state.get("action", "no_action")
            if cur_action == "throttle_embb" and prev_action != "throttle_embb":
                throttle_total += 1
            elif cur_action in ("restore_embb", "no_action") and prev_action == "throttle_embb":
                restore_total += 1
            prev_action = cur_action

            # ── WLA counters ──────────────────────────────────────────────────
            wla_event_this_cycle = agent_state.get("wrong_lever_event", False)
            if wla_event_this_cycle:
                wla_total += 1

            # ── Recovery latency tracking ─────────────────────────────────────
            cur_metrics = agent_state.get("metrics", {})
            cur_rtt     = cur_metrics.get("urllc_rtt_99", 0.0)
            if cur_rtt > config.URLLC_RTT_SLA_MS:
                if _breach_time == 0.0:
                    _breach_time = time.time()   # mark start of violation
                recovery_latency_s = 0.0
            elif _breach_time > 0.0:
                recovery_latency_s = round(time.time() - _breach_time, 1)
                _breach_time = 0.0               # cleared: back in SLA
                log.info(f"[Main    ] Recovery latency: {recovery_latency_s:.1f}s")
            else:
                recovery_latency_s = 0.0

            # ── Four-component latency ────────────────────────────────────────
            collect_ms = cur_metrics.get("collect_ms", 0.0)
            llm_ms     = agent_state.get("decision_latency_ms", 0.0)
            exec_ms    = agent_state.get("exec_ms", 0.0) or 0.0

            latency = {
                "collect_ms":         collect_ms,
                "llm_ms":             llm_ms,
                "exec_ms":            exec_ms if cur_action != "no_action" else None,
                "cycle_ms":           cycle_ms,
                "recovery_latency_s": recovery_latency_s if recovery_latency_s > 0 else None,
            }
            log.info(
                f"[Main    ] LATENCY collect={collect_ms:.0f}ms  "
                f"llm={llm_ms:.0f}ms  exec={exec_ms:.0f}ms  cycle={cycle_ms:.0f}ms"
            )

            # ── CoT trace log (one line per cycle) ────────────────────────────
            ss = agent_state.get("state_snapshot", {})
            trace_logger.log(
                cycle    = loop_count,
                metrics  = cur_metrics,
                state    = ss,
                decision = agent_state,
                latency  = latency,
            )

            # ── Update Prometheus with decision-layer data ────────────────────
            mem_stats    = memory.get_stats()
            is_throttled = agent_state.get("new_rate_int", config.EMBB_RATE_MAX) < config.EMBB_RATE_MAX

            with prom_lock:
                prom_state["embb_rate_mbit"]      = agent_state.get("new_rate_int", config.EMBB_RATE_MAX)
                prom_state["orchestrator_state"]  = 1 if is_throttled else 0
                prom_state["action"]              = cur_action
                prom_state["confidence"]          = agent_state.get("confidence", 0.0)
                prom_state["llm_latency_ms"]      = llm_ms
                prom_state["llm_used"]            = 1 if agent_state.get("llm_used", True) else 0
                prom_state["safety_overrides"]    = safety_overrides
                prom_state["loop_count"]          = loop_count
                prom_state["memory_success_rate"] = mem_stats["success_rate"]
                prom_state["throttle_total"]      = throttle_total
                prom_state["restore_total"]       = restore_total
                prom_state["urllc_replicas"]      = ss.get("urllc_replicas", 1)
                prom_state["embb_replicas"]       = ss.get("embb_replicas", 1)
                prom_state["mmtc_replicas"]       = ss.get("mmtc_replicas", 1)
                # Phase 1: WLA + latency
                prom_state["embb_load_fraction"]  = cur_metrics.get("embb_load_fraction") or 0.0
                prom_state["wla_total"]           = wla_total
                prom_state["wla_score"]           = 1 if wla_event_this_cycle else 0
                prom_state["lever_validity_score"]= agent_state.get("lever_validity_score", 0.0)
                prom_state["collect_ms"]          = collect_ms
                prom_state["exec_ms"]             = exec_ms
                prom_state["cycle_ms"]            = cycle_ms
                prom_state["recovery_latency_s"]  = recovery_latency_s

        except Exception as e:
            log.error(f"[ERROR   ] Cycle {loop_count} failed: {e}", exc_info=True)

        # Stop condition
        if args.loops and loop_count >= args.loops:
            log.info(f"[Main    ] Reached {args.loops} loops — stopping")
            break

        # No sleep — next cycle starts immediately after current completes.
        # Effective rate is determined by LLM inference time (~15s).
        cycle_dur = time.time() - cycle_start
        log.debug(f"[Main    ] Cycle {loop_count} complete in {cycle_dur:.1f}s")


if __name__ == "__main__":
    main()
