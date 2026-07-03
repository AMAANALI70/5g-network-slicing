#!/bin/bash
# Fix iptables: update stale 30800 rule to use correct pod IP / ClusterIP
# Run this on kube worker: sudo bash /tmp/fix_30800.sh

OLD_IP="10.244.2.25"
NEW_IP="10.106.200.147"   # ClusterIP of default-app service (stable)

echo "Removing stale rule (${OLD_IP}:80)..."
iptables -t nat -D PREROUTING -p tcp --dport 30800 -j DNAT --to-destination ${OLD_IP}:80 2>/dev/null && echo "Removed old rule" || echo "Old rule not found (OK)"

echo "Adding fresh rule (${NEW_IP}:80)..."
iptables -t nat -I PREROUTING -i ogstun-embb -p tcp --dport 30800 -j DNAT --to-destination ${NEW_IP}:80
echo "Added new rule"

echo "--- Verification ---"
iptables -t nat -L PREROUTING -n | grep 30800
echo "Done."
