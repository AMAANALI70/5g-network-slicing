#!/bin/bash
# =============================================================
# set_traffic_medium.sh
# Medium Traffic: All 3 UEs active → 3 eMBB + 3 URLLC + 3 mMTC
# =============================================================

EDGE_IP="${1:-192.168.49.171}"
LOG_DIR="/tmp/mec-clients"
CLIENT_DIR="$HOME/mec-clients"   # Python client scripts

mkdir -p "$LOG_DIR"

echo "[MEDIUM] Stopping all existing clients..."
pkill -f 'embb_client.py|urllc_client.py|mmtc_client.py' 2>/dev/null
sleep 2
echo "[MEDIUM] Clearing stale log files..."
rm -f "$LOG_DIR"/*.log

EMBB_IFACES=($(ip -4 addr | grep 'inet 10\.45\.' | grep uesimtun | awk '{print $NF}' | sort))
URLLC_IFACES=($(ip -4 addr | grep 'inet 10\.46\.' | grep uesimtun | awk '{print $NF}' | sort))
MMTC_IFACES=($(ip -4 addr | grep 'inet 10\.47\.' | grep uesimtun | awk '{print $NF}' | sort))

echo "[MEDIUM] Detected:"
echo "  eMBB : ${EMBB_IFACES[*]}"
echo "  URLLC: ${URLLC_IFACES[*]}"
echo "  mMTC : ${MMTC_IFACES[*]}"

# Start ALL 3 of each
for IF in "${EMBB_IFACES[@]}"; do
    nohup python3 -u "$CLIENT_DIR/embb_client.py" "$IF" "$EDGE_IP" \
        </dev/null >"$LOG_DIR/embb_${IF}.log" 2>&1 &
    disown $!
    echo "[MEDIUM] eMBB started: $IF (PID=$!)"
done

for IF in "${URLLC_IFACES[@]}"; do
    nohup python3 -u "$CLIENT_DIR/urllc_client.py" "$IF" "$EDGE_IP" \
        </dev/null >"$LOG_DIR/urllc_${IF}.log" 2>&1 &
    disown $!
    echo "[MEDIUM] URLLC started: $IF (PID=$!)"
done

for IF in "${MMTC_IFACES[@]}"; do
    nohup python3 -u "$CLIENT_DIR/mmtc_client.py" "$IF" "$EDGE_IP" 30883 \
        </dev/null >"$LOG_DIR/mmtc_${IF}.log" 2>&1 &
    disown $!
    echo "[MEDIUM] mMTC started: $IF (PID=$!)"
done

sleep 3
COUNT=$(ps -eo args | grep -E '(embb|urllc|mmtc)_client\.py' | grep -v grep | wc -l)
echo ""
echo "[MEDIUM] Traffic set. Running clients: $COUNT/9"
echo "         eMBB=3  URLLC=3  mMTC=3"
echo "         Logs: $LOG_DIR/"
