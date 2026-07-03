#!/bin/bash
# fix-pod-ip-dnat.sh
# DNAT from ogstun-* to actual Pod IPs (bypasses kube-proxy ClusterIP/NodePort limitations)
# Must run on master — uses kubectl exec into UPF pod (hostNetwork=true = worker iptables)
set -e

echo "=== Getting current Pod IPs ==="
NGINX_IP=$(kubectl get pod -n embb -l app=embb-app -o jsonpath='{.items[0].status.podIP}')
NR_IP=$(kubectl get pod -n urllc -l app=urllc-app -o jsonpath='{.items[0].status.podIP}')
MQTT_IP=$(kubectl get pod -n mmtc -l app=mmtc-app -o jsonpath='{.items[0].status.podIP}')
echo "  nginx-HLS  pod IP: $NGINX_IP:8080"
echo "  node-red   pod IP: $NR_IP:1880"
echo "  mosquitto  pod IP: $MQTT_IP:1883"

UPF=$(kubectl get pod -n embb -l app=upf-embb --no-headers | grep -v node2 | awk '{print $1}')
echo "  UPF pod (hostNetwork): $UPF"

echo ""
echo "=== Removing old broken DNAT rules (ClusterIP targets) ==="
kubectl exec -n embb $UPF -- bash -c "
  for port in 8080 1880 1883 80 5201; do
    while iptables -t nat -D PREROUTING -p tcp --dport \$port -j DNAT 2>/dev/null; do
      echo '  removed DNAT port '\$port; done
    while iptables -t nat -D PREROUTING -i ogstun-embb  -p tcp --dport \$port -j DNAT 2>/dev/null; do true; done
    while iptables -t nat -D PREROUTING -i ogstun-urllc -p tcp --dport \$port -j DNAT 2>/dev/null; do true; done
    while iptables -t nat -D PREROUTING -i ogstun-mmtc  -p tcp --dport \$port -j DNAT 2>/dev/null; do true; done
  done
  echo '  done.'
"

echo ""
echo "=== Adding correct Pod-IP DNAT rules on worker ==="
kubectl exec -n embb $UPF -- bash -c "
  iptables -t nat -A PREROUTING -i ogstun-embb  -p tcp --dport 8080 -j DNAT --to-destination ${NGINX_IP}:8080
  iptables -t nat -A PREROUTING -i ogstun-urllc -p tcp --dport 1880 -j DNAT --to-destination ${NR_IP}:1880
  iptables -t nat -A PREROUTING -i ogstun-mmtc  -p tcp --dport 1883 -j DNAT --to-destination ${MQTT_IP}:1883
  echo '  eMBB  ogstun-embb:8080  → ${NGINX_IP}:8080'
  echo '  URLLC ogstun-urllc:1880 → ${NR_IP}:1880'
  echo '  mMTC  ogstun-mmtc:1883  → ${MQTT_IP}:1883'
  iptables -t nat -L PREROUTING -n | grep DNAT
"

echo ""
echo "=== E2E Test via GTP tunnel ==="
sshpass -p '123' ssh -o StrictHostKeyChecking=no shinegami@192.168.49.139 "
  E=\$(ip -4 addr | grep 'inet 10\.45\.' | grep uesimtun | awk '{print \$NF}' | head -1)
  U=\$(ip -4 addr | grep 'inet 10\.46\.' | grep uesimtun | awk '{print \$NF}' | head -1)
  M=\$(ip -4 addr | grep 'inet 10\.47\.' | grep uesimtun | awk '{print \$NF}' | head -1)
  echo 'eMBB  ('\$E') → :8080 HLS'
  curl --interface \$E --max-time 8 -s --write-out 'HTTP:%{http_code} size=%{size_download}B\n' \
    http://192.168.49.171:8080/hls/master.m3u8 -o /tmp/hls.m3u8
  head -4 /tmp/hls.m3u8 2>/dev/null
  echo 'URLLC ('\$U') → :1880 Node-RED'
  curl --interface \$U --max-time 8 -s --write-out 'HTTP:%{http_code} size=%{size_download}B\n' \
    http://192.168.49.171:1880/ -o /dev/null
  echo 'mMTC  ('\$M') → :1883 Mosquitto'
  python3 -c \"
import socket, time
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b'\$M\x00')
s.settimeout(5)
try:
  s.connect(('192.168.49.171', 1883))
  data = s.recv(10)
  print('MQTT TCP connect: OK, got', len(data), 'bytes')
except Exception as e:
  print('MQTT TCP connect: FAIL -', e)
finally:
  s.close()
\"
" 2>&1

echo ""
echo "=== Updating and relaunching clients (ports 8080/1880/1883) ==="
# Upload fixed clients
for f in embb_client.py urllc_client.py mmtc_client.py run_all.sh; do
  sshpass -p '123' scp -o StrictHostKeyChecking=no \
    /home/kube-master/k8s/ue-clients/$f shinegami@192.168.49.139:~/mec-clients/$f
done

sshpass -p '123' ssh -o StrictHostKeyChecking=no shinegami@192.168.49.139 "
  pkill -f _client.py 2>/dev/null; sleep 1
  mkdir -p /tmp/mec-clients
  cd ~/mec-clients && bash run_all.sh 192.168.49.171
" 2>&1

echo ""
echo "=== Monitor logs: ==="
echo "  ssh shinegami@192.168.49.139 'tail -f /tmp/mec-clients/*.log'"
