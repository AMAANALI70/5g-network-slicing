#!/bin/bash
# Revert script: restores HTB tc hierarchy and iptables DNAT for port 30800
set -e

UPF_POD="upf-embb-849c45b856-ns98k"
DEFAULT_SVC_IP="10.106.200.147"

echo "=== CHANGE 7: Restoring HTB tc hierarchy on ogstun-embb ==="
kubectl exec -n embb "$UPF_POD" -- tc qdisc del dev ogstun-embb root 2>/dev/null || true
kubectl exec -n embb "$UPF_POD" -- tc qdisc add dev ogstun-embb root handle 1: htb default 20
kubectl exec -n embb "$UPF_POD" -- tc class add dev ogstun-embb parent 1: classid 1:1 htb rate 1gbit
kubectl exec -n embb "$UPF_POD" -- tc class add dev ogstun-embb parent 1:1 classid 1:10 htb rate 100mbit ceil 1gbit prio 1
kubectl exec -n embb "$UPF_POD" -- tc class add dev ogstun-embb parent 1:1 classid 1:20 htb rate 20mbit ceil 20mbit prio 2
kubectl exec -n embb "$UPF_POD" -- tc qdisc add dev ogstun-embb parent 1:10 handle 10: fq_codel
kubectl exec -n embb "$UPF_POD" -- tc qdisc add dev ogstun-embb parent 1:20 handle 20: fq_codel
echo "--- Verification: qdiscs ---"
kubectl exec -n embb "$UPF_POD" -- tc qdisc show dev ogstun-embb
echo "--- Verification: classes ---"
kubectl exec -n embb "$UPF_POD" -- tc class show dev ogstun-embb
echo "=== CHANGE 7 DONE ==="

echo ""
echo "=== CHANGE 8: Restoring iptables DNAT for port 30800 on kube worker ==="
# Remove any existing 30800 rules first (avoid duplicates)
ssh kube@192.168.49.171 "sudo iptables -t nat -L PREROUTING -n --line-numbers | grep '30800' | awk '{print \$1}' | sort -rn | xargs -I{} sudo iptables -t nat -D PREROUTING {} 2>/dev/null; echo 'Old 30800 rules cleared'"
# Add the clean rule
ssh kube@192.168.49.171 "sudo iptables -t nat -I PREROUTING -i ogstun-embb -p tcp --dport 30800 -j DNAT --to-destination ${DEFAULT_SVC_IP}:80 && echo 'DNAT ADDED OK'"
# Verify
echo "--- Verification: iptables 30800 rule ---"
ssh kube@192.168.49.171 "sudo iptables -t nat -L PREROUTING -n | grep 30800"
echo "=== CHANGE 8 DONE ==="

echo ""
echo "=== Restarting phase3-orchestrator.py fresh ==="
kill $(pgrep -f phase3-orchestrator.py) 2>/dev/null || true
sleep 2
nohup python3 /home/kube-master/k8s/phase3-orchestrator.py > /tmp/orch_reverted.log 2>&1 &
echo "Orchestrator restarted, PID=$!"
sleep 3
echo "--- Orchestrator metrics check ---"
curl -s http://localhost:9200/metrics | grep -E "(orchestrator_state|loop_count|embb_rate|restore_count)"
echo ""
echo "=== ALL DONE ==="
