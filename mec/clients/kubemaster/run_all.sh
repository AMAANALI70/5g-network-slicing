#!/bin/bash
# ============================================================
# run_all.sh — Auto-detect uesimtun interfaces and launch
#              the correct real application client per slice
#
# eMBB (10.45.x) → ffmpeg HLS pull   → nginx-HLS :8080
# URLLC(10.46.x) → WebSocket telemetry → Node-RED  :1880
# mMTC (10.47.x) → MQTT pub/sub      → Mosquitto  :1883
#
# Traffic flows through GTP-U → UPF → DNAT → K8s Service
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EDGE_IP="${1:-192.168.49.171}"
LOG_DIR="/tmp/mec-clients"
PID_FILE="/tmp/mec-pids.txt"

mkdir -p "$LOG_DIR"
rm -f "$PID_FILE"

echo "============================================="
echo " 5G MEC Client Launcher"
echo " Edge server: $EDGE_IP"
echo "============================================="

# Kill any previous clients
pkill -f embb_client.py 2>/dev/null
pkill -f urllc_client.py 2>/dev/null
pkill -f mmtc_client.py 2>/dev/null
pkill -f "ffmpeg.*hls" 2>/dev/null
sleep 1

# --- Detect active uesimtun interfaces ---
EMBB_IFACES=$(ip -4 addr | grep 'inet 10\.45\.' | grep uesimtun | awk '{print $NF}')
URLLC_IFACES=$(ip -4 addr | grep 'inet 10\.46\.' | grep uesimtun | awk '{print $NF}')
MMTC_IFACES=$(ip -4 addr | grep 'inet 10\.47\.' | grep uesimtun | awk '{print $NF}')

echo ""
echo "Detected interfaces:"
echo "  eMBB : $(echo $EMBB_IFACES | tr '\n' ' ') ($(echo $EMBB_IFACES | wc -w) UEs)"
echo "  URLLC: $(echo $URLLC_IFACES | tr '\n' ' ') ($(echo $URLLC_IFACES | wc -w) UEs)"
echo "  mMTC : $(echo $MMTC_IFACES | tr '\n' ' ') ($(echo $MMTC_IFACES | wc -w) UEs)"
echo ""

# --- Launch eMBB clients (real HLS video streaming) ---
echo "[eMBB] Starting HLS video clients..."
for IFACE in $EMBB_IFACES; do
    LOG="$LOG_DIR/embb_${IFACE}.log"
    python3 -u "$SCRIPT_DIR/embb_client.py" "$IFACE" "$EDGE_IP" > "$LOG" 2>&1 &
    PID=$!
    echo $PID >> "$PID_FILE"
    echo "  $IFACE → HLS :30880  (PID=$PID, log=$LOG)"
done

# --- Launch URLLC clients (WebSocket industrial telemetry) ---
echo "[URLLC] Starting WebSocket telemetry clients..."
for IFACE in $URLLC_IFACES; do
    LOG="$LOG_DIR/urllc_${IFACE}.log"
    python3 -u "$SCRIPT_DIR/urllc_client.py" "$IFACE" "$EDGE_IP" > "$LOG" 2>&1 &
    PID=$!
    echo $PID >> "$PID_FILE"
    echo "  $IFACE → WebSocket :30180  (PID=$PID, log=$LOG)"
done

# --- Launch mMTC clients (MQTT IoT sensor publishing) ---
echo "[mMTC] Starting IoT sensor clients..."
for IFACE in $MMTC_IFACES; do
    LOG="$LOG_DIR/mmtc_${IFACE}.log"
    python3 -u "$SCRIPT_DIR/mmtc_client.py" "$IFACE" "$EDGE_IP" 1883 > "$LOG" 2>&1 &
    PID=$!
    echo $PID >> "$PID_FILE"
    echo "  $IFACE → MQTT :30883  (PID=$PID, log=$LOG)"
done

echo ""
echo "============================================="
echo " All clients launched!"
echo ""
echo " Monitor logs:"
echo "   tail -f $LOG_DIR/*.log"
echo ""
echo " Check TUN counters:"
echo "   watch -n5 'ip -s link show | grep -A4 uesimtun'"
echo ""
echo " Stop all:"
echo "   kill \$(cat $PID_FILE)"
echo "   # or: pkill -f _client.py"
echo "============================================="
