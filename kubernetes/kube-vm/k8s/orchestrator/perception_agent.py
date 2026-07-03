"""
Perception Agent — Collects metrics from Prometheus and tc qdisc stats.
Does NOT make decisions.
"""

import time
import re
import subprocess
import requests
from config import (
    PROMETHEUS_URL, QUERY_RANGE,
    URLLC_INTERFACE, EMBB_INTERFACE,
)


class PerceptionAgent:
    """Gathers real-time metrics and emits structured JSON."""

    def __init__(self):
        self.prom = PROMETHEUS_URL

    # ── Public API ────────────────────────────────────────────

    def collect(self) -> dict:
        """Return normalised metrics snapshot."""
        ts = time.time()
        return {
            "timestamp": ts,
            "urllc_rtt_99": self._measure_urllc_rtt(),
            "embb_tp": self._query_embb_throughput(),
            "mmtc_pdr": self._query_mmtc_pdr(),
            "cpu": self._read_cpu(),
            "drops": self._query_total_drops(),
        }

    # ── Prometheus queries ────────────────────────────────────

    def _prom_query(self, expr: str) -> float:
        """Execute instant PromQL query; return scalar or 0."""
        try:
            r = requests.get(
                f"{self.prom}/api/v1/query",
                params={"query": expr},
                timeout=2,
            )
            data = r.json()
            results = data.get("data", {}).get("result", [])
            if results:
                return float(results[0]["value"][1])
        except Exception:
            pass
        return 0.0

    def _query_embb_throughput(self) -> float:
        """eMBB throughput in bytes/sec from Prometheus."""
        return self._prom_query(
            f'rate(tun_tx_bytes{{slice="embb"}}[{QUERY_RANGE}])'
        )

    def _query_mmtc_pdr(self) -> float:
        """mMTC Packet Delivery Ratio (1.0 = perfect)."""
        total = self._prom_query(
            f'rate(tun_tx_packets{{slice="mmtc"}}[{QUERY_RANGE}])'
            f' + rate(tun_rx_packets{{slice="mmtc"}}[{QUERY_RANGE}])'
        )
        drops = self._prom_query(
            f'rate(tun_tx_dropped{{slice="mmtc"}}[{QUERY_RANGE}])'
            f' + rate(tun_rx_dropped{{slice="mmtc"}}[{QUERY_RANGE}])'
        )
        if total <= 0:
            return 1.0  # No traffic → no loss
        return max(0.0, min(1.0, 1.0 - drops / total))

    def _query_total_drops(self) -> int:
        """Total drops across all slices."""
        val = self._prom_query(
            'sum(tun_tx_dropped + tun_rx_dropped)'
        )
        return int(val)

    # ── tc qdisc measurement ──────────────────────────────────

    def _measure_urllc_rtt(self) -> float:
        """
        Estimate URLLC RTT from tc netem configured delay + queue backlog.
        Reads `tc -s qdisc show dev ogstun-urllc` for both netem delay
        and HTB queue depth to compute effective latency.
        """
        try:
            out = subprocess.check_output(
                ["tc", "-s", "qdisc", "show", "dev", URLLC_INTERFACE],
                text=True, timeout=2,
            )
            delay_ms = self._parse_netem_delay(out)
            backlog_pkts = self._parse_backlog(out)
            # Estimate queuing delay: ~0.1ms per queued packet at 50mbit
            queue_delay = backlog_pkts * 0.1
            return delay_ms + queue_delay
        except Exception:
            return 0.0

    @staticmethod
    def _parse_netem_delay(output: str) -> float:
        """Extract delay value from netem qdisc output."""
        m = re.search(r'delay\s+([\d.]+)(ms|us|s)', output)
        if m:
            val, unit = float(m.group(1)), m.group(2)
            if unit == "us":
                return val / 1000.0
            elif unit == "s":
                return val * 1000.0
            return val  # ms
        return 0.0

    @staticmethod
    def _parse_backlog(output: str) -> int:
        """Extract backlog packet count."""
        m = re.search(r'backlog\s+\S+\s+(\d+)p', output)
        return int(m.group(1)) if m else 0

    # ── CPU ───────────────────────────────────────────────────

    @staticmethod
    def _read_cpu() -> float:
        """Read instant CPU usage from /proc/stat."""
        try:
            with open("/proc/stat") as f:
                line = f.readline()
            parts = line.split()
            idle = int(parts[4])
            total = sum(int(x) for x in parts[1:])
            # This is cumulative, so we return raw values
            # State agent will compute delta
            return round((1.0 - idle / total) * 100, 1) if total else 0.0
        except Exception:
            return 0.0
