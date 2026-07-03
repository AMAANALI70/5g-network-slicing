#!/bin/bash
# fix-upf-routing.sh
# Adds MASQUERADE + FORWARD rules to all UPF pods so TCP traffic
# through the 5G GTP tunnel gets properly NATted to K8s services.
# Also launches all MEC client scripts on UERANSIM VM.
set -e

echo "=========================================="
echo " UPF Routing Fix + MEC Client Launcher"
echo "=========================================="

# --- Step 1: Get UPF pod names ---
EMBB_POD=$(kubectl get pod -n embb -l app=upf-embb --no-headers | grep -v node2 | head -1 | awk '{print $1}')
URLLC_POD=$(kubectl get pod -n urllc -l app=upf-urllc --no-headers | grep -v node2 | head -1 | awk '{print $1}')
MMTC_POD=$(kubectl get pod -n mmtc -l app=upf-mmtc --no-headers | grep -v node2 | head -1 | awk '{print $1}')
echo "eMBB UPF:  $EMBB_POD"
echo "URLLC UPF: $URLLC_POD"
echo "mMTC UPF:  $MMTC_POD"

# --- Step 2: Show current state ---
echo ""
echo "--- Current FORWARD chain (eMBB UPF) ---"
kubectl exec -n embb $EMBB_POD -- iptables -L FORWARD -n 2>&1 | head -8
echo "--- Current POSTROUTING (eMBB UPF) ---"
kubectl exec -n embb $EMBB_POD -- iptables -t nat -L POSTROUTING -n 2>&1 | head -8

# --- Step 3: Apply rules to all 3 UPF pods ---
for ENTRY in "embb $EMBB_POD" "urllc $URLLC_POD" "mmtc $MMTC_POD"; do
  NS=$(echo $ENTRY | awk '{print $1}')
  POD=$(echo $ENTRY | awk '{print $2}')
  echo ""
  echo "=== Applying rules to $NS/$POD ==="

  # Allow forwarding from all 3 ogstun interfaces
  kubectl exec -n $NS $POD -- iptables -C FORWARD -i ogstun-embb  -j ACCEPT 2>/dev/null || \
    kubectl exec -n $NS $POD -- iptables -A FORWARD -i ogstun-embb  -j ACCEPT
  kubectl exec -n $NS $POD -- iptables -C FORWARD -i ogstun-urllc -j ACCEPT 2>/dev/null || \
    kubectl exec -n $NS $POD -- iptables -A FORWARD -i ogstun-urllc -j ACCEPT
  kubectl exec -n $NS $POD -- iptables -C FORWARD -i ogstun-mmtc  -j ACCEPT 2>/dev/null || \
    kubectl exec -n $NS $POD -- iptables -A FORWARD -i ogstun-mmtc  -j ACCEPT

  # MASQUERADE outgoing UE traffic so return path works
  kubectl exec -n $NS $POD -- iptables -t nat -C POSTROUTING -s 10.45.0.0/16 -j MASQUERADE 2>/dev/null || \
    kubectl exec -n $NS $POD -- iptables -t nat -A POSTROUTING -s 10.45.0.0/16 -j MASQUERADE
  kubectl exec -n $NS $POD -- iptables -t nat -C POSTROUTING -s 10.46.0.0/16 -j MASQUERADE 2>/dev/null || \
    kubectl exec -n $NS $POD -- iptables -t nat -A POSTROUTING -s 10.46.0.0/16 -j MASQUERADE
  kubectl exec -n $NS $POD -- iptables -t nat -C POSTROUTING -s 10.47.0.0/16 -j MASQUERADE 2>/dev/null || \
    kubectl exec -n $NS $POD -- iptables -t nat -A POSTROUTING -s 10.47.0.0/16 -j MASQUERADE

  echo "$NS UPF: rules applied ✓"
done

# --- Step 4: Verify DNAT still in place ---
echo ""
echo "--- PREROUTING (DNAT rules) ---"
kubectl exec -n embb $EMBB_POD -- iptables -t nat -L PREROUTING -n 2>&1 | grep DNAT
echo ""
echo "--- POSTROUTING (MASQUERADE rules) ---"
kubectl exec -n embb $EMBB_POD -- iptables -t nat -L POSTROUTING -n 2>&1

# --- Step 5: Quick E2E test ---
echo ""
echo "=========================================="
echo " E2E TCP Test via GTP Tunnel"
echo "=========================================="
echo "Testing eMBB HLS fetch from UERANSIM..."
sshpass -p '123' ssh -o StrictHostKeyChecking=no shinegami@192.168.49.139 "
  IFACE=\$(ip -4 addr | grep 'inet 10\.45\.' | grep uesimtun | awk '{print \$NF}' | head -1)
  echo \"  Interface: \$IFACE\"
  curl --interface \$IFACE --max-time 10 --silent \
    --write-out '  HTTP:%{http_code} size=%{size_download}B time=%{time_total}s\n' \
    http://192.168.49.171:8080/hls/master.m3u8 -o /tmp/master_test.m3u8
  cat /tmp/master_test.m3u8 | head -5
  echo ''
  echo 'Testing URLLC WebSocket...'
  IFACE2=\$(ip -4 addr | grep 'inet 10\.46\.' | grep uesimtun | awk '{print \$NF}' | head -1)
  echo \"  Interface: \$IFACE2\"
  curl --interface \$IFACE2 --max-time 5 --silent \
    --write-out '  HTTP:%{http_code} size=%{size_download}B\n' \
    http://192.168.49.171:1880/ -o /dev/null
  echo ''
  echo 'Testing mMTC MQTT...'
  IFACE3=\$(ip -4 addr | grep 'inet 10\.47\.' | grep uesimtun | awk '{print \$NF}' | head -1)
  echo \"  Interface: \$IFACE3\"
  mosquitto_pub --quiet -h 192.168.49.171 -p 1883 \
    -t sensors/test/fix -m '{\"status\":\"routing_fixed\"}' && echo '  MQTT: OK' || echo '  MQTT: FAIL'
" 2>&1

# --- Step 6: Launch all MEC clients ---
echo ""
echo "=========================================="
echo " Launching MEC Clients on UERANSIM VM"
echo "=========================================="
sshpass -p '123' ssh -o StrictHostKeyChecking=no shinegami@192.168.49.139 "
  cd ~/mec-clients
  bash run_all.sh 192.168.49.171
" 2>&1

echo ""
echo "=========================================="
echo " All done! Monitor with:"
echo "   ssh shinegami@192.168.49.139 'tail -f /tmp/mec-clients/*.log'"
echo "=========================================="
