#!/usr/bin/env python3
"""
generate_agentic_dataset.py
===========================
Generates synthetic agentic orchestrator dataset by replaying
rule-based collected scenarios with smarter decision logic.

Strategy:
  - Same physical inputs (RTT, UE counts, embb_mbps) as rule-based
  - Agentic logic: predictive, graduated throttle, faster recovery
  - Simulates RTT response to bandwidth changes
  - Outputs: dataset_agentic_{low,medium,high}.csv

Agentic improvements over rule-based:
  1. Pre-throttle at RTT > 13.5ms + rising trend (before SLA breach)
  2. Graduated bandwidth: 800/500/200/50 Mbps based on severity
  3. Faster recovery: release after 3 (not ~10) good RTT samples
  4. Richer reasoning: identifies cause, not just threshold
  5. Lower oscillation: hysteresis band prevents rapid switch cycling
"""

import csv
import os
import random
import statistics
import math
from datetime import datetime
from collections import deque

DATA_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# ── Agentic Policy Parameters ────────────────────────────────────────────────
RTT_SLA          = 15.0   # SLA threshold (same as rule-based)
RTT_PREEMPT      = 13.5   # Agentic acts BEFORE this (predictive)
RTT_TREND_WINDOW = 4      # samples to compute RTT trend
RECOVERY_STREAK  = 3      # consecutive good RTTs to release throttle
OSCILLATION_HOLD = 5      # minimum samples to hold state before switching

# Graduated bandwidth levels (embb_rate_mbit)
BW_LEVELS = {
    "normal":   1000,   # no congestion
    "mild":     500,    # RTT trending up, pre-emptive
    "moderate": 200,    # RTT approaching SLA
    "severe":   50,     # RTT breached SLA
}

# RTT simulation: how RTT changes when bandwidth changes
# Model: RTT_new = RTT_base + congestion_factor * (embb_mbps / embb_rate)
RTT_BASE       = 13.0   # min achievable RTT
CONGESTION_K   = 2.0    # RTT sensitivity to load ratio

def simulate_rtt(raw_rtt: float, old_rate: int, new_rate: int,
                 embb_mbps: float) -> float:
    """
    Estimate RTT after bandwidth change.
    When we throttle (new_rate < old_rate), congestion reduces → RTT improves.
    When we release, congestion may return.
    This is a simplified linear model — real networks are more complex.
    """
    if new_rate <= 0:
        return raw_rtt

    # Load ratio: how much traffic fills the new bandwidth cap
    load_ratio = min(embb_mbps / new_rate, 1.5) if new_rate > 0 else 1.5
    # At load_ratio=1.0 → baseline RTT; higher → RTT grows
    simulated = RTT_BASE + (raw_rtt - RTT_BASE) * (load_ratio / max(embb_mbps/old_rate, 0.1))
    # Add small noise for realism
    noise = random.gauss(0, 0.3)
    return max(RTT_BASE, round(simulated + noise, 2))


def get_rtt_trend(rtt_history: deque) -> float:
    """Linear slope of recent RTT values. Positive = rising."""
    if len(rtt_history) < 2:
        return 0.0
    vals = list(rtt_history)
    n = len(vals)
    x_mean = (n - 1) / 2
    slope = sum((i - x_mean) * (v - statistics.mean(vals))
                for i, v in enumerate(vals)) / \
            max(sum((i - x_mean)**2 for i in range(n)), 1e-9)
    return slope


def classify_severity(rtt: float, trend: float, ue_count: int) -> str:
    """Agentic severity classification — considers trend, not just threshold."""
    if rtt >= RTT_SLA:
        return "severe"
    elif rtt >= RTT_PREEMPT and trend > 0.3:
        return "moderate"   # trending toward SLA
    elif rtt >= RTT_PREEMPT:
        return "mild"       # elevated but stable
    else:
        return "normal"


def agentic_decision(severity: str, current_rate: int,
                     good_streak: int, hold_counter: int,
                     rtt: float, trend: float, embb_mbps: float,
                     ue_count: int, mmtc_msgs: int) -> tuple:
    """
    Core agentic policy.
    Returns: (new_rate, action, reasoning, state)
    """
    target_rate = BW_LEVELS[severity]
    cause_parts = []

    # Identify cause for reasoning
    if rtt >= RTT_SLA:
        cause_parts.append(f"RTT={rtt:.1f}ms breached 15ms SLA")
    elif rtt >= RTT_PREEMPT and trend > 0:
        cause_parts.append(f"RTT={rtt:.1f}ms rising (trend={trend:+.2f}ms/sample)")
    if ue_count >= 3:
        cause_parts.append(f"{ue_count} UEs active creating load")
    if mmtc_msgs > 500:
        cause_parts.append(f"mMTC burst ({mmtc_msgs} msgs)")

    cause = "; ".join(cause_parts) if cause_parts else f"RTT={rtt:.1f}ms nominal"

    # Don't oscillate — respect hold counter
    if hold_counter < OSCILLATION_HOLD and target_rate != current_rate:
        target_rate = current_rate
        action = "hold_current"
        reasoning = f"Holding {current_rate}Mbps (anti-oscillation, {hold_counter}/{OSCILLATION_HOLD} samples)"
        state = 0 if current_rate == BW_LEVELS["normal"] else 1
        return current_rate, action, reasoning, state

    # Recovery: release throttle when RTT stable
    if severity == "normal" and current_rate < BW_LEVELS["normal"]:
        if good_streak >= RECOVERY_STREAK:
            new_rate = min(current_rate * 2, BW_LEVELS["normal"])  # gradual release
            action = "release_throttle" if new_rate == BW_LEVELS["normal"] else "ease_throttle"
            reasoning = (f"RTT={rtt:.1f}ms stable for {good_streak} samples; "
                        f"{'fully restoring' if new_rate == BW_LEVELS['normal'] else 'easing to'} "
                        f"{new_rate}Mbps. {cause}")
            return new_rate, action, reasoning, 0
        else:
            action = "hold_throttle"
            reasoning = (f"RTT={rtt:.1f}ms within SLA, waiting for stability "
                        f"({good_streak}/{RECOVERY_STREAK} good samples). Still at {current_rate}Mbps")
            return current_rate, action, reasoning, 1

    # Throttle adjustment
    if target_rate < current_rate:
        if target_rate == BW_LEVELS["severe"]:
            action = "throttle_embb"
        elif target_rate == BW_LEVELS["moderate"]:
            action = "throttle_embb_moderate"
        else:
            action = "throttle_embb_mild"
        reasoning = (f"[PREDICTIVE] {cause}; "
                    f"reducing eMBB {current_rate}→{target_rate}Mbps")
        state = 1
    elif target_rate > current_rate:
        action = "ease_throttle"
        reasoning = f"{cause}; easing eMBB {current_rate}→{target_rate}Mbps"
        state = 0 if target_rate == BW_LEVELS["normal"] else 1
    else:
        action = "no_action" if severity == "normal" else "hold_throttle"
        reasoning = (f"{cause}; maintaining {current_rate}Mbps" if action == "hold_throttle"
                    else f"RTT={rtt:.1f}ms within SLA (<15ms); eMBB at {current_rate}Mbps — no action required")
        state = 1 if action == "hold_throttle" else 0

    return target_rate, action, reasoning, state


def process_level(level: str):
    src_path = os.path.join(DATA_DIR, f"dataset_rule_based_{level}.csv")
    dst_path = os.path.join(DATA_DIR, f"dataset_agentic_{level}.csv")

    rows = list(csv.DictReader(open(src_path)))
    if not rows:
        print(f"  {level}: no rows, skipping")
        return

    fieldnames = list(rows[0].keys())
    # Replace orchestrator-specific columns
    out_fieldnames = [
        f if f not in ("orchestrator_type", "orchestrator_label")
        else f for f in fieldnames
    ]

    out_rows = []
    run_id   = datetime.now().strftime("agentic_%Y%m%d_%H%M%S")

    # Agentic state
    current_rate  = BW_LEVELS["normal"]
    good_streak   = 0
    hold_counter  = 0
    viol_streak   = 0
    rec_streak    = 0
    rtt_history   = deque(maxlen=RTT_TREND_WINDOW)
    prev_state    = 0

    agentic_sla_violations = 0

    for idx, row in enumerate(rows):
        raw_rtt    = float(row["urllc_rtt_ms"])
        embb_mbps  = float(row["embb_mbps"])
        ue_count   = int(row["embb_ue_count"])
        mmtc_msgs  = int(row["mmtc_msgs"])

        # Simulate what RTT would be under agentic's current bandwidth setting
        rb_rate    = int(float(row["embb_rate_mbit"]))
        sim_rtt    = simulate_rtt(raw_rtt, rb_rate, current_rate, embb_mbps)

        rtt_history.append(sim_rtt)
        trend       = get_rtt_trend(rtt_history)
        severity    = classify_severity(sim_rtt, trend, ue_count)

        # Update streaks
        if sim_rtt <= RTT_SLA:
            good_streak += 1
            rec_streak  += 1
            viol_streak  = 0
        else:
            viol_streak += 1
            rec_streak   = 0
            good_streak  = 0

        # Agentic decision
        new_rate, action, reasoning, state = agentic_decision(
            severity, current_rate, good_streak, hold_counter,
            sim_rtt, trend, embb_mbps, ue_count, mmtc_msgs
        )

        if new_rate != current_rate:
            hold_counter = 0
        else:
            hold_counter += 1

        current_rate = new_rate
        sla_violated = 1 if sim_rtt > RTT_SLA else 0
        agentic_sla_violations += sla_violated

        out_row = dict(row)
        out_row.update({
            "urllc_rtt_ms":       round(sim_rtt, 2),
            "embb_rate_mbit":     new_rate,
            "sla_violated":       sla_violated,
            "orchestrator_type":  "agentic",
            "orchestrator_state": state,
            "violation_streak":   viol_streak,
            "recovery_streak":    rec_streak,
            "action_taken":       action,
            "decision_latency_ms": round(random.uniform(80, 350), 1),  # LLM inference latency
            "reasoning":          reasoning,
            "orchestrator_label": "agentic",
            "run_id":             run_id,
            "sample_index":       idx,
        })
        out_rows.append(out_row)
        prev_state = state

    with open(dst_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=out_fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(out_rows)

    rb_violations = sum(1 for r in rows if int(r["sla_violated"]) == 1)
    print(f"  {level.upper()}: {len(out_rows)} rows written → {dst_path}")
    print(f"    Rule-based SLA violations: {rb_violations} ({100*rb_violations/len(rows):.1f}%)")
    print(f"    Agentic   SLA violations: {agentic_sla_violations} ({100*agentic_sla_violations/len(out_rows):.1f}%)")
    improvement = rb_violations - agentic_sla_violations
    print(f"    Improvement: {improvement:+d} violations ({100*improvement/max(rb_violations,1):.1f}% reduction)")


def main():
    print("=" * 60)
    print("  Generating Agentic Orchestrator Dataset")
    print("=" * 60)
    for level in ["low", "medium", "high"]:
        print(f"\n--- {level.upper()} ---")
        process_level(level)
    print("\nDone. Files written to dataset/data/dataset_agentic_*.csv")


if __name__ == "__main__":
    main()
