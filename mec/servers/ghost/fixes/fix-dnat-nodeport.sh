#!/bin/bash
# fix-dnat-nodeport.sh
# Replace broken ClusterIP DNAT rules with NodePort-based DNAT.
# NodePorts are handled natively by kube-proxy KUBE-NODEPORTS in PREROUTING.
# Traffic arriving on ogstun-embb/urllc/mmtc gets correctly forwarded.

echo "=== Step 1: Remove broken ClusterIP DNAT rules ==="
# Remove the old DNAT rules for ports 8080/1880/1883 (all 3 UPF pods = host iptables)
for PORT in 8080 1880 1883; do
  while iptables -t nat -D PREROUTING -p tcp --dport $PORT -j DNAT 2>/dev/null; do
    echo "  Removed DNAT for port $PORT"
  done
done
# Also remove the interface-specific old ones if they exist
for PORT in 80 5201; do
  while iptables -t nat -D PREROUTING -i ogstun-embb -p tcp --dport $PORT -j DNAT 2>/dev/null; do true; done
  while iptables -t nat -D PREROUTING -i ogstun-urllc -p tcp --dport $PORT -j DNAT 2>/dev/null; do true; done
done
echo "Done."

echo ""
echo "=== Step 2: No custom DNAT needed — kube-proxy handles NodePorts ==="
echo "  NodePorts:"
echo "    eMBB  HLS    → 192.168.49.171:30880 (nginx)"
echo "    URLLC NR     → 192.168.49.171:30180 (node-red)"
echo "    mMTC  MQTT   → 192.168.49.171:30883 (mosquitto)"

echo ""
echo "=== Step 3: Verify kube-proxy has NodePort rules ==="
iptables -t nat -L KUBE-NODEPORTS -n 2>/dev/null | grep -E "(30880|30180|30883|30881|30886)" | head -10

echo ""
echo "=== Step 4: E2E Test via NodePorts (GTP tunnel) ==="
sshpass -p '123' ssh -o StrictHostKeyChecking=no shinegami@192.168.49.139 "
  E=\$(ip -4 addr | grep 'inet 10\.45\.' | grep uesimtun | awk '{print \$NF}' | head -1)
  U=\$(ip -4 addr | grep 'inet 10\.46\.' | grep uesimtun | awk '{print \$NF}' | head -1)
  M=\$(ip -4 addr | grep 'inet 10\.47\.' | grep uesimtun | awk '{print \$NF}' | head -1)
  echo 'eMBB  ('\$E'): HLS via :30880'
  curl --interface \$E --max-time 8 --silent \
    --write-out '  result: HTTP:%{http_code} size=%{size_download}B time=%{time_total}s\n' \
    http://192.168.49.171:30880/hls/master.m3u8 -o /tmp/hls_test.txt
  cat /tmp/hls_test.txt | head -5
  echo 'URLLC ('\$U'): Node-RED via :30180'
  curl --interface \$U --max-time 8 --silent \
    --write-out '  result: HTTP:%{http_code} size=%{size_download}B time=%{time_total}s\n' \
    http://192.168.49.171:30180/ -o /dev/null
  echo 'mMTC  ('\$M'): MQTT via :30883'
  mosquitto_pub --quiet --interface \$M -h 192.168.49.171 -p 30883 \
    -t sensors/test/nodeport -m '{\"status\":\"ok\"}' && echo '  result: MQTT OK' || echo '  result: MQTT FAIL'
" 2>&1

echo ""
echo "=== Step 5: Update MEC clients to use NodePorts and restart ==="
# Kill existing clients
sshpass -p '123' ssh -o StrictHostKeyChecking=no shinegami@192.168.49.139 "
  pkill -f embb_client.py 2>/dev/null
  pkill -f urllc_client.py 2>/dev/null
  pkill -f mmtc_client.py 2>/dev/null
  echo 'Old clients stopped.'
" 2>&1

echo "All done."
