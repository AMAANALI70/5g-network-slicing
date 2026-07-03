#!/bin/bash
# fix_flannel.sh — Restore Flannel CNI on kubemaster and kube2
# Run with: sudo bash fix_flannel.sh
set -e

echo "=== Step 1: Load kernel modules on THIS node (kubemaster) ==="
modprobe br_netfilter
modprobe overlay
echo "br_netfilter" >> /etc/modules-load.d/k8s.conf
echo "overlay" >> /etc/modules-load.d/k8s.conf

echo "=== Step 2: Set sysctl ==="
sysctl -w net.bridge.bridge-nf-call-iptables=1
sysctl -w net.bridge.bridge-nf-call-ip6tables=1
sysctl -w net.ipv4.ip_forward=1

# Persist
cat > /etc/sysctl.d/k8s-bridge.conf << 'EOF'
net.bridge.bridge-nf-call-iptables=1
net.bridge.bridge-nf-call-ip6tables=1
net.ipv4.ip_forward=1
EOF

echo "=== Step 3: Verify module loaded ==="
lsmod | grep br_netfilter
cat /proc/sys/net/bridge/bridge-nf-call-iptables

echo "=== Step 4: Fix kube2 (192.168.49.181) via SSH ==="
ssh -i /home/kube-master/.ssh/id_rsa -o StrictHostKeyChecking=no kube@192.168.49.181 "
    sudo modprobe br_netfilter
    sudo modprobe overlay
    sudo sysctl -w net.bridge.bridge-nf-call-iptables=1
    sudo sysctl -w net.bridge.bridge-nf-call-ip6tables=1
    sudo sysctl -w net.ipv4.ip_forward=1
    echo br_netfilter | sudo tee -a /etc/modules-load.d/k8s.conf
    lsmod | grep br_netfilter && echo 'kube2: OK'
" 2>/dev/null || echo "kube2 SSH failed — fix manually if needed"

echo ""
echo "Done. Flannel will now be restarted by Kubernetes automatically."
echo "Run: kubectl get pods -n kube-flannel -w"
