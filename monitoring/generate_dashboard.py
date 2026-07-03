#!/usr/bin/env python3
"""
generate_dashboard.py
Generates and uploads the enhanced 5G slicing dashboard to Grafana via API.
Run: python3 generate_dashboard.py
"""
import json, urllib.request, urllib.error

GRAFANA = "http://192.168.49.174:30300"
AUTH    = ("admin", "admin")
DS_UID  = "PBFA97CFB590B2093"

def req(method, path, body=None):
    import base64
    url = GRAFANA + path
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    creds = base64.b64encode(f"{AUTH[0]}:{AUTH[1]}".encode()).decode()
    r.add_header("Authorization", f"Basic {creds}")
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}

def ds(uid=DS_UID):
    return {"type": "prometheus", "uid": uid}

def stat(title, expr, unit="none", color="#73BF69", thresholds=None, x=0, y=0, w=4, h=3):
    t = thresholds or [{"color": "green", "value": None}]
    return {
        "type": "stat", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "datasource": ds(),
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "orientation": "auto", "textMode": "auto",
            "colorMode": "background", "graphMode": "area",
        },
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "thresholds": {"mode": "absolute", "steps": t},
                "color": {"mode": "thresholds"},
            }
        },
        "targets": [{"datasource": ds(), "expr": expr, "instant": True, "legendFormat": "{{slice}}{{instance}}"}],
    }

def timeseries(title, targets, unit="none", y=0, x=0, w=12, h=8,
               thresholds=None, fill=0.15, stack=False):
    overrides = []
    if thresholds:
        for name, val, color in thresholds:
            overrides.append({
                "matcher": {"id": "byName", "options": name},
                "properties": [{"id": "color", "value": {"fixedColor": color, "mode": "fixed"}}]
            })
    return {
        "type": "timeseries", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "datasource": ds(),
        "options": {
            "tooltip": {"mode": "multi", "sort": "none"},
            "legend": {"displayMode": "table", "placement": "bottom", "calcs": ["mean", "max", "last"]},
            "fillOpacity": int(fill * 100),
            "stacking": {"mode": "normal" if stack else "none"},
        },
        "fieldConfig": {
            "defaults": {"unit": unit, "custom": {"lineWidth": 2, "fillOpacity": int(fill * 100)}},
        },
        "overrides": overrides,
        "targets": targets,
    }

def target(expr, legend, instant=False):
    return {"datasource": ds(), "expr": expr, "legendFormat": legend,
            "interval": "5s", "instant": instant}

def text_panel(content, title="", x=0, y=0, w=24, h=2):
    return {
        "type": "text", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "options": {"content": content, "mode": "markdown"},
    }

def gauge(title, expr, unit, min_val, max_val, thresholds, x=0, y=0, w=4, h=4):
    return {
        "type": "gauge", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "datasource": ds(),
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "showThresholdLabels": True, "showThresholdMarkers": True},
        "fieldConfig": {
            "defaults": {
                "unit": unit, "min": min_val, "max": max_val,
                "thresholds": {"mode": "absolute", "steps": thresholds},
                "color": {"mode": "thresholds"},
            }
        },
        "targets": [{"datasource": ds(), "expr": expr, "instant": True}],
    }

# ─────────────────────────────────────────────────────────────────
# ROW 0 — Header banner
# ─────────────────────────────────────────────────────────────────
header = text_panel(
    "## 🛰️ 5G Network Slicing — Live QoS Orchestration Dashboard\n"
    "`eMBB` · `URLLC` · `mMTC`  |  Rule-Based vs Agentic (LLM) Orchestrator  |  Open5GS + UERANSIM on Kubernetes",
    x=0, y=0, w=24, h=2
)

# ─────────────────────────────────────────────────────────────────
# ROW 1 — Top KPI stats (y=2)
# ─────────────────────────────────────────────────────────────────
kpi_rtt = stat(
    "URLLC RTT (avg)", "orchestrator_urllc_rtt_ms", unit="ms",
    thresholds=[
        {"color": "green",  "value": None},
        {"color": "yellow", "value": 12},
        {"color": "orange", "value": 18},
        {"color": "red",    "value": 25},
    ], x=0, y=2, w=4, h=4
)
kpi_embb = stat(
    "eMBB Throughput", "orchestrator_embb_mbps", unit="Mbps",
    thresholds=[
        {"color": "red",    "value": None},
        {"color": "yellow", "value": 10},
        {"color": "green",  "value": 20},
    ], x=4, y=2, w=4, h=4
)
kpi_mmtc = stat(
    "mMTC PDR", "orchestrator_mmtc_pdr * 100", unit="percent",
    thresholds=[
        {"color": "red",    "value": None},
        {"color": "yellow", "value": 95},
        {"color": "green",  "value": 99.5},
    ], x=8, y=2, w=4, h=4
)
kpi_mode = stat(
    "Orchestrator Mode",
    'orchestrator_agentic_mode == 1 or vector(0)',
    thresholds=[
        {"color": "blue",  "value": None},
        {"color": "purple","value": 1},
    ], x=12, y=2, w=3, h=4
)
kpi_sla = stat(
    "SLA Violations (total)", "orchestrator_violation_count",
    thresholds=[
        {"color": "green",  "value": None},
        {"color": "yellow", "value": 5},
        {"color": "red",    "value": 20},
    ], x=15, y=2, w=3, h=4
)
kpi_throttle = stat(
    "Throttle Events", "orchestrator_throttle_total",
    thresholds=[{"color": "orange", "value": None}],
    x=18, y=2, w=3, h=4
)
kpi_loop = stat(
    "Orchestrator Cycles", "orchestrator_loop_count",
    thresholds=[{"color": "blue", "value": None}],
    x=21, y=2, w=3, h=4
)

# ─────────────────────────────────────────────────────────────────
# ROW 2 — URLLC RTT time series (y=6)
# ─────────────────────────────────────────────────────────────────
urllc_ts = timeseries(
    "⚡ URLLC RTT — Real-Time Latency",
    targets=[
        target("orchestrator_urllc_rtt_ms", "RTT avg (ms)"),
        target("25",  "SLA Limit (25ms)"),
        target("12",  "Early Warning (12ms)"),
    ],
    unit="ms", y=6, x=0, w=16, h=8,
)

urllc_gauge = gauge(
    "URLLC RTT", "orchestrator_urllc_rtt_ms",
    unit="ms", min_val=0, max_val=50,
    thresholds=[
        {"color": "green",  "value": None},
        {"color": "yellow", "value": 12},
        {"color": "orange", "value": 18},
        {"color": "red",    "value": 25},
    ], x=16, y=6, w=4, h=8
)

urllc_replicas = timeseries(
    "URLLC App Replicas",
    targets=[target("orchestrator_urllc_replicas", "urllc-app replicas")],
    unit="short", y=6, x=20, w=4, h=8
)

# ─────────────────────────────────────────────────────────────────
# ROW 3 — eMBB throughput (y=14)
# ─────────────────────────────────────────────────────────────────
embb_ts = timeseries(
    "📺 eMBB Throughput — HLS Video Streaming",
    targets=[
        target('rate(tun_tx_bytes{interface="ogstun-embb"}[60s])*8/1000000', "eMBB DL Mbps (tun)"),
        target("orchestrator_embb_mbps",   "eMBB Mbps (orchestrator)"),
        target("orchestrator_embb_rate_mbit", "tc Rate Limit (Mbit)"),
        target("20", "Min TP SLA (20Mbps)"),
    ],
    unit="Mbps", y=14, x=0, w=16, h=8
)

embb_gauge = gauge(
    "eMBB Rate Limit", "orchestrator_embb_rate_mbit",
    unit="Mbps", min_val=50, max_val=1000,
    thresholds=[
        {"color": "red",    "value": None},
        {"color": "yellow", "value": 200},
        {"color": "green",  "value": 500},
    ], x=16, y=14, w=4, h=8
)

embb_replicas = timeseries(
    "eMBB App Replicas",
    targets=[target("orchestrator_embb_replicas", "embb-app replicas")],
    unit="short", y=14, x=20, w=4, h=8
)

# ─────────────────────────────────────────────────────────────────
# ROW 4 — mMTC (y=22)
# ─────────────────────────────────────────────────────────────────
mmtc_pdr_ts = timeseries(
    "📡 mMTC Packet Delivery Ratio",
    targets=[
        target(
            'tun_rx_packets{interface="ogstun-mmtc"} / tun_tx_packets{interface="ogstun-mmtc"}',
            "mMTC PDR (tun)"
        ),
        target("orchestrator_mmtc_pdr", "mMTC PDR (orchestrator)"),
        target("0.995", "PDR SLA (99.5%)"),
    ],
    unit="percentunit", y=22, x=0, w=12, h=7
)

mmtc_pkt_ts = timeseries(
    "mMTC TUN Packet Rates",
    targets=[
        target('rate(tun_tx_packets{interface="ogstun-mmtc"}[60s])', "mMTC TX pkt/s"),
        target('rate(tun_rx_packets{interface="ogstun-mmtc"}[60s])', "mMTC RX pkt/s"),
    ],
    unit="pps", y=22, x=12, w=8, h=7
)

mmtc_replicas = timeseries(
    "mMTC App Replicas",
    targets=[target("orchestrator_mmtc_replicas", "mmtc-app replicas")],
    unit="short", y=22, x=20, w=4, h=7
)

# ─────────────────────────────────────────────────────────────────
# ROW 5 — All-slice TUN bytes (y=29)
# ─────────────────────────────────────────────────────────────────
all_tun = timeseries(
    "All-Slice GTP Tunnel Throughput (UPF → UE, Downlink)",
    targets=[
        target('rate(tun_tx_bytes{interface="ogstun-embb"}[60s])*8/1000000',  "eMBB DL Mbps"),
        target('rate(tun_tx_bytes{interface="ogstun-urllc"}[60s])*8/1000000', "URLLC DL Mbps"),
        target('rate(tun_tx_bytes{interface="ogstun-mmtc"}[60s])*8/1000000',  "mMTC DL Mbps"),
    ],
    unit="Mbps", y=29, x=0, w=12, h=7, fill=0.3, stack=True
)

all_tun_rx = timeseries(
    "All-Slice GTP Tunnel Throughput (UE → UPF, Uplink)",
    targets=[
        target('rate(tun_rx_bytes{interface="ogstun-embb"}[60s])*8/1000000',  "eMBB UL Mbps"),
        target('rate(tun_rx_bytes{interface="ogstun-urllc"}[60s])*8/1000000', "URLLC UL Mbps"),
        target('rate(tun_rx_bytes{interface="ogstun-mmtc"}[60s])*8/1000000',  "mMTC UL Mbps"),
    ],
    unit="Mbps", y=29, x=12, w=12, h=7, fill=0.3, stack=True
)

# ─────────────────────────────────────────────────────────────────
# ROW 6 — Orchestrator intelligence (y=36)
# ─────────────────────────────────────────────────────────────────
orch_state = timeseries(
    "Orchestrator Action & Mode",
    targets=[
        target("orchestrator_state",         "Throttled (1=yes)"),
        target("orchestrator_agentic_mode",  "Agentic Mode (1=LLM)"),
        target("orchestrator_llm_used",      "LLM Used (1=yes)"),
    ],
    unit="short", y=36, x=0, w=8, h=7
)

llm_latency = timeseries(
    "LLM Decision Latency",
    targets=[
        target("orchestrator_llm_latency_ms",  "LLM latency (ms)"),
        target("orchestrator_llm_confidence",  "Confidence (0–1)"),
    ],
    unit="ms", y=36, x=8, w=8, h=7
)

orch_events = timeseries(
    "Throttle / Restore Event Counts",
    targets=[
        target("orchestrator_throttle_total", "Throttle Events"),
        target("orchestrator_restore_total",  "Restore Events"),
        target("orchestrator_violation_count","SLA Violations"),
    ],
    unit="short", y=36, x=16, w=8, h=7
)

# ─────────────────────────────────────────────────────────────────
# ROW 7 — TUN drops and infra (y=43)
# ─────────────────────────────────────────────────────────────────
drops_ts = timeseries(
    "GTP Packet Drops (all slices)",
    targets=[
        target('rate(tun_tx_dropped{interface="ogstun-embb"}[60s])',  "eMBB drops/s"),
        target('rate(tun_tx_dropped{interface="ogstun-urllc"}[60s])', "URLLC drops/s"),
        target('rate(tun_tx_dropped{interface="ogstun-mmtc"}[60s])',  "mMTC drops/s"),
    ],
    unit="pps", y=43, x=0, w=12, h=6
)

recovery = timeseries(
    "SLA Recovery Streak & Memory Success Rate",
    targets=[
        target("orchestrator_recovery_streak",    "Stable for (s)"),
        target("orchestrator_memory_success_rate","Memory success rate"),
    ],
    unit="short", y=43, x=12, w=12, h=6
)

# ─────────────────────────────────────────────────────────────────
# Assemble panels list
# ─────────────────────────────────────────────────────────────────
panels = [
    header,
    kpi_rtt, kpi_embb, kpi_mmtc, kpi_mode, kpi_sla, kpi_throttle, kpi_loop,
    urllc_ts, urllc_gauge, urllc_replicas,
    embb_ts,  embb_gauge,  embb_replicas,
    mmtc_pdr_ts, mmtc_pkt_ts, mmtc_replicas,
    all_tun, all_tun_rx,
    orch_state, llm_latency, orch_events,
    drops_ts, recovery,
]

# Assign sequential IDs
for i, p in enumerate(panels):
    p["id"] = i + 1

dashboard = {
    "dashboard": {
        "id": None,
        "uid": "5g-slicing-enhanced-v2",
        "title": "5G Network Slicing — Enhanced QoS Dashboard",
        "description": "Real-time per-slice SLA monitoring: eMBB throughput, URLLC RTT, mMTC PDR, orchestrator intelligence, autoscaling, and GTP tunnel analytics.",
        "tags": ["5g", "slicing", "orchestrator", "open5gs", "ueransim"],
        "timezone": "browser",
        "refresh": "5s",
        "time": {"from": "now-15m", "to": "now"},
        "schemaVersion": 36,
        "version": 1,
        "panels": panels,
        "annotations": {
            "list": [{
                "builtIn": 1,
                "datasource": {"type": "datasource", "uid": "grafana"},
                "enable": True,
                "hide": True,
                "iconColor": "rgba(0, 211, 255, 1)",
                "name": "Annotations & Alerts",
                "type": "dashboard",
            }]
        },
        "templating": {"list": []},
        "links": [],
        "fiscalYearStartMonth": 0,
        "graphTooltip": 1,
        "liveNow": True,
    },
    "folderId": 0,
    "overwrite": True,
}

print("Uploading enhanced dashboard to Grafana...")
result = req("POST", "/api/dashboards/db", dashboard)
if "url" in result:
    print(f"✅ Dashboard created: http://192.168.49.174:30300{result['url']}")
else:
    print(f"❌ Error: {result}")
