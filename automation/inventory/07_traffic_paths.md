# Section 7 — End-to-End Traffic Paths

## eMBB Traffic Path (HTTP Video Streaming)

```
embb_client.py (UERANSIM VM, 192.168.49.139)
  │  binds socket to uesimtun0 (10.45.0.2)
  │  HTTP GET → 192.168.49.171:30880
  ▼
uesimtun0 (TUN device, kernel routes via UERANSIM)
  │  packet: src=10.45.0.2, dst=192.168.49.171:30880
  ▼
UERANSIM gNB (simulated radio, same VM)
  │  encapsulates in GTP-U
  │  outer: src=192.168.49.139, dst=192.168.49.171 (upf-embb N3)
  ▼
upf-embb pod (kube node, hostNetwork)
  │  GTP-U decapsulation via N3 (192.168.49.171)
  │  PFCP forwarding rules applied
  │  inner packet: src=10.45.0.2, dst=192.168.49.171:30880
  ▼
ogstun-embb (10.45.0.1) — N6 interface
  │  [tc qdisc tbf on ogstun-embb — bandwidth shaping here]
  ▼
kube-proxy / iptables DNAT
  │  NodePort 30880 → ClusterIP → embb-app pod (10.244.2.53:8080)
  ▼
nginx:alpine (embb-app pod)
  │  serves HTTP content
  ▼
Response follows reverse path → UE

Interfaces crossed: uesimtun0 → gNB → GTP-U → ogstun-embb → cni0 → veth → nginx pod
```

---

## URLLC Traffic Path (RTT Probe)

```
urllc_client.py (UERANSIM VM, 192.168.49.139)
  │  binds to uesimtun1 (10.46.0.2)
  │  TCP/HTTP probe → 192.168.49.171:30180
  ▼
uesimtun1 → gNB (GTP-U encap)
  │  outer: src=192.168.49.139, dst=192.168.49.172 (upf-urllc N3)
  ▼
upf-urllc pod (hostNetwork, N3=192.168.49.172)
  │  GTP-U decapsulation
  ▼
ogstun-urllc (10.46.0.1) — N6
  │  [No tc shaping on this interface]
  ▼
kube-proxy DNAT: NodePort 30180 → Node-RED pod (10.244.2.56:1880)
  ▼
Node-RED — responds immediately (RTT echo)
  ▼
Response: reverse path → UE

RTT measured: client sends timestamp in payload, computes elapsed on response.
Typical: avg 12–16ms. SLA threshold: 15ms (orchestrator), 20ms (experiment analysis).
```

---

## mMTC Traffic Path (MQTT IoT Publish)

```
mmtc_client.py (UERANSIM VM)
  │  binds to uesimtun6 (10.47.0.34)
  │  MQTT CONNECT + PUBLISH → 192.168.49.171:30883
  ▼
uesimtun6 → gNB (GTP-U encap)
  │  outer: src=192.168.49.139, dst=192.168.49.173 (upf-mmtc N3)
  ▼
upf-mmtc pod (hostNetwork, N3=192.168.49.173)
  │  GTP-U decapsulation
  ▼
ogstun-mmtc (10.47.0.1) — N6
  ▼
kube-proxy DNAT: NodePort 30883 → Mosquitto pod (10.244.2.58:1883)
  ▼
eclipse-mosquitto:2.0 — stores/forwards message
  ▼
MQTT PUBACK → client

PDR proxy: total published message count tracked by mmtc_client.py logs.
```

---

## Control Plane Path (UE Registration)

```
UERANSIM UE process
  ▼ RRC (simulated)
UERANSIM gNB (192.168.49.139)
  ▼ NGAP (SCTP) → AMF (192.168.49.143:38412)
Open5GS AMF
  ▼ SBI (HTTP/2) → AUSF (auth), UDM (subscription), NSSF (slice)
  ▼ N11 → SMF-embb / SMF-urllc / SMF-mmtc
Open5GS SMF
  ▼ PFCP → UPF pod on 192.168.49.171/172/173
  ▼ PDU Session Accept → AMF → gNB → UE
UE receives IP address, uesimtun interface appears
```
