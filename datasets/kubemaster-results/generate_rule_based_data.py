#!/usr/bin/env python3
"""
generate_rule_based_data.py
============================
Generates synthetic Rule-Based orchestrator CSVs for all three traffic levels.
Simulates the deterministic threshold policy:
  - RTT > 15ms → throttle eMBB to 50Mbit (binary)
  - Stable for 10 good samples → restore to 1000Mbit (binary)
  - No memory, no reasoning, no WLA

Output: results/datasets/dataset_rule_based_{low,medium,high}.csv

Traffic profiles:
  low    → 1 UE/slice, light load, rare congestion bursts
  medium → 3 UEs/slice, organic oscillating congestion (hardest to manage)
  high   → 3 UEs/slice + iperf3 80Mbps, immediately saturated then throttled
"""
import csv, os, random, math
from pathlib import Path
from datetime import datetime, timedelta
from collections import deque

random.seed(2024)

OUT_DIR = Path(__file__).parent / "datasets"
OUT_DIR.mkdir(exist_ok=True)

RTT_SLA        = 15.0
EMBB_RATE_MAX  = 1000
EMBB_RATE_FLOOR= 50
RECOVERY_STREAK= 10      # rule-based waits longer before restoring

COLUMNS = [
    "timestamp","datetime","urllc_rtt_ms","urllc_rtt_max_ms","urllc_fails",
    "embb_mbps","embb_rate_mbit","mmtc_msgs","mmtc_rate_per_min",
    "sla_violated","orchestrator_type","orchestrator_state",
    "violation_streak","recovery_streak","action_taken",
    "decision_latency_ms","reasoning",
    "node_cpu_percent","node_memory_percent",
    "traffic_level","orchestrator_label",
    "embb_ue_count","urllc_ue_count","mmtc_ue_count",
    "run_id","sample_index",
]

# ── Traffic profile parameters ───────────────────────────────────────────────
PROFILES = {
    "low": {
        "n_rows":       8000,
        "embb_ue":      1, "urllc_ue": 1, "mmtc_ue": 1,
        "rtt_base":     13.2,  "rtt_noise": 0.6,
        "congestion_p": 0.04,  "burst_rtt": (16, 22),
        "embb_base":    120,   "embb_noise": 40,
        "mmtc_base":    80,    "cpu_base": 18,
    },
    "medium": {
        "n_rows":       9000,
        "embb_ue":      3, "urllc_ue": 3, "mmtc_ue": 3,
        "rtt_base":     13.8,  "rtt_noise": 1.2,
        "congestion_p": 0.12,  "burst_rtt": (15.5, 35),
        "embb_base":    310,   "embb_noise": 80,
        "mmtc_base":    240,   "cpu_base": 42,
    },
    "high": {
        "n_rows":       10000,
        "embb_ue":      3, "urllc_ue": 3, "mmtc_ue": 5,
        "rtt_base":     14.5,  "rtt_noise": 0.4,
        "congestion_p": 0.06,  "burst_rtt": (15, 20),
        "embb_base":    160,   "embb_noise": 30,
        "mmtc_base":    400,   "cpu_base": 78,
    },
}


def derive_action(rtt, prev_state, cur_state, vstreak, rstreak, cur_rate):
    """Rule-based action derivation (deterministic)."""
    if rtt == 0:
        return "invalid_data", "RTT=0ms — PDU session drop detected"
    if cur_state == 1 and prev_state != 1:
        return ("throttle_embb",
                f"RTT={rtt:.1f}ms exceeded {RTT_SLA}ms SLA threshold "
                f"(streak={vstreak}); throttling eMBB to {cur_rate}Mbit")
    if cur_state == 0 and prev_state == 1:
        return ("release_throttle",
                f"RTT={rtt:.1f}ms below threshold for {rstreak} samples; "
                f"restoring eMBB to {cur_rate}Mbit")
    if cur_state == 1:
        return ("hold_throttle",
                f"RTT={rtt:.1f}ms still elevated (streak={vstreak}); "
                f"maintaining throttle at {cur_rate}Mbit")
    return ("no_action",
            f"RTT={rtt:.1f}ms within SLA (<{RTT_SLA}ms); "
            f"eMBB at {cur_rate}Mbit — no action required")


def generate_rtt_series(n, profile, cur_rate_series):
    """Generate RTT timeseries with congestion bursts."""
    base   = profile["rtt_base"]
    noise  = profile["rtt_noise"]
    cp     = profile["congestion_p"]
    bmin, bmax = profile["burst_rtt"]

    rtts        = []
    in_burst    = False
    burst_len   = 0
    burst_remaining = 0

    for i in range(n):
        rate = cur_rate_series[i] if i < len(cur_rate_series) else EMBB_RATE_MAX
        # Throttling reduces RTT
        throttle_factor = 0.88 if rate == EMBB_RATE_FLOOR else 1.0

        if in_burst:
            burst_rtt = random.uniform(bmin, bmax) * throttle_factor
            rtts.append(round(burst_rtt + random.gauss(0, noise*0.5), 2))
            burst_remaining -= 1
            if burst_remaining <= 0:
                in_burst = False
        else:
            if random.random() < cp and not in_burst:
                in_burst = True
                burst_remaining = random.randint(3, 18)
            rtt = base * throttle_factor + random.gauss(0, noise)
            rtts.append(round(max(12.5, rtt), 2))

    return rtts


def generate_level(level: str):
    p   = PROFILES[level]
    n   = p["n_rows"]
    run_id = f"rb_{level}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Pre-compute bandwidth series based on rule-based policy
    cur_rate    = EMBB_RATE_MAX
    rates       = []
    # placeholder first pass with random RTT
    tmp_rtts    = [p["rtt_base"] + random.gauss(0, p["rtt_noise"]) for _ in range(n)]

    good_streak = 0
    viol_streak = 0
    prev_state  = 0

    rate_series = []
    for rtt in tmp_rtts:
        if rtt > RTT_SLA:
            cur_rate = EMBB_RATE_FLOOR
        elif good_streak >= RECOVERY_STREAK and cur_rate == EMBB_RATE_FLOOR:
            cur_rate = EMBB_RATE_MAX
        rate_series.append(cur_rate)
        if rtt > RTT_SLA:
            viol_streak += 1; good_streak = 0
        else:
            good_streak += 1; viol_streak = 0

    # Final RTT series (rate-aware)
    rtts = generate_rtt_series(n, p, rate_series)

    # Build rows
    rows         = []
    cur_rate     = EMBB_RATE_MAX
    good_streak  = 0
    viol_streak  = 0
    prev_state   = 0
    t0           = datetime.now() - timedelta(hours=2)

    for i, rtt in enumerate(rtts):
        ts = t0 + timedelta(seconds=i*2)

        sla_v = 1 if rtt > RTT_SLA else 0
        if sla_v:
            cur_rate = EMBB_RATE_FLOOR
            viol_streak += 1; good_streak = 0
        else:
            good_streak += 1; viol_streak = 0
            if good_streak >= RECOVERY_STREAK and cur_rate == EMBB_RATE_FLOOR:
                cur_rate = EMBB_RATE_MAX

        state = 1 if cur_rate == EMBB_RATE_FLOOR else 0
        action, reasoning = derive_action(rtt, prev_state, state, viol_streak, good_streak, cur_rate)

        # eMBB throughput (lower when throttled)
        load_factor = (cur_rate / EMBB_RATE_MAX)
        embb_mbps   = round((p["embb_base"] + random.gauss(0, p["embb_noise"])) * load_factor, 1)
        embb_mbps   = max(0, embb_mbps)

        # mMTC
        mmtc_msgs = max(0, int(p["mmtc_base"] + random.gauss(0, p["mmtc_base"]*0.2)))
        mmtc_rate = round(mmtc_msgs / 2.0, 1)

        # CPU
        cpu = round(p["cpu_base"] + random.gauss(0, 5), 1)
        cpu = max(5, min(99, cpu))
        mem = round(70 + random.gauss(0, 5), 1)
        mem = max(40, min(95, mem))

        rows.append({
            "timestamp":         ts.timestamp(),
            "datetime":          ts.strftime("%Y-%m-%d %H:%M:%S"),
            "urllc_rtt_ms":      rtt,
            "urllc_rtt_max_ms":  round(rtt + random.uniform(0.5, 8.0), 1),
            "urllc_fails":       1 if rtt > 20 else 0,
            "embb_mbps":         embb_mbps,
            "embb_rate_mbit":    cur_rate,
            "mmtc_msgs":         mmtc_msgs,
            "mmtc_rate_per_min": mmtc_rate,
            "sla_violated":      sla_v,
            "orchestrator_type": "rule_based",
            "orchestrator_state":state,
            "violation_streak":  viol_streak,
            "recovery_streak":   good_streak,
            "action_taken":      action,
            "decision_latency_ms": round(random.uniform(0.1, 0.9), 3),
            "reasoning":         reasoning,
            "node_cpu_percent":  cpu,
            "node_memory_percent": mem,
            "traffic_level":     level,
            "orchestrator_label":"rule_based",
            "embb_ue_count":     p["embb_ue"],
            "urllc_ue_count":    p["urllc_ue"],
            "mmtc_ue_count":     p["mmtc_ue"],
            "run_id":            run_id,
            "sample_index":      i,
        })
        prev_state = state

    out_path = OUT_DIR / f"dataset_rule_based_{level}.csv"
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    violations = sum(1 for r in rows if r["sla_violated"])
    throttled  = sum(1 for r in rows if r["orchestrator_state"])
    print(f"  {level.upper():6s}: {len(rows):,} rows → {out_path.name}")
    print(f"           SLA violations: {violations} ({100*violations/len(rows):.1f}%)")
    print(f"           Throttled:      {throttled} ({100*throttled/len(rows):.1f}%)")
    actions = {}
    for r in rows:
        a = r["action_taken"]
        actions[a] = actions.get(a, 0) + 1
    for a, c in sorted(actions.items(), key=lambda x: -x[1]):
        print(f"             {a:<25} {c:>5} ({100*c/len(rows):.1f}%)")


def main():
    print("=" * 55)
    print("  Generating Rule-Based Datasets")
    print(f"  Output: {OUT_DIR}")
    print("=" * 55)
    for level in ["low", "medium", "high"]:
        print(f"\n── {level.upper()} ──")
        generate_level(level)
    print(f"\n✅  Done. Files in results/datasets/")


if __name__ == "__main__":
    main()
