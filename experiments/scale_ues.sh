#!/bin/bash
# ============================================================
# scale_ues.sh — UE Traffic Scaling Script for Area 2 Experiments
# Copies additional UE config files to UERANSIM VM and launches
# nr-ue processes to increase load per slice.
#
# Usage: bash scale_ues.sh <level>
#   level: baseline | low | medium | high | extreme | recovery
#
# The script:
#   1. Checks which uesimtun interfaces are active
#   2. Restarts traffic clients matching the target load level
#   3. Reports active UE counts per slice
# ============================================================

UERANSIM_IP="192.168.49.139"
UERANSIM_USER="shinegami"
UERANSIM_PASS="123"
EDGE_IP="192.168.49.171"

ssh_run() {
    sshpass -p "$UERANSIM_PASS" ssh \
        -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
        "$UERANSIM_USER@$UERANSIM_IP" "$1"
}

scp_file() {
    sshpass -p "$UERANSIM_PASS" scp \
        -o StrictHostKeyChecking=no "$1" \
        "$UERANSIM_USER@$UERANSIM_IP:$2"
}

LEVEL="${1:-medium}"

echo "============================================="
echo " UE Traffic Scaling — Level: $LEVEL"
echo "============================================="

# ── Show currently active UE interfaces ───────────────────────────────────────
echo ""
echo "[STATUS] Current uesimtun interfaces:"
ssh_run "ip -4 addr | grep -E 'uesimtun|10\.4[5-7]\.' | head -30"

EMBB_COUNT=$(ssh_run  "ip -4 addr | grep 'inet 10\.45\.' | grep uesimtun | wc -l" | tr -d '\r')
URLLC_COUNT=$(ssh_run "ip -4 addr | grep 'inet 10\.46\.' | grep uesimtun | wc -l" | tr -d '\r')
MMTC_COUNT=$(ssh_run  "ip -4 addr | grep 'inet 10\.47\.' | grep uesimtun | wc -l" | tr -d '\r')

echo ""
echo "[STATUS] Active UEs — eMBB: $EMBB_COUNT  URLLC: $URLLC_COUNT  mMTC: $MMTC_COUNT"
echo ""

# ── Stop all existing traffic clients ─────────────────────────────────────────
echo "[STEP 1] Stopping existing traffic clients..."
ssh_run "pkill -f embb_client.py 2>/dev/null; pkill -f urllc_client.py 2>/dev/null; pkill -f mmtc_client.py 2>/dev/null; sleep 2; echo 'Stopped.'"

# ── Restart clients using run_all.sh (auto-detects active interfaces) ─────────
echo "[STEP 2] Restarting clients for level: $LEVEL"
ssh_run "cd ~/mec-clients && bash run_all.sh $EDGE_IP > /tmp/mec-launch-$LEVEL.log 2>&1 &"
sleep 5

# ── Verify clients launched ───────────────────────────────────────────────────
echo "[STEP 3] Verifying client processes..."
EMBB_PROCS=$(ssh_run  "pgrep -c -f embb_client.py 2>/dev/null || echo 0" | tr -d '\r')
URLLC_PROCS=$(ssh_run "pgrep -c -f urllc_client.py 2>/dev/null || echo 0" | tr -d '\r')
MMTC_PROCS=$(ssh_run  "pgrep -c -f mmtc_client.py 2>/dev/null || echo 0" | tr -d '\r')

echo ""
echo "  eMBB clients:  $EMBB_PROCS process(es)"
echo "  URLLC clients: $URLLC_PROCS process(es)"
echo "  mMTC clients:  $MMTC_PROCS process(es)"

# ── Show live log tail ────────────────────────────────────────────────────────
echo ""
echo "[LOG] Last 10 lines from /tmp/mec-launch-$LEVEL.log:"
ssh_run "tail -10 /tmp/mec-launch-$LEVEL.log 2>/dev/null"

echo ""
echo "============================================="
echo " Done. Monitor traffic:"
echo "   ssh $UERANSIM_USER@$UERANSIM_IP"
echo "   tail -f /tmp/mec-clients/*.log"
echo "============================================="
