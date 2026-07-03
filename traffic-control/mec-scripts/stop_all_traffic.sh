#!/bin/bash
# =============================================================
# stop_all_traffic.sh
# Kill all MEC clients and iperf3 processes, reset testbed
# =============================================================

echo "[STOP] Killing all MEC clients and iperf3..."
pkill -f 'embb_client.py|urllc_client.py|mmtc_client.py' 2>/dev/null
pkill -f 'iperf3 -c' 2>/dev/null
sleep 2

COUNT=$(ps -eo args | grep -E '(embb|urllc|mmtc)_client\.py|iperf3 -c' | grep -v grep | wc -l)
if [ "$COUNT" -eq 0 ]; then
    echo "[STOP] All clients stopped. Testbed is clean."
else
    echo "[STOP] Warning: $COUNT processes still running. Force killing..."
    pkill -9 -f 'embb_client.py|urllc_client.py|mmtc_client.py' 2>/dev/null
    pkill -9 -f 'iperf3 -c' 2>/dev/null
fi
echo "[STOP] Done."
