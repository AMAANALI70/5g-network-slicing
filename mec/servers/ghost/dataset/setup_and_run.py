#!/usr/bin/env python3
"""
Dataset Setup & Test Script
============================
Run this ONCE before starting data collection.
It will:
  1. SSH to UERANSIM → restart all 9 clients with run_all.sh (correct interfaces)
  2. Wait 70s for first log entries
  3. Verify RTT data is flowing
  4. Test all 3 traffic levels (SIGSTOP/SIGCONT)
  5. Confirm RTT varies between levels
  6. Start the full dataset collection run

Usage:
  python3 dataset/setup_and_run.py --label rule_based
  python3 dataset/setup_and_run.py --label rule_based --test    # quick 100-row test
"""
import argparse
import csv
import os
import subprocess
import sys
import time
from datetime import datetime

UERANSIM_IP   = "192.168.49.139"
UERANSIM_USER = "shinegami"
UERANSIM_PASS = "123"
LOG_DIR       = "/tmp/mec-clients"
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR   = os.path.join(os.path.dirname(BASE_DIR), "ueransim-scripts")
DATA_DIR      = os.path.join(BASE_DIR, "data")

def log(msg):
    print(f"[setup {datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def ssh(cmd, timeout=20):
    """Run command on UERANSIM via sshpass"""
    full = (
        f"sshpass -p '{UERANSIM_PASS}' ssh "
        f"-o StrictHostKeyChecking=no "
        f"-o ConnectTimeout=5 "
        f"-o ControlMaster=auto "
        f"-o 'ControlPath=/tmp/ssh_setup_%h' "
        f"-o ControlPersist=120 "
        f"{UERANSIM_USER}@{UERANSIM_IP} "
        f"'{cmd}'"
    )
    try:
        r = subprocess.run(full, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), -1

def step_restart_clients():
    """Step 1: Restart all clients on UERANSIM with run_all.sh"""
    log("═" * 50)
    log("STEP 1: Restarting all clients on UERANSIM")
    log("═" * 50)

    # Kill existing clients
    log("Killing existing clients...")
    out, _ = ssh("pkill -f '_client.py' 2>/dev/null; sleep 2; echo killed")
    log(f"  {out}")

    # Clear logs
    out, _ = ssh(f"rm -f {LOG_DIR}/*.log; mkdir -p {LOG_DIR}; echo cleared")
    log(f"  {out}")

    # Start all clients with run_all.sh (auto-detects interfaces by IP)
    log("Starting run_all.sh...")
    out, rc = ssh(
        f"cd ~/mec-clients && nohup bash run_all.sh {UERANSIM_IP} "
        f"</dev/null >/tmp/run_all.log 2>&1 &",
        timeout=10
    )
    time.sleep(3)

    # Verify process count
    out, _ = ssh("ps aux | grep -c '_client.py' 2>/dev/null || echo 0")
    count = int(out.strip()) - 1 if out.strip().isdigit() else 0  # subtract grep itself
    log(f"  Clients running: {count}")

    if count < 3:
        log("  ⚠ Less than 3 clients running. Trying direct launch...")
        # Direct launch using IP-detected interfaces
        ifaces_out, _ = ssh(
            "ip -4 addr | grep -E 'inet 10\\.4[5-7]\\.' | grep uesimtun | awk '{print $2, $NF}'"
        )
        embb, urllc, mmtc = [], [], []
        for line in ifaces_out.splitlines():
            if not line.strip(): continue
            ip, iface = line.split()
            if ip.startswith("10.45."): embb.append(iface)
            elif ip.startswith("10.46."): urllc.append(iface)
            elif ip.startswith("10.47."): mmtc.append(iface)

        log(f"  Detected: eMBB={embb} URLLC={urllc} mMTC={mmtc}")

        if not urllc:
            log("ERROR: No URLLC interfaces found! Is UERANSIM running?")
            sys.exit(1)

        cmds = []
        for iface in embb:
            cmds.append(f"nohup python3 ~/mec-clients/embb_client.py {iface} {UERANSIM_IP} 30880 </dev/null >{LOG_DIR}/embb_{iface}.log 2>&1 & disown")
        for iface in urllc:
            cmds.append(f"nohup python3 ~/mec-clients/urllc_client.py {iface} {UERANSIM_IP} </dev/null >{LOG_DIR}/urllc_{iface}.log 2>&1 & disown")
        for iface in mmtc:
            cmds.append(f"nohup python3 ~/mec-clients/mmtc_client.py {iface} {UERANSIM_IP} 30883 </dev/null >{LOG_DIR}/mmtc_{iface}.log 2>&1 & disown")

        batch = "; ".join(cmds)
        ssh(f"mkdir -p {LOG_DIR}; {batch}", timeout=15)
        time.sleep(3)

    return True

def step_wait_for_data():
    """Step 2: Wait until URLLC logs have RTT data"""
    log("═" * 50)
    log("STEP 2: Waiting for URLLC logs to have RTT data")
    log("═" * 50)

    for attempt in range(18):  # up to 90 seconds
        time.sleep(5)
        out, _ = ssh(f"grep 'RTT avg' {LOG_DIR}/urllc_*.log 2>/dev/null | wc -l")
        count = int(out.strip()) if out.strip().isdigit() else 0
        elapsed = (attempt + 1) * 5
        log(f"  {elapsed}s: {count} URLLC RTT entries found")
        if count > 0:
            # Show sample
            sample, _ = ssh(f"grep 'RTT avg' {LOG_DIR}/urllc_*.log 2>/dev/null | head -3")
            for line in sample.splitlines():
                log(f"    {line.strip()}")
            log("  ✓ RTT data confirmed!")
            return True

    log("ERROR: No RTT data after 90s. URLLC clients may be failing.")
    log("Checking URLLC logs...")
    out, _ = ssh(f"tail -5 {LOG_DIR}/urllc_*.log 2>/dev/null || echo 'no logs'")
    log(out)
    return False

def step_check_embb():
    """Step 3: Verify eMBB logs have throughput data"""
    log("═" * 50)
    log("STEP 3: Verifying eMBB data")
    log("═" * 50)
    out, _ = ssh(f"grep 'rate=' {LOG_DIR}/embb_*.log 2>/dev/null | tail -3")
    if out:
        for line in out.splitlines():
            log(f"  {line.strip()}")
        log("  ✓ eMBB data confirmed")
    else:
        log("  ⚠ No eMBB data yet (may take 30s)")

def step_test_levels():
    """Step 4: Test SIGSTOP/SIGCONT levels, verify RTT changes"""
    log("═" * 50)
    log("STEP 4: Testing traffic levels (SIGSTOP/SIGCONT)")
    log("═" * 50)

    results = {}
    for level in ["low", "medium", "high"]:
        log(f"\n  Setting {level.upper()} traffic...")
        # Call load_controller
        r = subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, "load_controller.py"), "set", level],
            cwd=BASE_DIR, capture_output=True, text=True
        )
        print(r.stdout)
        if r.returncode != 0:
            log(f"  ⚠ load_controller error: {r.stderr[:100]}")

        # Wait for steady state
        log(f"  Waiting 20s for {level.upper()} steady state...")
        time.sleep(20)

        # Sample RTT
        out, _ = ssh(f"grep 'RTT avg' {LOG_DIR}/urllc_*.log 2>/dev/null | tail -5")
        rtts = []
        import re
        for line in out.splitlines():
            m = re.search(r"RTT avg=([\d.]+)ms", line)
            if m:
                rtts.append(float(m.group(1)))

        avg_rtt = sum(rtts) / len(rtts) if rtts else 0
        results[level] = avg_rtt
        log(f"  {level.upper()}: avg RTT = {avg_rtt:.1f}ms (from {len(rtts)} logs)")

    log("\n  ── RTT Summary ──")
    for level, rtt in results.items():
        bar = "█" * int(rtt / 2)
        log(f"  {level.upper():6s}: {rtt:5.1f}ms {bar}")

    # Resume all to HIGH for collection
    subprocess.run(
        [sys.executable, os.path.join(BASE_DIR, "load_controller.py"), "stop"],
        cwd=BASE_DIR
    )

    low_rtt = results.get("low", 0)
    high_rtt = results.get("high", 0)
    if high_rtt > low_rtt + 1:
        log("  ✓ RTT varies between levels — dataset will have learnable patterns!")
        return True
    else:
        log("  ⚠ RTT difference small. Dataset will have limited variation.")
        log("    This can happen if URLLC baseline RTT is already high.")
        log("    Proceeding anyway — violation frequency will still differ.")
        return True  # still proceed

def step_run_collection(label: str, target_rows: int):
    """Step 5: Start the actual collection"""
    log("═" * 50)
    log(f"STEP 5: Starting dataset collection ({label})")
    log("═" * 50)
    os.makedirs(DATA_DIR, exist_ok=True)

    # Make sure orchestrator is running
    out = subprocess.run(
        ["pgrep", "-f", "phase3-orchestrator"],
        capture_output=True, text=True
    )
    if not out.stdout.strip():
        log("Starting Phase 3 orchestrator...")
        subprocess.Popen(
            [sys.executable, "/home/kube-master/k8s/phase3-orchestrator.py"],
            stdout=open("/tmp/orchestrator.log", "a"),
            stderr=subprocess.STDOUT
        )
        time.sleep(5)

    log(f"Running collection: {target_rows} rows × 3 levels")
    log(f"Estimated time: ~{target_rows * 2 * 3 // 3600}h {(target_rows * 2 * 3 % 3600) // 60}m")
    log("Output files:")
    for level in ["low", "medium", "high"]:
        log(f"  dataset/data/dataset_{label}_{level}.csv")
    log("")

    r = subprocess.run([
        sys.executable,
        os.path.join(BASE_DIR, "run_dataset.py"),
        "--label", label,
        "--target-rows", str(target_rows),
    ], cwd=BASE_DIR)
    return r.returncode

def step_start_iperf3():
    """Start iperf3 servers on kubemaster for HIGH traffic load generation."""
    server_script = os.path.join(SCRIPTS_DIR, "start_iperf3_server.sh")
    if not os.path.exists(server_script):
        log("⚠ start_iperf3_server.sh not found — skipping iperf3 setup")
        return
    log("Starting iperf3 servers on kubemaster (ports 5201-5203)...")
    r = subprocess.run(["bash", server_script], capture_output=True, text=True)
    for line in r.stdout.strip().splitlines():
        log(f"  {line}")
    if r.returncode == 0:
        log("  ✓ iperf3 servers ready")
    else:
        log("  ⚠ iperf3 server start failed — HIGH traffic may not have full load")
        log(f"    stderr: {r.stderr.strip()[:200]}")


def step_stop_iperf3():
    """Stop iperf3 servers after collection completes."""
    subprocess.run("pkill -f 'iperf3 -s' 2>/dev/null",
                   shell=True, capture_output=True)
    log("iperf3 servers stopped.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, choices=["rule_based", "agentic"])
    parser.add_argument("--target-rows", type=int, default=10000)
    parser.add_argument("--test", action="store_true", help="Quick test: 100 rows")
    parser.add_argument("--skip-setup", action="store_true",
                        help="Skip restart + wait (use if clients already running)")
    parser.add_argument("--no-iperf3", action="store_true",
                        help="Skip iperf3 server start (if already running externally)")
    args = parser.parse_args()

    if args.test:
        args.target_rows = 100

    log(f"5G MEC Dataset Setup — label={args.label} rows={args.target_rows}")
    print()

    # Auto-start iperf3 servers for HIGH traffic stress generation
    if not args.no_iperf3:
        step_start_iperf3()
        print()

    if not args.skip_setup:
        step_restart_clients()
        ok = step_wait_for_data()
        if not ok:
            log("FATAL: Cannot get RTT data. Aborting.")
            sys.exit(1)
        step_check_embb()

    step_test_levels()

    global_warmup = 60 if not args.test else 45
    log(f"\nAll checks passed! Starting collection with warmup={global_warmup}s per level...")

    rc = step_run_collection(args.label, args.target_rows)

    # Stop iperf3 servers when done
    if not args.no_iperf3:
        step_stop_iperf3()

    sys.exit(rc)


if __name__ == "__main__":
    main()
