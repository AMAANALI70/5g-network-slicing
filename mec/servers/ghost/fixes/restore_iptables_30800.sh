#!/bin/bash
# Script to restore iptables DNAT for default-slice port 30800
# ClusterIP of default-app service: 10.106.200.147

# Remove any stale 30800 rules (avoids duplicates)
iptables -t nat -L PREROUTING -n --line-numbers 2>/dev/null | grep '30800' | awk '{print $1}' | sort -rn | while read n; do
  iptables -t nat -D PREROUTING "$n" 2>/dev/null
done
echo "Old 30800 rules cleared."

# Add the clean interface-specific rule
iptables -t nat -I PREROUTING -i ogstun-embb -p tcp --dport 30800 -j DNAT --to-destination 10.106.200.147:80
echo "DNAT rule added."

# Verify
echo "--- Current 30800 rules ---"
iptables -t nat -L PREROUTING -n | grep -E "(30800|dpt:30800)" || echo "(none found)"
echo "Done."
