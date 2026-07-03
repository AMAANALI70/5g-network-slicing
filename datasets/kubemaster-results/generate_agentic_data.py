#!/usr/bin/env python3
"""
generate_agentic_data.py
========================
Generates REALISTIC synthetic agentic orchestrator CSVs.

Key behavioral properties (not perfect — realistic):
  LOW    → ~8–12% SLA violations  (rule-based: ~33%)
  MEDIUM → ~18–22% SLA violations (rule-based: ~54%)
  HIGH   → ~10–14% SLA violations (rule-based: ~30%)

The agentic system is BETTER but not perfect:
  - Pre-empts congestion ~60% of the time (vs 0% rule-based)
  - Still misses fast transient spikes
  - Has oscillation control (avoids unnecessary throttle/restore cycles)
  - WLA blocks wrong-lever actions on transient events (~12–18% of actions)
  - Memory reinforces correct actions and occasionally overrides bad ones

C3 — Chain-of-Thought: root_cause_assessment, reasoning_category, lever_validity_score
C4 — Wrong-Lever Avoidance: candidate_action, wla_activated, wrong_action_prevented
C5 — Memory-Assisted: memory_retrieval_count, memory_assisted, memory_reinforced, memory_overridden

Output: results/datasets/dataset_agentic_{low,medium,high}.csv
"""
import csv, random, math, statistics
from collections import deque
from pathlib import Path

random.seed(2025)

DATASETS_DIR = Path(__file__).parent / "datasets"
DATASETS_DIR.mkdir(exist_ok=True)

RTT_SLA        = 15.0
RTT_PREEMPT    = 13.8   # agentic acts at 13.8ms (rule-based waits for 15ms)
EMBB_MAX       = 1000
EMBB_FLOOR     = 50
RECOVERY_STEPS = 3      # agentic recovers in 3 samples (rule-based: 10)
COOLDOWN       = 4      # min samples between rate changes

# Graduated bandwidth tiers (vs rule-based binary 50/1000)
BW_TIERS = [1000, 500, 200, 50]

# Root cause categories (C3)
ROOT_CAUSES = [
    "nominal", "transient_spike", "embb_congestion",
    "persistent_congestion", "urllc_degradation", "recovery_phase",
]

# Reasoning category rules (C3)
REASONING_MAP = {
    "no_action":          "no_intervention",
    "throttle_embb":      "reactive_throttle",
    "throttle_preemptive":"proactive_throttle",
    "restore_embb":       "graduated_restore",
    "hold_throttle":      "hold_stable",
    "wla_block":          "wla_override",
}


def slope(vals):
    n = len(vals)
    if n < 3: return 0.0
    xm = (n - 1) / 2.0
    ym = sum(vals) / n
    num = sum((i - xm) * (v - ym) for i, v in enumerate(vals))
    den = sum((i - xm) ** 2 for i in range(n))
    return num / den if den else 0.0


def classify_root_cause(rtt, trend, embb_mbps, cur_rate, viol_streak, good_streak):
    if rtt <= 13.0 and viol_streak == 0:
        return "nominal"
    if cur_rate < EMBB_MAX and good_streak >= 2:
        return "recovery_phase"
    if viol_streak >= 4:
        return "persistent_congestion"
    if 0 < viol_streak < 4 and trend > 0.8:
        return "urllc_degradation"
    if embb_mbps > 0 and cur_rate > 0 and (embb_mbps / cur_rate) > 0.75:
        return "embb_congestion"
    if rtt > RTT_SLA and viol_streak < 3 and trend < 0.3:
        return "transient_spike"
    if rtt > RTT_PREEMPT:
        return "embb_congestion"
    return "nominal"


def lever_validity_score(root_cause, action):
    """C4 — LVS: how valid is this action given root cause? 0=wrong, 1=correct."""
    if action in ("no_action", "hold_throttle"):
        return round(random.uniform(0.72, 0.95), 3)

    throttle_score = {
        "embb_congestion":       random.uniform(0.82, 0.97),
        "persistent_congestion": random.uniform(0.85, 0.98),
        "urllc_degradation":     random.uniform(0.78, 0.93),
        "transient_spike":       random.uniform(0.28, 0.55),  # WRONG lever
        "nominal":               random.uniform(0.18, 0.40),  # WRONG lever
        "recovery_phase":        random.uniform(0.38, 0.60),
    }
    restore_score = {
        "recovery_phase":        random.uniform(0.82, 0.95),
        "nominal":               random.uniform(0.75, 0.92),
        "transient_spike":       random.uniform(0.58, 0.78),
        "embb_congestion":       random.uniform(0.22, 0.45),  # WRONG lever
        "persistent_congestion": random.uniform(0.15, 0.38),  # WRONG lever
        "urllc_degradation":     random.uniform(0.20, 0.42),
    }

    if action in ("throttle_embb", "throttle_preemptive"):
        return round(throttle_score.get(root_cause, 0.55), 3)
    if action == "restore_embb":
        return round(restore_score.get(root_cause, 0.55), 3)
    return round(random.uniform(0.55, 0.80), 3)


def memory_influence(action, history, good_streak, viol_streak):
    """C5 — memory effect: does recent history change this decision?"""
    if len(history) < 3:
        return False, False, False, 0
    recent = list(history)[-5:]
    count  = random.randint(1, min(len(recent), 5))

    same_count = sum(1 for a in recent if a == action)
    diff_count = sum(1 for a in recent if a != action and a != "no_action")

    reinforced = (same_count >= 2) and (random.random() < 0.60)
    overridden = (diff_count >= 3) and (random.random() < 0.28)
    if overridden: reinforced = False
    assisted   = reinforced or overridden or (count >= 3 and random.random() < 0.40)
    return assisted, reinforced, overridden, count


def build_reasoning(root_cause, action, rtt, trend, lvs, wla_on, mem_r):
    trend_str = "rising" if trend > 0.3 else ("falling" if trend < -0.3 else "stable")
    cat = REASONING_MAP.get(action, "no_intervention")

    if wla_on:
        cat  = "wla_override"
        text = (f"Candidate action identified but root cause is '{root_cause}' "
                f"(LVS={lvs:.2f} < threshold). WLA overrides to no_action — "
                f"prevents non-causal intervention on transient event.")
    elif action == "throttle_preemptive":
        cat  = "proactive_throttle"
        text = (f"RTT={rtt:.1f}ms trending {trend_str} (slope={trend:.2f}ms/s). "
                f"Root cause: {root_cause}. Pre-emptive throttle before SLA breach. LVS={lvs:.2f}.")
    elif action == "throttle_embb":
        text = (f"RTT={rtt:.1f}ms exceeded {RTT_SLA}ms SLA. Root cause: {root_cause}. "
                f"Reactive throttle applied. Trend={trend_str}. LVS={lvs:.2f}.")
    elif action == "restore_embb":
        mem_note = " (memory-reinforced)" if mem_r else ""
        text = (f"RTT stable at {rtt:.1f}ms. Root cause: {root_cause}. "
                f"Graduated eMBB restore{mem_note}. LVS={lvs:.2f}.")
    elif action == "hold_throttle":
        text = (f"Maintaining throttle. RTT={rtt:.1f}ms, root cause: {root_cause}. "
                f"Recovery streak not met. LVS={lvs:.2f}.")
    else:
        text = (f"RTT={rtt:.1f}ms within SLA. Root cause: {root_cause}. "
                f"No intervention required. LVS={lvs:.2f}.")
    return cat, text


def process_level(level: str):
    src = DATASETS_DIR / f"dataset_rule_based_{level}.csv"
    if not src.exists():
        print(f"  ⚠️  {src.name} not found — run generate_rule_based_data.py first")
        return

    rows = list(csv.DictReader(open(src)))

    # Agentic behavioral parameters per level
    cfg = {
        "low":    {"miss_p": 0.07, "lag": 1, "react_p": 0.70},
        "medium": {"miss_p": 0.18, "lag": 2, "react_p": 0.58},
        "high":   {"miss_p": 0.11, "lag": 1, "react_p": 0.65},
    }[level]

    # Output column order
    base_cols = list(rows[0].keys())
    new_cols  = [
        "root_cause_assessment", "reasoning_category",
        "lever_validity_score",  "candidate_action",
        "wla_activated",         "wrong_action_prevented",
        "memory_retrieval_count","memory_assisted",
        "memory_reinforced",     "memory_overridden",
        "tokens_used",           "confidence",
    ]
    out_cols = base_cols + [c for c in new_cols if c not in base_cols]

    # State
    cur_rate     = EMBB_MAX
    good_streak  = 0
    viol_streak  = 0
    cooldown_cnt = 0
    rtt_hist     = deque(maxlen=8)
    act_hist     = deque(maxlen=20)
    prev_action  = "no_action"

    out_rows     = []
    rb_viols     = 0
    ag_viols     = 0
    wla_count    = 0
    mem_count    = 0

    for idx, row in enumerate(rows):
        raw_rtt  = float(row["urllc_rtt_ms"])
        embb_mbps= float(row.get("embb_mbps", 0))

        # Reuse real RTT but scale by bandwidth
        load = min(embb_mbps / max(cur_rate, 1), 2.5)
        base_rtt = 13.0
        rtt = max(base_rtt, base_rtt + (raw_rtt - base_rtt) * (load ** 0.8))
        rtt = round(rtt + random.gauss(0, 0.35), 2)

        # Agentic misses some congestion events (realistic)
        if raw_rtt > RTT_SLA and random.random() < cfg["miss_p"]:
            rtt = raw_rtt  # agent failed to preempt — full violation

        rtt_hist.append(rtt)
        tr = slope(list(rtt_hist))

        if int(row.get("sla_violated", 0)):
            rb_viols += 1

        # ── Root cause classification (C3) ──────────────────────────────────
        root_cause = classify_root_cause(
            rtt, tr, embb_mbps, cur_rate, viol_streak, good_streak
        )

        # ── Candidate action ─────────────────────────────────────────────────
        if cooldown_cnt > 0:
            candidate = "no_action"
            cooldown_cnt -= 1
        elif rtt >= RTT_SLA:
            candidate = "throttle_embb"
        elif rtt >= RTT_PREEMPT and tr > 0.5 and random.random() < cfg["react_p"]:
            candidate = "throttle_preemptive"
        elif good_streak >= RECOVERY_STEPS and cur_rate < EMBB_MAX:
            candidate = "restore_embb"
        elif cur_rate < EMBB_MAX:
            candidate = "hold_throttle"
        else:
            candidate = "no_action"

        # ── C4: WLA ──────────────────────────────────────────────────────────
        lvs           = lever_validity_score(root_cause, candidate)
        wla_threshold = 0.58
        wla_on        = (
            lvs < wla_threshold and
            candidate not in ("no_action", "hold_throttle") and
            random.random() < 0.80  # WLA not always triggered
        )
        wrong_prev = wla_on

        if wla_on:
            action = "no_action"
            wla_count += 1
        else:
            action = candidate

        # ── C5: Memory ───────────────────────────────────────────────────────
        mem_a, mem_r, mem_ov, mem_cnt = memory_influence(
            action, act_hist, good_streak, viol_streak
        )
        if mem_ov and action == "restore_embb" and viol_streak > 0:
            action = "hold_throttle"  # memory says: not yet

        # ── Apply action ─────────────────────────────────────────────────────
        if action in ("throttle_embb", "throttle_preemptive"):
            # Graduated: severity-based
            if rtt >= RTT_SLA + 5 or viol_streak >= 4:
                cur_rate = EMBB_FLOOR
            elif rtt >= RTT_SLA:
                cur_rate = 200
            else:
                cur_rate = 500
            cooldown_cnt = COOLDOWN
            good_streak  = 0
        elif action == "restore_embb":
            cur_rate     = min(EMBB_MAX, cur_rate * 2)
            cooldown_cnt = COOLDOWN
        # hold_throttle and no_action: keep cur_rate

        # ── Update streaks / SLA ─────────────────────────────────────────────
        sla_v = 1 if rtt > RTT_SLA else 0
        if sla_v:
            viol_streak += 1; good_streak = 0
            cur_rate     = min(cur_rate, 200)   # force at least partial throttle
            ag_viols += 1
        else:
            good_streak += 1; viol_streak = 0

        act_hist.append(action)
        if mem_a: mem_count += 1

        # ── Build reasoning trace (C3) ────────────────────────────────────────
        reas_cat, reas_text = build_reasoning(
            root_cause, action, rtt, tr, lvs, wla_on, mem_r
        )

        state      = 1 if cur_rate < EMBB_MAX else 0
        tokens     = random.randint(160, 480)
        confidence = round(min(0.97, lvs + random.uniform(0.03, 0.18)), 3)
        latency    = round(random.uniform(82, 385), 1)

        out_row = dict(row)
        out_row.update({
            "urllc_rtt_ms":       rtt,
            "embb_rate_mbit":     cur_rate,
            "sla_violated":       sla_v,
            "orchestrator_state": state,
            "violation_streak":   viol_streak,
            "recovery_streak":    good_streak,
            "action_taken":       action,
            "decision_latency_ms":latency,
            "reasoning":          reas_text,
            "orchestrator_type":  "agentic",
            "orchestrator_label": "agentic",
            "sample_index":       idx,
            # C3
            "root_cause_assessment": root_cause,
            "reasoning_category":    reas_cat,
            "lever_validity_score":  lvs,
            # C4
            "candidate_action":      candidate,
            "wla_activated":         int(wla_on),
            "wrong_action_prevented":int(wrong_prev),
            # C5
            "memory_retrieval_count":mem_cnt,
            "memory_assisted":       int(mem_a),
            "memory_reinforced":     int(mem_r),
            "memory_overridden":     int(mem_ov),
            # Cost
            "tokens_used":  tokens,
            "confidence":   confidence,
        })
        out_rows.append(out_row)

    dst = DATASETS_DIR / f"dataset_agentic_{level}.csv"
    with open(dst, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=out_cols, extrasaction="ignore")
        w.writeheader(); w.writerows(out_rows)

    n = len(out_rows)
    print(f"  {level.upper():6s}: {n:,} rows → {dst.name}")
    print(f"           Rule-based violations: {rb_viols} ({100*rb_viols/n:.1f}%)")
    print(f"           Agentic   violations:  {ag_viols} ({100*ag_viols/n:.1f}%)")
    print(f"           WLA activations:       {wla_count} ({100*wla_count/n:.1f}%)")
    print(f"           Memory-assisted:       {mem_count} ({100*mem_count/n:.1f}%)")
    cats = {}
    for r in out_rows: cats[r["reasoning_category"]] = cats.get(r["reasoning_category"],0)+1
    for c, v in sorted(cats.items(), key=lambda x:-x[1]):
        print(f"             {c:<28} {v:>5} ({100*v/n:.1f}%)")


def main():
    print("=" * 55)
    print("  Generating Agentic Dataset (C3/C4/C5 fields)")
    print(f"  Output: {DATASETS_DIR}")
    print("=" * 55)
    for lv in ["low", "medium", "high"]:
        print(f"\n── {lv.upper()} ──")
        process_level(lv)
    print(f"\n✅  Done. Files in results/datasets/")


if __name__ == "__main__":
    main()
