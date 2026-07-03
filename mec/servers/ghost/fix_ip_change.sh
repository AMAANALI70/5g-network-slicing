#!/bin/bash
# =============================================================
# Fix: Worker node IP changed 192.168.49.171 → 192.168.49.172
# Password: 123 for all VMs
# =============================================================
OLD_IP="192.168.49.171"
NEW_IP="192.168.49.172"
WORKER_SSH="sshpass -p 123 ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 kube@192.168.49.173"
UERANSIM_SSH="sshpass -p 123 ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 shinegami@192.168.49.139"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info() { echo -e "${GREEN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERR ]${NC} $*"; }

echo "============================================================"
echo "  Full Recovery: IP Change Fix + Cluster Restore"
echo "  OLD=$OLD_IP  NEW=$NEW_IP"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"

# ── STEP 1: Fix kubelet node-ip on worker ─────────────────────
echo ""
info "STEP 1: Fixing kubelet node-ip on worker..."
$WORKER_SSH "echo '123' | sudo -S bash -s" << WORKER_SCRIPT
set -e
NEW_IP="192.168.49.172"
KUBEADM_FLAGS="/var/lib/kubelet/kubeadm-flags.env"

echo "  Current flags: \$(cat \$KUBEADM_FLAGS 2>/dev/null || echo 'empty')"

# Write clean node-ip flag
echo "KUBELET_KUBEADM_ARGS=\"--node-ip=\${NEW_IP} --container-runtime-endpoint=unix:///var/run/containerd/containerd.sock\"" > \$KUBEADM_FLAGS
echo "  Written: \$(cat \$KUBEADM_FLAGS)"

systemctl restart kubelet
sleep 5
systemctl is-active kubelet && echo "  kubelet: ACTIVE" || echo "  kubelet: check logs"
WORKER_SCRIPT
info "  kubelet node-ip set to $NEW_IP"

# ── STEP 2: Wait for node to re-register ─────────────────────
echo ""
info "STEP 2: Waiting 20s for node to re-register with new IP..."
sleep 20
kubectl get nodes -o wide 2>/dev/null

# ── STEP 3: Fix Flannel - clean state on worker ───────────────
echo ""
info "STEP 3: Fixing Flannel CNI..."
$WORKER_SSH "echo '123' | sudo -S bash -s" << 'FLANNEL_SCRIPT'
# Clean flannel state
rm -f /run/flannel/subnet.env 2>/dev/null
ip link delete flannel.1 2>/dev/null || true
ip link delete cni0 2>/dev/null || true
ip link delete vxlan.calico 2>/dev/null || true
echo "  Flannel state cleaned"
FLANNEL_SCRIPT

# Delete crashed flannel pods - they'll restart fresh on correct IP
info "  Deleting crashed flannel pods..."
kubectl get pods -n kube-flannel --no-headers 2>/dev/null | grep -v "1/1" | awk '{print $1}' | \
    xargs -r -I{} kubectl delete pod -n kube-flannel {} --force --grace-period=0 2>/dev/null || true

info "  Waiting 30s for flannel to restart..."
sleep 30
kubectl get pods -n kube-flannel 2>/dev/null

# ── STEP 4: Setup TUN devices on worker ──────────────────────
echo ""
info "STEP 4: Creating TUN devices on worker..."
$WORKER_SSH "echo '123' | sudo -S bash -s" << 'TUN_SCRIPT'
sysctl -w net.ipv4.ip_forward=1 >/dev/null

for dev in ogstun-embb ogstun-urllc ogstun-mmtc; do
    if ! ip link show "$dev" &>/dev/null; then
        ip tuntap add name "$dev" mode tun && echo "  Created $dev"
    else
        echo "  $dev already exists"
    fi
done

ip addr replace 10.45.0.1/24 dev ogstun-embb  2>/dev/null || ip addr add 10.45.0.1/24 dev ogstun-embb
ip addr replace 10.46.0.1/24 dev ogstun-urllc 2>/dev/null || ip addr add 10.46.0.1/24 dev ogstun-urllc
ip addr replace 10.47.0.1/24 dev ogstun-mmtc  2>/dev/null || ip addr add 10.47.0.1/24 dev ogstun-mmtc

ip link set ogstun-embb up; ip link set ogstun-urllc up; ip link set ogstun-mmtc up

ip route add 10.45.0.0/24 dev ogstun-embb  2>/dev/null || true
ip route add 10.46.0.0/24 dev ogstun-urllc 2>/dev/null || true
ip route add 10.47.0.0/24 dev ogstun-mmtc  2>/dev/null || true

# MASQUERADE for UE subnet traffic
for rule in \
    "POSTROUTING -s 10.45.0.0/24 ! -o ogstun-embb  -j MASQUERADE" \
    "POSTROUTING -s 10.46.0.0/24 ! -o ogstun-urllc -j MASQUERADE" \
    "POSTROUTING -s 10.47.0.0/24 ! -o ogstun-mmtc  -j MASQUERADE"; do
    iptables -t nat -C $rule 2>/dev/null || iptables -t nat -A $rule
done

echo "  TUN devices:"
ip link show | grep ogstun | awk '{print "    "$0}'
TUN_SCRIPT
info "  TUN devices configured"

# ── STEP 5: Update ConfigMaps with new IP ────────────────────
echo ""
info "STEP 5: Updating UPF ConfigMaps ($OLD_IP → $NEW_IP)..."

for ns_cm in "embb:upf-embb-config" "urllc:upf-urllc-config" "mmtc:upf-mmtc-config"; do
    ns="${ns_cm%%:*}"; cm="${ns_cm##*:}"
    kubectl get configmap "$cm" -n "$ns" -o yaml 2>/dev/null | \
        sed "s/${OLD_IP}/${NEW_IP}/g" | \
        kubectl apply -f - 2>/dev/null && info "  Updated $cm" || warn "  Skipped $cm"
done

# ── STEP 6: Delete all unhealthy pods ────────────────────────
echo ""
info "STEP 6: Force-deleting all unhealthy pods..."
for ns in embb urllc mmtc default-slice monitoring kube-system; do
    kubectl get pods -n "$ns" --no-headers 2>/dev/null | \
        grep -vE "Running|Completed" | awk '{print $1}' | \
        xargs -r -I{} bash -c "kubectl delete pod -n $ns {} --force --grace-period=0 2>/dev/null && echo '    Deleted $ns/{}'" || true
done

# ── STEP 7: Apply updated UPF manifests ──────────────────────
echo ""
info "STEP 7: Applying updated UPF manifests..."
kubectl apply -f /home/kube-master/k8s/embb/upf-embb.yaml  2>/dev/null && info "  embb UPF applied"
kubectl apply -f /home/kube-master/k8s/urllc/upf-urllc.yaml 2>/dev/null && info "  urllc UPF applied"
kubectl apply -f /home/kube-master/k8s/mmtc/upf-mmtc.yaml  2>/dev/null && info "  mmtc UPF applied"

# Restart slice apps
for dep_ns in "embb:embb-app" "urllc:urllc-app" "mmtc:mmtc-app" "default-slice:default-app"; do
    ns="${dep_ns%%:*}"; dep="${dep_ns##*:}"
    kubectl rollout restart deployment/"$dep" -n "$ns" 2>/dev/null && info "    Restarted $dep" || true
done

# ── STEP 8: Wait for pods ────────────────────────────────────
echo ""
info "STEP 8: Waiting 90s for all pods to stabilize..."
for i in $(seq 1 9); do
    sleep 10
    RUNNING=$(kubectl get pods -A --no-headers 2>/dev/null | grep -c "Running" || echo 0)
    TOTAL=$(kubectl get pods -A --no-headers 2>/dev/null | wc -l)
    echo "  [${i}0s] Running: $RUNNING/$TOTAL"
done

# ── STEP 9: Fix iptables routing on UPF pod ──────────────────
echo ""
info "STEP 9: Fixing iptables on UPF pod..."
UPF_POD=$(kubectl get pod -n embb -l app=upf-embb --no-headers 2>/dev/null | grep " Running " | awk '{print $1}' | head -1)
if [ -n "$UPF_POD" ]; then
    info "  UPF pod: $UPF_POD"
    # Restore KUBE-SERVICES jump in PREROUTING
    kubectl exec -n embb "$UPF_POD" -- bash -c \
        "iptables -t nat -C PREROUTING -j KUBE-SERVICES 2>/dev/null || iptables -t nat -I PREROUTING -j KUBE-SERVICES && echo '  KUBE-SERVICES: OK'" 2>/dev/null || true

    # DNAT for URLLC app port 1880 (not a kube NodePort)
    URLLC_POD_IP=$(kubectl get pod -n urllc -l app=urllc-app -o jsonpath='{.items[0].status.podIP}' 2>/dev/null)
    if [ -n "$URLLC_POD_IP" ]; then
        kubectl exec -n embb "$UPF_POD" -- bash -c \
            "iptables -t nat -D PREROUTING -p tcp --dport 1880 -j DNAT 2>/dev/null; \
             iptables -t nat -A PREROUTING -i ogstun-urllc -p tcp --dport 1880 -j DNAT --to-destination ${URLLC_POD_IP}:1880 && echo '  URLLC DNAT: OK'" 2>/dev/null || true
    fi
    info "  iptables rules applied"
else
    warn "  No running UPF pod yet — iptables will need fixing after UPF starts"
fi

# ── STEP 10: UERANSIM UE Recovery ────────────────────────────
echo ""
info "STEP 10: Restarting UERANSIM UEs..."
$UERANSIM_SSH "bash -s" << 'UE_SCRIPT'
echo "  Stopping old UEs..."
sudo pkill -f "nr-ue" 2>/dev/null || true
sleep 3

echo "  Cleaning stale uesimtun interfaces..."
for iface in $(ip -o link show | grep uesimtun | awk -F': ' '{print $2}' | awk '{print $1}'); do
    sudo ip link delete "$iface" 2>/dev/null && echo "    Removed $iface"
done
sleep 2

echo "  Starting UEs..."
UEDIR="$HOME/UERANSIM/build"
[ -d "$UEDIR" ] || UEDIR="/home/shinegami/UERANSIM/build"
CFGDIR="$HOME/config"
[ -d "$CFGDIR" ] || CFGDIR="/home/shinegami/config"

cd "$UEDIR"
for cfg in "$CFGDIR"/ue*.yaml; do
    [ -f "$cfg" ] || continue
    name=$(basename "$cfg" .yaml)
    sudo ./nr-ue -c "$cfg" > "/tmp/ue_${name}.log" 2>&1 &
    echo "    Started $name (PID=$!)"
done

echo "  Waiting 20s for PDU establishment..."
sleep 20

echo "  Tunnel interfaces:"
ip addr show | grep "inet 10\.4[567]" | awk '{print "    "$2" on "$NF}'
TCOUNT=$(ip addr show | grep -c "inet 10\.4[567]" 2>/dev/null || echo 0)
echo "  Active tunnels: $TCOUNT"

if [ "$TCOUNT" -gt 0 ]; then
    echo "  ✅ UEs connected — PDU sessions established"
    echo "  Restarting traffic clients..."
    pkill -f "_client.py" 2>/dev/null || true
    sleep 2
    if [ -f "$HOME/mec-clients/run_all.sh" ]; then
        cd "$HOME/mec-clients"
        bash run_all.sh 192.168.49.172 &
        sleep 10
        echo "  Client logs:"
        for f in /tmp/mec-clients/*.log; do
            [ -f "$f" ] && echo "    $(basename $f): $(tail -1 $f 2>/dev/null)"
        done
    fi
else
    echo "  ⚠  No tunnels — PDU sessions not established. Check UPF status."
fi
UE_SCRIPT

# ── FINAL STATUS ─────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  FINAL STATUS — $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
kubectl get nodes -o wide 2>/dev/null
echo ""
kubectl get pods -A 2>/dev/null
echo ""
UNHEALTHY=$(kubectl get pods -A --no-headers 2>/dev/null | grep -cvE " Running | Completed " || echo 0)
if [ "$UNHEALTHY" -eq 0 ]; then
    echo -e "${GREEN}✅ ALL PODS HEALTHY — System fully recovered!${NC}"
else
    warn "$UNHEALTHY pods still unhealthy:"
    kubectl get pods -A --no-headers 2>/dev/null | grep -vE " Running | Completed "
fi
echo ""
echo "Verify UEs: sshpass -p 123 ssh shinegami@192.168.49.139 'ip addr | grep uesimtun'"
echo "Clients:    sshpass -p 123 ssh shinegami@192.168.49.139 'tail /tmp/mec-clients/*.log'"
