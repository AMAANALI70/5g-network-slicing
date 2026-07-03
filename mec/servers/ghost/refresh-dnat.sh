#!/bin/bash
UPF=$(kubectl get pod -n embb -l app=upf-embb --no-headers | awk '{print $1}' | head -1)
NGINX_IP=$(kubectl get pod -n embb -l app=embb-app -o jsonpath='{.items[0].status.podIP}')
NR_IP=$(kubectl get pod -n urllc -l app=urllc-app -o jsonpath='{.items[0].status.podIP}')
MQTT_IP=$(kubectl get pod -n mmtc -l app=mmtc-app -o jsonpath='{.items[0].status.podIP}')

kubectl exec -n embb $UPF -- bash -c "
  iptables -t nat -L PREROUTING --line-numbers -n | grep -E '8080|1880|1883' | awk '{print \$1}' | sort -rn | while read ln; do iptables -t nat -D PREROUTING \$ln; done
  iptables -t nat -A PREROUTING -i ogstun-embb  -p tcp --dport 8080 -j DNAT --to-destination ${NGINX_IP}:8080
  iptables -t nat -A PREROUTING -i ogstun-urllc -p tcp --dport 1880 -j DNAT --to-destination ${NR_IP}:1880
  iptables -t nat -A PREROUTING -i ogstun-mmtc  -p tcp --dport 1883 -j DNAT --to-destination ${MQTT_IP}:1883
  echo DNAT refreshed: nginx=${NGINX_IP} nodered=${NR_IP} mqtt=${MQTT_IP}
"
