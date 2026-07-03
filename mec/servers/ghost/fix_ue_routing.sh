#!/bin/bash
# Fix UE data plane routing on kube worker
# Run as: bash /tmp/fix_ue_routing.sh

echo "=== Current ogstun interface config ==="
ip addr show ogstun-embb
ip addr show ogstun-urllc
ip addr show ogstun-mmtc

echo ""
echo "=== Current route table ==="
ip route show

echo ""
echo "=== UE subnet routes ==="
ip route show | grep -E "10\.4[567]"

echo "=== Fixing ogstun addresses ==="
# Ensure ogstun interfaces have gateway IPs
ip addr show ogstun-embb  | grep "10.45.0.1" || ip addr add 10.45.0.1/24 dev ogstun-embb
ip addr show ogstun-urllc | grep "10.46.0.1" || ip addr add 10.46.0.1/24 dev ogstun-urllc
ip addr show ogstun-mmtc  | grep "10.47.0.1" || ip addr add 10.47.0.1/24 dev ogstun-mmtc

echo "=== Fixing UE subnet routes ==="
ip route replace 10.45.0.0/24 dev ogstun-embb  src 10.45.0.1
ip route replace 10.46.0.0/24 dev ogstun-urllc src 10.46.0.1
ip route replace 10.47.0.0/24 dev ogstun-mmtc  src 10.47.0.1

echo "=== Fixing MASQUERADE for UE traffic ==="
for subnet in "10.45.0.0/24" "10.46.0.0/24" "10.47.0.0/24"; do
    iptables -t nat -C POSTROUTING -s $subnet ! -o lo -j MASQUERADE 2>/dev/null || \
    iptables -t nat -A POSTROUTING -s $subnet ! -o lo -j MASQUERADE
done

echo "=== Enabling IP forwarding ==="
sysctl -w net.ipv4.ip_forward=1 >/dev/null

echo "=== Test routing for UE traffic ==="
ip route get 8.8.8.8 from 10.45.0.2 iif ogstun-embb 2>&1
ip route get 8.8.8.8 from 10.46.0.2 iif ogstun-urllc 2>&1

echo "=== Testing ICMP from ogstun-embb ==="
ping -c 2 -W 2 -I ogstun-embb 8.8.8.8 2>&1

echo "=== Done ==="
ip route show | grep -E "10\.4[567]|default"
