#!/bin/bash
# =============================================================
# set_traffic_low.sh
# Low Traffic: 1 UE active → 1 eMBB + 1 URLLC + 1 mMTC session
# =============================================================

EDGE_IP="${1:-192.168.49.171}"
LOG_DIR="/tmp/mec-clients"
CLIENT_DIR="$HOME/mec-clients"   # Python client scripts

mkdir -p "$LOG_DIR"

echo "[LOW] Stopping all existing clients..."
pkill -f 'embb_client.py|urllc_client.py|mmtc_client.py' 2>/dev/null
sleep 2
echo "[LOW] Clearing stale log files..."
rm -f "$LOG_DIR"/*.log

# Detect interfaces by IP prefix (auto-detects which uesimtun = which slice)
EMBB_IFACES=($(ip -4 addr | grep 'inet 10\.45\.' | grep uesimtun | awk '{print $NF}' | sort))
URLLC_IFACES=($(ip -4 addr | grep 'inet 10\.46\.' | grep uesimtun | awk '{print $NF}' | sort))
MMTC_IFACES=($(ip -4 addr | grep 'inet 10\.47\.' | grep uesimtun | awk '{print $NF}' | sort))

echo "[LOW] Detected:"
echo "  eMBB : ${EMBB_IFACES[*]}"
echo "  URLLC: ${URLLC_IFACES[*]}"
echo "  mMTC : ${MMTC_IFACES[*]}"

# Start ONLY 1 of each (first interface = UE 1)
IF="${EMBB_IFACES[0]}"
nohup python3 -u "$CLIENT_DIR/embb_client.py" "$IF" "$EDGE_IP" \
    </dev/null >"$LOG_DIR/embb_${IF}.log" 2>&1 &
disown $!
echo "[LOW] eMBB started: $IF (PID=$!)"

IF="${URLLC_IFACES[0]}"
nohup python3 -u "$CLIENT_DIR/urllc_client.py" "$IF" "$EDGE_IP" \
    </dev/null >"$LOG_DIR/urllc_${IF}.log" 2>&1 &
disown $!
echo "[LOW] URLLC started: $IF (PID=$!)"

IF="${MMTC_IFACES[0]}"
nohup python3 -u "$CLIENT_DIR/mmtc_client.py" "$IF" "$EDGE_IP" 30883 \
    </dev/null >"$LOG_DIR/mmtc_${IF}.log" 2>&1 &
disown $!
echo "[LOW] mMTC started: $IF (PID=$!)"

sleep 3
COUNT=$(ps -eo args | grep -E '(embb|urllc|mmtc)_client\.py' | grep -v grep | wc -l)
echo ""
echo "[LOW] Traffic set. Running clients: $COUNT/3"
echo "      eMBB=1  URLLC=1  mMTC=1"
echo "      Logs: $LOG_DIR/"
