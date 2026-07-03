# Section 3 — Open5GS Core Architecture

## Location: Core VM — 192.168.49.143

All 5G core NFs run as systemd services. No containerisation of core NFs.

---

## 5G Standalone NFs (Active)

| Service | NF | Role | Port |
|---|---|---|---|
| open5gs-amfd | AMF | Access and Mobility Management — handles NGAP from gNB, authenticates UEs, manages mobility | NGAP 38412/SCTP |
| open5gs-smfd-embb | SMF (eMBB) | Session Management for eMBB slice (SST=1, DNN=internet) — allocates UE IP, selects UPF, controls PFCP | N11/SBI |
| open5gs-smfd-urllc | SMF (URLLC) | Session Management for URLLC slice (SST=2, DNN=urllc) | N11/SBI |
| open5gs-smfd-mmtc | SMF (mMTC) | Session Management for mMTC slice (SST=3, DNN=iot) | N11/SBI |
| open5gs-nrfd | NRF | Network Repository Function — NF discovery and registration | SBI |
| open5gs-udmd | UDM | Unified Data Management — subscription data | SBI |
| open5gs-udrd | UDR | Unified Data Repository — persistent store for UDM | SBI |
| open5gs-ausfd | AUSF | Authentication Server — 5G-AKA / EAP-AKA' | SBI |
| open5gs-nssfd | NSSF | Network Slice Selection — slice admission | SBI |
| open5gs-pcfd | PCF | Policy Control — QoS rules | SBI |
| open5gs-bsfd | BSF | Binding Support — PCF binding | SBI |
| open5gs-scpd | SCP | Service Communication Proxy | SBI |
| open5gs-seppd | SEPP | Security Edge Protection | SBI |
| open5gs-webui | WebUI | Subscriber management (web) | 3000/TCP |

## 4G Legacy NFs (Active but unused in 5G path)

| Service | NF | Notes |
|---|---|---|
| open5gs-mmed | MME | 4G Mobility Management — not used, leftover from full Open5GS install |
| open5gs-hssd | HSS | 4G subscriber DB — not used in 5G path |
| open5gs-pcrfd | PCRF | 4G Policy — not used |

---

## UPF Placement

UPFs are NOT running as systemd services on the core VM.
They run as Kubernetes pods on the worker node (kube, 192.168.49.173) using `hostNetwork: true`.

| Slice | UPF Pod | Node | N3 Bind IP | N6 Interface |
|---|---|---|---|---|
| eMBB | upf-embb | kube (192.168.49.173) | 192.168.49.171 | ogstun-embb (10.45.0.1/24) |
| URLLC | upf-urllc | kube (192.168.49.173) | 192.168.49.172 | ogstun-urllc (10.46.0.1/24) |
| mMTC | upf-mmtc | kube (192.168.49.173) | 192.168.49.173 | ogstun-mmtc (10.47.0.1/24) |

All UPF pods share the same host network namespace. They are differentiated by:
- Separate PFCP associations to their respective SMF
- Separate ogstun interfaces per slice
- Separate IP pools per slice (10.45/46/47.x.x)

---

## Slice Selection Mechanism

1. UE sends PDU Session Establishment Request with S-NSSAI (SST + SD)
2. AMF selects NSSF for slice admission check
3. NSSF returns allowed NSSAIs and NRF selection info
4. AMF selects the correct SMF via NRF lookup (by S-NSSAI)
   - SST=1 → open5gs-smfd-embb
   - SST=2 → open5gs-smfd-urllc
   - SST=3 → open5gs-smfd-mmtc
5. SMF selects UPF (one per slice, pre-configured in SMF yaml)
6. SMF establishes PFCP session with selected UPF
7. UPF creates GTP-U tunnel endpoint on N3 and ogstun on N6
8. SMF returns PDU Session Accept to AMF → gNB → UE
9. UE gets IP from slice pool (10.45.x for eMBB, 10.46.x for URLLC, 10.47.x for mMTC)
10. uesimtun interface appears on UERANSIM VM with that IP
