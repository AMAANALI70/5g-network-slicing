#!/bin/bash
# =============================================================
# mec_restart.sh — Full MEC Testbed Restart Procedure
# =============================================================
# Run on MASTER NODE (192.168.49.174) to restart the full stack:
#   1. Restart all 3 UPF pods (clear stale PFCP)
#   2. Restart all 3 SMFs on core VM (192.168.49.143)
#   3. Clean-restart gNB + 3 UEs on UERANSIM VM (192.168.49.139)
#   4. Launch all 9 traffic clients
#
# Architecture:
#   3 UEs × 3 PDU sessions = 9 uesimtun interfaces:
#     eMBB  (10.45.x) → embb_client.py  → nginx HLS    :30880
#     URLLC (10.46.x) → urllc_client.py → Node-RED     :30180
#     mMTC  (10.47.x) → mmtc_client.py  → Mosquitto    :30883
#
# Core VM (192.168.49.143): AMF, 3×SMF (embb/urllc/mmtc), NRF, etc.
# Worker  (192.168.49.172): 3×UPF pods + app pods
# UERANSIM VM (192.168.49.139): gNB + 3 UEs
# =============================================================

set -euo pipefail

CORE_VM="192.168.49.143"
UERANSIM_VM="192.168.49.139"
WORKER="192.168.49.172"
UE_USER="shinegami"
PASS="123"
UERANSIM_LOG="/tmp/ueransim-logs"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info() { echo -e "${GREEN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
die()  { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

info "==========================================="
info " MEC Testbed Full Restart"
info "==========================================="

# ── Phase 1: Restart UPF pods ────────────────────────────────
info "[1/4] Restarting UPF pods..."
for ns in embb urllc mmtc; do
    kubectl delete pod -n $ns -l app=upf-${ns} --force --grace-period=0 2>/dev/null || true
    info "  deleted upf-${ns}"
done

info "  Waiting 35s for UPFs to come up..."
sleep 35

for ns in embb urllc mmtc; do
    status=$(kubectl get pods -n $ns -l app=upf-${ns} --no-headers 2>/dev/null | awk '{print $3}')
    [ "$status" = "Running" ] && info "  upf-${ns}: Running ✓" || warn "  upf-${ns}: $status ⚠"
done

# ── Phase 2: Restart SMFs + AMF on core VM ───────────────────
info "[2/4] Restarting AMF + SMFs on core VM..."
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no ${UE_USER}@${CORE_VM} '
echo 123 | sudo -S systemctl restart open5gs-amfd.service
sleep 5
echo 123 | sudo -S systemctl restart open5gs-smfd-embb.service
echo 123 | sudo -S systemctl restart open5gs-smfd-urllc.service
echo 123 | sudo -S systemctl restart open5gs-smfd-mmtc.service
sleep 8
for svc in open5gs-amfd open5gs-smfd-embb open5gs-smfd-urllc open5gs-smfd-mmtc; do
    state=$(systemctl is-active $svc 2>/dev/null)
    echo "  $svc: $state"
done
echo "  AMF NGAP socket (38412):"
ss -lnp | grep 38412 | head -2 || echo "  WARNING: AMF not listening on 38412 yet"
'

# ── Phase 3: Restart UERANSIM (gNB + 3 UEs) ─────────────────
info "[3/4] Restarting UERANSIM (gNB + 3 UEs)..."

# Write and run restart script on UERANSIM VM
cat > /tmp/_ue_restart.sh << 'UERANSCRIPT'
#!/bin/bash
LOG="/tmp/ueransim-logs"
OUT="/tmp/ueransim_restart_out.txt"
mkdir -p "$LOG"
exec > "$OUT" 2>&1

echo "[$(date)] Killing ALL UERANSIM processes..."
# Collect all PIDs first, then kill in one sudo call (avoids stdin-consumed-by-pipe bug)
PIDS=$(pgrep -f 'nr-gnb|nr-ue' 2>/dev/null | tr '\n' ' ')
if [ -n "$PIDS" ]; then
    echo "  PIDs: $PIDS"
    echo 123 | sudo -S kill -9 $PIDS 2>/dev/null; true
else
    echo "  No UERANSIM procs found"
fi

# Also kill traffic clients
for pid in $(pgrep -f '_client.py' 2>/dev/null); do kill -9 $pid 2>/dev/null; done; true

echo "  Waiting 8s for sockets to release..."
sleep 8
echo "  Remaining: $(pgrep -c -f 'nr-gnb|nr-ue' 2>/dev/null || echo 0) UERANSIM procs"

echo "[$(date)] Removing stale uesimtun interfaces..."
for i in $(seq 0 25); do
    ip link show uesimtun${i} &>/dev/null 2>&1 && \
        echo 123 | sudo -S ip link delete uesimtun${i} 2>/dev/null && \
        echo "  deleted uesimtun${i}"; true
done

echo "[$(date)] Clearing stale client log files..."
rm -f /tmp/mec-clients/*.log 2>/dev/null; true
echo "  Log dir cleared."

echo "[$(date)] Starting gNB..."
cd ~/UERANSIM
echo 123 | sudo -S nohup ./build/nr-gnb -c ./config/open5gs-gnb.yaml > "$LOG/gnb.log" 2>&1 &
sleep 7

if grep -q "NG Setup procedure is successful" "$LOG/gnb.log" 2>/dev/null; then
    echo "gNB NG Setup: SUCCESS"
else
    echo "gNB NG Setup: FAILED — last log:"
    tail -5 "$LOG/gnb.log"
fi
if grep -i "bind.*failed\|failed.*bind" "$LOG/gnb.log" 2>/dev/null; then
    echo "WARNING: Socket bind errors detected (stale process may still hold ports)"
else
    echo "gNB sockets: OK"
fi

echo "[$(date)] Starting 3 UEs (sequential, 4s gap)..."
echo 123 | sudo -S nohup ./build/nr-ue -c config/ue-embb.yaml  > "$LOG/ue-embb.log"  2>&1 & sleep 4
echo 123 | sudo -S nohup ./build/nr-ue -c config/ue-urllc.yaml > "$LOG/ue-urllc.log" 2>&1 & sleep 4
echo 123 | sudo -S nohup ./build/nr-ue -c config/ue-mmtc.yaml  > "$LOG/ue-mmtc.log"  2>&1 & sleep 12

echo "[$(date)] === TUNNELS ==="
ip -4 addr show | awk '/^[0-9]+: uesimtun/{iface=$2;gsub(/:$/,"",iface)} /inet 10\.4[567]\./{
    ip=$2; sub(/\/.*$/,"",ip)
    if (ip ~ /^10\.45\./) slice="eMBB "
    else if (ip ~ /^10\.46\./) slice="URLLC"
    else slice="mMTC "
    printf "  %-14s %-15s [%s]\n",iface,ip,slice
}'

echo "[$(date)] === CONNECTIVITY ==="
ok=0; fail=0
for iface in $(ip -4 addr show | awk '/^[0-9]+: uesimtun/{iface=$2;gsub(/:$/,"",iface);print iface}' 2>/dev/null); do
    ip_addr=$(ip -4 addr show $iface 2>/dev/null | grep -oP 'inet \K[\d.]+')
    loss=$(ping -I $iface -c 2 -W 2 192.168.49.172 2>&1 | grep -oP '\d+% packet loss')
    [ "$loss" = "0% packet loss" ] && { ok=$((ok+1)); echo "  $iface ($ip_addr): OK"; } \
                                   || { fail=$((fail+1)); echo "  $iface ($ip_addr): FAIL"; }
done
echo "RESULT: $ok OK / $fail FAIL"
UERANSCRIPT

sshpass -p "$PASS" scp -o StrictHostKeyChecking=no /tmp/_ue_restart.sh ${UE_USER}@${UERANSIM_VM}:/tmp/_ue_restart.sh
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no ${UE_USER}@${UERANSIM_VM} \
    'nohup bash /tmp/_ue_restart.sh > /dev/null 2>&1 < /dev/null & disown $!; echo "Launched PID=$!"'

info "  Waiting 55s for UEs + PDU sessions to establish..."
sleep 55

# Read results
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no ${UE_USER}@${UERANSIM_VM} 'cat /tmp/ueransim_restart_out.txt 2>/dev/null'

# ── Phase 4: Launch Traffic Clients + Orchestrator ──────────
info "[4/4] Launching 9 traffic clients..."
sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no ${UE_USER}@${UERANSIM_VM} \
    'bash ~/mec-clients/launch_mec_clients.sh 2>&1'

info "[5/5] Restarting rule-based orchestrator..."
pkill -f phase3-orchestrator 2>/dev/null; sleep 1
nohup python3 /home/kube-master/k8s/phase3-orchestrator.py > /tmp/orchestrator_ruleb.log 2>&1 &
ORCH_PID=$!
info "  Orchestrator PID=$ORCH_PID"
sleep 4
if curl -s http://localhost:9200/metrics > /dev/null 2>&1; then
    RTT=$(curl -s http://localhost:9200/metrics 2>/dev/null | grep urllc_rtt | awk '{print $2}')
    TP=$(curl -s http://localhost:9200/metrics  2>/dev/null | grep embb_mbps | awk '{print $2}')
    info "  Metrics OK — RTT=${RTT}ms  eMBB=${TP}Mbps"
else
    warn "  Orchestrator not yet responding on :9200"
fi

info "==========================================="
info " Done! Full restart complete."
info " Check Grafana: http://192.168.49.174:30300"
info " Orchestrator:  curl http://localhost:9200/metrics"
info " Monitor:       bash phase3-monitor.sh"
info "==========================================="
