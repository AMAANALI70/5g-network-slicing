#!/usr/bin/env python3
"""
experiment_collector.py — Continuous Research-Grade Metrics Collector
======================================================================
Collects 20+ metrics from Prometheus every 1s (default) and writes to CSV.
Designed to collect 50,000+ rows for ML training over ~14 hours.

Features:
  - Fixed metric names matching phase3-orchestrator.py exports
  - 5-class SLA label for ML (normal/near_sla/violation/throttled/recovering)
  - Interrupt cause detection and display
  - ETA countdown to target row count
  - Auto-rotation every 10,000 rows
  - Watchdog: alerts if metrics go stale (orchestrator died)

Usage:
    python3 experiment_collector.py \\
        --output experiments/results/continuous/dataset.csv \\
        --interval 1 \\
        --target 50000
"""
import requests, time, csv, argparse, os, math, sys, traceback
from datetime import datetime, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
PROM_URL      = "http://192.168.49.174:30090/api/v1/query"
ORCH_URL      = "http://192.168.49.174:9200/metrics"
PROM_TIMEOUT  = 4       # seconds per query
STALE_THRESH  = 30      # alert if loop_count unchanged for 30s

# ── Metrics to collect (aligned to phase3-orchestrator.py exports) ─────────────
QUERIES = {
    # ── Core Orchestrator KPIs ────────────────────────────────────────────
    "urllc_rtt_ms":        "orchestrator_urllc_rtt_ms",
    "embb_throughput_mbps":"orchestrator_embb_mbps",
    "mmtc_msgs_total":     "orchestrator_mmtc_msgs_total",
    "embb_tc_rate_mbit":   "orchestrator_embb_rate_mbit",
    "orchestrator_state":  "orchestrator_state",        # 0=NORMAL 1=THROTTLED
    # ── SLA / Control Counters ────────────────────────────────────────────
    "violation_count":     "orchestrator_violation_count",
    "recovery_streak":     "orchestrator_recovery_streak",
    "throttle_total":      "orchestrator_throttle_total",
    "restore_total":       "orchestrator_restore_total",
    "loop_count":          "orchestrator_loop_count",
    # ── Kubernetes CPU (cores) per namespace ──────────────────────────────
    "cpu_embb_cores":      'sum(rate(container_cpu_usage_seconds_total{namespace="embb"}[1m]))',
    "cpu_urllc_cores":     'sum(rate(container_cpu_usage_seconds_total{namespace="urllc"}[1m]))',
    "cpu_mmtc_cores":      'sum(rate(container_cpu_usage_seconds_total{namespace="mmtc"}[1m]))',
    # ── Kubernetes Memory (Mi) per namespace ──────────────────────────────
    "mem_embb_mi":         'sum(container_memory_working_set_bytes{namespace="embb"}) / 1048576',
    "mem_urllc_mi":        'sum(container_memory_working_set_bytes{namespace="urllc"}) / 1048576',
    "mem_mmtc_mi":         'sum(container_memory_working_set_bytes{namespace="mmtc"}) / 1048576',
    # ── Node CPU (worker node) ────────────────────────────────────────────
    "node_cpu_pct":        '100*(1 - avg(rate(node_cpu_seconds_total{mode="idle",instance=~".*171.*"}[1m])))',
    # ── Pod restart counts (instability indicator) ────────────────────────
    "pod_restarts_embb":   'sum(kube_pod_container_status_restarts_total{namespace="embb"})',
    "pod_restarts_urllc":  'sum(kube_pod_container_status_restarts_total{namespace="urllc"})',
    "pod_restarts_mmtc":   'sum(kube_pod_container_status_restarts_total{namespace="mmtc"})',
}

# ── 5-Class SLA Label (for ML classification) ────────────────────────────────
def sla_label(row: dict) -> str:
    """
    Classes:
      normal       — RTT < 12ms, no throttle     (healthy baseline)
      near_sla     — 12ms ≤ RTT < 15ms, no throttle (approaching limit)
      violation    — RTT ≥ 15ms, not yet throttled  (SLA breach active)
      throttled    — orchestrator_state=1, RTT still high (tc=50Mbit applied)
      recovering   — orchestrator_state=1, RTT < 15ms   (throttle working)
    """
    rtt   = row.get("urllc_rtt_ms", 0.0)
    state = row.get("orchestrator_state", 0.0)
    tc    = row.get("embb_tc_rate_mbit", 1000.0)

    if state == 1.0 or tc < 900.0:          # orchestrator has throttled
        if rtt < 15.0:
            return "recovering"              # throttle working, RTT back down
        else:
            return "throttled"               # still high despite throttle
    elif rtt >= 15.0:
        return "violation"                   # SLA breach, throttle pending
    elif rtt >= 12.0:
        return "near_sla"                    # approaching limit
    else:
        return "normal"                      # healthy

# ── Prometheus query helper ───────────────────────────────────────────────────
def prom_query(q: str) -> float:
    try:
        r = requests.get(PROM_URL, params={"query": q}, timeout=PROM_TIMEOUT)
        result = r.json()["data"]["result"]
        if result:
            v = float(result[0]["value"][1])
            return 0.0 if math.isnan(v) or math.isinf(v) else v
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Prometheus unreachable — check if port-forward is active: kubectl port-forward -n monitoring svc/prometheus 30090:9090")
    except requests.exceptions.Timeout:
        raise RuntimeError("Prometheus query timed out — Prometheus may be overloaded")
    except Exception as e:
        pass  # return 0.0 for transient errors
    return 0.0

# ── Orchestrator health check ─────────────────────────────────────────────────
def check_orchestrator_alive(last_loop_count: float, current_loop_count: float,
                              stale_since: float) -> tuple:
    """Returns (is_healthy, warning_message)"""
    if current_loop_count == 0.0:
        return False, "⚠️  ORCHESTRATOR DEAD — loop_count=0. Restart: nohup python3 phase3-orchestrator.py > /tmp/orchestrator.log 2>&1 &"
    if current_loop_count == last_loop_count and time.time() - stale_since > STALE_THRESH:
        return False, f"⚠️  ORCHESTRATOR STALE — loop_count stuck at {current_loop_count:.0f} for {STALE_THRESH}s. Check: tail -5 /tmp/orchestrator.log"
    return True, ""

# ── File rotation ─────────────────────────────────────────────────────────────
def rotate_path(base_path: str, part: int) -> str:
    root, ext = os.path.splitext(base_path)
    return f"{root}_part{part:02d}{ext}"

# ── Main collector loop ───────────────────────────────────────────────────────
def run(output_file: str, interval: float, target_rows: int):
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)

    columns    = ["timestamp"] + list(QUERIES.keys()) + ["sla_label"]
    total_rows = 0
    part       = 1
    rows_in_part = 0
    ROWS_PER_FILE = 10_000

    t_start    = time.time()
    last_loop  = 0.0
    stale_since= time.time()

    print("=" * 68)
    print("  5G MEC Research Collector — 50K Row Dataset Builder")
    print("=" * 68)
    print(f"  Output  : {output_file}")
    print(f"  Interval: {interval}s/sample")
    print(f"  Target  : {target_rows:,} rows")
    eta_hours = (target_rows * interval) / 3600
    print(f"  ETA     : ~{eta_hours:.1f} hours ({datetime.now() + timedelta(hours=eta_hours):%Y-%m-%d %H:%M} IST)")
    print(f"  Metrics : {len(QUERIES)} Prometheus queries + sla_label")
    print(f"  Files   : auto-rotate every {ROWS_PER_FILE:,} rows")
    print("=" * 68)
    print("  Ctrl+C to stop gracefully\n")

    current_file = rotate_path(output_file, part)
    f = open(current_file, "a", newline="")
    writer = csv.DictWriter(f, fieldnames=columns)
    if os.path.getsize(current_file) == 0:
        writer.writeheader()
    print(f"[part {part:02d}] Writing → {current_file}")

    try:
        while True:
            t_sample = time.time()
            row = {"timestamp": datetime.now().isoformat()}

            # ── Query all metrics ──────────────────────────────────────────
            for key, query in QUERIES.items():
                try:
                    row[key] = round(prom_query(query), 5)
                except RuntimeError as e:
                    # Critical error — display and wait before retrying
                    print(f"\n{'!'*68}")
                    print(f"  INTERRUPT: {e}")
                    print(f"{'!'*68}\n")
                    time.sleep(10)
                    row[key] = 0.0

            row["sla_label"] = sla_label(row)

            # ── Orchestrator watchdog ──────────────────────────────────────
            cur_loop = row.get("loop_count", 0.0)
            if cur_loop != last_loop:
                stale_since = time.time()
                last_loop = cur_loop
            alive, warn = check_orchestrator_alive(last_loop, cur_loop, stale_since)
            if not alive:
                print(f"\n{'!'*68}")
                print(f"  WATCHDOG: {warn}")
                print(f"{'!'*68}\n")

            # ── Write row ──────────────────────────────────────────────────
            writer.writerow(row)
            f.flush()
            total_rows   += 1
            rows_in_part += 1

            # ── Progress display every 100 samples ────────────────────────
            if total_rows % 100 == 0:
                elapsed   = time.time() - t_start
                rate      = total_rows / elapsed if elapsed > 0 else 0
                remaining = max(0, target_rows - total_rows)
                eta_s     = remaining / rate if rate > 0 else 0
                pct       = min(100, total_rows / target_rows * 100)
                bar       = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
                print(f"[{datetime.now():%H:%M:%S}] "
                      f"{total_rows:>6}/{target_rows:,} ({pct:5.1f}%) "
                      f"|{bar}| "
                      f"ETA {timedelta(seconds=int(eta_s))} | "
                      f"RTT={row['urllc_rtt_ms']:.1f}ms "
                      f"eMBB={row['embb_throughput_mbps']:.0f}Mbps "
                      f"tc={row['embb_tc_rate_mbit']:.0f}Mbit "
                      f"[{row['sla_label']}]")

            # ── Rotate file every 10K rows ─────────────────────────────────
            if rows_in_part >= ROWS_PER_FILE:
                f.close()
                print(f"\n[part {part:02d}] Closed → {current_file} ({rows_in_part} rows)")
                part += 1
                rows_in_part = 0
                current_file = rotate_path(output_file, part)
                f = open(current_file, "a", newline="")
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                print(f"[part {part:02d}] Writing → {current_file}\n")

            # ── Check if target reached ────────────────────────────────────
            if total_rows >= target_rows:
                print(f"\n{'='*68}")
                print(f"  🎉 TARGET REACHED: {total_rows:,} rows collected!")
                print(f"  Total time: {timedelta(seconds=int(time.time()-t_start))}")
                print(f"{'='*68}")
                break

            # ── Sleep remainder of interval ────────────────────────────────
            elapsed_sample = time.time() - t_sample
            sleep_t = max(0, interval - elapsed_sample)
            time.sleep(sleep_t)

    except KeyboardInterrupt:
        print(f"\n[collector] Stopped by user after {total_rows:,} rows.")
    except Exception as e:
        print(f"\n{'!'*68}")
        print(f"  FATAL INTERRUPT — {type(e).__name__}: {e}")
        print(f"  Traceback:")
        traceback.print_exc()
        print(f"\n  Rows collected before crash: {total_rows:,}")
        print(f"  Last written file: {current_file}")
        print(f"  To resume, re-run with same --output path (appends automatically)")
        print(f"{'!'*68}")
    finally:
        if not f.closed:
            f.close()
        print(f"\n[collector] Final count: {total_rows:,} rows across {part} file(s)")
        print(f"[collector] Data location: {os.path.dirname(os.path.abspath(output_file))}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="5G MEC Continuous Metrics Collector")
    parser.add_argument("--output",   default="experiments/results/continuous/dataset.csv",
                        help="Output CSV path (auto-rotated every 10K rows)")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="Seconds between samples (default: 1)")
    parser.add_argument("--target",   type=int,   default=50_000,
                        help="Stop after N rows (default: 50000)")
    args = parser.parse_args()
    run(args.output, args.interval, args.target)