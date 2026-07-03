# Section 5 — UPF Architecture

## Deployment Model

All UPFs run as Kubernetes Deployments with `hostNetwork: true` on the `kube` worker.
Image: `192.168.49.174:5000/open5gs-upf:local` (custom-built Open5GS UPF, stored in local registry on kubemaster).

Because `hostNetwork: true`, all 3 UPF pods share the same network namespace as the host node.
They are differentiated by their PFCP peer (SMF) and the ogstun interface they create.

---

## UPF Table

| Slice | Pod | Namespace | Node | N3 Bind IP | N6 Interface | N6 IP | Connected App |
|---|---|---|---|---|---|---|---|
| eMBB | upf-embb-5d448f6f78-nr6s5 | embb | kube (192.168.49.173) | 192.168.49.171 | ogstun-embb | 10.45.0.1/24 | nginx (embb-app:30880) |
| URLLC | upf-urllc-5bc8dfb7f6-98kjn | urllc | kube (192.168.49.173) | 192.168.49.172 | ogstun-urllc | 10.46.0.1/24 | Node-RED (urllc-app:30180) |
| mMTC | upf-mmtc-8549b975ff-s65rl | mmtc | kube (192.168.49.173) | 192.168.49.173 | ogstun-mmtc | 10.47.0.1/24 | Mosquitto (mmtc-app:30883) |

---

## Interface Details (from `kubectl exec -- ip addr`)

All 3 UPF pods show identical interfaces (shared host network namespace):
```
192.168.49.171/24  ens33 (primary)
192.168.49.172/24  ens33 (secondary)
192.168.49.173/24  ens33 (secondary — K8s node IP)
192.168.49.187/24  ens33 (secondary, DHCP)
10.45.0.1/24       ogstun-embb  ← eMBB UPF N6
10.46.0.1/24       ogstun-urllc ← URLLC UPF N6
10.47.0.1/24       ogstun-mmtc  ← mMTC UPF N6
10.244.2.1/24      cni0 (Flannel bridge)
10.244.2.0/32      flannel.1 (VXLAN)
```

---

## Data Plane Path Through UPF

```
UE transmits packet:
  Source: 10.45.0.2 (UE IP)
  Destination: 192.168.49.171:30880 (nginx NodePort)

1. UE sends IP packet via uesimtun0
2. UERANSIM encapsulates in GTP-U: src=192.168.49.139, dst=192.168.49.171
3. GTP-U arrives at upf-embb N3 interface (192.168.49.171)
4. UPF decapsulates, applies PFCP forwarding rules
5. Decapsulated packet exits via ogstun-embb (10.45.0.1)
6. Kernel routes to nginx pod via NodePort DNAT (iptables/kube-proxy)
7. nginx processes HTTP request and responds
8. Response follows reverse path through UPF back to UE
```

---

## tc Shaping Enforcement Point

The orchestrator applies `tc qdisc` rules on `ogstun-embb` — the N6 egress interface of the eMBB UPF. This is the correct enforcement point because:
- All eMBB downlink traffic exits through ogstun-embb
- Shaping here affects all eMBB UEs simultaneously
- URLLC and mMTC traffic is on separate interfaces and is unaffected

```bash
# Throttle (applied by orchestrator when URLLC RTT > 15ms)
tc qdisc del dev ogstun-embb root 2>/dev/null
tc qdisc add dev ogstun-embb root tbf rate 50mbit burst 32kbit latency 400ms

# Restore (when URLLC RTT recovers to < 15ms for N consecutive loops)
tc qdisc del dev ogstun-embb root
```

---

## Pending / Non-Active UPF Deployments

| Deployment | Status | Reason |
|---|---|---|
| upf-embb-node2 | Pending (0/1) | kube2 SchedulingDisabled |
| upf-urllc-node2 | Pending (0/1) | kube2 SchedulingDisabled |
| upf-mmtc-node2 | 0 replicas | Not started |
| upf-node1, upf-node2 (embb ns) | 0 replicas | Legacy, not active |

These were designed for a multi-node deployment where each worker hosts UPFs.
Currently only node1 (kube) UPFs are active.
