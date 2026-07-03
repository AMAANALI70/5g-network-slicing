# Section 1 — Physical / Virtual Infrastructure

## Hypervisor

VMware (vSphere/ESXi or Workstation) — confirmed by VM UUID format
(`fa4e4d56-3eca-777b-162c-d2526c6fec11`, `eafd4d56-5e47-3425-...`).
All VMs share a single flat L2 network: `192.168.49.0/24`.

---

## VM Inventory

### VM1 — kubemaster

| Property | Value |
|---|---|
| Hostname | kubemaster |
| IP | 192.168.49.174 |
| CPU | 8 × Intel Xeon Gold 5418Y |
| RAM | 15 GiB |
| Disk | 245 GB |
| OS | Ubuntu 22.04.5 LTS, kernel 6.8.0-111-generic |
| Role | Kubernetes control-plane + orchestrators + monitoring |

Services running:
- kube-apiserver, etcd, kube-scheduler, kube-controller-manager
- Prometheus (NodePort 30090)
- Grafana (NodePort 30300)
- Rule-based orchestrator — `phase3-orchestrator.py` (port 9200)
- Agentic orchestrator — `orchestrator_agentic/main.py` (port 9200, alternating)
- Ollama (port 11434) — local LLM inference for agentic orchestrator
- Local Docker registry (port 5000) — hosts `open5gs-upf:local` image

---

### VM2 — kube (primary worker)

| Property | Value |
|---|---|
| Hostname | kube |
| Primary IP | 192.168.49.171 (ens33) |
| Secondary IPs | 192.168.49.172, 192.168.49.173, 192.168.49.187 |
| K8s reports as | 192.168.49.173 |
| CPU | 16 × Intel Xeon Gold 5418Y |
| RAM | 62 GiB |
| Disk | 491 GB |
| OS | Ubuntu 22.04.5 LTS, kernel 6.8.0-111-generic |
| Role | Kubernetes worker — UPF pods + application pods + MEC edge |

Services running:
- All slice UPF pods (upf-embb, upf-urllc, upf-mmtc) — hostNetwork mode
- embb-app (nginx), urllc-app (Node-RED), mmtc-app (Mosquitto), influxdb
- tun-metrics-exporter (port 9100)
- Slice-specific ogstun interfaces: ogstun-embb (10.45.0.1), ogstun-urllc (10.46.0.1), ogstun-mmtc (10.47.0.1)

> Note: Multiple secondary IPs (192.168.49.171/172/173) are configured on the same NIC.
> The UPF pods use hostNetwork and thus bind to the host IP.
> The tc shaping enforcement point is this node — `ogstun-embb` interface.

---

### VM3 — kube2 (secondary worker)

| Property | Value |
|---|---|
| Hostname | kube2 |
| IP | 192.168.49.181 |
| CPU | 8 × Intel Xeon Gold 5418Y |
| RAM | 15 GiB |
| Disk | 308 GB |
| OS | Ubuntu 22.04.5 LTS, kernel 6.8.0-111-generic |
| Role | Kubernetes worker — currently SchedulingDisabled |

Status: Flannel CNI in CrashLoopBackOff (1773+ restarts). No workloads scheduled.
tun-metrics-exporter pod present but crash-looping. Not used for any experiment workload.

---

### VM4 — Core VM (shinegami@192.168.49.143)

| Property | Value |
|---|---|
| Hostname | shinegami |
| IP | 192.168.49.143 |
| CPU | 8 × Intel Xeon Gold 5418Y |
| RAM | 62 GiB |
| Disk | 491 GB |
| OS | Ubuntu 22.04.5 LTS |
| Role | Open5GS 5G Core Network |

Services running (systemd):
- open5gs-amfd (AMF)
- open5gs-smfd-embb, open5gs-smfd-urllc, open5gs-smfd-mmtc (3× SMF)
- open5gs-nrfd (NRF)
- open5gs-udmd, open5gs-udrd (UDM/UDR)
- open5gs-ausfd (AUSF)
- open5gs-nssfd (NSSF)
- open5gs-pcfd, open5gs-pcrfd (PCF/PCRF)
- open5gs-bsfd (BSF)
- open5gs-scpd (SCP)
- open5gs-seppd (SEPP)
- open5gs-mmed, open5gs-hssd (MME/HSS — 4G legacy, not used in 5G path)
- open5gs-webui (subscriber management UI)
- Docker daemon (docker0: 172.17.0.1)

---

### VM5 — UERANSIM VM (shinegami@192.168.49.139)

| Property | Value |
|---|---|
| Hostname | shinegami |
| IP | 192.168.49.139 |
| CPU | Intel Xeon Gold 5418Y |
| RAM | 62 GiB |
| Disk | 491 GB |
| OS | Ubuntu 22.04.5 LTS |
| Role | RAN simulation — gNB + UEs |

Services running:
- UERANSIM gNB process (nr-gnb)
- 3× UERANSIM UE processes (nr-ue, one per IMSI)
- 9× MEC client scripts (embb_client.py, urllc_client.py, mmtc_client.py)
- ogstun interfaces: 10.45.0.1, 10.46.0.1, 10.47.0.1 (UPF N6 side visible here)
- uesimtun0–8 (UE tunnel interfaces — one per PDU session)

---

## Network Topology

```
192.168.49.0/24  (flat VMware L2 segment)
┌────────────────────────────────────────────────────────────┐
│  .139  UERANSIM VM    gNB + 3 UE processes                 │
│  .143  Core VM        Open5GS AMF/SMF/NRF/UDM/AUSF/...     │
│  .171  Worker (kube)  UPF pods + App pods  (primary NIC)   │
│  .172  Worker (kube)  secondary IP                          │
│  .173  Worker (kube)  secondary IP (K8s node IP)            │
│  .174  kubemaster     K8s control-plane + orchestrators     │
│  .181  kube2          worker (disabled)                     │
└────────────────────────────────────────────────────────────┘

GTP-U (N3):  UERANSIM .139  ←→  UPF pod on .171/.172/.173
SBI (N2/N11): Core VM .143  ←→  UERANSIM .139 (NGAP)
SBI (N11):    Core VM .143  ←→  UPF pod .171 (PFCP)
N6 (data):    UPF ogstun  →  Applications on pod network / NodePort
```
