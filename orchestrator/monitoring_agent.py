"""
monitoring_agent.py — Agentic Orchestrator Monitoring
Reads URLLC RTT, eMBB throughput, mMTC PDR from:
  1. Prometheus tun_tx_bytes rate (real throughput from UPF interface counters)
  2. SSH to UERANSIM (live URLLC RTT logs)
  3. /proc/stat for CPU
"""
import json
import logging
import re
import subprocess
import time
import urllib.request
from collections import deque

import config

log = logging.getLogger("monitor")

LOG_DIR  = "/tmp/mec-clients"
PROM_URL = config.PROMETHEUS_URL   # http://localhost:30090


def _run(cmd: str, timeout: int = 8) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def _ssh(remote_cmd: str, timeout: int = 10) -> str:
    cmd = [
        "sshpass", "-p", config.UERANSIM_PASS,
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=4",
        f"{config.UERANSIM_USER}@{config.UERANSIM_HOST}",
        remote_cmd,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def _prom_query(query: str, default: float = 0.0) -> float:
    """Execute an instant PromQL query and return the first scalar value."""
    try:
        url  = f"{PROM_URL}/api/v1/query?query={urllib.request.quote(query)}"
        resp = urllib.request.urlopen(url, timeout=3)
        data = json.loads(resp.read().decode())
        results = data.get("data", {}).get("result", [])
        if results:
            return float(results[0]["value"][1])
    except Exception:
        pass
    return default


def _prom_text_metric(text: str, key: str, default: float = 0.0) -> float:
    for line in text.splitlines():
        if line.startswith(key + " "):
            try:
                return float(line.split()[-1])
            except Exception:
                pass
    return default


class MonitoringAgent:
    """Collects current network state for the agentic orchestrator."""

    # Rolling window length: 100 samples × 3s interval = ~5 minutes of history
    _PKT_RATE_WINDOW = 100

    def __init__(self):
        self._prev_cpu    = (0, 0)   # (total, idle) for /proc/stat delta
        # Rolling window of non-zero eMBB pkt_rate observations.
        # Used to compute embb_load_fraction = current / session_max.
        self._pkt_rate_history: deque[float] = deque(maxlen=self._PKT_RATE_WINDOW)

    def collect(self) -> dict:
        t0 = time.time()

        # ── 1. Read orchestrator own metrics (rate/state tracking) ────────────
        prom_text = ""
        try:
            resp      = urllib.request.urlopen(
                f"http://localhost:{config.METRICS_PORT}/metrics", timeout=2)
            prom_text = resp.read().decode()
        except Exception:
            pass

        embb_rate = int(_prom_text_metric(prom_text, "orchestrator_embb_rate_mbit",
                                          config.EMBB_RATE_MAX))

        # ── 2. eMBB throughput — real rate from UPF tun interface counter ─────
        # tun_tx_bytes on ogstun-embb = bytes sent from UPF to UEs (downlink)
        # Use 60s window for stability; fall back to 30s if 60s yields 0
        embb_tp_mbps = _prom_query(
            'irate(tun_tx_bytes{interface="ogstun-embb"}[30s])*8/1000000'
        )
        if embb_tp_mbps == 0.0:
            embb_tp_mbps = _prom_query(
                'rate(tun_tx_bytes{interface="ogstun-embb"}[2m])*8/1000000'
            )
        embb_tp = embb_tp_mbps * 1e6   # bytes/s for backward compatibility

        # ── 3. mMTC via SSH log (ground truth — avoids circular Prometheus read) ─
        mmtc_ssh = _ssh(
            f"for f in {LOG_DIR}/mmtc_uesimtun*.log; do "
            f"  [ -s \"$f\" ] && tail -1 \"$f\" 2>/dev/null; "
            f"done"
        )
        mmtc_msgs   = 0
        mmtc_ok_tun = 0
        mmtc_total_tun = 0
        for line in mmtc_ssh.splitlines():
            mmtc_total_tun += 1
            m_msgs = re.search(r'(\d+)\s+msgs published', line)
            if m_msgs:
                mmtc_msgs   += int(m_msgs.group(1))
                mmtc_ok_tun += 1
        # PDR = fraction of mMTC tunnels actively delivering
        mmtc_pdr = mmtc_ok_tun / mmtc_total_tun if mmtc_total_tun > 0 else 1.0

        # ── 5. Live RTT from UERANSIM SSH logs ───────────────────────────────
        ssh_out = _ssh(
            f"for f in {LOG_DIR}/urllc_uesimtun*.log; do "
            f"  [ -s \"$f\" ] && tail -1 \"$f\" 2>/dev/null; "
            f"done"
        )

        avg_rtts, max_rtts, fails, dead_tunnels = [], [], 0, 0
        for line in ssh_out.splitlines():
            m_avg = re.search(r'RTT avg=(\d+\.?\d*)ms', line)
            m_max = re.search(r'max=(\d+\.?\d*)ms', line)
            m_f   = re.search(r'fails=(\d+)', line)
            fail_val = int(m_f.group(1)) if m_f else 0
            avg_val  = float(m_avg.group(1)) if m_avg else None
            # FIX: exclude dead tunnels (zero RTT co-occurring with max fails)
            if avg_val is not None:
                if avg_val > 0:
                    avg_rtts.append(avg_val)
                elif fail_val >= 3:      # zero RTT + repeated fails = dead tunnel
                    dead_tunnels += 1
            if m_max and avg_val and avg_val > 0:
                max_rtts.append(float(m_max.group(1)))
            if fail_val > 0:
                fails += fail_val

        rtt_99 = round(sum(avg_rtts) / len(avg_rtts), 2) if avg_rtts else \
                 _prom_text_metric(prom_text, "orchestrator_urllc_rtt_ms", 0)
        # Per-tunnel loss rate (for LLM context)
        total_urllc_tun = len(avg_rtts) + dead_tunnels
        urllc_loss_rate = dead_tunnels / total_urllc_tun if total_urllc_tun > 0 else 0.0

        # ── 6. CPU: master /proc/stat + UPF pod CPU from cadvisor ──────────────
        cpu_pct = 0
        try:
            with open('/proc/stat') as f:
                fields = [int(x) for x in f.readline().split()[1:]]
            idle  = fields[3]
            total = sum(fields)
            pt, pi = self._prev_cpu
            dt = total - pt
            di = idle  - pi
            cpu_pct = round(100 * (1 - di / dt)) if dt else 0
            self._prev_cpu = (total, idle)
        except Exception:
            pass

        # eMBB namespace pod CPU (cadvisor — where congestion actually shows)
        embb_pod_cpu_m = _prom_query(
            'sum(rate(container_cpu_usage_seconds_total{container!="",namespace="embb"}[30s]))*1000'
        )
        # eMBB packet rate (congestion indicator — drop if bursting)
        embb_pkt_rate = _prom_query(
            'irate(tun_tx_packets{interface="ogstun-embb"}[30s])'
        )

        # ── 7. eMBB load fraction — relative to session peak ───────────────
        # Records non-trivial pkt_rate samples and computes current / session_max.
        # This gives the LLM a self-referential scale: 0.05 = idle, 1.0 = peak.
        # Returns None until the window has at least 5 samples (cold-start guard).
        embb_load_fraction = None
        if embb_pkt_rate > 0:
            self._pkt_rate_history.append(embb_pkt_rate)
        if len(self._pkt_rate_history) >= 5:
            session_max = max(self._pkt_rate_history)
            if session_max > 0:
                embb_load_fraction = round(embb_pkt_rate / session_max, 3)

        result = {
            "urllc_rtt_99":       rtt_99,
            "urllc_rtt_max":      max(max_rtts) if max_rtts else rtt_99,
            "urllc_fails":        fails,
            "urllc_dead_tunnels": dead_tunnels,
            "urllc_loss_rate":    round(urllc_loss_rate, 3),
            "embb_tp":            embb_tp,
            "embb_tp_mbps":       embb_tp_mbps,
            "embb_pkt_rate":      embb_pkt_rate,
            "embb_load_fraction": embb_load_fraction,   # None = insufficient history
            "embb_pod_cpu_m":     round(embb_pod_cpu_m, 1),
            "embb_rate":          embb_rate,
            "mmtc_pdr":           mmtc_pdr,
            "mmtc_msgs_total":    mmtc_msgs,
            "drops":              fails,
            "cpu":                cpu_pct,
            "collect_ms":         round((time.time() - t0) * 1000, 1),
        }

        log.debug(
            f"[Monitor] RTT={rtt_99:.1f}ms(dead={dead_tunnels})  "
            f"eMBB={embb_tp_mbps:.1f}Mbps(cpu={embb_pod_cpu_m:.0f}m)  "
            f"mMTC_PDR={mmtc_pdr:.2f}({mmtc_msgs}msgs)  CPU={cpu_pct}%  "
            f"collect={result['collect_ms']}ms"
        )

        return result
