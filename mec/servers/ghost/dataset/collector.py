#!/usr/bin/env python3
"""
Phase 1: Dataset Collector
==========================
Reads all metrics every CHECK_INTERVAL seconds and appends to CSV.
Sources:
  - Orchestrator Prometheus endpoint (localhost:9200/metrics)
  - SSH to UERANSIM: ONE batched call for all log data
  - kubectl top node / kubectl top pod (with /proc/stat fallback)
  - kubectl get deploy (replica counts)

Usage:
  python3 dataset/collector.py --output data/dataset_rule_based.csv \
      --label rule_based --traffic-level medium --duration 900
"""
import argparse
import csv
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────────────────
UERANSIM_IP   = "192.168.49.139"
UERANSIM_USER = "shinegami"
UERANSIM_PASS = "123"
LOG_DIR       = "/tmp/mec-clients"
METRICS_URL   = "http://localhost:9200/metrics"
CHECK_INTERVAL = 2   # seconds (reduced from 5s to reach 10k rows in ~5.6h)

# ── CSV columns (in order) ───────────────────────────────────────────────────
COLUMNS = [
    # Time
    "timestamp", "datetime",
    # Slice performance
    "urllc_rtt_ms", "urllc_rtt_max_ms", "urllc_fails",
    "embb_mbps", "embb_rate_mbit",
    "mmtc_msgs", "mmtc_rate_per_min",
    # SLA
    "sla_violated",
    # Orchestrator internals
    "orchestrator_type", "orchestrator_state",
    "violation_streak", "recovery_streak",
    "action_taken", "decision_latency_ms", "reasoning",
    # Hardware (node)
    "node_cpu_percent", "node_memory_percent",
    # Replicas
    "pod_replicas_embb", "pod_replicas_urllc", "pod_replicas_mmtc",
    # Tags
    "traffic_level", "orchestrator_label",
    "embb_ue_count", "urllc_ue_count", "mmtc_ue_count",
    "run_id", "sample_index",
]

def run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""

def ssh_batch(remote_cmd, timeout=12):
    """Single SSH call — avoids per-call connection overhead"""
    cmd = ["sshpass", "-p", UERANSIM_PASS,
           "ssh", "-o", "StrictHostKeyChecking=no",
           "-o", "ConnectTimeout=5",
           "-o", "ControlMaster=auto",
           "-o", "ControlPath=/tmp/ssh_mec_%r@%h:%p",
           "-o", "ControlPersist=30",
           f"{UERANSIM_USER}@{UERANSIM_IP}", remote_cmd]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""

def read_local_cpu():
    """Read CPU% from /proc/stat — fallback when metrics-server unavailable"""
    try:
        with open('/proc/stat') as f:
            line = f.readline()
        fields = [int(x) for x in line.split()[1:]]
        idle = fields[3]
        total = sum(fields)
        # Store state between calls
        prev = getattr(read_local_cpu, '_prev', (total, idle))
        read_local_cpu._prev = (total, idle)
        d_total = total - prev[0]
        d_idle  = idle  - prev[1]
        if d_total == 0:
            return 0
        return round(100 * (1 - d_idle / d_total))
    except Exception:
        return 0

# ── Metric collectors ────────────────────────────────────────────────────────

def get_orchestrator_metrics():
    """Parse Prometheus text from localhost:9200/metrics"""
    try:
        resp = urllib.request.urlopen(METRICS_URL, timeout=3)
        text = resp.read().decode()
    except Exception:
        return {}
    metrics = {}
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) == 2:
            metrics[parts[0]] = parts[1]
    return metrics

def get_ue_log_metrics():
    """ONE batched SSH call to UERANSIM — reads FRESH data only (stale logs cleared by load_controller)"""
    remote = (
        f"echo '===URLLC==='; "
        f"for f in {LOG_DIR}/urllc_*.log; do "
        f"  [ -s \"$f\" ] && tail -1 \"$f\" 2>/dev/null; "
        f"done; "
        f"echo '===MMTC==='; "
        f"for f in {LOG_DIR}/mmtc_*.log; do "
        f"  [ -s \"$f\" ] && tail -1 \"$f\" 2>/dev/null; "
        f"done; "
        f"echo '===PROCS==='; "
        f"ps -eo stat,args | grep -E '(embb|urllc|mmtc)_client' | grep -v grep"
    )
    out = ssh_batch(remote)

    sections = {"URLLC": "", "MMTC": "", "PROCS": ""}
    current = None
    for line in out.splitlines():
        if line == "===URLLC===": current = "URLLC"
        elif line == "===MMTC===": current = "MMTC"
        elif line == "===PROCS===": current = "PROCS"
        elif current:
            sections[current] += line + "\n"

    # Parse URLLC — avg and max RTT from lines like:
    # [URLLC] uesimtun0: msgs=30 fails=0 RTT avg=14.9ms max=24.5ms cmd=HOLD
    avg_rtts, max_rtts, fails = [], [], 0
    for line in sections["URLLC"].splitlines():
        m_avg = re.search(r'RTT avg=(\d+\.\d+)ms', line)
        m_max = re.search(r'max=(\d+\.\d+)ms', line)
        m_f   = re.search(r'fails=(\d+)', line)
        if m_avg: avg_rtts.append(float(m_avg.group(1)))
        if m_max: max_rtts.append(float(m_max.group(1)))
        if m_f:   fails += int(m_f.group(1))

    # Parse process counts — only RUNNING (not paused by SIGSTOP, stat='T')
    embb = mmtc = urllc = 0
    for line in sections["PROCS"].splitlines():
        # ps -eo stat,args format or ps aux — check for 'T' in stat field
        # Skip lines where process is stopped (SIGSTOP'd by load_controller)
        parts = line.split()
        if len(parts) < 2:
            continue
        # Try to detect stopped state: ps aux has STAT in col 8 (0-indexed 7)
        # ps -eo has stat in col 0; we check if 'T' appears near the start
        stat_field = ""
        for p in parts[:3]:
            if p.replace('T','').replace('S','').replace('R','').replace('s','').replace('+','').replace('l','').replace('<','').replace('N','') == '':
                stat_field = p
                break
        if 'T' in stat_field:
            continue  # skip stopped processes
        cmd = " ".join(parts)
        if 'embb_client'  in cmd: embb  += 1
        elif 'urllc_client' in cmd: urllc += 1
        elif 'mmtc_client'  in cmd: mmtc  += 1

    return {
        "urllc_rtt_live_ms":  round(sum(avg_rtts)/len(avg_rtts), 2) if avg_rtts else 0.0,
        "urllc_rtt_max_ms":  max(max_rtts) if max_rtts else 0.0,
        "urllc_active_ues":  len(avg_rtts),   # how many URLLC logs had fresh data
        "urllc_fails": fails,
        "mmtc_raw_lines": sections["MMTC"],
        "embb_ue_count": embb,
        "urllc_ue_count": urllc,
        "mmtc_ue_count": mmtc,
    }

def get_node_metrics():
    """kubectl top node for worker 'kube' — fallback to /proc/stat"""
    cpu_pct = mem_pct = 0
    # Try metrics-server first (worker node is named 'kube')
    out = run("kubectl top node kube --no-headers 2>/dev/null")
    if out and "%" in out:
        parts = out.split()
        try:
            cpu_pct = int(parts[2].replace('%', ''))
            mem_pct = int(parts[4].replace('%', ''))
        except Exception:
            pass
    if cpu_pct == 0:
        # Fallback: read from kubemaster's own /proc/stat
        cpu_pct = read_local_cpu()
        # Try to get memory from /proc/meminfo
        try:
            info = {}
            for line in open('/proc/meminfo').readlines():
                k, v = line.split(':')[0], line.split(':')[1].strip().split()[0]
                info[k] = int(v)
            used = info['MemTotal'] - info['MemAvailable']
            mem_pct = round(100 * used / info['MemTotal'])
        except Exception:
            pass
    return {"node_cpu_percent": cpu_pct, "node_memory_percent": mem_pct}

def get_pod_metrics():
    """
    Pod CPU/memory via kubectl top.
    NOTE: requires metrics-server. If not deployed, returns all zeros.
    Uses single --all-namespaces call instead of 3 per-namespace calls.
    """
    result = {"pod_cpu_embb_m": 0, "pod_cpu_urllc_m": 0, "pod_cpu_mmtc_m": 0,
              "pod_mem_embb_mi": 0, "pod_mem_urllc_mi": 0, "pod_mem_mmtc_mi": 0}
    out = run("kubectl top pod --all-namespaces --no-headers 2>/dev/null", timeout=4)
    if not out:
        return result  # metrics-server not available
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        ns = parts[0].lower()
        if ns not in ("embb", "urllc", "mmtc"):
            continue
        try:
            cpu_m = int(parts[2].replace('m', ''))
        except Exception:
            cpu_m = 0
        try:
            mem_s = parts[3].lower()
            mem_mi = int(float(mem_s.replace('gi', '')) * 1024) if 'gi' in mem_s \
                     else int(mem_s.replace('mi', ''))
        except Exception:
            mem_mi = 0
        result[f'pod_cpu_{ns}_m']  = result.get(f'pod_cpu_{ns}_m',  0) + cpu_m
        result[f'pod_mem_{ns}_mi'] = result.get(f'pod_mem_{ns}_mi', 0) + mem_mi
    return result

def get_replica_counts():
    """kubectl get deploy — replica counts"""
    result = {"pod_replicas_embb": 0, "pod_replicas_urllc": 0, "pod_replicas_mmtc": 0}
    for ns, key in [("embb", "pod_replicas_embb"),
                    ("urllc", "pod_replicas_urllc"),
                    ("mmtc", "pod_replicas_mmtc")]:
        out = run(f"kubectl get deploy -n {ns} --no-headers 2>/dev/null | "
                  f"awk '{{sum += $4}} END {{print sum+0}}'")
        try:
            result[key] = int(out)
        except Exception:
            pass
    return result


# ── Main collection loop ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/dataset_rule_based.csv")
    parser.add_argument("--label", default="rule_based",
                        help="orchestrator_label: rule_based or agentic")
    parser.add_argument("--traffic-level", default="medium",
                        choices=["low", "medium", "high"])
    parser.add_argument("--duration", type=int, default=0,
                        help="Run duration in seconds (0 = run until Ctrl+C or --target-rows)")
    parser.add_argument("--target-rows", type=int, default=0,
                        help="Stop after collecting this many rows (0 = unlimited)")
    parser.add_argument("--interval", type=float, default=CHECK_INTERVAL,
                        help=f"Collection interval in seconds (default={CHECK_INTERVAL})")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    sample_idx = 0
    prev_mmtc_msgs = 0
    prev_time = time.time()
    prev_state = -1          # track state transitions for action_taken
    prev_embb_mbps = 0.0    # forward-fill eMBB when Prometheus returns 0

    # Write CSV header if file doesn't exist
    write_header = not os.path.exists(args.output)
    outfile = open(args.output, "a", newline="")
    writer = csv.DictWriter(outfile, fieldnames=COLUMNS)
    if write_header:
        writer.writeheader()
        print(f"[collector] Created {args.output}")

    print(f"[collector] Starting — label={args.label} traffic={args.traffic_level} "
          f"run_id={run_id} interval={CHECK_INTERVAL}s")
    print(f"[collector] Press Ctrl+C to stop" +
          (f" (auto-stop in {args.duration}s)" if args.duration else "") +
          (f" (target: {args.target_rows} rows)" if args.target_rows else ""))
    print("-" * 60)

    interval = args.interval

    start_time = time.time()
    try:
        while True:
            t0 = time.time()

            # Check stop conditions
            if args.duration and (t0 - start_time) >= args.duration:
                print(f"\n[collector] Duration reached ({args.duration}s). Stopping.")
                break
            if args.target_rows and sample_idx >= args.target_rows:
                print(f"\n[collector] Target rows reached ({args.target_rows}). Stopping.")
                break

            # Read current traffic level (updated live by load_controller)
            try:
                live_level = open("/tmp/current_traffic_level").read().strip()
                if live_level in ("low", "medium", "high"):
                    args.traffic_level = live_level
            except Exception:
                pass  # use the CLI arg if file missing

            # Collect all metrics
            orch = get_orchestrator_metrics()
            ue_logs = get_ue_log_metrics()
            node = get_node_metrics()
            replicas = get_replica_counts()
            # UE counts come from the batched SSH call (no extra SSH needed)
            embb_count  = ue_logs.get("embb_ue_count", 0)
            urllc_count = ue_logs.get("urllc_ue_count", 0)
            mmtc_count  = ue_logs.get("mmtc_ue_count", 0)

            # Parse orchestrator metrics (state/decisions — not RTT, that's stale)
            embb_mbps_raw = float(orch.get("orchestrator_embb_mbps", 0))
            # Forward-fill embb_mbps: Prometheus resets to 0 between HLS log reads
            embb_mbps = embb_mbps_raw if embb_mbps_raw > 0 else prev_embb_mbps
            if embb_mbps_raw > 0:
                prev_embb_mbps = embb_mbps_raw
            mmtc_msgs  = int(float(orch.get("orchestrator_mmtc_msgs_total", 0)))
            state      = int(float(orch.get("orchestrator_state", 0)))
            embb_rate  = int(float(orch.get("orchestrator_embb_rate_mbit", 1000)))
            viol_streak= int(float(orch.get("orchestrator_violation_count", 0)))
            rec_streak = int(float(orch.get("orchestrator_recovery_streak", 0)))

            # Use LIVE RTT from SSH logs (fresh — stale logs cleared on level switch)
            # Fall back to Prometheus only if SSH has no data yet (clients just started)
            live_rtt   = ue_logs.get("urllc_rtt_live_ms", 0.0)
            orch_rtt   = float(orch.get("orchestrator_urllc_rtt_ms", 0))
            urllc_rtt  = live_rtt if live_rtt > 0 else orch_rtt

            # Derived
            now = time.time()
            elapsed = now - prev_time if prev_time else CHECK_INTERVAL
            mmtc_rate = (mmtc_msgs - prev_mmtc_msgs) / elapsed * 60
            prev_mmtc_msgs = mmtc_msgs
            prev_time = now
            sla_violated = 1 if urllc_rtt > 15.0 else 0

            # ── Derive action_taken + reasoning from state transitions ────────
            decision_t0 = time.time()

            if urllc_rtt == 0.0 or ue_logs.get("urllc_fails", 0) > 0 and urllc_rtt == 0:
                # RTT=0 with fails = PDU session drop / UE disconnect
                # Do NOT treat as normal input — mark explicitly as invalid
                action_taken = "invalid_data"
                reasoning = (
                    f"RTT=0ms with fails={ue_logs.get('urllc_fails',0)} — "
                    f"PDU session drop / UE disconnect detected; row excluded from training"
                )
            elif state == 1 and prev_state != 1:
                # Transition: NORMAL → THROTTLED
                action_taken = "throttle_embb"
                reasoning = (
                    f"RTT={urllc_rtt:.1f}ms exceeded 15ms SLA threshold "
                    f"(streak={viol_streak}); throttling eMBB to {embb_rate}Mbps"
                )
            elif state == 0 and prev_state == 1:
                # Transition: THROTTLED → NORMAL (recovery)
                action_taken = "release_throttle"
                reasoning = (
                    f"RTT={urllc_rtt:.1f}ms below 15ms threshold "
                    f"(recovery_streak={rec_streak}); restoring eMBB to {embb_rate}Mbps"
                )
            elif state == 1:
                # Sustained throttle
                action_taken = "hold_throttle"
                reasoning = (
                    f"RTT={urllc_rtt:.1f}ms still elevated "
                    f"(streak={viol_streak}); maintaining throttle at {embb_rate}Mbps"
                )
            elif state == 0 and sla_violated == 1:
                # RTT > 15ms but orchestrator hasn't acted yet (lag) — NOT within SLA
                action_taken = "no_action"
                reasoning = (
                    f"RTT={urllc_rtt:.1f}ms exceeds 15ms but orchestrator in recovery grace period "
                    f"(streak={viol_streak}); monitoring"
                )
            else:
                # NORMAL, RTT within SLA, no action needed
                action_taken = "no_action"
                reasoning = (
                    f"RTT={urllc_rtt:.1f}ms within SLA (<15ms); "
                    f"eMBB at {embb_rate}Mbps — no action required"
                )
            prev_state = state
            decision_latency = round((time.time() - decision_t0) * 1000, 2)
            # ─────────────────────────────────────────────────────────────────

            row = {
                "timestamp":       now,
                "datetime":        datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
                "urllc_rtt_ms":    round(urllc_rtt, 2),
                "urllc_rtt_max_ms":round(ue_logs["urllc_rtt_max_ms"], 2),
                "urllc_fails":     ue_logs["urllc_fails"],
                "embb_mbps":       round(embb_mbps, 2),
                "embb_rate_mbit":  embb_rate,
                "mmtc_msgs":       mmtc_msgs,
                "mmtc_rate_per_min": round(max(0, mmtc_rate), 1),
                "sla_violated":    sla_violated,
                "orchestrator_type":  args.label,
                "orchestrator_state": state,
                "violation_streak": viol_streak,
                "recovery_streak":  rec_streak,
                "action_taken":    action_taken,
                "decision_latency_ms": decision_latency,
                "reasoning":       reasoning,
                **node,
                **replicas,
                "traffic_level":   args.traffic_level,
                "orchestrator_label": args.label,
                "embb_ue_count":   embb_count,
                "urllc_ue_count":  urllc_count,
                "mmtc_ue_count":   mmtc_count,
                "run_id":          run_id,
                "sample_index":    sample_idx,
            }

            writer.writerow(row)
            outfile.flush()
            sample_idx += 1

            # Console output
            sla_icon = "❌" if sla_violated else "✓"
            state_str = "THROTTLED" if state else "NORMAL   "
            print(f"[{row['datetime']}] #{sample_idx:04d} "
                  f"RTT={urllc_rtt:5.1f}ms {sla_icon}  "
                  f"eMBB={embb_mbps:6.1f}Mbps  "
                  f"mMTC={mmtc_msgs}msgs  "
                  f"State={state_str}  "
                  f"CPU={node['node_cpu_percent']}%  "
                  f"UEs={embb_count}e/{urllc_count}u/{mmtc_count}m")

            # Sleep for remaining interval
            elapsed_collection = time.time() - t0
            sleep_time = max(0, interval - elapsed_collection)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print(f"\n[collector] Stopped. {sample_idx} rows written to {args.output}")
    finally:
        outfile.close()

if __name__ == "__main__":
    main()
