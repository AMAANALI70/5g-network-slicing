#!/bin/bash
# Full diagnostic script for eMBB/URLLC no-data issue
# Run as: bash /home/kube-master/k8s/diagnose.sh 2>&1 | tee /tmp/diag_out.txt

UERANSIM_IP="192.168.49.139"
UERANSIM_USER="shinegami"
UERANSIM_PASS="123"
KUBE_WORKER="192.168.49.171"
PROM_URL="http://192.168.49.174:30090"

echo "============================================================"
echo "SECTION 1: Orchestrator process & metrics"
echo "============================================================"
echo "-- Running orchestrator processes --"
ps aux | grep phase3-orchestrator | grep -v grep || echo "NO ORCHESTRATOR RUNNING!"
echo ""
echo "-- Orchestrator log (last 20 lines) --"
tail -20 /tmp/orchestrator.log 2>/dev/null || echo "No /tmp/orchestrator.log found"
echo ""
echo "-- Orchestrator metrics endpoint --"
python3 -c "
import urllib.request, sys
try:
    r = urllib.request.urlopen('http://127.0.0.1:9200/metrics', timeout=5)
    print(r.read().decode())
except Exception as e:
    print('METRICS PORT UNREACHABLE:', e)
"

echo ""
echo "============================================================"
echo "SECTION 2: UERANSIM VM — clients, interfaces, logs"
echo "============================================================"
sshpass -p "$UERANSIM_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 \
  "${UERANSIM_USER}@${UERANSIM_IP}" "
echo '-- PROCESSES --'
ps aux | grep -E '(nr-ue|nr-gnb|embb_client|urllc_client|mmtc_client|run_all)' | grep -v grep || echo 'NO CLIENT PROCESSES!'
echo ''
echo '-- UESIMTUN INTERFACES --'
ip addr show | grep -E '(uesimtun|10\.4[5-7]\.)' || echo 'NO UESIMTUN INTERFACES!'
echo ''
echo '-- LOG FILES IN /tmp/mec-clients --'
ls /tmp/mec-clients/ 2>/dev/null || echo 'NO /tmp/mec-clients/ directory!'
echo ''
echo '-- LOG TAILS --'
for f in /tmp/mec-clients/*.log; do
    echo \"=== \$f ===\"
    tail -3 \"\$f\" 2>/dev/null || echo '(empty)'
done
" 2>&1 || echo "SSH TO UERANSIM FAILED!"

echo ""
echo "============================================================"
echo "SECTION 3: Kubernetes pods"
echo "============================================================"
kubectl get pods -n embb --no-headers 2>&1
echo "---"
kubectl get pods -n urllc --no-headers 2>&1
echo "---"
kubectl get pods -n mmtc --no-headers 2>&1

echo ""
echo "============================================================"
echo "SECTION 4: UPF embb pod — PFCP, tun interface, tc"
echo "============================================================"
UPF_POD=$(kubectl get pod -n embb -l app=upf-embb --no-headers 2>/dev/null | awk '{print $1}' | head -1)
echo "UPF pod: $UPF_POD"
if [ -n "$UPF_POD" ]; then
    echo "-- UPF logs (PFCP/GTP) --"
    kubectl logs -n embb "$UPF_POD" --tail=30 2>&1 | grep -E "(PFCP|GTP|associated|error|ERROR|WARN|FAT)" | tail -15 || echo "No matching logs"
    echo ""
    echo "-- ogstun-embb interface --"
    kubectl exec -n embb "$UPF_POD" -- ip addr show ogstun-embb 2>&1
    echo ""
    echo "-- ogstun-urllc interface --"
    kubectl exec -n embb "$UPF_POD" -- ip addr show ogstun-urllc 2>&1 || echo "urllc tun not in embb pod"
    echo ""
    echo "-- tc qdisc on ogstun-embb --"
    kubectl exec -n embb "$UPF_POD" -- tc qdisc show dev ogstun-embb 2>&1
    echo "-- tc class on ogstun-embb --"
    kubectl exec -n embb "$UPF_POD" -- tc class show dev ogstun-embb 2>&1
    echo ""
    echo "-- /proc/net/dev (TUN counters) --"
    kubectl exec -n embb "$UPF_POD" -- cat /proc/net/dev 2>&1 | grep -E "(ogstun|uesimtun)"
    echo ""
    echo "-- iptables PREROUTING --"
    kubectl exec -n embb "$UPF_POD" -- iptables -t nat -L PREROUTING -n 2>&1
fi

echo ""
echo "============================================================"
echo "SECTION 5: URLLC UPF pod"
echo "============================================================"
URLLC_POD=$(kubectl get pod -n urllc -l app=upf-urllc --no-headers 2>/dev/null | awk '{print $1}' | head -1)
echo "URLLC UPF pod: $URLLC_POD"
if [ -n "$URLLC_POD" ]; then
    echo "-- URLLC UPF logs (PFCP) --"
    kubectl logs -n urllc "$URLLC_POD" --tail=20 2>&1 | grep -E "(PFCP|GTP|associated|error|ERROR)" | tail -10
    echo ""
    echo "-- ogstun-urllc interface --"
    kubectl exec -n urllc "$URLLC_POD" -- ip addr show ogstun-urllc 2>&1
    echo ""
    echo "-- URLLC tun counters --"
    kubectl exec -n urllc "$URLLC_POD" -- cat /proc/net/dev 2>&1 | grep ogstun
fi

echo ""
echo "============================================================"
echo "SECTION 6: SSH check — orchestrator → UERANSIM"
echo "============================================================"
echo "Testing SSH from kubemaster to UERANSIM..."
sshpass -p "$UERANSIM_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
  "${UERANSIM_USER}@${UERANSIM_IP}" "echo SSH_OK; ls /tmp/mec-clients/ 2>/dev/null | head -5" 2>&1 || echo "SSH FAILED"

echo ""
echo "============================================================"
echo "SECTION 7: Prometheus — is it up and seeing data?"
echo "============================================================"
python3 -c "
import urllib.request, json
base = 'http://192.168.49.174:30090/api/v1/query'
metrics = [
    'orchestrator_urllc_rtt_ms',
    'orchestrator_embb_mbps',
    'orchestrator_loop_count',
    'rate(tun_tx_bytes{slice=\"embb\"}[30s])',
    'rate(tun_tx_bytes{slice=\"urllc\"}[30s])',
]
for m in metrics:
    try:
        url = base + '?query=' + urllib.parse.quote(m)
        import urllib.parse
        url = base + '?query=' + urllib.parse.quote(m)
        r = urllib.request.urlopen(url, timeout=5)
        data = json.loads(r.read())
        result = data.get('data', {}).get('result', [])
        val = result[0]['value'][1] if result else 'NO DATA'
        print(f'{m[:50]}: {val}')
    except Exception as e:
        print(f'{m[:50]}: ERROR - {e}')
" 2>&1

echo ""
echo "============================================================"
echo "DIAGNOSTIC COMPLETE"
echo "============================================================"
