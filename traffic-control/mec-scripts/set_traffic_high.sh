#!/bin/bash
# =============================================================
# set_traffic_high.sh  v3 — IP-based iperf3 binding
# High Traffic: 3 eMBB + iperf3 × 3 + 3 URLLC + 5 mMTC
#
# Strategy:
#   - 3 embb_client.py (HLS video, bound by uesimtunX interface name)
#   - 3 iperf3 TCP clients bound to 10.45.x.x source IPs (no --bind-dev)
#     → Kernel routes through GTP tunnel automatically based on source IP
#     → Works regardless of how uesimtunX names change across UE restarts
#
# Requires iperf3 server on edge (run once on kubemaster):
#   bash ~/k8s/ueransim-scripts/start_iperf3_server.sh
# =============================================================

EDGE_IP="${1:-192.168.49.171}"        # HLS nginx / URLLC Node-RED / mMTC MQTT
IPERF_SERVER="${2:-192.168.49.174}"   # iperf3 server on kubemaster
IPERF_BASE_PORT="${3:-5201}"
LOG_DIR="/tmp/mec-clients"
CLIENT_DIR="$HOME/mec-clients"

mkdir -p "$LOG_DIR"

echo "[HIGH] Stopping all existing clients and iperf3..."
pkill -f 'embb_client.py|urllc_client.py|mmtc_client.py' 2>/dev/null
pkill -f 'iperf3 -c' 2>/dev/null
sleep 2
echo "[HIGH] Clearing stale log files..."
rm -f "$LOG_DIR"/*.log

# ── Detect interfaces by IP prefix ───────────────────────────────────────────
EMBB_IFACES=($(ip -4 addr | grep 'inet 10\.45\.' | grep uesimtun | awk '{print $NF}' | sort))
URLLC_IFACES=($(ip -4 addr | grep 'inet 10\.46\.' | grep uesimtun | awk '{print $NF}' | sort))
MMTC_IFACES=($(ip -4 addr | grep 'inet 10\.47\.' | grep uesimtun | awk '{print $NF}' | sort))

# Detect eMBB IPs by subnet (10.45.x.x) — used for iperf3 binding
EMBB_IPS=($(ip -4 addr | grep 'inet 10\.45\.' | grep uesimtun | awk '{print $2}' | cut -d/ -f1 | sort))

echo "[HIGH] Detected:"
echo "  eMBB ifaces : ${EMBB_IFACES[*]}"
echo "  eMBB IPs    : ${EMBB_IPS[*]}   ← used for iperf3 -B"
echo "  URLLC ifaces: ${URLLC_IFACES[*]}"
echo "  mMTC ifaces : ${MMTC_IFACES[*]}"
echo ""

# ── eMBB: 3 HLS clients (1 per interface) ────────────────────────────────────
echo "[HIGH] Starting eMBB HLS clients (3 total: 1 per interface)..."
for IF in "${EMBB_IFACES[@]}"; do
    nohup python3 -u "$CLIENT_DIR/embb_client.py" "$IF" "$EDGE_IP" \
        </dev/null >"$LOG_DIR/embb_${IF}.log" 2>&1 &
    disown $!
    echo "  HLS via $IF (PID=$!)"
done

# ── iperf3: 3 TCP clients bound to 10.45.x.x IPs ────────────────────────────
# No --bind-dev needed: source IP 10.45.x.x is routed through GTP automatically
# IMPORTANT: -b 0 (unlimited) kills the GTP tunnel — cap at 80M per stream
# 3 streams × 80Mbps = 240Mbps total eMBB load → high congestion, tunnel survives
echo ""
echo "[HIGH] Starting iperf3 flood clients (3 total, bound by 10.45.x.x IP)..."
PORT=$IPERF_BASE_PORT
for LOCAL_IP in "${EMBB_IPS[@]}"; do
    nohup iperf3 \
        -c "$IPERF_SERVER" \
        -p "$PORT" \
        -B "$LOCAL_IP" \
        -t 86400 \
        -b 80M \
        -P 2 \
        </dev/null >"$LOG_DIR/iperf3_${LOCAL_IP}.log" 2>&1 &
    disown $!
    echo "  iperf3 -B $LOCAL_IP -b 80M -P 2 → $IPERF_SERVER:$PORT (PID=$!)"
    PORT=$((PORT + 1))
done

# ── URLLC: 3 clients (1 per interface) ───────────────────────────────────────
echo ""
echo "[HIGH] Starting URLLC clients (3 total: 1 per interface)..."
for IF in "${URLLC_IFACES[@]}"; do
    nohup python3 -u "$CLIENT_DIR/urllc_client.py" "$IF" "$EDGE_IP" \
        </dev/null >"$LOG_DIR/urllc_${IF}.log" 2>&1 &
    disown $!
    echo "  URLLC $IF (PID=$!)"
done

# ── mMTC: 5 clients (2+2+1 across interfaces) ────────────────────────────────
MMTC_COUNT=0
echo ""
echo "[HIGH] Starting mMTC clients (5 total: 2+2+1)..."
for IDX in 0 1 2; do
    IF="${MMTC_IFACES[$IDX]}"
    [ -z "$IF" ] && continue
    nohup python3 -u "$CLIENT_DIR/mmtc_client.py" "$IF" "$EDGE_IP" 30883 \
        </dev/null >"$LOG_DIR/mmtc_${IF}_a.log" 2>&1 &
    disown $!
    echo "  mMTC[$IDX-a] $IF (PID=$!)"
    MMTC_COUNT=$((MMTC_COUNT+1))
    if [ "$IDX" -lt 2 ]; then
        nohup python3 -u "$CLIENT_DIR/mmtc_client.py" "$IF" "$EDGE_IP" 30883 \
            </dev/null >"$LOG_DIR/mmtc_${IF}_b.log" 2>&1 &
        disown $!
        echo "  mMTC[$IDX-b] $IF ← extra (PID=$!)"
        MMTC_COUNT=$((MMTC_COUNT+1))
    fi
done

sleep 4
EMBB_P=$(ps -eo args | grep 'embb_client\.py'  | grep -v grep | wc -l)
IPERF_P=$(ps -eo args | grep 'iperf3 -c'        | grep -v grep | wc -l)
URLLC_P=$(ps -eo args | grep 'urllc_client\.py' | grep -v grep | wc -l)
MMTC_P=$(ps -eo args  | grep 'mmtc_client\.py'  | grep -v grep | wc -l)

echo ""
echo "[HIGH] Traffic set:"
echo "  HLS eMBB = $EMBB_P / 3"
echo "  iperf3   = $IPERF_P / 3  ← extra bandwidth stress via 10.45.x.x IPs"
echo "  URLLC    = $URLLC_P / 3"
echo "  mMTC     = $MMTC_P / 5"
echo "  Logs: $LOG_DIR/"
