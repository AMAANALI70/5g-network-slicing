# Section 6 — Application Layer

## eMBB Application

| Property | Value |
|---|---|
| Pod | embb-app-78fdbdbc8-gtf4p |
| Namespace | embb |
| Image | `nginx:alpine` |
| Service | NodePort 8080 → 30880 |
| Slice | eMBB (SST=1, DNN=internet) |
| Purpose | HTTP content server simulating video streaming (HLS) |

**Behavior:**
- nginx serves static HTTP content on port 8080
- `embb_client.py` on UERANSIM VM downloads content in a loop via the uesimtun0/2/5 tunnels
- Traffic flows: UE → uesimtun → GTP-U → upf-embb → ogstun-embb → nginx:30880
- Throughput measured by parsing client log lines: `rate=43.7Mbps`
- nginx stub_status endpoint at `/status` is scraped by Prometheus

---

## URLLC Application

| Property | Value |
|---|---|
| Pods | urllc-app-76dbdf578c-qdl5l, urllc-app-76dbdf578c-lgcg7 (2 replicas during pilot) |
| Namespace | urllc |
| Image | `nodered/node-red:latest` |
| Service | NodePort 1880 → 30180 |
| Slice | URLLC (SST=2, DNN=urllc) |
| Purpose | RTT echo responder for latency measurement |

**Behavior:**
- Node-RED runs as a lightweight HTTP/TCP responder
- `urllc_client.py` sends periodic probe packets via uesimtun1/3/4 and measures round-trip time
- RTT is logged: `[URLLC] uesimtun1: msgs=630 RTT avg=13.7ms max=16.3ms`
- RTT is the primary SLA metric for the entire orchestration system
- Node-RED was chosen for fast startup and low resource footprint

---

## mMTC Applications

### Mosquitto (MQTT Broker)

| Property | Value |
|---|---|
| Pod | mmtc-app-77899f7894-n9dxw |
| Namespace | mmtc |
| Image | `eclipse-mosquitto:2.0` |
| Service | NodePort 1883 → 30883, 9001 → 30901 (WebSocket) |
| Slice | mMTC (SST=3, DNN=iot) |
| Purpose | MQTT message broker — accepts IoT sensor publishes |

**Behavior:**
- `mmtc_client.py` on UERANSIM VM connects via MQTT and publishes messages via uesimtun6/7/8
- Simulates IoT sensors sending telemetry
- Message count tracked as PDR proxy: `orchestrator_mmtc_msgs_total`

### InfluxDB

| Property | Value |
|---|---|
| Pod | influxdb-7b4c95fd84-9zd8z |
| Namespace | mmtc |
| Image | `influxdb:1.8-alpine` |
| Service | NodePort 8086 → 30886 |
| Purpose | Time-series storage for mMTC telemetry |

---

## Default Slice Application

| Pod | Image | Service | Notes |
|---|---|---|---|
| default-app-6c7cf49ff7-2qld2 | (unknown) | NodePort 80 → 30800 | Fallback slice app, not used in experiments |

---

## Application Summary Table

| Slice | Application | Image | Protocol | Port | Traffic Type |
|---|---|---|---|---|---|
| eMBB | nginx | nginx:alpine | HTTP | 30880 | Large payload downloads (HLS video simulation) |
| URLLC | Node-RED | nodered/node-red | HTTP/TCP | 30180 | Small probes, latency-sensitive |
| mMTC | Mosquitto | eclipse-mosquitto:2.0 | MQTT | 30883 | Frequent small IoT messages |
| mMTC | InfluxDB | influxdb:1.8-alpine | HTTP | 30886 | Time-series storage |

---

## Is Traffic Local? (MEC Assessment per Application)

| Application | Traffic stays local? | Evidence |
|---|---|---|
| nginx (eMBB) | YES | UE → GTP-U → upf-embb (192.168.49.171) → ogstun-embb → nginx pod (10.244.2.53). All on 192.168.49.0/24 / 10.244.x.x. No external routing. |
| Node-RED (URLLC) | YES | UE → GTP-U → upf-urllc (192.168.49.172) → ogstun-urllc → Node-RED pod (10.244.2.56). All local. |
| Mosquitto (mMTC) | YES | UE → GTP-U → upf-mmtc (192.168.49.173) → ogstun-mmtc → Mosquitto pod (10.244.2.58). All local. |

No traffic exits the 192.168.49.0/24 network or reaches any external internet endpoint.
