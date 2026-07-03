#!/usr/bin/env python3
"""
rtt_monitor.py — Measures RTT through URLLC uesimtun interfaces
Logs in format: RTT avg=X.Xms max=Y.Yms fails=N
(Read by orchestrator monitoring_agent.py)
"""
import subprocess, time, re, os, glob

LOG_DIR = "/tmp/mec-clients"
os.makedirs(LOG_DIR, exist_ok=True)

def get_urllc_tuns():
    """Return list of URLLC uesimtun interfaces (10.46.x)"""
    out = subprocess.run("ip addr show | grep -B1 '10\\.46\\.'",
                         shell=True, capture_output=True, text=True).stdout
    tuns = re.findall(r'(uesimtun\d+)', out)
    return tuns

def measure_rtt(iface, target="8.8.8.8", count=5):
    """Ping through iface, return (avg_ms, max_ms, fails)"""
    r = subprocess.run(
        f"ping -c {count} -W 2 -I {iface} {target}",
        shell=True, capture_output=True, text=True, timeout=15
    )
    out = r.stdout
    # Parse: rtt min/avg/max/mdev = X/Y/Z/W ms
    m = re.search(r'rtt .* = [\d.]+/([\d.]+)/([\d.]+)/', out)
    sent = re.search(r'(\d+) packets transmitted', out)
    recv = re.search(r'(\d+) received', out)
    if m:
        avg_ms = float(m.group(1))
        max_ms = float(m.group(2))
        fails = (int(sent.group(1)) - int(recv.group(1))) if sent and recv else count
        return avg_ms, max_ms, fails
    else:
        return 0.0, 0.0, count  # all failed

print(f"[RTT Monitor] Starting — logs to {LOG_DIR}/urllc_*.log")
while True:
    tuns = get_urllc_tuns()
    if not tuns:
        print("[RTT Monitor] No URLLC uesimtun found, waiting...")
        time.sleep(5)
        continue

    for tun in tuns:
        avg, maxv, fails = measure_rtt(tun)
        log_line = f"RTT avg={avg}ms max={maxv}ms fails={fails}"
        log_path = f"{LOG_DIR}/urllc_{tun}.log"
        with open(log_path, "a") as f:
            f.write(log_line + "\n")
        print(f"[{tun}] {log_line}")

    time.sleep(3)
