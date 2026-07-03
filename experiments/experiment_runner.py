#!/usr/bin/env python3
"""
experiment_runner.py v2 — Controlled Multi-Level Traffic Experiment Framework
=============================================================================
Executes a structured sequence of load levels and records all metrics.

Load differentiation methodology (v2 hardened):
  UE count is FIXED across all levels (all active uesimtun interfaces used).
  Load is varied ONLY via traffic generation parameters:
    eMBB : HLS quality (360p/720p/1080p) + per-quality session/break timing
    URLLC: request rate (urllc_rate_hz: 1/2/4 Hz per UE)
    mMTC : publish rate multiplier (mmtc_rate_mult: 1x/2x/4x)

  Level 1 — LOW   : 360p  (duty~37%) | URLLC 1.0Hz | mMTC 1.0x  → ~370 Mbps offered
  Level 2 — MED   : 720p  (duty~72%) | URLLC 2.0Hz | mMTC 2.0x  → ~720 Mbps offered
  Level 3 — HIGH  : 1080p (duty~86%) | URLLC 4.0Hz | mMTC 4.0x  → ~860 Mbps offered

Segment sizes verified on nginx: 360p=676KB  720p=2.33MB  1080p=4.72MB

Usage:
    python3 experiment_runner.py [--levels 0,1,2,3,4,5] [--dwell 120] [--output results/]
"""

import argparse, subprocess, time, csv, os, json, threading
from datetime import datetime
from pathlib import Path
import requests

# ── Config ────────────────────────────────────────────────────────────────────
PROM_URL       = "http://192.168.49.174:30090/api/v1/query"
UERANSIM_IP    = "192.168.49.139"
UERANSIM_USER  = "shinegami"
UERANSIM_PASS  = "123"
EDGE_IP        = "192.168.49.171"
COLLECT_INTERVAL = 3   # seconds (matches orchestrator loop)

# ── Load Level Definitions ────────────────────────────────────────────────────
LOAD_LEVELS = {
    0: {
        "name": "baseline",
        "description": "Single UE per slice, minimum HLS quality",
        "embb_ues":  1, "urllc_ues": 1, "mmtc_ues": 3,
        "hls_quality": "360p",
        "embb_replicas": 1, "urllc_replicas": 1, "mmtc_replicas": 1,
        "dwell_sec": 120,
        "expected_urllc_rtt_ms": "<3",
        "expected_embb_mbps": ">20",
        "expected_mmtc_pdr": ">99.9%",
    },
    1: {
        "name": "low",
        "description": "LOW load — 360p quality, 37% eMBB duty cycle, URLLC 1Hz, mMTC 1x",
        "hls_quality":    "360p",
        "urllc_rate_hz":  1.0,
        "mmtc_rate_mult": 1.0,
        "embb_replicas": 1, "urllc_replicas": 1, "mmtc_replicas": 1,
        "dwell_sec": 1200,
        "expected_embb_offered_mbps": "~370",
        "expected_urllc_rtt_ms":      "<14 (comfortable headroom)",
        "expected_mmtc_pdr":          ">99.8%",
    },
    2: {
        "name": "medium",
        "description": "MEDIUM load — 720p quality, 72% eMBB duty cycle, URLLC 2Hz, mMTC 2x",
        "hls_quality":    "720p",
        "urllc_rate_hz":  2.0,
        "mmtc_rate_mult": 2.0,
        "embb_replicas": 1, "urllc_replicas": 1, "mmtc_replicas": 1,
        "dwell_sec": 1200,
        "expected_embb_offered_mbps": "~720",
        "expected_urllc_rtt_ms":      "14–16 (mild pressure)",
        "expected_mmtc_pdr":          ">99.5%",
    },
    3: {
        "name": "high",
        "description": "HIGH load — 1080p quality, 86% eMBB duty cycle, URLLC 4Hz, mMTC 4x",
        "hls_quality":    "1080p",
        "urllc_rate_hz":  4.0,
        "mmtc_rate_mult": 4.0,
        "embb_replicas": 1, "urllc_replicas": 1, "mmtc_replicas": 1,
        "dwell_sec": 1200,
        "expected_embb_offered_mbps": "~860",
        "expected_urllc_rtt_ms":      ">15 (SLA breach likely, orchestrator reacts)",
        "expected_mmtc_pdr":          ">99.0%",
    },
    4: {
        "name": "extreme",
        "description": "EXTREME load — 1080p, 4Hz URLLC, 4x mMTC (reserved, not used in campaign)",
        "hls_quality":    "1080p",
        "urllc_rate_hz":  4.0,
        "mmtc_rate_mult": 4.0,
        "embb_replicas": 2, "urllc_replicas": 1, "mmtc_replicas": 1,
        "dwell_sec": 1200,
        "expected_embb_offered_mbps": "~860+",
        "expected_urllc_rtt_ms":      ">20 (sustained)",
        "expected_mmtc_pdr":          ">98.5%",
    },
    5: {
        "name": "recovery",
        "description": "RECOVERY — 720p, 2Hz URLLC, 2x mMTC (reserved, not used in campaign)",
        "hls_quality":    "720p",
        "urllc_rate_hz":  2.0,
        "mmtc_rate_mult": 2.0,
        "embb_replicas": 1, "urllc_replicas": 1, "mmtc_replicas": 1,
        "dwell_sec": 1200,
        "expected_embb_offered_mbps": "~720 (recovering)",
        "expected_urllc_rtt_ms":      "<15 (recovering)",
        "expected_mmtc_pdr":          ">99.5%",
    },
}

# ── Prometheus Metrics (aligned to phase3-orchestrator.py exports) ────────────
METRICS = {
    # Core phase3 orchestrator metrics
    "urllc_rtt_ms":        "orchestrator_urllc_rtt_ms",
    "embb_throughput_mbps":"orchestrator_embb_mbps",          # phase3 uses Mbps
    "mmtc_msgs_total":     "orchestrator_mmtc_msgs_total",    # phase3 counts msgs
    "embb_tc_rate_mbit":   "orchestrator_embb_rate_mbit",
    "orchestrator_state":  "orchestrator_state",
    "violation_count":     "orchestrator_violation_count",
    "recovery_streak":     "orchestrator_recovery_streak",
    "throttle_total":      "orchestrator_throttle_total",
    "restore_total":       "orchestrator_restore_total",
    "loop_count":          "orchestrator_loop_count",
    # Kubernetes CPU per namespace
    "cpu_embb_cores":      'sum(rate(container_cpu_usage_seconds_total{namespace="embb"}[1m]))',
    "cpu_urllc_cores":     'sum(rate(container_cpu_usage_seconds_total{namespace="urllc"}[1m]))',
    "cpu_mmtc_cores":      'sum(rate(container_cpu_usage_seconds_total{namespace="mmtc"}[1m]))',
    # Node CPU
    "node_cpu_pct":        '100 - (avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)',
    # Memory per namespace (Mi)
    "mem_embb_mi":         'sum(container_memory_working_set_bytes{namespace="embb"}) / 1048576',
    "mem_urllc_mi":        'sum(container_memory_working_set_bytes{namespace="urllc"}) / 1048576',
    "mem_mmtc_mi":         'sum(container_memory_working_set_bytes{namespace="mmtc"}) / 1048576',
}

# ── Prometheus helper ─────────────────────────────────────────────────────────
def prom_query(q: str) -> float:
    try:
        r = requests.get(PROM_URL, params={"query": q}, timeout=3)
        result = r.json()["data"]["result"]
        if result:
            return float(result[0]["value"][1])
    except Exception:
        pass
    return float("nan")

# ── SSH helpers ───────────────────────────────────────────────────────────────
def ssh(cmd: str) -> str:
    """Run command on UERANSIM VM via sshpass."""
    full = (
        f"sshpass -p '{UERANSIM_PASS}' ssh "
        f"-o StrictHostKeyChecking=no -o ConnectTimeout=5 "
        f"{UERANSIM_USER}@{UERANSIM_IP} '{cmd}'"
    )
    try:
        r = subprocess.run(full, shell=True, capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except Exception as e:
        return f"SSH_ERR: {e}"

def kubectl(cmd: str) -> str:
    try:
        r = subprocess.run(f"kubectl {cmd}", shell=True, capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except Exception as e:
        return f"KUBECTL_ERR: {e}"

# ── UE scaling on UERANSIM VM ─────────────────────────────────────────────────
def get_active_ue_count(slice_prefix: str) -> int:
    """Count active UE processes on UERANSIM VM for a given slice."""
    count = ssh(f"pgrep -c -f 'nr-ue.*{slice_prefix}' || echo 0")
    try:
        return int(count.strip())
    except Exception:
        return 0

def scale_ues(level: dict):
    """
    Restart traffic clients on UERANSIM VM with load-level traffic parameters.
    v2: UE count is FIXED (all active uesimtun interfaces used).
    Load differentiation via: eMBB quality, URLLC rate_hz, mMTC rate_mult.
    """
    quality    = level.get("hls_quality",    "1080p")
    urllc_rate = level.get("urllc_rate_hz",   1.0)
    mmtc_mult  = level.get("mmtc_rate_mult",  1.0)

    print(f"  [UE] Restarting clients for level '{level['name']}' — "
          f"quality={quality}  urllc={urllc_rate}Hz  mmtc={mmtc_mult}x")

    iface_count = ssh("ip -4 addr show | grep -c uesimtun")
    try:
        n = int(iface_count.strip())
    except Exception:
        n = 0
    print(f"  [UE] Active uesimtun interfaces: {n}")

    if n == 0:
        print("  [UE] WARNING: No uesimtun interfaces — skipping client restart.")
        return

    # Kill existing traffic clients
    ssh("pkill -f embb_client.py 2>/dev/null; "
        "pkill -f urllc_client.py 2>/dev/null; "
        "pkill -f mmtc_client.py 2>/dev/null; sleep 2")

    # Launch with load-level parameters (v2 launch script)
    launch_cmd = (
        f"cd ~/mec-clients && nohup bash launch_mec_clients.sh "
        f"{quality} {urllc_rate} {mmtc_mult} "
        f"> /tmp/clients.log 2>&1 &"
    )
    ssh(launch_cmd)
    time.sleep(6)

    ec = ssh("pgrep -c -f embb_client.py 2>/dev/null || echo 0").strip()
    uc = ssh("pgrep -c -f urllc_client.py 2>/dev/null || echo 0").strip()
    mc = ssh("pgrep -c -f mmtc_client.py 2>/dev/null || echo 0").strip()
    print(f"  [UE] Traffic clients — eMBB:{ec}  URLLC:{uc}  mMTC:{mc}")
    print(f"  [eMBB] quality={quality}  session/break per profile  "
          f"segs: 360p=676KB  720p=2.33MB  1080p=4.72MB")

# ── Kubernetes workload scaling ───────────────────────────────────────────────
def scale_k8s_workloads(level: dict):
    """Scale Kubernetes deployments to match load level."""
    for ns, deploy, replicas in [
        ("embb",  "embb-app",  level["embb_replicas"]),
        ("urllc", "urllc-app", level["urllc_replicas"]),
        ("mmtc",  "mmtc-app",  level["mmtc_replicas"]),
    ]:
        result = kubectl(f"scale deployment/{deploy} -n {ns} --replicas={replicas}")
        print(f"  [K8s] {ns}/{deploy} → {replicas} replica(s): {result[:50]}")
    time.sleep(10)  # wait for pods to stabilise

# ── Data Collection ───────────────────────────────────────────────────────────
class DataCollector:
    def __init__(self, output_dir: str, level_name: str, orchestrator_type: str = "rule_based"):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filepath = os.path.join(output_dir, f"exp_{level_name}_{orchestrator_type}_{ts}.csv")
        self._file = open(self.filepath, "w", newline="")
        self._writer = csv.writer(self._file)
        self._writer.writerow(["timestamp", "load_level", "orchestrator_type"] + list(METRICS.keys()))
        self._running = False
        self._thread = None
        self.level_name = level_name
        self.orchestrator_type = orchestrator_type
        self.rows = []
        print(f"  [CSV] Writing to: {self.filepath}")

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        self._file.flush()
        self._file.close()
        print(f"  [CSV] Saved {len(self.rows)} rows → {self.filepath}")

    def _loop(self):
        while self._running:
            row = [datetime.now().isoformat(), self.level_name, self.orchestrator_type]
            for key, query in METRICS.items():
                row.append(prom_query(query))
            self._writer.writerow(row)
            self._file.flush()
            self.rows.append(row)
            time.sleep(COLLECT_INTERVAL)

# ── Experiment Summary ────────────────────────────────────────────────────────
def compute_summary(rows: list, level: dict) -> dict:
    """Compute per-level statistics from collected rows."""
    if not rows:
        return {}

    # Column indices (after timestamp and load_level)
    col_names = list(METRICS.keys())
    def col_vals(col_name):
        idx = col_names.index(col_name) + 3  # +3: timestamp, load_level, orchestrator_type
        vals = []
        for r in rows:
            try:
                v = float(r[idx])
                if v == v:  # exclude NaN
                    vals.append(v)
            except Exception:
                pass
        return vals

    def safe_avg(vals): return sum(vals)/len(vals) if vals else float("nan")
    def safe_max(vals): return max(vals) if vals else float("nan")
    def safe_min(vals): return min(vals) if vals else float("nan")

    rtt_vals = col_vals("urllc_rtt_ms")
    tp_vals  = col_vals("embb_throughput_mbps")   # phase3: Mbps not bps
    pdr_vals = col_vals("mmtc_msgs_total")         # phase3: msg count not PDR
    thr_vals = col_vals("throttle_total")
    tc_vals  = col_vals("embb_tc_rate_mbit")
    fair_vals= col_vals("loop_count")              # fairness not in phase3

    # Count SLA violations (RTT > 20ms per EXPERIMENT_PARAMS.md URLLC_RTT_SLA_MS=20)
    SLA_THRESHOLD_MS = 20.0
    sla_violations = sum(1 for v in rtt_vals if v > SLA_THRESHOLD_MS)

    # Estimate recovery time: find first RTT > SLA then first RTT <= SLA after that
    recovery_time_s = float("nan")
    breach_idx = next((i for i, v in enumerate(rtt_vals) if v > SLA_THRESHOLD_MS), None)
    if breach_idx is not None:
        recovery_idx = next(
            (i for i, v in enumerate(rtt_vals[breach_idx:]) if v <= SLA_THRESHOLD_MS), None)
        if recovery_idx is not None:
            recovery_time_s = recovery_idx * COLLECT_INTERVAL

    return {
        "level":               level["name"],
        "samples":             len(rows),
        "urllc_rtt_avg_ms":    round(safe_avg(rtt_vals), 2),
        "urllc_rtt_max_ms":    round(safe_max(rtt_vals), 2),
        "urllc_rtt_min_ms":    round(safe_min(rtt_vals), 2),
        "embb_tp_avg_mbps":    round(safe_avg(tp_vals), 2),   # already Mbps
        "embb_tp_min_mbps":    round(safe_min(tp_vals), 2),
        "mmtc_msgs_avg":       round(safe_avg(pdr_vals), 0),
        "mmtc_msgs_max":       round(safe_max(pdr_vals), 0),
        "throttle_actions":    int(safe_max(thr_vals)) if thr_vals else 0,
        "tc_rate_min_mbit":    round(safe_min(tc_vals), 1),
        "tc_rate_avg_mbit":    round(safe_avg(tc_vals), 1),
        "orchestrator_loops":  int(safe_max(fair_vals)) if fair_vals else 0,
        "sla_violations":      sla_violations,
        "recovery_time_s":     round(recovery_time_s, 1) if recovery_time_s == recovery_time_s else "N/A",
        "expected_rtt":        level["expected_urllc_rtt_ms"],
        "expected_embb":       level.get("expected_embb_mbps", level.get("expected_embb_offered_mbps", "?")),  # v2 compat
        "expected_pdr":        level["expected_mmtc_pdr"],
    }

# ── Main Experiment Loop ──────────────────────────────────────────────────────
def run_experiment(levels_to_run: list, output_dir: str, orchestrator_type: str = "rule_based"):
    all_summaries = []
    print("=" * 65)
    print("  5G MEC QoS Orchestration — Controlled Traffic Experiment")
    print(f"  Output: {output_dir}")
    print(f"  Orchestrator: {orchestrator_type}")
    print(f"  Levels: {[LOAD_LEVELS[l]['name'] for l in levels_to_run]}")
    print("=" * 65)

    # Verify Prometheus reachable
    test = prom_query("orchestrator_loop_count")
    if test != test:
        print("[WARN] Prometheus not reachable — metrics will be NaN. Continuing.")
    else:
        print(f"[OK] Prometheus reachable. Orchestrator loops: {test:.0f}")

    print()

    for level_id in levels_to_run:
        level = LOAD_LEVELS[level_id]
        print(f"{'─'*65}")
        print(f"  Level {level_id}: {level['name'].upper()} — {level['description']}")
        print(f"  quality={level['hls_quality']}  urllc={level['urllc_rate_hz']}Hz  "
              f"mmtc={level['mmtc_rate_mult']}x  offered~{level.get('expected_embb_offered_mbps','?')}Mbps  "
              f"dwell={level['dwell_sec']}s")
        print(f"{'─'*65}")

        # Step 1: Scale Kubernetes workloads
        print(f"\n[1/3] Scaling Kubernetes workloads...")
        scale_k8s_workloads(level)

        # Step 2: Scale UE traffic clients
        print(f"\n[2/3] Scaling traffic clients on UERANSIM VM...")
        scale_ues(level)

        # Step 3: Collect data for dwell period
        print(f"\n[3/3] Collecting data for {level['dwell_sec']}s...")
        collector = DataCollector(output_dir, level["name"], orchestrator_type)
        collector.start()

        t_start = time.time()
        while time.time() - t_start < level["dwell_sec"]:
            elapsed = int(time.time() - t_start)
            remaining = level["dwell_sec"] - elapsed
            # Live status every 15s
            if elapsed % 15 == 0 and elapsed > 0:
                rtt = prom_query("orchestrator_urllc_rtt_ms")
                tp  = prom_query("orchestrator_embb_mbps")
                tc  = prom_query("orchestrator_embb_rate_mbit")
                vio = prom_query("orchestrator_violation_count")
                tp_disp = tp if tp == tp else 0.0  # handle NaN
                print(f"  t+{elapsed:3d}s | RTT={rtt:.1f}ms | "
                      f"eMBB={tp_disp:.1f}Mbps | tc={tc:.0f}Mbit | "
                      f"violations={vio:.0f} | {remaining}s left")
            time.sleep(3)

        collector.stop()

        # Compute and display summary
        summary = compute_summary(collector.rows, level)
        all_summaries.append(summary)

        print(f"\n  ── Summary: {level['name'].upper()} ──────────────────────────")
        print(f"  URLLC RTT: avg={summary['urllc_rtt_avg_ms']}ms "
              f"max={summary['urllc_rtt_max_ms']}ms")
        print(f"  eMBB Throughput: avg={summary['embb_tp_avg_mbps']}Mbps "
              f"min={summary['embb_tp_min_mbps']}Mbps")
        print(f"  mMTC msgs: avg={summary['mmtc_msgs_avg']:.0f} "
              f"max={summary['mmtc_msgs_max']:.0f}")
        print(f"  Throttle actions: {summary['throttle_actions']} | "
              f"tc_rate_min: {summary['tc_rate_min_mbit']}Mbit")
        print(f"  SLA violations: {summary['sla_violations']} | "
              f"Recovery time: {summary['recovery_time_s']}s")
        print(f"  Orchestrator loops: {summary['orchestrator_loops']}")
        print()

    # ── Final Results Table ──────────────────────────────────────────────────
    print("\n" + "="*65)
    print("  EXPERIMENT RESULTS TABLE")
    print("="*65)
    header = (f"{'Level':<10} {'RTT_avg':>8} {'RTT_max':>8} {'eMBB_avg':>9} "
              f"{'PDR':>7} {'Throttle':>9} {'Recovery':>10} {'Fairness':>9}")
    print(header)
    print("─" * 70)
    for s in all_summaries:
        print(f"{s['level']:<10} {s['urllc_rtt_avg_ms']:>7.2f}ms "
              f"{s['urllc_rtt_max_ms']:>7.2f}ms "
              f"{s['embb_tp_avg_mbps']:>7.2f}Mbps "
              f"{s['mmtc_msgs_avg']:>7.0f}msgs "
              f"{s['throttle_actions']:>8} "
              f"{str(s['recovery_time_s']):>9}s "
              f"{s['orchestrator_loops']:>9}loops")

    # Save summary JSON
    summary_file = os.path.join(output_dir, f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(summary_file, "w") as f:
        json.dump(all_summaries, f, indent=2)
    print(f"\n[DONE] Summary saved → {summary_file}")

# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="5G MEC Experiment Runner")
    parser.add_argument("--levels", default="0,1,2,3,4,5",
                        help="Comma-separated level IDs to run (default: 0,1,2,3,4,5)")
    parser.add_argument("--dwell", type=int, default=None,
                        help="Override dwell time in seconds for all levels")
    parser.add_argument("--output", default="experiments/results",
                        help="Output directory for CSV and JSON files")
    parser.add_argument("--orchestrator", default="rule_based",
                        choices=["rule_based", "agentic"],
                        help="Orchestrator type tag written to every CSV row (default: rule_based)")
    args = parser.parse_args()

    levels = [int(x) for x in args.levels.split(",") if x.strip().isdigit()]
    if args.dwell:
        for l in LOAD_LEVELS.values():
            l["dwell_sec"] = args.dwell

    run_experiment(levels, args.output, args.orchestrator)
