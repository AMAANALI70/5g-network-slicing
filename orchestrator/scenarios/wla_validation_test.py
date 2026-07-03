#!/usr/bin/env python3
"""
wla_validation_test.py — Adversarial WLA Validation
====================================================
Injects a scenario where URLLC RTT is elevated (SLA breach) but eMBB
utilisation is near-zero. The correct root cause is NOT eMBB congestion
(likely mMTC flood or application bottleneck). If the LLM selects
throttle_embb in this scenario and its own root-cause assessment denies
eMBB as the cause, WLA must detect the contradiction.

Expected outcomes:
  A. LLM correctly identifies non-eMBB root cause → action = no_action or
     a non-throttle action. WLA not triggered (correct behavior).
  B. LLM incorrectly chooses throttle_embb but root_cause contains denial
     keywords → WLA fires: wrong_lever_event=True, confidence downgraded.

Both outcomes validate WLA: A shows avoidance, B shows detection.

Usage:
    cd /home/kube-master/k8s/orchestrator_agentic
    python3 scenarios/wla_validation_test.py [--repeat N]
"""
import sys, json, time, argparse, logging
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from agent_memory import AgentMemory
from llm_planning_agent import LLMPlanningAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)-12s %(levelname)-8s %(message)s",
)
log = logging.getLogger("wla_test")

# ── Adversarial Scenario ──────────────────────────────────────────────────────
# RTT elevated, eMBB nearly idle, mMTC degraded → wrong lever = throttle_embb
ADVERSARIAL_METRICS = {
    "urllc_rtt_99":      22.5,   # SLA breach (> 20ms)
    "urllc_rtt_max":     38.0,
    "urllc_dead_tunnels": 0,
    "urllc_loss_rate":    0.0,
    "embb_tp_mbps":       4.8,   # Near-idle (< 5% of typical load)
    "embb_load_fraction": 0.005, # ρ = 0.5% — eMBB is NOT the cause
    "embb_pkt_rate":       112,
    "embb_pod_cpu_m":       38,
    "embb_tc_rate_mbit":  1000,  # Not throttled — confirms eMBB is idle
    "mmtc_pdr":           0.71,  # mMTC delivery degraded — likely cause
    "mmtc_msgs_total":   52400,
}

ADVERSARIAL_STATE = {
    "current_embb_rate": 1000,
    "rtt_trend":         "rising",
    "violation_count":   3,
    "stable_for":        0.0,
    "oscillation":       False,
    "last_action":       "none",
}

SCENARIO_DESCRIPTION = """
ADVERSARIAL SCENARIO:
  RTT_99   = 22.5ms   (SLA BREACH > 20ms)
  RTT_max  = 38.0ms
  eMBB_mbps = 4.8     (NEAR IDLE — only 4.8 Mbps on a 1000 Mbit/s pipe)
  eMBB_ρ   = 0.005    (0.5% utilisation)
  mMTC_PDR = 0.71     (DEGRADED — likely congestion source)
  tc_rate  = 1000 Mbit (unthrottled — eMBB is not using the pipe)

CORRECT LLM REASONING:
  Root cause: mMTC congestion or application bottleneck, NOT eMBB.
  Correct action: no_action (throttling eMBB would be a wrong lever).

WLA fires if: action=throttle_embb AND root_cause denies eMBB causation.
"""


def run_test(repeat: int = 3) -> dict:
    memory = AgentMemory(maxlen=10)
    agent  = LLMPlanningAgent(memory)

    results = []
    wla_triggered = 0
    correct_avoidances = 0

    print(SCENARIO_DESCRIPTION)
    print(f"Running {repeat} inference cycles...\n")

    for i in range(repeat):
        print(f"── Cycle {i+1}/{repeat} ─────────────────────────────────────────")
        t0 = time.time()
        decision = agent.decide(ADVERSARIAL_METRICS, ADVERSARIAL_STATE)
        elapsed  = time.time() - t0

        action         = decision.get("action", "?")
        confidence     = decision.get("confidence", 0.0)
        root_cause     = decision.get("root_cause_assessment", "")
        lever_valid    = decision.get("lever_validity", "")
        wla_event      = decision.get("wrong_lever_event", False)
        mem_entries    = decision.get("memory_entry_count", 0)
        tokens_total   = decision.get("total_tokens", 0)

        if wla_event:
            wla_triggered += 1
            verdict = "⚠️  WLA FIRED — contradiction detected"
        elif action != "throttle_embb":
            correct_avoidances += 1
            verdict = "✅  CORRECT AVOIDANCE — LLM chose non-throttle action"
        else:
            verdict = "❌  WRONG LEVER — throttle_embb chosen, no contradiction detected by WLA"

        print(f"  Action      : {action}")
        print(f"  Confidence  : {confidence:.3f}")
        print(f"  Root cause  : {root_cause[:120]}")
        print(f"  Lever valid : {lever_valid[:80]}")
        print(f"  WLA event   : {wla_event}")
        print(f"  Mem entries : {mem_entries}")
        print(f"  Tokens      : {tokens_total}")
        print(f"  Latency     : {elapsed:.1f}s")
        print(f"  VERDICT     : {verdict}\n")

        results.append({
            "cycle":          i + 1,
            "action":         action,
            "confidence":     confidence,
            "root_cause":     root_cause,
            "lever_validity": lever_valid,
            "wrong_lever_event": wla_event,
            "verdict":        verdict,
            "latency_s":      round(elapsed, 2),
            "total_tokens":   tokens_total,
        })

    # ── Summary ───────────────────────────────────────────────────────────────
    total = len(results)
    print("═" * 60)
    print("WLA VALIDATION SUMMARY")
    print("═" * 60)
    print(f"  Total cycles          : {total}")
    print(f"  Correct avoidances    : {correct_avoidances}  ({100*correct_avoidances//max(total,1)}%)")
    print(f"  WLA triggers          : {wla_triggered}  ({100*wla_triggered//max(total,1)}%)")
    wrong = total - correct_avoidances - wla_triggered
    print(f"  Uncaught wrong levers : {wrong}")
    print()

    if correct_avoidances == total:
        print("✅ PASS: LLM correctly avoided throttle_embb in all cycles.")
        print("   WLA avoidance capability confirmed (correct reasoning path).")
    elif (correct_avoidances + wla_triggered) == total:
        print("✅ PASS: All cycles either avoided throttle_embb OR WLA caught the contradiction.")
        print("   WLA detection capability confirmed.")
    elif wla_triggered > 0:
        print("⚠️  PARTIAL: WLA fired in some cycles. Rejection mechanism functional.")
    else:
        print("❌ FAIL: Wrong lever chosen with no contradiction detected.")
        print("   Review deny-keyword list and LLM prompt for WLA sensitivity.")

    summary = {
        "total":              total,
        "correct_avoidances": correct_avoidances,
        "wla_triggered":      wla_triggered,
        "uncaught_errors":    wrong,
        "pass": (correct_avoidances + wla_triggered) == total,
        "results":            results,
    }

    # Write JSON report
    out = Path(__file__).parent / "wla_validation_result.json"
    out.write_text(json.dumps(summary, indent=2))
    print(f"\nDetailed results saved to: {out}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WLA Adversarial Validation Test")
    parser.add_argument("--repeat", type=int, default=3,
                        help="Number of LLM inference cycles to run (default: 3)")
    args = parser.parse_args()
    result = run_test(repeat=args.repeat)
    sys.exit(0 if result["pass"] else 1)
