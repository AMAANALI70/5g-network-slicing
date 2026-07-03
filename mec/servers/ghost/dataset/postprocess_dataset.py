#!/usr/bin/env python3
"""
postprocess_dataset.py
======================
Fixes quality issues in already-collected dataset CSVs:

1. Backfills action_taken / reasoning for rows where action_taken == ""
   (collected before the collector fix was applied)
2. Marks RTT=0 rows as "invalid_data" (PDU session drops)
3. Fixes reasoning string for RTT>15ms but state=NORMAL (grace period)
4. Removes rows where all UE counts are 0 (full session drop)
5. Reports a quality summary

Usage:
    python3 dataset/postprocess_dataset.py
    python3 dataset/postprocess_dataset.py --dry-run   # show stats only
    python3 dataset/postprocess_dataset.py --remove-invalid  # also drop invalid rows
"""

import argparse
import csv
import os
import shutil
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

def derive_action_and_reasoning(row: dict, prev_state: int) -> tuple:
    """Replicate collector logic to derive action_taken + reasoning."""
    try:
        rtt        = float(row.get("urllc_rtt_ms", 0))
        fails      = int(row.get("urllc_fails", 0))
        state      = int(row.get("orchestrator_state", 0))
        embb_rate  = int(float(row.get("embb_rate_mbit", 1000)))
        viol_streak= int(float(row.get("violation_streak", 0)))
        rec_streak = int(float(row.get("recovery_streak", 0)))
        sla_viol   = int(row.get("sla_violated", 0))
    except (ValueError, TypeError):
        return "invalid_data", "Parse error in row"

    # RTT=0 = PDU session drop
    if rtt == 0.0:
        return (
            "invalid_data",
            f"RTT=0ms with fails={fails} — PDU session drop / UE disconnect detected"
        )

    if state == 1 and prev_state != 1:
        return (
            "throttle_embb",
            f"RTT={rtt:.1f}ms exceeded 15ms SLA threshold "
            f"(streak={viol_streak}); throttling eMBB to {embb_rate}Mbps"
        )
    elif state == 0 and prev_state == 1:
        return (
            "release_throttle",
            f"RTT={rtt:.1f}ms below 15ms threshold "
            f"(recovery_streak={rec_streak}); restoring eMBB to {embb_rate}Mbps"
        )
    elif state == 1:
        return (
            "hold_throttle",
            f"RTT={rtt:.1f}ms still elevated "
            f"(streak={viol_streak}); maintaining throttle at {embb_rate}Mbps"
        )
    elif state == 0 and sla_viol == 1:
        return (
            "no_action",
            f"RTT={rtt:.1f}ms exceeds 15ms but orchestrator in recovery grace period "
            f"(streak={viol_streak}); monitoring"
        )
    else:
        return (
            "no_action",
            f"RTT={rtt:.1f}ms within SLA (<15ms); eMBB at {embb_rate}Mbps — no action required"
        )


def is_invalid_row(row: dict) -> bool:
    """True if row represents a PDU session drop / invalid measurement."""
    try:
        rtt   = float(row.get("urllc_rtt_ms", 0))
        eu    = int(row.get("embb_ue_count", 0))
        uu    = int(row.get("urllc_ue_count", 0))
        mu    = int(row.get("mmtc_ue_count", 0))
    except (ValueError, TypeError):
        return True
    return rtt == 0.0 or (eu == 0 and uu == 0 and mu == 0)


def postprocess(csv_path: str, remove_invalid: bool, dry_run: bool):
    print(f"\n{'='*60}")
    print(f"Processing: {csv_path}")
    print(f"{'='*60}")

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    total = len(rows)
    stats = {
        "backfilled_action": 0,
        "fixed_reasoning":   0,
        "marked_invalid":    0,
        "removed_invalid":   0,
        "all_ue_zero":       0,
    }

    prev_state = -1
    out_rows = []

    for row in rows:
        # Track state for transition detection
        try:
            cur_state = int(row.get("orchestrator_state", 0))
        except (ValueError, TypeError):
            cur_state = 0

        # Detect invalid rows
        invalid = is_invalid_row(row)
        if int(row.get("embb_ue_count", 0)) == 0 and \
           int(row.get("urllc_ue_count", 0)) == 0 and \
           int(row.get("mmtc_ue_count", 0)) == 0:
            stats["all_ue_zero"] += 1

        if invalid:
            stats["marked_invalid"] += 1
            if remove_invalid:
                stats["removed_invalid"] += 1
                prev_state = cur_state
                continue
            # Mark but keep
            if row.get("action_taken", "") != "invalid_data":
                row["action_taken"] = "invalid_data"
                row["reasoning"] = (
                    f"RTT=0ms or all-UE-count=0 — PDU session drop; excluded from training"
                )
            out_rows.append(row)
            prev_state = cur_state
            continue

        # Backfill empty action_taken
        existing_action = row.get("action_taken", "").strip()
        if existing_action == "":
            action, reasoning = derive_action_and_reasoning(row, prev_state)
            row["action_taken"] = action
            row["reasoning"]    = reasoning
            stats["backfilled_action"] += 1

        # Fix wrong reasoning (RTT>15 but says "within SLA")
        elif "within SLA" in row.get("reasoning", "") and \
             float(row.get("urllc_rtt_ms", 0)) > 15.0:
            action, reasoning = derive_action_and_reasoning(row, prev_state)
            row["reasoning"] = reasoning
            stats["fixed_reasoning"] += 1

        out_rows.append(row)
        prev_state = cur_state

    # Report
    print(f"  Total rows:          {total:,}")
    print(f"  Backfilled actions:  {stats['backfilled_action']:,}")
    print(f"  Fixed reasoning:     {stats['fixed_reasoning']:,}")
    print(f"  Marked invalid:      {stats['marked_invalid']:,} (RTT=0 or UE=0)")
    print(f"  All-UE-zero rows:    {stats['all_ue_zero']:,}")
    if remove_invalid:
        print(f"  REMOVED invalid:     {stats['removed_invalid']:,}")
    print(f"  Output rows:         {len(out_rows):,}")

    # Action distribution after fix
    from collections import Counter
    actions = Counter(r.get("action_taken","") for r in out_rows)
    print(f"\n  Action distribution after fix:")
    for a, c in actions.most_common():
        label = a if a else "(empty)"
        print(f"    {label:<25} {c:>5}  ({100*c/len(out_rows):.1f}%)")

    if dry_run:
        print(f"\n  [DRY RUN] No changes written.")
        return

    # Backup original
    backup = csv_path.replace(".csv", f"_backup_{datetime.now().strftime('%H%M%S')}.csv")
    shutil.copy2(csv_path, backup)
    print(f"\n  Backup saved: {backup}")

    # Write fixed file
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"  Fixed file written: {csv_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Show stats without writing changes")
    parser.add_argument("--remove-invalid", action="store_true",
                        help="Remove RTT=0 and all-UE=0 rows from output")
    parser.add_argument("--files", nargs="*",
                        help="Specific CSV files to process (default: all in data/)")
    args = parser.parse_args()

    if args.files:
        csv_files = args.files
    else:
        csv_files = [
            os.path.join(DATA_DIR, f)
            for f in os.listdir(DATA_DIR)
            if f.endswith(".csv") and "backup" not in f
        ]

    if not csv_files:
        print(f"No CSV files found in {DATA_DIR}")
        return

    for path in sorted(csv_files):
        postprocess(path, remove_invalid=args.remove_invalid, dry_run=args.dry_run)

    print(f"\n{'='*60}")
    print("Postprocessing complete.")
    print("Run with --remove-invalid to strip PDU-drop rows from final dataset.")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
