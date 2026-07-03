#!/bin/bash
set -e

# --- Environment variables (set from K8s manifests) ---
TUN_DEV=${TUN_DEV:-ogstun}
UE_SUBNET=${UE_SUBNET:-10.45.0.0/24}
UE_GATEWAY=${UE_GATEWAY:-10.45.0.1/24}
UPF_CONFIG=${UPF_CONFIG:-/etc/open5gs/upf.yaml}

# Slice-specific tc shaping (env vars from deployment)
TC_RATE=${TC_RATE:-}
TC_CEIL=${TC_CEIL:-}
TC_LATENCY=${TC_LATENCY:-}

# --- 1. Create TUN device ---
echo "[entrypoint] Creating TUN device: $TUN_DEV"
if ! ip link show "$TUN_DEV" &>/dev/null; then
    ip tuntap add name "$TUN_DEV" mode tun
fi
ip addr add "$UE_GATEWAY" dev "$TUN_DEV" 2>/dev/null || true
ip link set "$TUN_DEV" up

# --- 2. Enable IP forwarding + NAT ---
echo "[entrypoint] Setting up IP forwarding and NAT"
sysctl -w net.ipv4.ip_forward=1
iptables -t nat -C POSTROUTING -s "$UE_SUBNET" ! -o "$TUN_DEV" -j MASQUERADE 2>/dev/null \
    || iptables -t nat -A POSTROUTING -s "$UE_SUBNET" ! -o "$TUN_DEV" -j MASQUERADE

# --- 3. Apply tc shaping (if configured) ---
if [ -n "$TC_RATE" ]; then
    echo "[entrypoint] Applying tc shaping: rate=$TC_RATE ceil=${TC_CEIL:-$TC_RATE}"
    tc qdisc del dev "$TUN_DEV" root 2>/dev/null || true
    tc qdisc add dev "$TUN_DEV" root handle 1: htb default 1
    tc class add dev "$TUN_DEV" parent 1: classid 1:1 htb \
        rate "$TC_RATE" ceil "${TC_CEIL:-$TC_RATE}"

    if [ -n "$TC_LATENCY" ]; then
        echo "[entrypoint] Adding netem: latency=$TC_LATENCY"
        tc qdisc add dev "$TUN_DEV" parent 1:1 handle 10: netem \
            delay "$TC_LATENCY"
    fi
fi

# --- 4. Launch UPF ---
echo "[entrypoint] Starting open5gs-upfd with config: $UPF_CONFIG"
echo "[entrypoint] TUN=$TUN_DEV SUBNET=$UE_SUBNET GATEWAY=$UE_GATEWAY"
exec open5gs-upfd -c "$UPF_CONFIG"
