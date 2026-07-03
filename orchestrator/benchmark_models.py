#!/usr/bin/env python3
"""
benchmark_models.py — Compare LLM candidates using the actual orchestration prompt.
Tests:
  Scenario A: SLA violated, eMBB actively bursting → correct: throttle_embb
  Scenario B: SLA violated, eMBB traffic LOW      → correct: no_action (wrong lever)
  Scenario C: Stable after throttle               → correct: restore_embb
  Scenario D: Oscillation context                 → correct: no_action
"""
import json, time, urllib.request, urllib.parse, sys

# Import the actual system prompt used in production
import importlib.util, os
_spec = importlib.util.spec_from_file_location("prompt", os.path.join(os.path.dirname(__file__), "prompt.py"))
_prompt_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_prompt_mod)
SYSTEM_PROMPT = _prompt_mod.SYSTEM_PROMPT

OLLAMA_URL = "http://localhost:11434/api/chat"

SCENARIOS = {
    "A_burst_throttle": {
        "desc": "SLA violated + eMBB bursting → CORRECT: throttle_embb",
        "expected": "throttle_embb",
        "user": """CURRENT NETWORK STATE (snapshot at decision time):

  URLLC (latency-critical):
    RTT avg:       18.50ms     ❌ VIOLATED (+3.5ms)
    RTT max:       22.10ms
    RTT trend:     rising
    Dead tunnels:  0/3    OK
    Tunnel fails:  2 (cumulative since last log line)
    Loss rate:     0.0% of tunnels unreachable

  eMBB (throughput):
    Throughput:    187.3Mbps   ✅ OK
    Packet rate:   9350 pkt/s  ← congestion indicator
    Pod CPU:       790mCPU      ← UPF-eMBB processing load
    tc rate limit: 1000Mbit

  mMTC (IoT delivery):
    PDR (tunnels): 1.00     ✅ OK
    Msgs total:    4821

  Infrastructure:
    Master CPU:    22%
    Replicas:      urllc-app=1  embb-app=1  mmtc-app=1

  Orchestration:
    Violation cnt: 3 (cumulative)
    Stable for:    0s
    Oscillating:   False
    Last action:   none

RECENT DECISION HISTORY (newest first, includes outcomes):
(no prior decisions)

Based on the above, identify the root cause of any SLA issue and choose the most appropriate action.
Output JSON only."""
    },
    "B_highRTT_lowEMBB": {
        "desc": "SLA slightly violated + eMBB traffic LOW → CORRECT: no_action (wrong lever)",
        "expected": "no_action",
        "user": """CURRENT NETWORK STATE (snapshot at decision time):

  URLLC (latency-critical):
    RTT avg:       16.80ms     ❌ VIOLATED (+1.8ms)
    RTT max:       19.20ms
    RTT trend:     stable
    Dead tunnels:  0/3    OK
    Tunnel fails:  1 (cumulative since last log line)
    Loss rate:     0.0% of tunnels unreachable

  eMBB (throughput):
    Throughput:    11.2Mbps   ✅ OK
    Packet rate:   541 pkt/s  ← congestion indicator
    Pod CPU:       95mCPU      ← UPF-eMBB processing load
    tc rate limit: 1000Mbit

  mMTC (IoT delivery):
    PDR (tunnels): 1.00     ✅ OK
    Msgs total:    3104

  Infrastructure:
    Master CPU:    18%
    Replicas:      urllc-app=1  embb-app=1  mmtc-app=1

  Orchestration:
    Violation cnt: 1 (cumulative)
    Stable for:    0s
    Oscillating:   False
    Last action:   none

RECENT DECISION HISTORY (newest first, includes outcomes):
(no prior decisions)

Based on the above, identify the root cause of any SLA issue and choose the most appropriate action.
Output JSON only."""
    },
    "C_stable_restore": {
        "desc": "Post-throttle, RTT stable for 90s → CORRECT: restore_embb",
        "expected": "restore_embb",
        "user": """CURRENT NETWORK STATE (snapshot at decision time):

  URLLC (latency-critical):
    RTT avg:       12.10ms     ✅ WITHIN SLA
    RTT max:       13.80ms
    RTT trend:     falling
    Dead tunnels:  0/3    OK
    Tunnel fails:  0 (cumulative since last log line)
    Loss rate:     0.0% of tunnels unreachable

  eMBB (throughput):
    Throughput:    38.5Mbps   ✅ OK
    Packet rate:   1920 pkt/s  ← congestion indicator
    Pod CPU:       210mCPU      ← UPF-eMBB processing load
    tc rate limit: 400Mbit

  mMTC (IoT delivery):
    PDR (tunnels): 1.00     ✅ OK
    Msgs total:    5510

  Infrastructure:
    Master CPU:    15%
    Replicas:      urllc-app=1  embb-app=1  mmtc-app=1

  Orchestration:
    Violation cnt: 2 (cumulative)
    Stable for:    90s
    Oscillating:   False
    Last action:   throttle_embb

RECENT DECISION HISTORY (newest first, includes outcomes):
[90s ago] throttle_embb → 400Mbit | RTT before=18.5ms | RTT after=12.1ms | outcome: ✅ RTT improved

Based on the above, identify the root cause of any SLA issue and choose the most appropriate action.
Output JSON only."""
    },
    "D_oscillation_hold": {
        "desc": "Rapid throttle/restore switching → CORRECT: no_action (hold)",
        "expected": "no_action",
        "user": """CURRENT NETWORK STATE (snapshot at decision time):

  URLLC (latency-critical):
    RTT avg:       15.40ms     ❌ VIOLATED (+0.4ms)
    RTT max:       16.10ms
    RTT trend:     stable
    Dead tunnels:  0/3    OK
    Tunnel fails:  0 (cumulative since last log line)
    Loss rate:     0.0% of tunnels unreachable

  eMBB (throughput):
    Throughput:    95.0Mbps   ✅ OK
    Packet rate:   4750 pkt/s  ← congestion indicator
    Pod CPU:       420mCPU      ← UPF-eMBB processing load
    tc rate limit: 700Mbit

  mMTC (IoT delivery):
    PDR (tunnels): 1.00     ✅ OK
    Msgs total:    4201

  Infrastructure:
    Master CPU:    20%
    Replicas:      urllc-app=1  embb-app=1  mmtc-app=1

  Orchestration:
    Violation cnt: 5 (cumulative)
    Stable for:    8s
    Oscillating:   True
    Last action:   restore_embb

RECENT DECISION HISTORY (newest first, includes outcomes):
[8s ago]  restore_embb  → 700Mbit  | RTT before=13.1ms | RTT after=15.4ms | outcome: ❌ RTT worsened
[22s ago] throttle_embb → 400Mbit  | RTT before=17.2ms | RTT after=13.1ms | outcome: ✅ RTT improved
[35s ago] restore_embb  → 700Mbit  | RTT before=12.8ms | RTT after=17.2ms | outcome: ❌ RTT worsened

Based on the above, identify the root cause of any SLA issue and choose the most appropriate action.
Output JSON only."""
    },
}

VALID_ACTIONS = {"throttle_embb", "restore_embb", "no_action", "patch_replicas"}

def call_ollama(model: str, system: str, user: str) -> tuple[dict, float, int, int]:
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "options": {"temperature": 0.2, "num_predict": 200}
    }
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(OLLAMA_URL, data=data,
                                  headers={"Content-Type": "application/json"})
    t0   = time.time()
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = json.loads(resp.read().decode())
    latency = time.time() - t0
    content = raw["message"]["content"]
    try:
        parsed = json.loads(content)
    except Exception:
        parsed = {"_parse_error": content[:200]}
    prompt_tokens = raw.get("prompt_eval_count", 0)
    eval_tokens   = raw.get("eval_count", 0)
    return parsed, latency, prompt_tokens, eval_tokens


def run_benchmark(models: list[str]):
    results = {}
    for model in models:
        print(f"\n{'='*60}")
        print(f"MODEL: {model}")
        print(f"{'='*60}")
        results[model] = {}
        for scen_id, scen in SCENARIOS.items():
            print(f"\n  Scenario {scen_id}: {scen['desc']}")
            try:
                parsed, latency, p_tok, e_tok = call_ollama(
                    model, SYSTEM_PROMPT, scen["user"]
                )
                action    = parsed.get("action", "MISSING")
                reasoning = parsed.get("reasoning", parsed.get("reason", ""))[:100]
                rate      = parsed.get("new_rate_mbit", "?")
                conf      = parsed.get("confidence", "?")
                correct   = (action == scen["expected"])
                status    = "✅ CORRECT" if correct else f"❌ WRONG (expected {scen['expected']})"
                print(f"    Action:    {action}  {status}")
                print(f"    Rate:      {rate} Mbit")
                print(f"    Reasoning: {reasoning}")
                print(f"    Latency:   {latency:.2f}s   prompt={p_tok}tok  eval={e_tok}tok")
                results[model][scen_id] = {
                    "action": action, "correct": correct,
                    "latency_s": round(latency, 2),
                    "reasoning": reasoning,
                    "prompt_tokens": p_tok, "eval_tokens": e_tok
                }
            except Exception as e:
                print(f"    ERROR: {e}")
                results[model][scen_id] = {"action": "ERROR", "correct": False,
                                            "latency_s": 0, "error": str(e)}

    # Summary table
    print(f"\n\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"{'Model':<20} {'Scen':<25} {'Correct':<10} {'Latency':>10}")
    print("-"*70)
    for model, scens in results.items():
        score = sum(1 for v in scens.values() if v.get("correct"))
        total = len(scens)
        for sid, v in scens.items():
            c = "✅" if v.get("correct") else "❌"
            print(f"  {model:<18} {sid:<25} {c:<10} {v.get('latency_s', 0):>8.1f}s")
        print(f"  {'TOTAL':18} {'':25} {score}/{total}")
        print()
    return results


if __name__ == "__main__":
    models = ["qwen2.5:3b", "llama3.2:3b"]
    if len(sys.argv) > 1:
        models = sys.argv[1:]
    run_benchmark(models)
