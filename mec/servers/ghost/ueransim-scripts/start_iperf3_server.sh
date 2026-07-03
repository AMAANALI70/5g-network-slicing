#!/bin/bash
# =============================================================
# start_iperf3_server.sh  (run on kubemaster before HIGH traffic)
# Starts iperf3 servers accessible to UERANSIM via eMBB GTP tunnel
#
# Usage:
#   bash ueransim-scripts/start_iperf3_server.sh
#
# If iperf3 not installed:
#   sudo apt-get install -y iperf3
# =============================================================

PORTS=(5201 5202 5203)
KUBEMASTER_IP=$(hostname -I | awk '{print $1}')   # 192.168.49.174

# Check iperf3 exists
if ! command -v iperf3 &>/dev/null; then
    echo "[iperf3-server] iperf3 not found. Installing..."
    sudo apt-get install -y iperf3
fi

echo "[iperf3-server] Killing any existing iperf3 servers..."
pkill -f 'iperf3 -s' 2>/dev/null
sleep 1

LOG_DIR="/tmp/iperf3-server"
mkdir -p "$LOG_DIR"

for PORT in "${PORTS[@]}"; do
    iperf3 -s -p "$PORT" -D --logfile "$LOG_DIR/server_${PORT}.log"
    echo "[iperf3-server] Listening on $KUBEMASTER_IP:$PORT"
done

sleep 1
COUNT=$(pgrep -c 'iperf3' 2>/dev/null || echo 0)
echo "[iperf3-server] Running: $COUNT servers on ports ${PORTS[*]}"
echo ""
echo "Now update HIGH script EDGE_IP for iperf3 to: $KUBEMASTER_IP"
echo "Run: python3 dataset/load_controller.py set high --edge-ip 192.168.49.171 --iperf-server $KUBEMASTER_IP"
