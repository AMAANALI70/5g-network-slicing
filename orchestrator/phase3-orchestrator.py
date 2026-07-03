#!/usr/bin/env python3
"""
Phase 3 QoS Orchestrator — Rule-Based Baseline with Autoscaling
================================================================
Deterministic rule-based baseline for comparative experiment.

Actions:
  1. tc-shaping : throttle / restore eMBB GTP tunnel bandwidth
  2. Autoscaling: kubectl scale app deployments based on SLA state

SLA Thresholds (aligned with 3GPP TS 22.261 / research standard):
  URLLC RTT  < 15ms   (throttle eMBB when violated)
  eMBB  TP   > 20Mbps (scale up embb-app when violated)
  mMTC  PDR  > 99.5%  (scale up mmtc-app when violated)

Exposes Prometheus metrics on port 9200 for Grafana dashboards.
"""
import subprocess, time, re, sys, threading, json
import urllib.request, urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

# ---- Configuration -----------------------------------------------
UERANSIM_IP       = "192.168.49.139"
UERANSIM_USER     = "shinegami"
UERANSIM_PASS     = "123"
LOG_DIR           = "/tmp/mec-clients"

# SLA thresholds (3GPP / research standard)
URLLC_SLA_MS      = 15.0   # URLLC RTT SLA — throttle eMBB when exceeded
EMBB_MIN_TP_MBPS  = 20.0   # eMBB throughput floor — scale up when below this
MMTC_MIN_PDR      = 0.995  # mMTC packet delivery ratio floor

# tc shaping parameters
EMBB_THROTTLE_BW  = "50mbit"
EMBB_RESTORE_BW   = "1000mbit"

# Autoscaling parameters
URLLC_MAX_REPLICAS = 3
URLLC_MIN_REPLICAS = 1
EMBB_MAX_REPLICAS  = 3
EMBB_MIN_REPLICAS  = 1
MMTC_MAX_REPLICAS  = 3
MMTC_MIN_REPLICAS  = 1
SCALE_UP_STREAK    = 3   # consecutive violations before scaling up
SCALE_DOWN_STREAK  = 10  # consecutive healthy cycles before scaling down

# Loop timing
CHECK_INTERVAL    = 5
VIOLATION_COUNT   = 3    # RTT violations before eMBB throttle
RESTORE_COUNT     = 5    # OK cycles before eMBB restore
METRICS_PORT      = 9200

# ---- Shared metrics state ----------------------------------------
_m = {
    "urllc_rtt_ms":       0.0,
    "embb_mbps":          0.0,
    "mmtc_msgs":          0,
    "state":              0,        # 0=NORMAL 1=THROTTLED
    "embb_rate_mbit":     1000,
    "violation_count":    0,
    "throttle_total":     0,
    "restore_total":      0,
    "recovery_streak":    0,
    "loop_count":         0,
    # Autoscaling replica counts
    "urllc_replicas":     1,
    "embb_replicas":      1,
    "mmtc_replicas":      1,
    "scale_up_total":     0,
    "scale_down_total":   0,
}


def metrics_text():
    return "\n".join([
        "# HELP orchestrator_urllc_rtt_ms URLLC avg RTT from client logs (ms)",
        "# TYPE orchestrator_urllc_rtt_ms gauge",
        f'orchestrator_urllc_rtt_ms {_m["urllc_rtt_ms"]:.2f}',
        "# HELP orchestrator_embb_mbps eMBB aggregate throughput (Mbps)",
        "# TYPE orchestrator_embb_mbps gauge",
        f'orchestrator_embb_mbps {_m["embb_mbps"]:.1f}',
        "# HELP orchestrator_mmtc_msgs_total Total mMTC MQTT messages published",
        "# TYPE orchestrator_mmtc_msgs_total gauge",
        f'orchestrator_mmtc_msgs_total {_m["mmtc_msgs"]}',
        "# HELP orchestrator_state Orchestrator state: 0=NORMAL 1=THROTTLED",
        "# TYPE orchestrator_state gauge",
        f'orchestrator_state {_m["state"]}',
        "# HELP orchestrator_embb_rate_mbit Current tc bandwidth cap on ogstun-embb (Mbit)",
        "# TYPE orchestrator_embb_rate_mbit gauge",
        f'orchestrator_embb_rate_mbit {_m["embb_rate_mbit"]}',
        "# HELP orchestrator_violation_count Current SLA violation streak",
        "# TYPE orchestrator_violation_count gauge",
        f'orchestrator_violation_count {_m["violation_count"]}',
        "# HELP orchestrator_throttle_total Total eMBB throttle actions",
        "# TYPE orchestrator_throttle_total counter",
        f'orchestrator_throttle_total {_m["throttle_total"]}',
        "# HELP orchestrator_restore_total Total eMBB restore actions",
        "# TYPE orchestrator_restore_total counter",
        f'orchestrator_restore_total {_m["restore_total"]}',
        "# HELP orchestrator_recovery_streak Current recovery streak",
        "# TYPE orchestrator_recovery_streak gauge",
        f'orchestrator_recovery_streak {_m["recovery_streak"]}',
        "# HELP orchestrator_loop_count Total orchestrator evaluation loops",
        "# TYPE orchestrator_loop_count counter",
        f'orchestrator_loop_count {_m["loop_count"]}',
        # Autoscaling metrics
        "# HELP orchestrator_urllc_replicas Current urllc-app replica count",
        "# TYPE orchestrator_urllc_replicas gauge",
        f'orchestrator_urllc_replicas {_m["urllc_replicas"]}',
        "# HELP orchestrator_embb_replicas Current embb-app replica count",
        "# TYPE orchestrator_embb_replicas gauge",
        f'orchestrator_embb_replicas {_m["embb_replicas"]}',
        "# HELP orchestrator_mmtc_replicas Current mmtc-app replica count",
        "# TYPE orchestrator_mmtc_replicas gauge",
        f'orchestrator_mmtc_replicas {_m["mmtc_replicas"]}',
        "# HELP orchestrator_scale_up_total Total scale-up events",
        "# TYPE orchestrator_scale_up_total counter",
        f'orchestrator_scale_up_total {_m["scale_up_total"]}',
        "# HELP orchestrator_scale_down_total Total scale-down events",
        "# TYPE orchestrator_scale_down_total counter",
        f'orchestrator_scale_down_total {_m["scale_down_total"]}',
        "# HELP orchestrator_agentic_mode 0=rule-based 1=agentic",
        "# TYPE orchestrator_agentic_mode gauge",
        "orchestrator_agentic_mode 0",
        # ── Agentic-only stubs (always 0 for rule-based, prevents Grafana 'No data') ──
        "# HELP orchestrator_llm_used 1 if LLM used this cycle",
        "# TYPE orchestrator_llm_used gauge",
        "orchestrator_llm_used 0",
        "# HELP orchestrator_llm_latency_ms LLM inference latency ms (0=not used)",
        "# TYPE orchestrator_llm_latency_ms gauge",
        "orchestrator_llm_latency_ms 0",
        "# HELP orchestrator_llm_confidence LLM decision confidence 0-1 (0=not used)",
        "# TYPE orchestrator_llm_confidence gauge",
        "orchestrator_llm_confidence 0",
        "# HELP orchestrator_memory_success_rate Memory-assisted success rate (0=not used)",
        "# TYPE orchestrator_memory_success_rate gauge",
        "orchestrator_memory_success_rate 0",
        "# HELP orchestrator_safety_overrides_total WLA safety overrides (0=not used)",
        "# TYPE orchestrator_safety_overrides_total counter",
        "orchestrator_safety_overrides_total 0",
    ]) + "\n"


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200); self.end_headers()
            self.wfile.write(b"ok"); return
        body = metrics_text().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass


def start_metrics_server():
    srv = HTTPServer(("0.0.0.0", METRICS_PORT), MetricsHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f"📡 Prometheus metrics on :{METRICS_PORT}/metrics")


# ---- SSH helpers -------------------------------------------------
def ssh_tail(pattern):
    remote_cmd = f"for f in {LOG_DIR}/{pattern}; do tail -1 $f 2>/dev/null; done"
    cmd = ["sshpass", "-p", UERANSIM_PASS,
           "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
           f"{UERANSIM_USER}@{UERANSIM_IP}", remote_cmd]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return [l for l in r.stdout.splitlines() if l.strip()]
    except Exception:
        return []


def get_urllc_rtt():
    rtts = []
    for line in ssh_tail("urllc_*.log"):
        m = re.search(r'RTT avg=([\d.]+)ms', line)
        if m:
            rtts.append(float(m.group(1)))
    return sum(rtts) / len(rtts) if rtts else 0.0


# Prometheus URL for unified eMBB throughput measurement
PROM_URL = "http://192.168.49.174:30090/api/v1/query"


def get_embb_mbps() -> float:
    """
    Read eMBB throughput from Prometheus UPF tun_tx_bytes counter.
    Unified measurement source (same as agentic orchestrator):
      irate(tun_tx_bytes{interface="ogstun-embb"}[30s]) * 8 / 1_000_000
    Falls back to 0.0 on Prometheus unavailability.
    """
    queries = [
        'irate(tun_tx_bytes{interface="ogstun-embb"}[30s])*8/1000000',
        'rate(tun_tx_bytes{interface="ogstun-embb"}[2m])*8/1000000',
    ]
    for q in queries:
        try:
            url = f"{PROM_URL}?query={urllib.parse.quote(q)}"
            with urllib.request.urlopen(url, timeout=3) as resp:
                d   = json.loads(resp.read().decode())
                res = d["data"]["result"]
                if res:
                    val = float(res[0]["value"][1])
                    if val > 0.0:
                        return round(val, 2)
        except Exception:
            pass
    return 0.0


def get_mmtc_msgs():
    total = 0
    for line in ssh_tail("mmtc_*.log"):
        m = re.search(r'(\d+) msgs published', line)
        if m:
            total += int(m.group(1))
    return total


# ---- Kubernetes helpers ------------------------------------------
def kubectl_scale(namespace, deployment, replicas):
    """Scale a deployment to the specified replica count."""
    try:
        r = subprocess.run(
            ["kubectl", "scale", f"deployment/{deployment}",
             "-n", namespace, f"--replicas={replicas}"],
            capture_output=True, text=True, timeout=15)
        return r.returncode == 0, r.stderr.strip()
    except Exception as e:
        return False, str(e)


def get_current_replicas(namespace, deployment):
    """Get current ready replica count."""
    try:
        out = subprocess.check_output(
            ["kubectl", "get", "deployment", deployment, "-n", namespace,
             "-o", "jsonpath={.spec.replicas}"],
            text=True, timeout=10).strip()
        return int(out) if out else 1
    except Exception:
        return 1


def kubectl_exec_upf(bash_cmd):
    try:
        upf = subprocess.check_output(
            "kubectl get pod -n embb -l app=upf-embb --no-headers | awk '{print $1}' | head -1",
            shell=True, text=True).strip()
        r = subprocess.run(
            ["kubectl", "exec", "-n", "embb", upf, "--", "bash", "-c", bash_cmd],
            capture_output=True, text=True, timeout=15)
        return r.returncode == 0, r.stdout.strip()
    except Exception as e:
        return False, str(e)


def throttle_embb(bw):
    rate_mbit = int(bw.replace("mbit", ""))
    cmd = f"""
      tc qdisc del dev ogstun-embb root 2>/dev/null || true
      tc qdisc add dev ogstun-embb root tbf rate {bw} burst 32kbit latency 400ms
      echo "throttled:{bw}"
    """
    ok, out = kubectl_exec_upf(cmd)
    if ok:
        _m["embb_rate_mbit"] = rate_mbit
    return ok, out


def restore_embb():
    ok, out = kubectl_exec_upf(
        "tc qdisc del dev ogstun-embb root 2>/dev/null && echo 'restored' || echo 'no-tc'")
    if ok:
        _m["embb_rate_mbit"] = 1000
    return ok, out


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---- Autoscaling controller --------------------------------------
class AutoscaleController:
    """Deterministic policy-driven pod autoscaler for app deployments."""

    def __init__(self):
        # Per-deployment violation / stable streak counters
        self._violation = {"urllc-app": 0, "embb-app": 0, "mmtc-app": 0}
        self._stable    = {"urllc-app": 0, "embb-app": 0, "mmtc-app": 0}
        # Cache current replicas to avoid redundant kubectl calls
        self._replicas  = {}
        for ns, dep in [("urllc","urllc-app"), ("embb","embb-app"), ("mmtc","mmtc-app")]:
            self._replicas[(ns, dep)] = get_current_replicas(ns, dep)

    def evaluate(self, rtt, embb_mbps, mmtc_msgs, tc_state):
        """
        Evaluate SLA state for each slice and scale app pods accordingly.

        Rules:
          URLLC: RTT > 15ms for SCALE_UP_STREAK cycles → scale urllc-app up
                 RTT < 10ms stable for SCALE_DOWN_STREAK cycles → scale down
          eMBB:  throughput < 20Mbps (and not throttled) → scale embb-app up
                 throughput > 50Mbps stable → scale down
          mMTC:  msgs == 0 for SCALE_UP_STREAK cycles → scale mmtc-app up
                 msgs > 0 stable for SCALE_DOWN_STREAK cycles → scale down
        """
        actions_taken = []

        # ── URLLC app scaling ─────────────────────────────────────
        urllc_violated = (rtt > URLLC_SLA_MS) and (rtt > 0)
        actions_taken += self._evaluate_deployment(
            ns="urllc", dep="urllc-app",
            violated=urllc_violated,
            max_rep=URLLC_MAX_REPLICAS, min_rep=URLLC_MIN_REPLICAS,
            metric_key="urllc_replicas",
            up_reason=f"URLLC RTT {rtt:.1f}ms > {URLLC_SLA_MS}ms SLA",
            down_reason=f"URLLC RTT stable at {rtt:.1f}ms",
        )

        # ── eMBB app scaling (only scale up when NOT throttled) ───
        # If we're in throttle state, eMBB low TP is intentional
        embb_low = (embb_mbps > 0) and (embb_mbps < EMBB_MIN_TP_MBPS)
        embb_violated = embb_low and (tc_state == "NORMAL")
        actions_taken += self._evaluate_deployment(
            ns="embb", dep="embb-app",
            violated=embb_violated,
            max_rep=EMBB_MAX_REPLICAS, min_rep=EMBB_MIN_REPLICAS,
            metric_key="embb_replicas",
            up_reason=f"eMBB throughput {embb_mbps:.1f}Mbps < {EMBB_MIN_TP_MBPS}Mbps SLA",
            down_reason=f"eMBB throughput stable at {embb_mbps:.1f}Mbps",
        )

        # ── mMTC app scaling ──────────────────────────────────────
        mmtc_violated = (mmtc_msgs == 0)
        actions_taken += self._evaluate_deployment(
            ns="mmtc", dep="mmtc-app",
            violated=mmtc_violated,
            max_rep=MMTC_MAX_REPLICAS, min_rep=MMTC_MIN_REPLICAS,
            metric_key="mmtc_replicas",
            up_reason=f"mMTC msgs=0 (broker unresponsive)",
            down_reason=f"mMTC msgs={mmtc_msgs} stable",
        )

        return actions_taken

    def _evaluate_deployment(self, ns, dep, violated,
                              max_rep, min_rep, metric_key,
                              up_reason, down_reason):
        key = (ns, dep)
        cur = self._replicas.get(key, 1)
        taken = []

        if violated:
            self._violation[dep] += 1
            self._stable[dep]    = 0
            if self._violation[dep] >= SCALE_UP_STREAK and cur < max_rep:
                new = min(max_rep, cur + 1)
                ok, err = kubectl_scale(ns, dep, new)
                if ok:
                    log(f"   ⬆ SCALE UP  {ns}/{dep}: {cur}→{new}  [{up_reason}]")
                    self._replicas[key] = new
                    _m[metric_key]      = new
                    _m["scale_up_total"] += 1
                    self._violation[dep] = 0
                    taken.append(f"scale_up:{dep}:{new}")
                else:
                    log(f"   ❌ Scale-up failed {ns}/{dep}: {err}")
        else:
            self._stable[dep]    += 1
            self._violation[dep]  = 0
            if self._stable[dep] >= SCALE_DOWN_STREAK and cur > min_rep:
                new = max(min_rep, cur - 1)
                ok, err = kubectl_scale(ns, dep, new)
                if ok:
                    log(f"   ⬇ SCALE DOWN {ns}/{dep}: {cur}→{new}  [{down_reason}]")
                    self._replicas[key] = new
                    _m[metric_key]      = new
                    _m["scale_down_total"] += 1
                    self._stable[dep]    = 0
                    taken.append(f"scale_down:{dep}:{new}")
                else:
                    log(f"   ❌ Scale-down failed {ns}/{dep}: {err}")

        # Keep metric in sync even without scaling event
        _m[metric_key] = self._replicas.get(key, cur)
        return taken


# ---- Main loop ---------------------------------------------------
def main():
    start_metrics_server()
    log("🤖 Phase 3 QoS Orchestrator (Rule-Based) starting...")
    log(f"   URLLC SLA={URLLC_SLA_MS}ms | eMBB floor={EMBB_MIN_TP_MBPS}Mbps "
        f"| throttle={EMBB_THROTTLE_BW} | interval={CHECK_INTERVAL}s")

    lines = ssh_tail("urllc_*.log")
    if not lines:
        log("⚠️  No data from UERANSIM — check sshpass/SSH connectivity")
    else:
        log(f"   SSH OK — {len(lines)} URLLC log lines from UERANSIM")
    log("")

    state         = "NORMAL"
    violation_streak = ok_streak = cycle_count = 0
    autoscaler    = AutoscaleController()

    # Sync initial replica state into metrics
    _m["urllc_replicas"] = get_current_replicas("urllc", "urllc-app")
    _m["embb_replicas"]  = get_current_replicas("embb",  "embb-app")
    _m["mmtc_replicas"]  = get_current_replicas("mmtc",  "mmtc-app")

    while True:
        rtt   = get_urllc_rtt()
        embb  = get_embb_mbps()
        mmtc  = get_mmtc_msgs()
        sla_ok = (rtt <= URLLC_SLA_MS) or (rtt == 0.0)

        # Update shared metrics
        _m["urllc_rtt_ms"]    = rtt
        _m["embb_mbps"]       = embb
        _m["mmtc_msgs"]       = mmtc
        _m["state"]           = 0 if state == "NORMAL" else 1
        _m["violation_count"] = violation_streak
        _m["recovery_streak"] = ok_streak
        _m["loop_count"]     += 1

        log(f"📊 [{state:9s}] URLLC={rtt:5.1f}ms {'✓' if sla_ok else '⚠️ BREACH'} "
            f"| eMBB={embb:.1f}Mbps | mMTC={mmtc}msgs "
            f"| replicas U={_m['urllc_replicas']} E={_m['embb_replicas']} M={_m['mmtc_replicas']}")

        # ── tc-shaping: URLLC SLA enforcement ────────────────────
        if state == "NORMAL":
            if not sla_ok:
                violation_streak += 1
                _m["violation_count"] = violation_streak
                log(f"   ⚠️  RTT violation #{violation_streak}: {rtt:.1f}ms > {URLLC_SLA_MS}ms")
                if violation_streak >= VIOLATION_COUNT:
                    log(f"   🔴 Throttling eMBB → {EMBB_THROTTLE_BW}...")
                    success, out = throttle_embb(EMBB_THROTTLE_BW)
                    if success:
                        state = "THROTTLED"
                        cycle_count += 1
                        _m["throttle_total"] = cycle_count
                        violation_streak = 0
                        log(f"   ✅ Throttled. Cycle #{cycle_count}")
                    else:
                        log(f"   ❌ Throttle failed: {out}")
            else:
                violation_streak = 0
        elif state == "THROTTLED":
            if sla_ok:
                ok_streak += 1
                _m["recovery_streak"] = ok_streak
                log(f"   ✓  Recovering — streak {ok_streak}/{RESTORE_COUNT}")
                if ok_streak >= RESTORE_COUNT:
                    log("   🟢 Restoring eMBB...")
                    success, out = restore_embb()
                    if success:
                        state = "NORMAL"
                        ok_streak = 0
                        _m["restore_total"] = cycle_count
                        log(f"   ✅ Restored. Total throttle cycles: {cycle_count}")
                    else:
                        log(f"   ❌ Restore failed: {out}")
            else:
                ok_streak = 0
                log(f"   ⏳ RTT still high ({rtt:.1f}ms) — holding throttle")

        # ── Autoscaling: app pod scaling ──────────────────────────
        scale_actions = autoscaler.evaluate(rtt, embb, mmtc, state)
        if scale_actions:
            log(f"   🔧 Autoscaler: {', '.join(scale_actions)}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped.")
