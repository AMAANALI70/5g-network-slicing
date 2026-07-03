#!/bin/bash
# launch_mec_clients.sh
# 3 eMBB + 3 URLLC + 3 mMTC clients on their correct slice tunnels

SERVER="192.168.49.172"
LOG_DIR="/tmp/mec-clients"
CLIENTS_DIR="${HOME}/mec-clients"
mkdir -p "$LOG_DIR"

# Kill stale clients
pkill -9 -f "_client.py" 2>/dev/null; sleep 1

echo "=== Current tunnel map ==="
ip -4 addr show | awk '/^[0-9]+: uesimtun/{iface=$2;gsub(/:$/,"",iface)} /inet 10\.4[567]\./{
    ip=$2; sub(/\/.*$/,"",ip)
    if (ip ~ /^10\.45\./) slice="eMBB "
    else if (ip ~ /^10\.46\./) slice="URLLC"
    else if (ip ~ /^10\.47\./) slice="mMTC "
    printf "  %-14s %s  [%s]\n",iface,ip,slice
}'

echo ""
echo "=== Launching eMBB clients (10.45.x tunnels → :30880) ==="
for IF in $(ip -4 addr | grep 'inet 10\.45\.' | grep uesimtun | awk '{print $NF}'); do
    nohup python3 -u "$CLIENTS_DIR/embb_client.py" "$IF" "$SERVER" 30880 > "$LOG_DIR/embb_${IF}.log" 2>&1 &
    echo "  eMBB on $IF (PID=$!)"
done

echo ""
echo "=== Launching URLLC clients (10.46.x tunnels → :30180) ==="
for IF in $(ip -4 addr | grep 'inet 10\.46\.' | grep uesimtun | awk '{print $NF}'); do
    nohup python3 -u "$CLIENTS_DIR/urllc_client.py" "$IF" "$SERVER" 30180 > "$LOG_DIR/urllc_${IF}.log" 2>&1 &
    echo "  URLLC on $IF (PID=$!)"
done

echo ""
echo "=== Launching mMTC clients (10.47.x tunnels → :30883) ==="
for IF in $(ip -4 addr | grep 'inet 10\.47\.' | grep uesimtun | awk '{print $NF}'); do
    nohup python3 -u "$CLIENTS_DIR/mmtc_client.py" "$IF" "$SERVER" 30883 > "$LOG_DIR/mmtc_${IF}.log" 2>&1 &
    echo "  mMTC on $IF (PID=$!)"
done

sleep 8
echo ""
echo "=== Process count ==="
echo "  eMBB:  $(ps aux | grep -c '[e]mbb_client.py')  / 3"
echo "  URLLC: $(ps aux | grep -c '[u]rllc_client.py') / 3"
echo "  mMTC:  $(ps aux | grep -c '[m]mtc_client.py')  / 3"
echo ""
echo "=== Live log check ==="
for f in "$LOG_DIR"/*.log; do
    [ -f "$f" ] && echo "  $(basename $f): $(tail -1 $f 2>/dev/null)"
done
echo "DONE"
