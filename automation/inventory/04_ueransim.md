# Section 4 — UERANSIM Architecture

## Location: UERANSIM VM — 192.168.49.139

---

## gNB

- Count: 1
- Binary: UERANSIM `nr-gnb`
- PLMN: MCC=999, MNC=70
- gNB search list: 192.168.49.139, 192.168.49.140
- NGAP (N2): connects to AMF at 192.168.49.143:38412 (SCTP)
- GTP-U (N3): binds on 192.168.49.139, tunnels to UPF pods on 192.168.49.171/172/173
- Supported NSSAIs: SST 1 (eMBB), SST 2 (URLLC), SST 3 (mMTC)

---

## UE Processes

| Process | SUPI (IMSI) | Config File |
|---|---|---|
| nr-ue (ue-embb) | imsi-999700000000001 | config/ue-embb.yaml |
| nr-ue (ue-urllc) | imsi-999700000000002 | config/ue-urllc.yaml |
| nr-ue (ue-mmtc) | imsi-999700000000003 | config/ue-mmtc.yaml |

Common parameters across all UE configs:
- MCC/MNC: 999/70
- Key: `465B5CE8B199B49FAA5F0A2EE238A6BC`
- OPC: `E8ED289DEBA952E4283B54E88E6183CA`
- Ciphering: EA1/EA2/EA3 (all enabled)
- Integrity: IA1/IA2/IA3 (all enabled)
- Each UE config requests 3 PDU sessions (SST 1/2/3)

> All 3 UE configs are nearly identical — same security credentials, same
> requested sessions. The naming (embb/urllc/mmtc) refers to the primary
> traffic use case, not exclusive slice membership.

---

## PDU Sessions — 9 Active

Each of the 3 UE processes establishes 3 PDU sessions (SST 1, 2, 3).
Total: 3 UEs × 3 sessions = 9 uesimtun interfaces.

| Interface | UE IMSI | SST | DNN | UE IP | Slice |
|---|---|---|---|---|---|
| uesimtun0 | 001 | 1 | internet | 10.45.0.2 | eMBB |
| uesimtun1 | 001 | 2 | urllc | 10.46.0.2 | URLLC |
| uesimtun2 | 002 | 1 | internet | 10.45.0.3 | eMBB |
| uesimtun3 | 002 | 2 | urllc | 10.46.0.3 | URLLC |
| uesimtun4 | 003 | 2 | urllc | 10.46.0.4 | URLLC |
| uesimtun5 | 003 | 1 | internet | 10.45.0.4 | eMBB |
| uesimtun6 | 001 | 3 | iot | 10.47.0.34 | mMTC |
| uesimtun7 | 002 | 3 | iot | 10.47.0.35 | mMTC |
| uesimtun8 | 003 | 3 | iot | 10.47.0.36 | mMTC |

---

## UE → Slice → UPF → Application Mapping

```
UE-001 (uesimtun0, 10.45.0.2)  → SST1/eMBB  → upf-embb (ogstun-embb)  → nginx:30880
UE-001 (uesimtun1, 10.46.0.2)  → SST2/URLLC → upf-urllc (ogstun-urllc) → Node-RED:30180
UE-001 (uesimtun6, 10.47.0.34) → SST3/mMTC  → upf-mmtc (ogstun-mmtc)  → Mosquitto:30883

UE-002 (uesimtun2, 10.45.0.3)  → SST1/eMBB  → upf-embb (ogstun-embb)  → nginx:30880
UE-002 (uesimtun3, 10.46.0.3)  → SST2/URLLC → upf-urllc (ogstun-urllc) → Node-RED:30180
UE-002 (uesimtun7, 10.47.0.35) → SST3/mMTC  → upf-mmtc (ogstun-mmtc)  → Mosquitto:30883

UE-003 (uesimtun5, 10.45.0.4)  → SST1/eMBB  → upf-embb (ogstun-embb)  → nginx:30880
UE-003 (uesimtun4, 10.46.0.4)  → SST2/URLLC → upf-urllc (ogstun-urllc) → Node-RED:30180
UE-003 (uesimtun8, 10.47.0.36) → SST3/mMTC  → upf-mmtc (ogstun-mmtc)  → Mosquitto:30883
```

---

## Traffic Clients (running on UERANSIM VM)

| Client Script | Tunnels | Target | Purpose |
|---|---|---|---|
| embb_client.py | uesimtun0/2/5 | 192.168.49.171:30880 | HTTP video streaming (HLS simulation) |
| urllc_client.py | uesimtun1/3/4 | 192.168.49.171:30180 | Periodic ping/RTT measurement |
| mmtc_client.py | uesimtun6/7/8 | 192.168.49.171:30883 | MQTT publish (IoT sensor simulation) |

Each client binds to a specific uesimtun interface ensuring traffic routes
through the correct GTP-U tunnel and slice UPF.
