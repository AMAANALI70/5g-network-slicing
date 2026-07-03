#!/bin/bash
# launch_mec_clients.sh v2
# Args: [embb_quality] [urllc_rate_hz] [mmtc_rate_mult]
# UE count is NOT capped — all active uesimtun interfaces are used.
# Load differentiation is achieved solely via traffic parameters.

EMBB_QUALITY=${1:-1080p}
URLLC_RATE=${2:-1.0}
MMTC_MULT=${3:-1.0}

SERVER="192.168.49.172"
LOG_DIR="/tmp/mec-clients"
CLIENTS_DIR="${HOME}/mec-clients"
mkdir -p "$LOG_DIR"

# Kill stale clients
pkill -9 -f "_client.py" 2>/dev/null; sleep 1

echo "=== Load parameters ==="
echo "  eMBB quality : $EMBB_QUALITY"
echo "  URLLC rate   : ${URLLC_RATE} Hz"
echo "  mMTC mult    : ${MMTC_MULT}x"
echo ""
echo "=== Current tunnel map ==="
ip -4 addr show | awk '/^[0-9]+: uesimtun/{iface=$2;gsub(/:$/,"",iface)} /inet 10\.4[567]\./{
    ip=$2; sub(/\/.*$/,"",ip)
    if (ip ~ /^10\.45\./) slice="eMBB "
    else if (ip ~ /^10\.46\./) slice="URLLC"
    else if (ip ~ /^10\.47\./) slice="mMTC "
    printf "  %-14s %s  [%s]\n",iface,ip,slice
}'

echo ""
echo "=== Launching eMBB clients (quality=$EMBB_QUALITY) ==="
for IF in $(ip -4 addr | grep 'inet 10\.45\.' | grep uesimtun | awk '{print $NF}'); do
    nohup python3 -u "$CLIENTS_DIR/embb_client.py" \
        "$IF" "$SERVER" 30880 "$EMBB_QUALITY" \
        > "$LOG_DIR/embb_${IF}.log" 2>&1 &
    echo "  eMBB on $IF (PID=$!) quality=$EMBB_QUALITY"
done

echo ""
echo "=== Launching URLLC clients (rate=${URLLC_RATE}Hz) ==="
for IF in $(ip -4 addr | grep 'inet 10\.46\.' | grep uesimtun | awk '{print $NF}'); do
    nohup python3 -u "$CLIENTS_DIR/urllc_client.py" \
        "$IF" "$SERVER" 30180 "$URLLC_RATE" \
        > "$LOG_DIR/urllc_${IF}.log" 2>&1 &
    echo "  URLLC on $IF (PID=$!) rate=${URLLC_RATE}Hz"
done

echo ""
echo "=== Launching mMTC clients (mult=${MMTC_MULT}x) ==="
for IF in $(ip -4 addr | grep 'inet 10\.47\.' | grep uesimtun | awk '{print $NF}'); do
    nohup python3 -u "$CLIENTS_DIR/mmtc_client.py" \
        "$IF" "$SERVER" 1883 "$MMTC_MULT" \
        > "$LOG_DIR/mmtc_${IF}.log" 2>&1 &
    echo "  mMTC on $IF (PID=$!) mult=${MMTC_MULT}x"
done

sleep 8
echo ""
echo "=== Process count ==="
echo "  eMBB:  $(ps aux | grep -c '[e]mbb_client.py')  clients"
echo "  URLLC: $(ps aux | grep -c '[u]rllc_client.py') clients"
echo "  mMTC:  $(ps aux | grep -c '[m]mtc_client.py')  clients"
echo ""
echo "=== Live log check ==="
for f in "$LOG_DIR"/*.log; do
    [ -f "$f" ] && echo "  $(basename $f): $(tail -1 $f 2>/dev/null)"
done
echo "DONE"
