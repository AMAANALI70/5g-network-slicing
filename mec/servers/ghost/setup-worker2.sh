#!/bin/bash
# ============================================================
# Worker Node 2 Setup Script for Kubernetes v1.29
# Run this on kube2@192.168.49.181 as a regular user (uses sudo)
# ============================================================
set -e

echo "============================================"
echo "  Worker Node 2 Setup — Kubernetes v1.29"
echo "============================================"

# ── Step 2: Update system ────────────────────────────────────
echo ""
echo "[Step 2/8] Updating system packages..."
sudo apt update -y
sudo apt upgrade -y

# ── Step 3: Disable swap ─────────────────────────────────────
echo ""
echo "[Step 3/8] Disabling swap..."
sudo swapoff -a
sudo sed -i '/ swap / s/^/#/' /etc/fstab
echo "  Swap disabled ✓"

# ── Step 4: Install containerd ────────────────────────────────
echo ""
echo "[Step 4/8] Installing containerd..."
sudo apt install -y containerd
sudo mkdir -p /etc/containerd
sudo containerd config default | sudo tee /etc/containerd/config.toml > /dev/null
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
sudo systemctl restart containerd
sudo systemctl enable containerd
echo "  containerd installed with SystemdCgroup ✓"

# ── Step 5: Enable networking ────────────────────────────────
echo ""
echo "[Step 5/8] Enabling Kubernetes networking prerequisites..."
sudo modprobe br_netfilter
sudo modprobe overlay

echo 1 | sudo tee /proc/sys/net/ipv4/ip_forward > /dev/null
echo 1 | sudo tee /proc/sys/net/bridge/bridge-nf-call-iptables > /dev/null

sudo tee /etc/modules-load.d/k8s.conf > /dev/null <<EOF
br_netfilter
overlay
EOF

sudo tee /etc/sysctl.d/k8s.conf > /dev/null <<EOF
net.ipv4.ip_forward=1
net.bridge.bridge-nf-call-iptables=1
EOF

sudo sysctl --system > /dev/null
echo "  br_netfilter + ip_forward enabled ✓"

# ── Step 6: Install Kubernetes packages ───────────────────────
echo ""
echo "[Step 6/8] Installing kubeadm, kubelet, kubectl (v1.29)..."
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.29/deb/Release.key | \
  sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg 2>/dev/null

echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.29/deb/ /' | \
  sudo tee /etc/apt/sources.list.d/kubernetes.list > /dev/null

sudo apt update -y
sudo apt install -y kubeadm kubelet kubectl
sudo apt-mark hold kubelet kubeadm kubectl
echo "  kubeadm, kubelet, kubectl installed ✓"

# ── Step 8: Configure private registry ────────────────────────
echo ""
echo "[Step 7/8] Configuring private registry (192.168.49.174:5000)..."
sudo mkdir -p /etc/containerd/certs.d/192.168.49.174:5000

sudo tee /etc/containerd/certs.d/192.168.49.174:5000/hosts.toml > /dev/null <<EOF
server = "http://192.168.49.174:5000"

[host."http://192.168.49.174:5000"]
  capabilities = ["pull", "resolve"]
  skip_verify = true
EOF

sudo systemctl restart containerd
echo "  Private registry configured ✓"

# ── SSH key setup ─────────────────────────────────────────────
echo ""
echo "[Step 8/8] Setting up SSH key for master node..."
mkdir -p ~/.ssh && chmod 700 ~/.ssh
MASTER_KEY="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQCrvcVrZ80Xgf0bBCoh95RWuHPJ8kCaqs4c41ftBRZHVwito512mGal7e325aSeZ+GENvBGcxUzDrEPs1iJTNEjs3OsBl2pYp2tf3WVHTzIXwW03mRv/tvSXpPB61y233TF1DvrldXVvWWyj8EIuw/oAwXoA3EiwqXx1yPDJW3NVDBvE2GB2OtegQRcSFavjx0aKyQ1NGw7WrEZpzFuyOKCJ6/cd8nGnGefRB+xOqeJCt8Slj/Y5OxQjay/IAGHUBprQ+c/CmLalCEpt249tufgQaJ3BGP8C2fQqVxDhzyD/8w1R3CfSBAuknuG+gJ2jCJZ2OYD08VidqoZl3wWAJy26WXei0EEosz8olTXG6mxLM9D2KC6wdnQBC0dH5oJ01bdIl5vKUuWTTrtpvP7c1BNkW9Pjt1sL36VhfiHJCQ5RZXH2Pbp6Ub8U8mmrEFW2zBWadYvy6hN/E/ybpUsANTN1X/8sFmOm5qM03cNbq9vOnXOlW7ilLU5uP9QaIXQaqAi4aFiVgyPdO4H1908wNH8v3/3n2q4xS/26USR/mh3j3kC+KUw4gqBbluZkb9o2Lb+8MS/MhZ21Gsj8fVpwbnAMiOBkSjRBY9IxqzzINRof8xSwZeMcuRqU/o7ukf14pzOJ+atvAk4dEnxrX1AQjMpGU3GbPgV3P8gvE1w8HpY4w== kube-master@kubemaster"
grep -qF "$MASTER_KEY" ~/.ssh/authorized_keys 2>/dev/null || echo "$MASTER_KEY" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
echo "  SSH key configured ✓"

# ── Done ──────────────────────────────────────────────────────
echo ""
echo "============================================"
echo "  SETUP COMPLETE!"
echo "============================================"
echo ""
echo "Next step: Generate join command on master node (192.168.49.174):"
echo ""
echo "  kubeadm token create --print-join-command"
echo ""
echo "Then paste the join command here with sudo, adding:"
echo "  --cri-socket unix:///var/run/containerd/containerd.sock"
echo ""
