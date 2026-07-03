#!/bin/bash
set -e

# ============================================================
# Unified UPF Entrypoint — creates multiple TUN devices
# for multi-slice operation (eMBB, URLLC, mMTC)
# ============================================================

# Enable IP forwarding
sysctl -w net.ipv4.ip_forward=1

# Parse comma-separated TUN device definitions
# Format: TUN_DEVICES="name:subnet:gateway,name:subnet:gateway,..."
IFS=',' read -ra DEVICES <<< "${TUN_DEVICES}"

for entry in "${DEVICES[@]}"; do
    IFS=':' read -r tun_name subnet gateway <<< "$entry"
    echo "[entrypoint] Creating TUN device: $tun_name  subnet=$subnet  gateway=$gateway"

    # Create TUN device
    ip tuntap add name "$tun_name" mode tun || true
    ip addr add "$gateway" dev "$tun_name" || true
    ip link set "$tun_name" up

    # Add route for the subnet
    subnet_base=$(echo "$subnet" | cut -d/ -f1)
    subnet_mask=$(echo "$subnet" | cut -d/ -f2)
    ip route add "${subnet_base}/${subnet_mask}" dev "$tun_name" || true

    # NAT masquerade for outbound traffic
    iptables -t nat -A POSTROUTING -s "$subnet" ! -o "$tun_name" -j MASQUERADE
done

# Apply tc shaping if TC_RATE is set (applies to first TUN device)
if [ -n "$TC_RATE" ] && [ -n "$TC_DEV" ]; then
    echo "[entrypoint] Applying tc shaping on $TC_DEV: rate=$TC_RATE ceil=${TC_CEIL:-$TC_RATE}"
    tc qdisc add dev "$TC_DEV" root handle 1: htb default 1 || true
    tc class add dev "$TC_DEV" parent 1: classid 1:1 htb \
        rate "$TC_RATE" ceil "${TC_CEIL:-$TC_RATE}" || true
fi

echo "[entrypoint] Starting open5gs-upfd with config: ${UPF_CONFIG}"
echo "[entrypoint] TUN devices: ${TUN_DEVICES}"

exec open5gs-upfd -c "${UPF_CONFIG}"
