#!/usr/bin/env python3
"""
rtt_monitor.py — URLLC RTT Measurement + Prometheus HTTP Endpoint
Measures RTT through URLLC uesimtun interfaces (10.46.x).

Logs: /tmp/mec-clients/urllc_*.log  (for SSH fallback compatibility)
HTTP: http://0.0.0.0:9300/metrics    (scraped by Prometheus)

Prometheus metrics exposed:
  urllc_rtt_avg_ms   — average RTT across all URLLC UE tunnels
  urllc_rtt_max_ms   — max RTT across all URLLC UE tunnels
  urllc_rtt_fails    — total packet failures
  urllc_ue_count     — number of active URLLC uesimtun interfaces
"""
import re
import os
import glob
import subprocess
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

LOG_DIR      = "/tmp/mec-clients"
METRICS_PORT = 9300
PING_TARGET  = "192.168.49.174"
PING_COUNT   = 5

os.makedirs(LOG_DIR, exist_ok=True)

# ── Shared state (updated by measurement loop, read by HTTP handler) ──────────
_rtt_state = {
    "avg_ms":   0.0,
    "max_ms":   0.0,
    "fails":    0,
    "ue_count": 0,
}
_rtt_lock = threading.Lock()


# ── Prometheus HTTP handler ───────────────────────────────────────────────────

class RTTMetricsHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass  # suppress access logs

    def do_GET(self):
        if self.path not in ("/metrics", "/metrics/"):
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        with _rtt_lock:
            s = dict(_rtt_state)
        body = (
            f"# HELP urllc_rtt_avg_ms Average URLLC RTT across all UE tunnels\n"
            f"# TYPE urllc_rtt_avg_ms gauge\n"
            f"urllc_rtt_avg_ms {s['avg_ms']:.2f}\n"
            f"# HELP urllc_rtt_max_ms Maximum URLLC RTT\n"
            f"# TYPE urllc_rtt_max_ms gauge\n"
            f"urllc_rtt_max_ms {s['max_ms']:.2f}\n"
            f"# HELP urllc_rtt_fails Total ping failures\n"
            f"# TYPE urllc_rtt_fails counter\n"
            f"urllc_rtt_fails {s['fails']}\n"
            f"# HELP urllc_ue_count Active URLLC uesimtun interfaces\n"
            f"# TYPE urllc_ue_count gauge\n"
            f"urllc_ue_count {s['ue_count']}\n"
        )
        self.wfile.write(body.encode())


# ── RTT measurement functions ─────────────────────────────────────────────────

def get_urllc_tuns():
    """Return list of URLLC uesimtun interfaces (10.46.x subnet)."""
    out = subprocess.run(
        "ip addr show | grep -B1 '10\\.46\\.'",
        shell=True, capture_output=True, text=True
    ).stdout
    return re.findall(r'(uesimtun\d+)', out)


def measure_rtt(iface, target=PING_TARGET, count=PING_COUNT):
    """Ping through iface. Returns (avg_ms, max_ms, fails)."""
    try:
        r = subprocess.run(
            f"ping -c {count} -W 2 -I {iface} {target}",
            shell=True, capture_output=True, text=True, timeout=15
        )
        out = r.stdout
        m     = re.search(r'rtt .* = [\d.]+/([\d.]+)/([\d.]+)/', out)
        sent  = re.search(r'(\d+) packets transmitted', out)
        recv  = re.search(r'(\d+) received', out)
        if m:
            avg_ms = float(m.group(1))
            max_ms = float(m.group(2))
            fails  = (int(sent.group(1)) - int(recv.group(1))) if sent and recv else count
            return avg_ms, max_ms, fails
    except Exception:
        pass
    return 0.0, 0.0, count


# ── Measurement loop ──────────────────────────────────────────────────────────

def measurement_loop():
    print(f"[RTT Monitor] Starting — logs→{LOG_DIR}/  metrics→:{METRICS_PORT}/metrics")
    while True:
        tuns = get_urllc_tuns()
        if not tuns:
            print("[RTT Monitor] No URLLC uesimtun found, waiting 5s...")
            time.sleep(5)
            continue

        avgs, maxes, total_fails = [], [], 0
        ts = time.strftime("%Y-%m-%d %H:%M:%S")

        for tun in tuns:
            avg, maxv, fails = measure_rtt(tun)
            total_fails += fails
            if avg > 0:
                avgs.append(avg)
                maxes.append(maxv)

            log_line = f"{ts} RTT avg={avg}ms max={maxv}ms fails={fails}"
            log_path = f"{LOG_DIR}/urllc_{tun}.log"
            with open(log_path, "a") as f:
                f.write(log_line + "\n")
            print(f"[{tun}] RTT avg={avg:.1f}ms max={maxv:.1f}ms fails={fails}")

        # Update shared state for Prometheus
        with _rtt_lock:
            _rtt_state["avg_ms"]   = round(sum(avgs) / len(avgs), 2) if avgs else 0.0
            _rtt_state["max_ms"]   = round(max(maxes), 2) if maxes else 0.0
            _rtt_state["fails"]    = total_fails
            _rtt_state["ue_count"] = len(tuns)

        time.sleep(3)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Start HTTP server in background thread
    server = HTTPServer(("0.0.0.0", METRICS_PORT), RTTMetricsHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[RTT Monitor] Prometheus endpoint: http://0.0.0.0:{METRICS_PORT}/metrics")

    # Measurement runs in main thread
    measurement_loop()
