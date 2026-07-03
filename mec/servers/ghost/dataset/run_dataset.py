#!/usr/bin/env python3
"""
Dataset Run Master Script
==========================
Runs the full dataset collection for rule-based OR agentic orchestrator.
Collects 3 separate CSVs (low / medium / high traffic), 10,000 rows each.

Watchdog: Detects UE disconnection (zero/invalid metrics) in real-time,
          restarts UE sessions automatically, and resumes collection.

At 2s interval: 10,000 rows ≈ 5.6 hours per level → ~17 hours total.
Run this overnight with nohup.

Usage:
  # Rule-based (Phase 3):
  nohup python3 dataset/run_dataset.py --label rule_based > /tmp/dataset_run_rule.log 2>&1 &

  # Agentic (Phase 5):
  nohup python3 dataset/run_dataset.py --label agentic > /tmp/dataset_run_agentic.log 2>&1 &

  # Quick test (100 rows each, ~3 min total):
  python3 dataset/run_dataset.py --label rule_based --target-rows 100 --test
"""
import argparse
import csv
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

# ── Config ───────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

DEFAULT_TARGET_ROWS      = 10_000
COLLECTION_INTERVAL      = 2       # seconds per sample
WARMUP_SECONDS           = 60      # wait after setting traffic level
LEVEL_ORDER              = ["low", "medium", "high"]

# UERANSIM connection
UERANSIM_IP   = "192.168.49.139"
UERANSIM_USER = "shinegami"
UERANSIM_PASS = "123"

# Watchdog settings
WATCHDOG_CHECK_INTERVAL  = 20      # check CSV validity every N seconds
INVALID_STREAK_THRESHOLD = 5       # consecutive invalid rows to trigger recovery
MAX_RESTARTS_PER_LEVEL   = 10      # give up after this many recovery attempts
RESTART_COOLDOWN         = 5       # seconds before triggering recovery
POST_RESTART_WARMUP      = 45      # seconds after tunnel restoration before collecting


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[run_dataset {ts}] {msg}", flush=True)

def estimate_time(rows, interval_s):
    secs = rows * interval_s
    return str(timedelta(seconds=int(secs)))

# ── SSH helper ────────────────────────────────────────────────────────────────

def ssh_ue(cmd: str, timeout: int = 60) -> tuple:
    """Run command on UERANSIM VM via SSH. Returns (stdout, returncode)."""
    full = (
        f"sshpass -p '{UERANSIM_PASS}' ssh "
        f"-o StrictHostKeyChecking=no "
        f"-o ConnectTimeout=5 "
        f"-o ControlMaster=auto "
        f"-o 'ControlPath=/tmp/ssh_rd_%h' "
        f"-o ControlPersist=120 "
        f"{UERANSIM_USER}@{UERANSIM_IP} "
        f"'{cmd}'"
    )
    try:
        r = subprocess.run(full, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), -1

def scp_to_ue(local_path: str, remote_path: str) -> bool:
    """Copy a file to UERANSIM VM."""
    cmd = (
        f"sshpass -p '{UERANSIM_PASS}' scp "
        f"-o StrictHostKeyChecking=no "
        f"{local_path} {UERANSIM_USER}@{UERANSIM_IP}:{remote_path}"
    )
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    return r.returncode == 0


def count_csv_rows(path: str) -> int:
    """Count data rows in CSV (excluding header)."""
    if not os.path.exists(path):
        return 0
    try:
        with open(path) as f:
            return max(0, sum(1 for _ in f) - 1)
    except Exception:
        return 0

def get_csv_tail(path: str, n: int = 8) -> list:
    """Get last n data rows from CSV as list of dicts."""
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            rows = list(csv.DictReader(f))
        return rows[-n:] if len(rows) >= n else rows
    except Exception:
        return []

def is_row_valid(row: dict) -> bool:
    """
    Return True if the row contains real (non-zero) metrics.
    Invalid = UE disconnected: no URLLC sessions OR zero RTT.
    """
    try:
        rtt   = float(row.get("urllc_rtt_ms", 0))
        ue_u  = int(row.get("urllc_ue_count", 0))
        # A valid row: URLLC UE must be present AND RTT measurable
        return ue_u > 0 and rtt > 0.5
    except (ValueError, TypeError):
        return False

# ── GTP tunnel verification ──────────────────────────────────────────────────

def check_gtp_tunnels() -> dict:
    """
    SSH to UERANSIM and check uesimtunX interfaces by IP prefix.
    Returns {'embb': N, 'urllc': N, 'mmtc': N} (current live tunnel counts).
    """
    out, rc = ssh_ue(
        "ip -4 addr | grep 'inet 10\.4[567]\.' | grep uesimtun"
    )
    counts = {"embb": 0, "urllc": 0, "mmtc": 0}
    if rc != 0:
        return counts
    for line in out.splitlines():
        if "10.45." in line:
            counts["embb"] += 1
        elif "10.46." in line:
            counts["urllc"] += 1
        elif "10.47." in line:
            counts["mmtc"] += 1
    return counts


def wait_for_tunnels(required: dict, timeout_s: int = 180) -> bool:
    """
    Poll UERANSIM until all GTP tunnels are restored or timeout.
    required: {'embb': 3, 'urllc': 3, 'mmtc': 3}
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        tunnels = check_gtp_tunnels()
        if all(tunnels.get(k, 0) >= v for k, v in required.items()):
            return True
        remaining_s = int(deadline - time.time())
        log(f"  [recovery] Tunnels={tunnels} waiting for {required} ({remaining_s}s left)...")
        time.sleep(10)
    return False


# ── PDU Session Recovery ──────────────────────────────────────────────────────

def recover_pdu_sessions(level: str) -> bool:
    """
    Simplified recovery:
      - UE restart is NOT attempted automatically (complex, unreliable)
      - Instead: pause collection, wait for tunnels to come back
        (user reconnects UEs manually, or they recover on their own)
      - Once ANY uesimtun interfaces with 10.45/10.46/10.47 IPs appear,
        restart traffic scripts (they auto-detect interface names by IP prefix)
      - Resume collection

    Interface name→slice mapping is dynamic:
      10.45.x.x = eMBB,  10.46.x.x = URLLC,  10.47.x.x = mMTC
    Traffic scripts already detect this — no hardcoded interface names.
    """
    log("═" * 50)
    log("[recovery] UE disconnect detected — collection PAUSED")
    log("[recovery] Waiting for GTP tunnels to recover...")
    log("[recovery] (Reconnect UEs manually if needed)")
    log("═" * 50)

    # Kill all client apps to stop bad traffic (don't touch nr-ue)
    log("[recovery] Stopping client apps while waiting...")
    ssh_ue("pkill -f 'embb_client.py|urllc_client.py|mmtc_client.py' 2>/dev/null;"
           "pkill -f 'iperf3 -c' 2>/dev/null;"
           "rm -f /tmp/mec-clients/*.log")

    # Poll indefinitely until at least 1 of each slice type is up
    # (we need minimum 1 eMBB + 1 URLLC + 1 mMTC to run any traffic level)
    POLL_INTERVAL = 15
    elapsed = 0
    while True:
        tunnels = check_gtp_tunnels()
        has_embb  = tunnels.get("embb",  0) >= 1
        has_urllc = tunnels.get("urllc", 0) >= 1
        has_mmtc  = tunnels.get("mmtc",  0) >= 1

        log(f"[recovery] [{elapsed:4d}s] Tunnels: "
            f"eMBB={tunnels.get('embb',0)}  "
            f"URLLC={tunnels.get('urllc',0)}  "
            f"mMTC={tunnels.get('mmtc',0)}"
            f"{'  ← RECONNECTED!' if (has_embb and has_urllc and has_mmtc) else ''}")

        if has_embb and has_urllc and has_mmtc:
            break

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    log(f"[recovery] ✓ Tunnels back after {elapsed}s — interfaces auto-detected by IP prefix")

    # Restart application clients — traffic scripts detect new uesimtunX names via IP
    log(f"[recovery] Restarting {level.upper()} traffic clients...")
    r = subprocess.run(
        [sys.executable, os.path.join(BASE_DIR, "load_controller.py"), "set", level],
        cwd=BASE_DIR
    )
    if r.returncode == 0:
        log(f"[recovery] ✓ {level.upper()} clients restarted with new interface mapping")
    else:
        log("[recovery] ⚠ load_controller returned non-zero")

    log(f"[recovery] Post-recovery warmup: {POST_RESTART_WARMUP}s...")
    time.sleep(POST_RESTART_WARMUP)

    log("═" * 50)
    log("[recovery] Collection RESUMED")
    log("═" * 50)
    return True

# ── Core collection logic ─────────────────────────────────────────────────────

def run_level(level: str, label: str, target_rows: int, output_path: str) -> int:
    """
    Collect target_rows for one traffic level with UE watchdog.
    Uses Popen (non-blocking) so the watchdog can monitor while collecting.
    collector.py already appends to existing files — no header duplication.
    """
    log("=" * 60)
    log(f"Starting: {label.upper()} / {level.upper()} traffic")
    log(f"Output:   {output_path}")
    log(f"Target:   {target_rows:,} rows  (~{estimate_time(target_rows, COLLECTION_INTERVAL)})")
    log("=" * 60)

    # ── Step 1: Set traffic level ─────────────────────────────────────────────
    log(f"Setting traffic level to {level.upper()}...")
    r = subprocess.run(
        [sys.executable, os.path.join(BASE_DIR, "load_controller.py"), "set", level],
        cwd=BASE_DIR
    )
    if r.returncode != 0:
        log("WARNING: load_controller returned non-zero exit code")

    with open("/tmp/current_traffic_level", "w") as f:
        f.write(level)

    # ── Step 2: Warmup ────────────────────────────────────────────────────────
    log(f"Warming up for {WARMUP_SECONDS}s...")
    for i in range(WARMUP_SECONDS, 0, -10):
        time.sleep(10)
        log(f"  ...{i}s remaining")

    # ── Step 3: Collect with watchdog ─────────────────────────────────────────
    restart_count = 0

    while True:
        rows_so_far = count_csv_rows(output_path)
        remaining   = target_rows - rows_so_far

        if remaining <= 0:
            log(f"✓ {level.upper()} target reached ({rows_so_far:,} rows)")
            break

        if restart_count > MAX_RESTARTS_PER_LEVEL:
            log(f"✗ {level.upper()}: max restarts ({MAX_RESTARTS_PER_LEVEL}) exceeded. Aborting level.")
            return 1

        if restart_count > 0:
            log(f"  [watchdog] Resuming from row {rows_so_far:,} — need {remaining:,} more")

        # Build collector command — collector.py appends to existing file automatically
        log(f"Starting collector → {output_path}  (collecting {remaining:,} rows)")
        collector_cmd = [
            sys.executable,
            os.path.join(BASE_DIR, "collector.py"),
            "--output",        output_path,
            "--label",         label,
            "--traffic-level", level,
            "--target-rows",   str(remaining),
            "--interval",      str(COLLECTION_INTERVAL),
        ]

        # Start collector as non-blocking background process
        proc = subprocess.Popen(collector_cmd, cwd=BASE_DIR)

        # Watchdog: poll while collector is running
        invalid_streak = 0
        ue_disconnect  = False
        last_row_count = rows_so_far

        while proc.poll() is None:   # collector still running
            time.sleep(WATCHDOG_CHECK_INTERVAL)

            # Count rows to detect stall (no new rows = collector stuck)
            current_rows = count_csv_rows(output_path)
            new_rows = current_rows - last_row_count
            last_row_count = current_rows

            if new_rows == 0:
                log(f"  [watchdog] ⚠ No new rows in last {WATCHDOG_CHECK_INTERVAL}s — checking metrics...")

            # Check last N rows for validity
            tail = get_csv_tail(output_path, n=INVALID_STREAK_THRESHOLD + 2)
            if len(tail) < 3:
                continue  # Not enough data yet

            recent = tail[-INVALID_STREAK_THRESHOLD:]
            bad    = sum(1 for r in recent if not is_row_valid(r))

            if bad >= INVALID_STREAK_THRESHOLD:
                log(f"\n[watchdog] ⚠ DETECTED {bad}/{len(recent)} invalid rows!")
                log(f"[watchdog]   Symptoms: RTT=0 or URLLC UE count=0")
                log(f"[watchdog]   PDU session may be lost — triggering recovery #{restart_count + 1}")
                ue_disconnect = True
                # Kill the collector gracefully
                proc.terminate()
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
            elif bad > 0:
                log(f"  [watchdog] ⚠ {bad}/{len(recent)} invalid rows — monitoring...")

        if ue_disconnect:
            restart_count += 1
            log(f"  [watchdog] Cooldown {RESTART_COOLDOWN}s before recovery...")
            time.sleep(RESTART_COOLDOWN)

            # Full PDU session recovery (not just app restart)
            success = recover_pdu_sessions(level)
            if not success:
                log(f"[watchdog] ✗ PDU recovery failed for {level} (attempt {restart_count})")
                if restart_count >= MAX_RESTARTS_PER_LEVEL:
                    log(f"[watchdog] ✗ Max recovery attempts reached. Aborting level.")
                    return 1
            # Continue outer while loop → resume collector

        else:
            # Collector finished normally (target_rows reached or exited cleanly)
            break

    # ── Final count ───────────────────────────────────────────────────────────
    rows_written = count_csv_rows(output_path)
    log(f"✓ {level.upper()} DONE — {rows_written:,} rows  restarts={restart_count}  → {output_path}")
    return 0

# ── Verification ──────────────────────────────────────────────────────────────

def verify_output(label: str, target_rows: int):
    """Quick sanity check on all output files."""
    log("\n" + "=" * 60)
    log("VERIFICATION SUMMARY")
    log("=" * 60)
    all_ok = True
    for level in LEVEL_ORDER:
        path = os.path.join(DATA_DIR, f"dataset_{label}_{level}.csv")
        if not os.path.exists(path):
            log(f"  ✗ MISSING: {path}")
            all_ok = False
            continue
        try:
            rows   = list(csv.DictReader(open(path)))
            viols  = sum(1 for r in rows if r.get("sla_violated") == "1")
            states = {}
            for r in rows:
                s = r.get("orchestrator_state", "?")
                states[s] = states.get(s, 0) + 1
            ok = "✓" if len(rows) >= target_rows * 0.95 else "⚠"
            if len(rows) < target_rows * 0.95:
                all_ok = False
            log(f"  {ok} {label}_{level}.csv: {len(rows):,} rows  "
                f"SLA_violated={viols} ({100*viols/max(1,len(rows)):.1f}%)  "
                f"states={states}")
        except Exception as e:
            log(f"  ✗ Error reading {path}: {e}")
            all_ok = False

    log("=" * 60)
    log(f"All files ready: {'YES ✓' if all_ok else 'NO — check above'}")
    return all_ok

# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Collect 10,000-row datasets for each traffic level with UE watchdog"
    )
    parser.add_argument("--label", required=True, choices=["rule_based", "agentic"])
    parser.add_argument("--target-rows", type=int, default=DEFAULT_TARGET_ROWS)
    parser.add_argument("--levels", nargs="+", default=LEVEL_ORDER,
                        choices=["low", "medium", "high"])
    parser.add_argument("--test", action="store_true",
                        help="Quick test: 100 rows, 45s warmup")
    args = parser.parse_args()

    if args.test:
        args.target_rows = 100
        global WARMUP_SECONDS
        WARMUP_SECONDS = 45
        log("TEST MODE: 100 rows per level, 45s warmup")

    os.makedirs(DATA_DIR, exist_ok=True)

    total_start = time.time()
    eta = estimate_time(
        len(args.levels) * args.target_rows * COLLECTION_INTERVAL + WARMUP_SECONDS, 1
    )
    log(f"Dataset collection starting — label={args.label}")
    log(f"Levels: {args.levels}  Target: {args.target_rows:,} rows each")
    log(f"Estimated total time: ~{eta}")
    log(f"Data directory: {DATA_DIR}")
    log(f"Watchdog: check every {WATCHDOG_CHECK_INTERVAL}s  "
        f"threshold={INVALID_STREAK_THRESHOLD} invalid rows  "
        f"max_restarts={MAX_RESTARTS_PER_LEVEL}")
    print()

    errors = []
    for level in args.levels:
        output_path = os.path.join(DATA_DIR, f"dataset_{args.label}_{level}.csv")
        rc = run_level(level, args.label, args.target_rows, output_path)
        if rc != 0:
            errors.append(level)
        print()

    verify_output(args.label, args.target_rows)

    total_elapsed = time.time() - total_start
    log(f"Total time: {total_elapsed/3600:.2f}h")

    if errors:
        log(f"ERRORS in levels: {errors}")
        sys.exit(1)

if __name__ == "__main__":
    main()
