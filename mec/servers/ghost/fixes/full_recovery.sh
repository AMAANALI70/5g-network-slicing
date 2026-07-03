#!/bin/bash
# =============================================================
# FULL 5G CLUSTER + UE RECOVERY SCRIPT
# Fixes: Flannel CNI crashes → UPF crashes → PDU rejection → App pods stuck
# =============================================================
set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*"; }

echo "========================================================"
echo "  5G Cluster Full Recovery — $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================================"

# ── PHASE 0: DIAGNOSTICS ──────────────────────────────────────
echo ""
echo "═══ PHASE 0: DIAGNOSTICS ═══"

info "Current pod status:"
kubectl get pods -A --no-headers 2>/dev/null | while read ns pod rest; do
    status=$(echo "$rest" | awk '{print $2}')
    if [[ "$status" != "Running" && "$status" != "Completed" ]]; then
        warn "  UNHEALTHY: $ns/$pod → $status"
    fi
done

info "Flannel logs (worker nodes):"
for pod in $(kubectl get pods -n kube-flannel --no-headers 2>/dev/null | grep -v Running | awk '{print $1}'); do
    echo "  --- $pod ---"
    kubectl logs -n kube-flannel "$pod" --tail=10 2>&1 | sed 's/^/    /'
done

info "UPF crash logs:"
for ns in embb urllc mmtc; do
    for pod in $(kubectl get pods -n $ns --no-headers 2>/dev/null | grep -i crash | awk '{print $1}'); do
        echo "  --- $ns/$pod ---"
        kubectl logs -n $ns "$pod" --tail=10 2>&1 | sed 's/^/    /'
    done
done

info "App pods stuck:"
for ns in embb urllc mmtc default-slice; do
    for pod in $(kubectl get pods -n $ns --no-headers 2>/dev/null | grep -vE "Running|Completed" | awk '{print $1}'); do
        echo "  --- $ns/$pod ---"
        kubectl describe pod -n $ns "$pod" 2>&1 | grep -A5 "Events:" | tail -6 | sed 's/^/    /'
    done
done

# ── PHASE 1: FIX FLANNEL CNI ──────────────────────────────────
echo ""
echo "═══ PHASE 1: FIX FLANNEL CNI ═══"
info "Force-deleting stuck/crashed flannel pods..."
for pod in $(kubectl get pods -n kube-flannel --no-headers 2>/dev/null | grep -v Running | awk '{print $1}'); do
    kubectl delete pod -n kube-flannel "$pod" --force --grace-period=0 2>/dev/null && info "  Deleted $pod"
done

info "Restarting flannel daemonset..."
kubectl rollout restart daemonset/kube-flannel-ds -n kube-flannel 2>/dev/null || true

info "Cleaning flannel subnet cache on workers..."
for host in 192.168.49.171 192.168.49.181; do
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes \
        kube@$host "sudo rm -f /run/flannel/subnet.env 2>/dev/null; echo '  Cleaned $host'" 2>/dev/null || \
        warn "  Could not clean $host (SSH issue — may need password)"
done

info "Waiting 20s for flannel to stabilize..."
sleep 20

# Check flannel status
FLANNEL_OK=$(kubectl get pods -n kube-flannel --no-headers 2>/dev/null | grep -c "Running" || echo 0)
FLANNEL_TOTAL=$(kubectl get pods -n kube-flannel --no-headers 2>/dev/null | wc -l)
info "Flannel: $FLANNEL_OK/$FLANNEL_TOTAL running"

# ── PHASE 2: FIX COREDNS ──────────────────────────────────────
echo ""
echo "═══ PHASE 2: FIX COREDNS ═══"
info "Restarting CoreDNS..."
kubectl rollout restart deployment/coredns -n kube-system 2>/dev/null || true
sleep 10

# ── PHASE 3: FIX UPF PODS ─────────────────────────────────────
echo ""
echo "═══ PHASE 3: FIX UPF PODS ═══"

info "Creating TUN devices on worker1 (kube)..."
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes kube@192.168.49.171 '
    echo "  Creating ogstun-embb..."
    sudo ip tuntap add name ogstun-embb mode tun 2>/dev/null || true
    sudo ip addr add 10.45.0.1/24 dev ogstun-embb 2>/dev/null || true
    sudo ip link set ogstun-embb up 2>/dev/null || true
    sudo ip route add 10.45.0.0/24 dev ogstun-embb 2>/dev/null || true

    echo "  Creating ogstun-urllc..."
    sudo ip tuntap add name ogstun-urllc mode tun 2>/dev/null || true
    sudo ip addr add 10.46.0.1/24 dev ogstun-urllc 2>/dev/null || true
    sudo ip link set ogstun-urllc up 2>/dev/null || true
    sudo ip route add 10.46.0.0/24 dev ogstun-urllc 2>/dev/null || true

    echo "  Creating ogstun-mmtc..."
    sudo ip tuntap add name ogstun-mmtc mode tun 2>/dev/null || true
    sudo ip addr add 10.47.0.1/24 dev ogstun-mmtc 2>/dev/null || true
    sudo ip link set ogstun-mmtc up 2>/dev/null || true
    sudo ip route add 10.47.0.0/24 dev ogstun-mmtc 2>/dev/null || true

    echo "  Enabling IP forwarding..."
    sudo sysctl -w net.ipv4.ip_forward=1 >/dev/null

    echo "  Adding MASQUERADE rules..."
    sudo iptables -t nat -C POSTROUTING -s 10.45.0.0/24 ! -o ogstun-embb -j MASQUERADE 2>/dev/null || \
        sudo iptables -t nat -A POSTROUTING -s 10.45.0.0/24 ! -o ogstun-embb -j MASQUERADE
    sudo iptables -t nat -C POSTROUTING -s 10.46.0.0/24 ! -o ogstun-urllc -j MASQUERADE 2>/dev/null || \
        sudo iptables -t nat -A POSTROUTING -s 10.46.0.0/24 ! -o ogstun-urllc -j MASQUERADE
    sudo iptables -t nat -C POSTROUTING -s 10.47.0.0/24 ! -o ogstun-mmtc -j MASQUERADE 2>/dev/null || \
        sudo iptables -t nat -A POSTROUTING -s 10.47.0.0/24 ! -o ogstun-mmtc -j MASQUERADE

    echo "  TUN devices and routing configured"
    ip link show | grep ogstun | awk "{print \"    \" \$0}"
' 2>&1 || warn "  SSH to worker1 failed — you may need to do this manually"

info "Force-deleting crashed UPF pods..."
for ns in embb urllc mmtc; do
    for pod in $(kubectl get pods -n $ns --no-headers 2>/dev/null | grep -iE "crash|error|unknown" | awk '{print $1}'); do
        kubectl delete pod -n $ns "$pod" --force --grace-period=0 2>/dev/null && info "  Deleted $ns/$pod"
    done
done

info "Restarting UPF deployments..."
for dep in "embb:upf-embb" "embb:upf-embb-node2" "urllc:upf-urllc" "mmtc:upf-mmtc"; do
    ns="${dep%%:*}"
    name="${dep##*:}"
    kubectl rollout restart deployment/$name -n $ns 2>/dev/null && info "  Restarted $name" || true
done

info "Waiting 30s for UPFs to start..."
sleep 30

# ── PHASE 4: FIX APP PODS ─────────────────────────────────────
echo ""
echo "═══ PHASE 4: FIX APP PODS ═══"
info "Force-deleting stuck app pods..."
for ns in embb urllc mmtc default-slice; do
    for pod in $(kubectl get pods -n $ns --no-headers 2>/dev/null | grep -vE "Running|Completed" | awk '{print $1}'); do
        kubectl delete pod -n $ns "$pod" --force --grace-period=0 2>/dev/null && info "  Deleted $ns/$pod"
    done
done

info "Restarting app deployments..."
for dep in "embb:embb-app" "urllc:urllc-app" "mmtc:mmtc-app" "default-slice:default-app"; do
    ns="${dep%%:*}"
    name="${dep##*:}"
    kubectl rollout restart deployment/$name -n $ns 2>/dev/null && info "  Restarted $name" || true
done

# ── PHASE 5: FIX METRICS EXPORTER ─────────────────────────────
echo ""
echo "═══ PHASE 5: FIX MONITORING ═══"
info "Restarting tun-metrics-exporter..."
kubectl rollout restart daemonset/tun-metrics-exporter -n monitoring 2>/dev/null || true

info "Restarting metrics-server..."
kubectl rollout restart deployment/metrics-server -n kube-system 2>/dev/null || true

# ── PHASE 6: WAIT AND VERIFY ──────────────────────────────────
echo ""
echo "═══ PHASE 6: WAIT AND VERIFY ═══"
info "Waiting 60s for all pods to stabilize..."
sleep 60

echo ""
echo "═══ FINAL POD STATUS ═══"
kubectl get pods -A 2>/dev/null
echo ""

UNHEALTHY=$(kubectl get pods -A --no-headers 2>/dev/null | grep -cvE "Running|Completed" || echo 0)
if [ "$UNHEALTHY" -eq 0 ]; then
    info "✅ All pods are healthy!"
else
    warn "⚠  $UNHEALTHY unhealthy pods remaining"
fi

# ── PHASE 7: FIX IPTABLES (KUBE-SERVICES + DNAT) ──────────────
echo ""
echo "═══ PHASE 7: FIX IPTABLES ROUTING ═══"

# Find the running UPF pod on worker1 for iptables manipulation
UPF_POD=$(kubectl get pod -n embb -l app=upf-embb --no-headers 2>/dev/null | grep Running | awk '{print $1}' | head -1)
if [ -n "$UPF_POD" ]; then
    info "Using UPF pod: $UPF_POD for iptables fixes"

    # Ensure KUBE-SERVICES jump exists in PREROUTING
    kubectl exec -n embb "$UPF_POD" -- bash -c \
        "iptables -t nat -C PREROUTING -j KUBE-SERVICES 2>/dev/null || iptables -t nat -I PREROUTING -j KUBE-SERVICES" 2>/dev/null \
        && info "  KUBE-SERVICES jump restored in PREROUTING" || warn "  Could not fix KUBE-SERVICES"

    # Add DNAT for URLLC port 1880 (not a NodePort, needs manual DNAT)
    URLLC_POD_IP=$(kubectl get pod -n urllc -l app=urllc-app -o jsonpath='{.items[0].status.podIP}' 2>/dev/null)
    if [ -n "$URLLC_POD_IP" ]; then
        kubectl exec -n embb "$UPF_POD" -- bash -c \
            "iptables -t nat -D PREROUTING -p tcp --dport 1880 -j DNAT --to-destination $URLLC_POD_IP:1880 2>/dev/null; \
             iptables -t nat -A PREROUTING -i ogstun-urllc -p tcp --dport 1880 -j DNAT --to-destination $URLLC_POD_IP:1880" 2>/dev/null \
            && info "  URLLC DNAT: 1880 → $URLLC_POD_IP:1880" || warn "  URLLC DNAT failed"
    fi

    info "Current PREROUTING rules:"
    kubectl exec -n embb "$UPF_POD" -- iptables -t nat -L PREROUTING -n 2>/dev/null | sed 's/^/    /' || true
else
    warn "No running UPF pod found — iptables fixes skipped"
fi

# ── PHASE 8: FIX UERANSIM UEs ─────────────────────────────────
echo ""
echo "═══ PHASE 8: UERANSIM UE RECOVERY ═══"
info "Restarting UEs on UERANSIM VM (192.168.49.139)..."
sshpass -p 123 ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
    shinegami@192.168.49.139 '
    echo "  Stopping existing UEs..."
    sudo pkill -f "nr-ue" 2>/dev/null; sleep 3

    echo "  Cleaning stale tun interfaces..."
    for iface in $(ip link show | grep uesimtun | awk -F": " "{print \$2}"); do
        sudo ip link delete $iface 2>/dev/null && echo "    Removed $iface"
    done
    sleep 2

    echo "  Starting UEs..."
    cd ~/UERANSIM/build 2>/dev/null || cd /home/shinegami/UERANSIM/build
    for cfg in ~/config/ue*.yaml /home/shinegami/config/ue*.yaml; do
        [ -f "$cfg" ] || continue
        name=$(basename $cfg .yaml)
        sudo ./nr-ue -c $cfg > /tmp/ue_${name}.log 2>&1 &
        echo "    Started $name (PID=$!)"
    done

    sleep 15
    echo "  Tunnel interfaces:"
    ip addr show | grep "inet 10\.4[567]" | awk "{print \"    \"\$2\" on \"\$NF}"

    TUNNEL_COUNT=$(ip addr show | grep -c "inet 10\.4[567]" 2>/dev/null || echo 0)
    echo "  Active tunnels: $TUNNEL_COUNT"

    if [ "$TUNNEL_COUNT" -gt 0 ]; then
        echo "  ✅ UEs connected — PDU sessions should be established"
    else
        echo "  ⚠  No tunnels — PDU session establishment may still be failing"
        echo "  Check UE logs: tail /tmp/ue_*.log"
    fi
' 2>&1 || warn "  UERANSIM SSH failed — do this manually"

# ── PHASE 9: RESTART UE CLIENTS ───────────────────────────────
echo ""
echo "═══ PHASE 9: RESTART UE TRAFFIC CLIENTS ═══"
sshpass -p 123 ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
    shinegami@192.168.49.139 '
    echo "  Killing old clients..."
    pkill -f "_client.py" 2>/dev/null; sleep 2

    if [ -f ~/mec-clients/run_all.sh ]; then
        echo "  Starting traffic clients..."
        cd ~/mec-clients
        bash run_all.sh 192.168.49.171
        sleep 10
        echo "  Client logs:"
        for f in /tmp/mec-clients/*.log; do
            [ -f "$f" ] && echo "    $(basename $f): $(tail -1 $f)"
        done
    else
        echo "  ⚠  ~/mec-clients/run_all.sh not found"
    fi
' 2>&1 || warn "  Client restart failed"

# ── FINAL SUMMARY ─────────────────────────────────────────────
echo ""
echo "========================================================"
echo "  RECOVERY COMPLETE — $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================================"
echo ""
kubectl get pods -A 2>/dev/null
echo ""
UNHEALTHY=$(kubectl get pods -A --no-headers 2>/dev/null | grep -cvE "Running|Completed" || echo 0)
if [ "$UNHEALTHY" -eq 0 ]; then
    echo -e "${GREEN}✅ ALL PODS HEALTHY — System fully recovered${NC}"
else
    echo -e "${YELLOW}⚠  $UNHEALTHY pods still unhealthy — check logs above${NC}"
fi
echo ""
echo "Next steps:"
echo "  1. Verify UE connectivity: sshpass -p 123 ssh shinegami@192.168.49.139 'ip addr | grep uesimtun'"
echo "  2. Check orchestrator: tail -f /tmp/orchestrator.log"
echo "  3. Check client traffic: sshpass -p 123 ssh shinegami@192.168.49.139 'tail /tmp/mec-clients/*.log'"
