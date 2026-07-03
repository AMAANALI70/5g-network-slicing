#!/usr/bin/env python3
"""
clean_dataset.py
================
Surgically cleans all three traffic-level CSVs without recollection.

Fixes applied:
  1. Remove RTT=0 / all-UE=0 rows (session drops / PDU failures)
  2. Remove RTT statistical outliers per level (Q3 + 3×IQR fence)
  3. Forward-fill embb_mbps=0 gaps (HLS log timing artifact, not real zero)
  4. Remove rows where UE count is below minimum for that traffic level
     (transient session instability mid-run)
  5. Backfill action_taken / reasoning for pre-fix empty rows
  6. Reindex sample_index sequentially after cleaning
  7. Write final clean files + print report
"""

import csv
import os
import shutil
import statistics
from collections import Counter

DATA_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Minimum UE counts that must be present for a row to be "valid" for that level
MIN_UE = {
    "low":    {"embb": 1, "urllc": 1, "mmtc": 1},
    "medium": {"embb": 2, "urllc": 2, "mmtc": 2},   # allow 1 of 3 to drop
    "high":   {"embb": 2, "urllc": 2, "mmtc": 2},
}

def derive_action(row: dict, prev_state: int) -> tuple:
    try:
        rtt     = float(row.get("urllc_rtt_ms", 0))
        state   = int(row.get("orchestrator_state", 0))
        rate    = int(float(row.get("embb_rate_mbit", 1000)))
        vstreak = int(float(row.get("violation_streak", 0)))
        rstreak = int(float(row.get("recovery_streak", 0)))
        sla_v   = int(row.get("sla_violated", 0))
    except Exception:
        return "no_action", "parse error"

    if rtt == 0.0:
        return "invalid_data", f"RTT=0ms — PDU session drop"
    if state == 1 and prev_state != 1:
        return ("throttle_embb",
                f"RTT={rtt:.1f}ms exceeded 15ms SLA threshold (streak={vstreak}); throttling eMBB to {rate}Mbps")
    if state == 0 and prev_state == 1:
        return ("release_throttle",
                f"RTT={rtt:.1f}ms below 15ms threshold (recovery_streak={rstreak}); restoring eMBB to {rate}Mbps")
    if state == 1:
        return ("hold_throttle",
                f"RTT={rtt:.1f}ms still elevated (streak={vstreak}); maintaining throttle at {rate}Mbps")
    if state == 0 and sla_v == 1:
        return ("no_action",
                f"RTT={rtt:.1f}ms exceeds 15ms — orchestrator in grace period (streak={vstreak})")
    return ("no_action",
            f"RTT={rtt:.1f}ms within SLA (<15ms); eMBB at {rate}Mbps — no action required")


def iqr_fence(values: list, k: float = 3.0) -> float:
    q1 = statistics.quantiles(values, n=4)[0]
    q3 = statistics.quantiles(values, n=4)[2]
    return q3 + k * (q3 - q1)


def clean_level(level: str) -> dict:
    path = os.path.join(DATA_DIR, f"dataset_rule_based_{level}.csv")
    rows = list(csv.DictReader(open(path)))
    original_count = len(rows)
    fieldnames = list(rows[0].keys()) if rows else []

    stats = {
        "original": original_count,
        "removed_rtt0": 0,
        "removed_ue0": 0,
        "removed_ue_low": 0,
        "removed_rtt_outlier": 0,
        "embb_ffill": 0,
        "action_backfill": 0,
    }

    # ── Step 1: Compute RTT fence from valid rows ─────────────────────────────
    rtt_valid = [float(r["urllc_rtt_ms"]) for r in rows if float(r["urllc_rtt_ms"]) > 0]
    fence = iqr_fence(rtt_valid) if len(rtt_valid) > 4 else 999
    min_ue = MIN_UE[level]

    # ── Step 2: Filter rows ───────────────────────────────────────────────────
    kept = []
    prev_embb_mbps = 0.0
    prev_state = -1

    for r in rows:
        rtt  = float(r.get("urllc_rtt_ms", 0))
        eu   = int(r.get("embb_ue_count", 0))
        uu   = int(r.get("urllc_ue_count", 0))
        mu   = int(r.get("mmtc_ue_count", 0))

        # Remove RTT=0 (session drop)
        if rtt == 0.0:
            stats["removed_rtt0"] += 1
            continue

        # Remove all-UE=0 (full session down)
        if eu == 0 and uu == 0 and mu == 0:
            stats["removed_ue0"] += 1
            continue

        # Remove insufficient UE counts for this traffic level
        if eu < min_ue["embb"] or uu < min_ue["urllc"]:
            stats["removed_ue_low"] += 1
            continue

        # Remove RTT outliers (beyond Q3 + 3×IQR)
        if rtt > fence:
            stats["removed_rtt_outlier"] += 1
            continue

        # ── Forward-fill embb_mbps=0 (HLS log timing gap) ────────────────────
        embb_raw = float(r.get("embb_mbps", 0))
        if embb_raw == 0.0 and prev_embb_mbps > 0:
            r["embb_mbps"] = str(round(prev_embb_mbps, 2))
            stats["embb_ffill"] += 1
        elif embb_raw > 0:
            prev_embb_mbps = embb_raw

        # ── Backfill empty action_taken / reasoning ───────────────────────────
        cur_state = int(r.get("orchestrator_state", 0))
        existing_action = r.get("action_taken", "").strip()
        if existing_action == "":
            action, reasoning = derive_action(r, prev_state)
            r["action_taken"] = action
            r["reasoning"]    = reasoning
            stats["action_backfill"] += 1

        prev_state = cur_state
        kept.append(r)

    # ── Step 3: Reindex sample_index ─────────────────────────────────────────
    for i, r in enumerate(kept):
        r["sample_index"] = str(i)

    # ── Step 4: Write clean file ──────────────────────────────────────────────
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept)

    stats["final"] = len(kept)
    stats["removed_total"] = original_count - len(kept)
    stats["fence"] = round(fence, 1)
    return stats


def main():
    # Backup first
    archive = os.path.join(DATA_DIR, "archive_preclean")
    os.makedirs(archive, exist_ok=True)
    for level in ["low", "medium", "high"]:
        src = os.path.join(DATA_DIR, f"dataset_rule_based_{level}.csv")
        shutil.copy2(src, os.path.join(archive, f"dataset_rule_based_{level}_preclean.csv"))
    print(f"Backups saved to {archive}/\n")

    total_before = total_after = 0

    for level in ["low", "medium", "high"]:
        print(f"{'='*60}")
        print(f"  Cleaning: {level.upper()}")
        print(f"{'='*60}")
        s = clean_level(level)
        total_before += s["original"]
        total_after  += s["final"]

        print(f"  Original rows:          {s['original']:>7,}")
        print(f"  RTT=0 removed:          {s['removed_rtt0']:>7,}")
        print(f"  All-UE=0 removed:       {s['removed_ue0']:>7,}")
        print(f"  Insufficient UE removed:{s['removed_ue_low']:>7,}")
        print(f"  RTT outlier removed:    {s['removed_rtt_outlier']:>7,}  (fence={s['fence']}ms)")
        print(f"  ──────────────────────────────")
        print(f"  Total removed:          {s['removed_total']:>7,}  ({100*s['removed_total']/s['original']:.1f}%)")
        print(f"  Final clean rows:       {s['final']:>7,}")
        print(f"  embb_mbps forward-fill: {s['embb_ffill']:>7,}")
        print(f"  action_taken backfill:  {s['action_backfill']:>7,}")
        print()

        # Post-clean stats
        rows = list(csv.DictReader(open(
            os.path.join(DATA_DIR, f"dataset_rule_based_{level}.csv"))))
        rtts = [float(r["urllc_rtt_ms"]) for r in rows]
        actions = Counter(r["action_taken"] for r in rows)
        states  = Counter(int(r["orchestrator_state"]) for r in rows)
        print(f"  POST-CLEAN RTT: min={min(rtts):.1f}  max={max(rtts):.1f}  "
              f"avg={statistics.mean(rtts):.1f}  stdev={statistics.stdev(rtts):.1f}ms")
        print(f"  SLA violations: {sum(1 for r in rows if int(r['sla_violated'])==1)} "
              f"({100*sum(1 for r in rows if int(r['sla_violated'])==1)/len(rows):.1f}%)")
        print(f"  State=THROTTLED: {states[1]} ({100*states[1]/len(rows):.1f}%)")
        print(f"  Actions:")
        for a, c in actions.most_common():
            label = a or "(empty)"
            print(f"    {label:<35} {c:>6}  ({100*c/len(rows):.1f}%)")
        print()

    print(f"{'='*60}")
    print(f"  TOTAL: {total_before:,} → {total_after:,} rows "
          f"(removed {total_before-total_after:,} = {100*(total_before-total_after)/total_before:.1f}%)")
    print(f"  Dataset is ready for ML inference / comparison.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
