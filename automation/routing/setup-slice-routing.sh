#!/bin/bash
# =============================================================
# Per-Slice Routing Script for kube worker (192.168.49.171)
# Routes UE subnet traffic to slice application pods via iptables DNAT
# =============================================================
# Run this on the kube worker node (where UPFs and apps are co-located)
#
# Traffic flow:
#   UE (10.45.x.x) -> ogstun-embb -> iptables DNAT -> nginx pod (ClusterIP:80)
#   UE (10.46.x.x) -> ogstun-urllc -> iptables DNAT -> iperf3 pod (ClusterIP:5201)
#   UE (10.47.x.x) -> ogstun-mmtc -> iptables DNAT -> mosquitto pod (ClusterIP:1883)

set -e

# Get pod ClusterIPs for each app service
EMBB_SVC_IP=$(kubectl get svc embb-app -n embb -o jsonpath='{.spec.clusterIP}' 2>/dev/null)
URLLC_SVC_IP=$(kubectl get svc urllc-app -n urllc -o jsonpath='{.spec.clusterIP}' 2>/dev/null)
MMTC_SVC_IP=$(kubectl get svc mmtc-app -n mmtc -o jsonpath='{.spec.clusterIP}' 2>/dev/null)

echo "=== Slice App Service IPs ==="
echo "eMBB  (nginx):     $EMBB_SVC_IP:80"
echo "URLLC (iperf3):    $URLLC_SVC_IP:5201"
echo "mMTC  (mosquitto): $MMTC_SVC_IP:1883"

# Flush old slice routing rules (idempotent)
iptables -t nat -D PREROUTING -i ogstun-embb -p tcp --dport 80 -j DNAT --to-destination ${EMBB_SVC_IP}:80 2>/dev/null || true
iptables -t nat -D PREROUTING -i ogstun-urllc -p tcp --dport 5201 -j DNAT --to-destination ${URLLC_SVC_IP}:5201 2>/dev/null || true
iptables -t nat -D PREROUTING -i ogstun-mmtc -p tcp --dport 1883 -j DNAT --to-destination ${MMTC_SVC_IP}:1883 2>/dev/null || true

# Add DNAT rules: UE traffic on ogstun → app service ClusterIP
echo "=== Adding iptables DNAT rules ==="

# eMBB: HTTP traffic on ogstun-embb → nginx ClusterIP
iptables -t nat -A PREROUTING -i ogstun-embb -p tcp --dport 80 -j DNAT --to-destination ${EMBB_SVC_IP}:80
echo "  eMBB: ogstun-embb :80 → ${EMBB_SVC_IP}:80"

# URLLC: iperf3 traffic on ogstun-urllc → iperf3 ClusterIP
iptables -t nat -A PREROUTING -i ogstun-urllc -p tcp --dport 5201 -j DNAT --to-destination ${URLLC_SVC_IP}:5201
echo "  URLLC: ogstun-urllc :5201 → ${URLLC_SVC_IP}:5201"

# mMTC: MQTT traffic on ogstun-mmtc → mosquitto ClusterIP
iptables -t nat -A PREROUTING -i ogstun-mmtc -p tcp --dport 1883 -j DNAT --to-destination ${MMTC_SVC_IP}:1883
echo "  mMTC: ogstun-mmtc :1883 → ${MMTC_SVC_IP}:1883"

# Enable masquerade so return traffic goes back through UPF
iptables -t nat -A POSTROUTING -s 10.45.0.0/16 -j MASQUERADE 2>/dev/null || true
iptables -t nat -A POSTROUTING -s 10.46.0.0/16 -j MASQUERADE 2>/dev/null || true
iptables -t nat -A POSTROUTING -s 10.47.0.0/16 -j MASQUERADE 2>/dev/null || true

echo ""
echo "=== Per-slice routing configured ==="
echo "UEs can now reach apps via their slice TUN interface:"
echo "  eMBB UE:  curl --interface uesimtun0 http://<any-ip>:80  → nginx"
echo "  URLLC UE: iperf3 -c <any-ip> -p 5201 --bind 10.46.x.x  → iperf3"
echo "  mMTC UE:  mosquitto_pub -h <any-ip> -p 1883             → mosquitto"
