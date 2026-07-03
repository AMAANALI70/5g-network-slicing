#!/bin/bash
# fix_system.sh — Full cluster + UE recovery script
set -e
echo "========================================"
echo "  5G Cluster + UE Full Recovery"
echo "========================================"

# ── 1. Force-delete Unknown/stuck pods ───────────────────────────────────────
echo ""
echo "[1/6] Force-deleting stuck Unknown pods..."
for ns in default-slice embb mmtc urllc monitoring kube-system kube-flannel; do
    kubectl get pods -n $ns --no-headers 2>/dev/null | \
        grep -v "Running\|Completed" | awk '{print $1}' | \
        while read pod; do
            kubectl delete pod -n $ns $pod --force --grace-period=0 2>/dev/null \
                && echo "  Deleted $ns/$pod"
        done
done
echo "  Done"

# ── 2. Fix kube-flannel (CNI broken = no pod networking = PDU rejected) ───────
echo ""
echo "[2/6] Fixing kube-flannel CNI..."
kubectl rollout restart daemonset/kube-flannel-ds -n kube-flannel 2>/dev/null \
    && echo "  kube-flannel restarted" || echo "  kube-flannel restart skipped"

# Clean flannel subnet cache on workers
for host in 192.168.49.171 192.168.49.181; do
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
        -i /home/kube-master/.ssh/id_rsa kube@$host \
        "sudo rm -f /run/flannel/subnet.env 2>/dev/null; echo cleaned $host" 2>/dev/null || true
done
sleep 15

# ── 3. Restart all UPF deployments ───────────────────────────────────────────
echo ""
echo "[3/6] Restarting UPF deployments..."
for ns_dep in "urllc:upf-urllc" "embb:upf-embb" "embb:upf-embb-node2" "mmtc:upf-mmtc"; do
    ns="${ns_dep%%:*}"
    dep="${ns_dep##*:}"
    kubectl rollout restart deployment/$dep -n $ns 2>/dev/null \
        && echo "  Restarted $dep in $ns" || echo "  Skipped $dep (may not exist)"
done

# ── 4. Restart slice apps ─────────────────────────────────────────────────────
echo ""
echo "[4/6] Restarting slice applications..."
for ns_dep in "embb:embb-app" "urllc:urllc-app" "mmtc:mmtc-app" "default-slice:default-app"; do
    ns="${ns_dep%%:*}"
    dep="${ns_dep##*:}"
    kubectl rollout restart deployment/$dep -n $ns 2>/dev/null \
        && echo "  Restarted $dep" || echo "  Skipped $dep"
done

# ── 5. Wait for pods to come up ───────────────────────────────────────────────
echo ""
echo "[5/6] Waiting 45s for pods to stabilize..."
sleep 45

echo ""
echo "=== Pod Status ==="
kubectl get pods -A | grep -v "NAME"
echo ""
UNHEALTHY=$(kubectl get pods -A | grep -v "Running\|Completed\|NAME" | wc -l)
echo "Unhealthy pods: $UNHEALTHY"

# ── 6. Fix UEs - PDU session recovery ─────────────────────────────────────────
echo ""
echo "[6/6] Fixing UERANSIM UEs (PDU session recovery)..."
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

    sleep 12
    echo "  Tunnel interfaces:"
    ip addr show | grep "inet 10\.4[567]" | awk "{print \"    \"\$2\" on \"\$NF}"
    
    TUNNEL_COUNT=$(ip addr show | grep -c "inet 10\.4[567]" 2>/dev/null || echo 0)
    echo "  Active tunnels: $TUNNEL_COUNT"
' 2>&1

echo ""
echo "========================================"
echo "  Recovery Complete"
echo "========================================"
