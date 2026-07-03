#!/usr/bin/env python3
"""
baseline_audit.py — Behavioral baseline for Ollama-backed agentic orchestrator.
Runs 3 controlled scenarios through both orchestrators and captures full
decision trace, performance metrics, and comparative analysis.
"""
import json, sys, time, threading, urllib.request
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────────────────────
# Load agentic modules only — rule-based logic is reproduced inline
# to avoid sys.path collision (both use a module named 'config').
AGENTIC_DIR = Path(__file__).parent / "orchestrator_agentic"
sys.path.insert(0, str(AGENTIC_DIR))

import config as agentic_cfg
from prompt import SYSTEM_PROMPT, build_user_prompt
from agent_memory import AgentMemory

# ── Rule-based decision logic (inline, aligned config values) ──────────────
# Reproduces PlanningAgent.decide() from orchestrator/planning_agent.py
# using the Phase-0-aligned parameters: SLA=20ms, RATE_MAX=1000Mbit,
# THROTTLE_STEP=200Mbit, RESTORE_STEP=100Mbit, FLOOR=50Mbit, COOLDOWN=15s.

_RB_SLA       = 20.0    # ms  — aligned
_RB_RATE_MAX  = 1000    # Mbit
_RB_RATE_FLOOR=  50     # Mbit
_RB_STEP_DN   = 200     # Mbit per throttle action
_RB_STEP_UP   = 100     # Mbit per restore action
_RB_COOLDOWN  =  15.0   # s
_RB_STAB_WIN  =  60.0   # s

def rule_based_decide(metrics: dict) -> dict:
    """
    Faithful reproduction of PlanningAgent.decide() + _plan_throttle/_plan_restore
    with Phase-0-aligned parameters.
    """
    rtt        = metrics.get("urllc_rtt_99", 0.0)
    rtt_trend  = metrics.get("_rtt_trend",   "stable")
    violations = metrics.get("_violations",  0)
    stable_for = metrics.get("_stable_for",  0.0)
    oscillating= metrics.get("_oscillating", False)
    cur_rate   = metrics.get("_cur_rate",    _RB_RATE_MAX)
    last_ts    = metrics.get("_last_action_ts", 0.0)

    now = time.time()

    # Cooldown
    if (now - last_ts) < _RB_COOLDOWN:
        return _rb_no_action(cur_rate,
            f"Cooldown active ({_RB_COOLDOWN-(now-last_ts):.0f}s remaining)")

    # Oscillation dampening
    if oscillating:
        return _rb_no_action(cur_rate, "Oscillation detected — suppressing actions")

    # THROTTLE: RTT violated AND rising trend
    if rtt > _RB_SLA and rtt_trend == "rising":
        return _rb_throttle(cur_rate, rtt, violations, rtt_trend, severe=False)

    # THROTTLE: RTT violated AND 3+ violations (persistent)
    if rtt > _RB_SLA and violations > 2:
        return _rb_throttle(cur_rate, rtt, violations, rtt_trend, severe=True)

    # RESTORE: stable long enough, not at max
    if stable_for >= _RB_STAB_WIN and cur_rate < _RB_RATE_MAX and rtt <= _RB_SLA:
        return _rb_restore(cur_rate, stable_for)

    return _rb_no_action(cur_rate, "SLA within bounds — no action")


def _rb_throttle(cur, rtt, violations, trend, severe):
    step     = _RB_STEP_DN * 1.5 if severe or violations > 4 else _RB_STEP_DN
    new_rate = max(_RB_RATE_FLOOR, cur - int(step))
    if new_rate >= cur:
        return _rb_no_action(cur, f"Already at rate floor ({_RB_RATE_FLOOR}Mbit)")
    sev_frac = min(1.0, (rtt - _RB_SLA) / _RB_SLA)
    tw = {"rising": 0.3, "stable": 0.1, "falling": 0.0}.get(trend, 0.1)
    hw = min(0.3, violations * 0.05)
    conf = round(min(1.0, 0.3 + sev_frac + tw + hw), 2)
    return {
        "action": "throttle_embb",
        "new_rate": f"{new_rate}mbit", "new_rate_int": new_rate,
        "confidence": conf,
        "reason": (f"URLLC RTT {rtt:.1f}ms > SLA {_RB_SLA}ms, "
                   f"trend={trend}, violations={violations}. "
                   f"Throttle eMBB {cur}→{new_rate}Mbit."),
    }

def _rb_restore(cur, stable_for):
    new_rate = min(_RB_RATE_MAX, cur + _RB_STEP_UP)
    conf = min(0.9, 0.5 + (stable_for - _RB_STAB_WIN) / 120)
    return {
        "action": "restore_embb",
        "new_rate": f"{new_rate}mbit", "new_rate_int": new_rate,
        "confidence": round(conf, 2),
        "reason": (f"Stable for {stable_for:.0f}s (>{_RB_STAB_WIN}s). "
                   f"Restoring eMBB {cur}→{new_rate}Mbit."),
    }

def _rb_no_action(cur, reason):
    return {
        "action": "no_action",
        "new_rate": f"{cur}mbit", "new_rate_int": cur,
        "confidence": 1.0, "reason": reason,
    }

# ── Performance sampler ────────────────────────────────────────────────────
class PerfSampler:
    def __init__(self):
        self._running = False
        self._cpu_samples, self._mem_samples = [], []
        self._thread = None

    def _read_cpu(self):
        with open("/proc/stat") as f:
            fields = [int(x) for x in f.readline().split()[1:]]
        idle = fields[3]; total = sum(fields)
        return total, idle

    def start(self):
        self._running = True
        self._prev_cpu = self._read_cpu()
        def _loop():
            while self._running:
                time.sleep(0.5)
                total, idle = self._read_cpu()
                pt, pi = self._prev_cpu
                dt = total - pt; di = idle - pi
                if dt > 0:
                    self._cpu_samples.append(round(100 * (1 - di/dt), 1))
                self._prev_cpu = (total, idle)
                with open("/proc/meminfo") as f:
                    lines = {l.split(":")[0]: int(l.split()[1])
                             for l in f if ":" in l}
                self._mem_samples.append(lines.get("MemAvailable", 0) // 1024)
        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread: self._thread.join(timeout=2)

    def summary(self):
        if not self._cpu_samples:
            return {"cpu_avg": 0, "cpu_peak": 0, "mem_used_mb": 0}
        with open("/proc/meminfo") as f:
            lines = {l.split(":")[0]: int(l.split()[1]) for l in f if ":" in l}
        total_mb = lines.get("MemTotal", 0) // 1024
        avail_mb = min(self._mem_samples) if self._mem_samples else 0
        return {
            "cpu_avg_pct":   round(sum(self._cpu_samples)/len(self._cpu_samples), 1),
            "cpu_peak_pct":  max(self._cpu_samples),
            "ram_used_mb":   total_mb - avail_mb,
            "ram_avail_mb":  avail_mb,
        }


# ── Ollama call ────────────────────────────────────────────────────────────
def call_ollama(system_prompt, user_prompt):
    payload = json.dumps({
        "model":   agentic_cfg.OLLAMA_MODEL,
        "stream":  False,
        "format":  "json",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "options": {"temperature": agentic_cfg.LLM_TEMPERATURE,
                    "num_predict": 400}   # raised for CoT fields
    }).encode()
    req = urllib.request.Request(
        f"{agentic_cfg.OLLAMA_HOST}/api/chat", data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=90) as resp:
        raw = json.loads(resp.read().decode())
    latency = time.time() - t0
    content = raw["message"]["content"].strip()
    parsed  = json.loads(content)
    tok_info = {
        "prompt_tokens": raw.get("prompt_eval_count", 0),
        "eval_tokens":   raw.get("eval_count", 0),
        "eval_rate_tps": round(raw.get("eval_count",0) /
                               max(raw.get("eval_duration",1)/1e9, 0.001), 1),
        "prefill_rate_tps": round(raw.get("prompt_eval_count",0) /
                                  max(raw.get("prompt_eval_duration",1)/1e9, 0.001), 1),
        "total_s":  round(raw.get("total_duration",0)/1e9, 2),
        "load_s":   round(raw.get("load_duration",0)/1e9, 3),
    }
    return parsed, latency, tok_info


# ── Rule-based simulation ─────────────────────────────────────────────────
class RuleBasedSim:
    """Simulate rule-based planning_agent with aligned config."""
    def __init__(self):
        self._agent = rb_planning.PlanningAgent()
        # Patch agent to use aligned config values
        import planning_agent as _pa
    
    def decide(self, metrics, state_override=None):
        """Build state dict as rule-based StateAgent would produce it."""
        import time as _t
        state = {
            "metrics":           metrics,
            "rtt_trend":         metrics.get("_rtt_trend", "stable"),
            "violation_count":   metrics.get("_violations", 0),
            "stable_for":        metrics.get("_stable_for", 0.0),
            "oscillation":       metrics.get("_oscillating", False),
            "current_embb_rate": metrics.get("_cur_rate", rb_cfg.EMBB_RATE_MAX),
            "last_action_time":  metrics.get("_last_action_ts", 0.0),
        }
        if state_override:
            state.update(state_override)
        # Use aligned thresholds
        import planning_agent as _pa
        orig_sla = rb_cfg.URLLC_RTT_SLA_MS
        # Already aligned to 20ms
        return self._agent.decide(state)


# ── Scenario definitions ───────────────────────────────────────────────────
SCENARIOS = {
    "S1_pre_congestion_trend": {
        "title": "Pre-Congestion Rising Trend (RTT within SLA, eMBB bursting)",
        "hypothesis": "Agent throttles pre-emptively; rule-based waits for threshold breach.",
        "metrics": {
            "urllc_rtt_99":       18.2,   # WITHIN 20ms SLA
            "urllc_rtt_max":      19.5,
            "urllc_dead_tunnels": 0,
            "urllc_fails":        0,
            "urllc_loss_rate":    0.0,
            "embb_tp_mbps":       168.0,  # high — actively bursting
            "embb_tp":            168e6,
            "embb_pkt_rate":      8400,   # high pkt rate
            "embb_load_fraction": 1.0,    # at session peak — HIGH
            "embb_pod_cpu_m":     780.0,
            "mmtc_pdr":           1.0,
            "mmtc_msgs_total":    3801,
            "cpu":                21,
            # State hints for rule-based
            "_rtt_trend":    "rising",
            "_violations":   0,         # no violations yet
            "_stable_for":   0.0,
            "_oscillating":  False,
            "_cur_rate":     1000,
            "_last_action_ts": 0.0,     # no cooldown
        },
        "state_snapshot": {
            "rtt_trend":        "rising",
            "violation_count":  0,
            "stable_for":       0.0,
            "oscillation":      False,
            "current_embb_rate":1000,
            "last_action":      "none",
            "urllc_replicas":   1,
            "embb_replicas":    1,
            "mmtc_replicas":    1,
        },
    },

    "S2_high_rtt_low_embb": {
        "title": "SLA Violated + eMBB Traffic LOW (Wrong-Lever Scenario B)",
        "hypothesis": "Rule-based throttles eMBB; agent should not (wrong lever).",
        "metrics": {
            "urllc_rtt_99":       22.4,   # VIOLATED (+2.4ms)
            "urllc_rtt_max":      25.1,
            "urllc_dead_tunnels": 0,
            "urllc_fails":        1,
            "urllc_loss_rate":    0.0,
            "embb_tp_mbps":       8.7,    # very low
            "embb_tp":            8.7e6,
            "embb_pkt_rate":      435,    # very low
            "embb_load_fraction": 0.05,   # 435/8400 — LOW (5% of session peak)
            "embb_pod_cpu_m":     82.0,   # low CPU — not bursting
            "mmtc_pdr":           1.0,
            "mmtc_msgs_total":    4102,
            "cpu":                17,
            "_rtt_trend":    "rising",
            "_violations":   2,
            "_stable_for":   0.0,
            "_oscillating":  False,
            "_cur_rate":     1000,
            "_last_action_ts": 0.0,
        },
        "state_snapshot": {
            "rtt_trend":        "rising",
            "violation_count":  2,
            "stable_for":       0.0,
            "oscillation":      False,
            "current_embb_rate":1000,
            "last_action":      "none",
            "urllc_replicas":   1,
            "embb_replicas":    1,
            "mmtc_replicas":    1,
        },
    },

    "S3_stable_restore": {
        "title": "Post-Throttle Stability — Restoration Decision",
        "hypothesis": "Both restore; agent may reason from memory, not just timer.",
        "metrics": {
            "urllc_rtt_99":       12.8,   # well within SLA
            "urllc_rtt_max":      14.2,
            "urllc_dead_tunnels": 0,
            "urllc_fails":        0,
            "urllc_loss_rate":    0.0,
            "embb_tp_mbps":       35.0,   # constrained by throttle
            "embb_tp":            35e6,
            "embb_pkt_rate":      1750,
            "embb_load_fraction": 0.21,   # 1750/8400 — MODERATE (constrained by tc 400Mbit)
            "embb_pod_cpu_m":     190.0,
            "mmtc_pdr":           1.0,
            "mmtc_msgs_total":    5201,
            "cpu":                14,
            "_rtt_trend":    "stable",
            "_violations":   3,
            "_stable_for":   78.0,        # > 60s stability window
            "_oscillating":  False,
            "_cur_rate":     400,          # currently throttled
            "_last_action_ts": time.time() - 80,  # cooldown expired
        },
        "state_snapshot": {
            "rtt_trend":        "stable",
            "violation_count":  3,
            "stable_for":       78.0,
            "oscillation":      False,
            "current_embb_rate":400,
            "last_action":      "throttle_embb",
            "urllc_replicas":   1,
            "embb_replicas":    1,
            "mmtc_replicas":    1,
        },
        # Memory context: prior throttle was effective
        "memory_entries": [
            {"rtt_ms": 24.1, "embb_rate": 1000, "action": "throttle_embb",
             "reasoning": "RTT violated, eMBB bursting at 8200 pkt/s (load_fraction=0.98)",
             "root_cause": "eMBB was bursting at near-peak load, causing GTP-U queue pressure",
             "confidence": 0.85, "rtt_after": 12.8},
        ],
    },
}


# ── Run audit ─────────────────────────────────────────────────────────────
def run_audit():
    results = {}

    print("=" * 70)
    print("AGENTIC ORCHESTRATOR — PHASE 1 POST-CHANGE AUDIT")
    print(f"Model: {agentic_cfg.OLLAMA_MODEL}  SLA: {agentic_cfg.URLLC_RTT_SLA_MS}ms")
    print("Changes: embb_load_fraction + root_cause_assessment + lever_validity")
    print("=" * 70)

    for scen_id, scen in SCENARIOS.items():
        print(f"\n{'─'*70}")
        print(f"SCENARIO: {scen['title']}")
        print(f"Hypothesis: {scen['hypothesis']}")
        print(f"{'─'*70}")

        metrics = scen["metrics"]
        state   = scen["state_snapshot"]

        # Build memory context
        memory = AgentMemory(maxlen=10)
        for entry in scen.get("memory_entries", []):
            memory.record(
                rtt=entry["rtt_ms"], embb_rate=entry["embb_rate"],
                action=entry["action"], reasoning=entry["reasoning"],
                confidence=entry["confidence"],
                root_cause=entry.get("root_cause", ""),
            )
            if entry.get("rtt_after"):
                memory.update_outcome(entry["rtt_after"])

        memory_text = memory.format_for_prompt(n=5)
        user_prompt = build_user_prompt(metrics, state, memory_text)

        frac  = metrics.get("embb_load_fraction")
        frac_str = f"{frac:.2f} ({frac*100:.0f}% of peak)" if frac is not None else "N/A"
        print(f"\n[INPUT] RTT={metrics['urllc_rtt_99']:.1f}ms  "
              f"eMBB={metrics['embb_tp_mbps']:.0f}Mbps  "
              f"pkt_rate={metrics['embb_pkt_rate']:.0f}  "
              f"load_fraction={frac_str}  "
              f"stable_for={state['stable_for']:.0f}s  "
              f"trend={state['rtt_trend']}")
        print(f"[STATE] cur_rate={state['current_embb_rate']}Mbit  "
              f"violations={state['violation_count']}  "
              f"oscillating={state['oscillation']}")
        print(f"[MEMORY] {memory_text.strip()}")

        # ── Rule-based decision ───────────────────────────────────────────
        rb_decision = rule_based_decide(metrics)
        print(f"\n[RULE-BASED]")
        print(f"  action={rb_decision['action']}  "
              f"rate={rb_decision.get('new_rate','?')}  "
              f"conf={rb_decision['confidence']:.2f}")
        print(f"  reason: {rb_decision['reason']}")

        # ── Agentic decision ──────────────────────────────────────────────
        print(f"\n[AGENTIC — calling Ollama {agentic_cfg.OLLAMA_MODEL}]")
        perf = PerfSampler()
        perf.start()
        t_wall = time.time()
        try:
            parsed, ollama_lat, tok = call_ollama(SYSTEM_PROMPT, user_prompt)
            wall_lat = time.time() - t_wall

            # Suppress patch_replicas
            action = parsed.get("action", "no_action")
            if action == "patch_replicas":
                print(f"  [patch_replicas suppressed]")
                action = "no_action"

            reason       = parsed.get("reasoning", parsed.get("reason", ""))
            confidence   = parsed.get("confidence", 0.0)
            new_rate     = parsed.get("new_rate_mbit", agentic_cfg.EMBB_RATE_MAX)
            root_cause   = parsed.get("root_cause_assessment", "")
            lever_valid  = parsed.get("lever_validity", "")

            # Detect contradiction
            _deny_kw = ["not embb", "embb is not", "embb not", "low load",
                        "nearly idle", "not the cause", "cannot help",
                        "wrong lever", "unlikely", "idle"]
            contradiction = (
                action == "throttle_embb"
                and bool(root_cause)
                and any(kw in root_cause.lower() for kw in _deny_kw)
            )

            print(f"  action={action}  rate={new_rate}Mbit  conf={confidence:.2f}  "
                  f"contradiction={'⚠️ YES' if contradiction else 'no'}")
            if root_cause:
                print(f"  root_cause:  {root_cause}")
            if lever_valid:
                print(f"  lever_valid: {lever_valid}")
            print(f"  reasoning:   {reason}")

        except Exception as e:
            print(f"  ERROR: {e}")
            parsed, ollama_lat, tok, wall_lat = {}, 0, {}, 0
            action, reason, confidence, new_rate = "ERROR", str(e), 0, 1000
            root_cause, lever_valid, contradiction = "", "", False
        finally:
            perf.stop()

        perf_data = perf.summary()

        # ── Performance metrics ───────────────────────────────────────────
        print(f"\n[PERFORMANCE]")
        print(f"  Wall latency:   {wall_lat:.2f}s")
        print(f"  Ollama total:   {tok.get('total_s','?')}s  "
              f"(load={tok.get('load_s','?')}s)")
        print(f"  Prefill rate:   {tok.get('prefill_rate_tps','?')} tok/s  "
              f"({tok.get('prompt_tokens','?')} tokens)")
        print(f"  Gen rate:       {tok.get('eval_rate_tps','?')} tok/s  "
              f"({tok.get('eval_tokens','?')} tokens)")
        print(f"  CPU avg/peak:   {perf_data['cpu_avg_pct']}% / {perf_data['cpu_peak_pct']}%")
        print(f"  RAM used:       {perf_data['ram_used_mb']} MB  "
              f"(avail: {perf_data['ram_avail_mb']} MB)")

        # ── Comparative analysis ──────────────────────────────────────────
        differ = (action != rb_decision["action"])
        print(f"\n[COMPARISON]")
        print(f"  Rule-based: {rb_decision['action']}  |  Agentic: {action}  |  "
              f"Differ: {'YES ← key differentiation' if differ else 'NO — same decision'}")

        results[scen_id] = {
            "rule_action":          rb_decision["action"],
            "agent_action":         action,
            "agent_reason":         reason,
            "agent_conf":           confidence,
            "root_cause":           root_cause,
            "lever_valid":          lever_valid,
            "contradiction":        contradiction,
            "differ":               differ,
            "wall_latency_s":       round(wall_lat, 2),
            "ollama_total_s":       tok.get("total_s", 0),
            "prompt_tokens":        tok.get("prompt_tokens", 0),
            "eval_tokens":          tok.get("eval_tokens", 0),
            "gen_rate_tps":         tok.get("eval_rate_tps", 0),
            "cpu_avg_pct":          perf_data["cpu_avg_pct"],
            "cpu_peak_pct":         perf_data["cpu_peak_pct"],
            "ram_used_mb":          perf_data["ram_used_mb"],
        }

    # ── Summary table ─────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"{'Scenario':<30} {'Rule':<18} {'Agent':<18} {'Differ'}")
    print("-" * 70)
    for sid, r in results.items():
        flag = "✅ DIFFERENT" if r["differ"] else "➖ SAME"
        print(f"  {sid[:28]:<30} {r['rule_action']:<18} {r['agent_action']:<18} {flag}")

    print(f"\n{'─'*70}")
    print("PERFORMANCE AVERAGES")
    lats = [r["wall_latency_s"] for r in results.values() if r["wall_latency_s"] > 0]
    cpus = [r["cpu_avg_pct"] for r in results.values()]
    rams = [r["ram_used_mb"] for r in results.values()]
    toks = [r["prompt_tokens"] for r in results.values() if r["prompt_tokens"] > 0]
    if lats: print(f"  Avg decision latency: {sum(lats)/len(lats):.1f}s  peak: {max(lats):.1f}s")
    if cpus: print(f"  Avg CPU during infer: {sum(cpus)/len(cpus):.1f}%  peak: {max(cpus):.1f}%")
    if rams: print(f"  Avg RAM used:         {sum(rams)/len(rams):.0f} MB")
    if toks: print(f"  Avg prompt tokens:    {sum(toks)/len(toks):.0f}")

    print(f"\n{'='*70}")
    print("RESEARCH ASSESSMENT")
    print(f"{'='*70}")
    differ_count = sum(1 for r in results.values() if r["differ"])
    print(f"Scenarios with different decisions: {differ_count}/{len(results)}")

    return results


if __name__ == "__main__":
    run_audit()
