#!/usr/bin/env python3
"""
Load Controller v3 — Shell-script based
=========================================
Controls traffic levels by SSHing to UERANSIM and running
pre-built bash scripts. Clean, simple, no PID management.

Scripts live on UERANSIM at: ~/mec-scripts/set_traffic_{level}.sh

Usage:
  python3 dataset/load_controller.py set low
  python3 dataset/load_controller.py set medium
  python3 dataset/load_controller.py set high
  python3 dataset/load_controller.py stop
  python3 dataset/load_controller.py verify
  python3 dataset/load_controller.py deploy   ← copy scripts to UERANSIM
"""
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime

# ── Config ───────────────────────────────────────────────────────────────────
UERANSIM_IP   = "192.168.49.139"
UERANSIM_USER = "shinegami"
UERANSIM_PASS = "123"
REMOTE_DIR    = "~/mec-scripts"      # where scripts live on UERANSIM
LOCAL_SCRIPTS = os.path.join(        # local source dir
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ueransim-scripts"
)
LEVEL_FILE    = "/tmp/current_traffic_level"   # shared with collector

# Expected client counts per level
EXPECTED_COUNTS = {
    "low":    3,    # 1 eMBB + 1 URLLC + 1 mMTC
    "medium": 9,    # 3 eMBB + 3 URLLC + 3 mMTC
    "high":   11,   # 5 eMBB + 3 URLLC + 3 mMTC
}

def log(msg):
    print(f"[load_ctrl {datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def ssh(cmd, timeout=30):
    """Run command on UERANSIM"""
    full = [
        "sshpass", "-p", UERANSIM_PASS,
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=5",
        "-o", "ControlMaster=auto",
        "-o", "ControlPath=/tmp/ssh_lc_%h",
        "-o", "ControlPersist=120",
        f"{UERANSIM_USER}@{UERANSIM_IP}", cmd
    ]
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), -1

def scp(local_file, remote_path):
    """Copy file to UERANSIM"""
    full = [
        "sshpass", "-p", UERANSIM_PASS,
        "scp", "-o", "StrictHostKeyChecking=no",
        local_file, f"{UERANSIM_USER}@{UERANSIM_IP}:{remote_path}"
    ]
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False

def deploy_scripts():
    """Copy traffic scripts from kubemaster to UERANSIM"""
    log(f"Deploying scripts to {UERANSIM_USER}@{UERANSIM_IP}:{REMOTE_DIR}")

    # Create remote dir
    ssh(f"mkdir -p {REMOTE_DIR}")

    scripts = [
        "set_traffic_low.sh",
        "set_traffic_medium.sh",
        "set_traffic_high.sh",
        "stop_all_traffic.sh",
    ]

    ok = 0
    for script in scripts:
        local = os.path.join(LOCAL_SCRIPTS, script)
        if not os.path.exists(local):
            log(f"  ✗ Missing: {local}")
            continue
        success = scp(local, f"{REMOTE_DIR}/{script}")
        if success:
            ssh(f"chmod +x {REMOTE_DIR}/{script}")
            log(f"  ✓ {script}")
            ok += 1
        else:
            log(f"  ✗ Failed: {script}")

    if ok == len(scripts):
        log(f"All {ok} scripts deployed successfully.")
    else:
        log(f"Deployed {ok}/{len(scripts)} scripts.")
    return ok == len(scripts)

def set_level(level: str, edge_ip: str = "192.168.49.171"):
    """Switch traffic level by running the appropriate bash script"""
    log(f"═══ Switching to {level.upper()} traffic ═══")

    # Write level for collector immediately
    with open(LEVEL_FILE, "w") as f:
        f.write(level)

    # Run the script on UERANSIM
    script = f"{REMOTE_DIR}/set_traffic_{level}.sh"
    log(f"Running: {script} {edge_ip}")
    out, rc = ssh(f"bash {script} {edge_ip}", timeout=30)

    # Print script output
    for line in out.splitlines():
        print(f"  {line}")

    if rc != 0:
        log(f"⚠ Script returned code {rc}")

    # Verify
    time.sleep(3)
    verify(level)
    return rc == 0

def verify(expected_level: str = None):
    """Show running client counts"""
    out, _ = ssh(
        "ps -eo stat,args | grep -E '(embb|urllc|mmtc)_client\\.py' | grep -v grep"
    )

    embb = urllc = mmtc = 0
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        stat, cmd = parts[0], parts[1]
        if 'T' in stat:          # stopped/paused — don't count
            continue
        if 'embb_client'  in cmd: embb  += 1
        elif 'urllc_client' in cmd: urllc += 1
        elif 'mmtc_client'  in cmd: mmtc  += 1

    total = embb + urllc + mmtc
    log(f"Running: eMBB={embb}  URLLC={urllc}  mMTC={mmtc}  total={total}")

    if expected_level:
        expected = EXPECTED_COUNTS[expected_level]
        if total >= expected * 0.8:
            log(f"✓ {expected_level.upper()} confirmed ({total}/{expected} clients)")
        else:
            log(f"⚠ Expected ~{expected} clients, got {total}")

    return embb, urllc, mmtc

def stop_all():
    """Kill all clients"""
    log("Stopping all traffic...")
    with open(LEVEL_FILE, "w") as f:
        f.write("none")
    out, _ = ssh(f"bash {REMOTE_DIR}/stop_all_traffic.sh", timeout=15)
    for line in out.splitlines():
        print(f"  {line}")

def check_scripts_exist():
    """Verify scripts are deployed on UERANSIM"""
    out, rc = ssh(f"ls {REMOTE_DIR}/*.sh 2>/dev/null | wc -l")
    count = int(out.strip()) if out.strip().isdigit() else 0
    if count >= 4:
        log(f"✓ Scripts ready on UERANSIM ({count} files in {REMOTE_DIR})")
        return True
    else:
        log(f"✗ Scripts not found on UERANSIM (found {count}). Run: deploy")
        return False

def main():
    parser = argparse.ArgumentParser(
        description="Traffic level controller for 5G MEC dataset collection"
    )
    sub = parser.add_subparsers(dest="cmd")

    # Set level
    set_p = sub.add_parser("set", help="Set traffic level (low/medium/high)")
    set_p.add_argument("level", choices=["low", "medium", "high"])
    set_p.add_argument("--edge-ip", default="192.168.49.171")

    # Other commands
    sub.add_parser("stop",   help="Kill all clients")
    sub.add_parser("verify", help="Show running client counts")
    sub.add_parser("deploy", help="Copy scripts to UERANSIM (run once)")
    sub.add_parser("check",  help="Verify scripts exist on UERANSIM")

    args = parser.parse_args()

    if args.cmd == "set":
        # Auto-deploy if not present
        if not check_scripts_exist():
            log("Auto-deploying scripts first...")
            if not deploy_scripts():
                log("Deploy failed. Aborting.")
                sys.exit(1)
        set_level(args.level, args.edge_ip)

    elif args.cmd == "stop":
        stop_all()

    elif args.cmd == "verify":
        verify()

    elif args.cmd == "deploy":
        deploy_scripts()

    elif args.cmd == "check":
        check_scripts_exist()

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
