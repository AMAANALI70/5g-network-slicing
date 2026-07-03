<div align="center">

# 🛰️ Cloud-Native 5G Network Slicing with Autonomous QoS Orchestration

[![Kubernetes](https://img.shields.io/badge/Kubernetes-v1.28-326CE5?logo=kubernetes&logoColor=white)](https://kubernetes.io/)
[![Open5GS](https://img.shields.io/badge/Open5GS-v2.7-00B4D8)](https://open5gs.org/)
[![UERANSIM](https://img.shields.io/badge/UERANSIM-v3.2-FF6B6B)](https://github.com/aligungr/UERANSIM)
[![Prometheus](https://img.shields.io/badge/Prometheus-v2.51-E6522C?logo=prometheus&logoColor=white)](https://prometheus.io/)
[![Grafana](https://img.shields.io/badge/Grafana-v10.4-F46800?logo=grafana&logoColor=white)](https://grafana.com/)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/Docker-Containerized-2496ED?logo=docker&logoColor=white)](https://docker.com/)

**A production-grade, multi-VM 5G core network with Kubernetes-orchestrated UPF pods, per-slice QoS enforcement, real-time monitoring, and an autonomous multi-agent system for SLA-driven bandwidth management.**

[Features](#-features) · [Architecture](#-architecture) · [Quick Start](#-quick-start) · [Orchestrator](#-autonomous-qos-orchestrator) · [Dashboards](#-monitoring--dashboards) · [Contributing](#-contributing)

</div>

---

## 📋 Table of Contents

- [About the Project](#-about-the-project)
- [Features](#-features)
- [Architecture](#-architecture)
- [Tech Stack](#-tech-stack)
- [Project Structure](#-project-structure)
- [Prerequisites](#-prerequisites)
- [Installation & Setup](#-installation--setup)
- [Usage](#-usage)
- [Autonomous QoS Orchestrator](#-autonomous-qos-orchestrator)
- [Monitoring & Dashboards](#-monitoring--dashboards)
- [API & Metrics](#-api--metrics)
- [Testing](#-testing)
- [Deployment](#-deployment)
- [Roadmap](#-roadmap)
- [Contributing](#-contributing)
- [License](#-license)
- [Contact](#-contact)

---

## 📖 About the Project

This project implements a **cloud-native 5G network slicing testbed** that separates the 5G control plane from the data plane across multiple VMs, with User Plane Functions (UPFs) running as Kubernetes pods. It features three distinct network slices — **eMBB**, **URLLC**, and **mMTC** — each with dedicated QoS policies enforced via Linux Traffic Control (`tc`).

### Problem It Solves

Traditional 5G deployments tightly couple control and data planes, making it difficult to:
- **Scale UPFs independently** based on slice demand
- **Enforce per-slice QoS** with fine-grained traffic shaping
- **Monitor slice performance** in real time
- **Autonomously react** to SLA violations without human intervention

This project solves all four by combining Kubernetes orchestration, `tc` shaping, Prometheus/Grafana observability, and a **multi-agent AI system** that autonomously adjusts bandwidth allocation to maintain SLA compliance.

### Demo / Screenshots

> 📸 *Screenshots of the Grafana dashboards are available in the [Monitoring & Dashboards](#-monitoring--dashboards) section.*

---

## ✨ Features

- **Three Network Slices** with namespace-level isolation:
  - 🟢 **eMBB** — Enhanced Mobile Broadband (100 Mbit, high throughput)
  - 🟡 **URLLC** — Ultra-Reliable Low-Latency (50 Mbit + 1ms netem)
  - 🟠 **mMTC** — Massive Machine-Type Communications (1 Mbit, IoT)
- **Kubernetes-Native UPF Deployment** using Minikube (`--driver=none`) with `hostNetwork`
- **Per-Slice Traffic Shaping** via `tc` HTB + netem qdiscs
- **Real-Time Monitoring** with custom TUN metrics exporter → Prometheus → Grafana
- **Autonomous QoS Orchestrator** — 4-agent control loop (Perception → State → Planning → Execution)
- **SLA-Driven Bandwidth Management** with cooldown, anti-oscillation, and confidence scoring
- **Two Grafana Dashboards** — Slice Monitor + QoS Orchestrator
- **Multi-VM Architecture** separating control plane, data plane, and RAN

---

## 🏗️ Architecture

```
┌──────────────────────┐    PFCP    ┌──────────────────────────┐   GTP-U   ┌──────────────────┐
│  VM1 — Control Plane │◄──────────►│  VM2 — Data Plane (K8s)  │◄─────────►│  VM3 — RAN       │
│  192.168.49.143      │            │  192.168.49.171           │           │  192.168.49.139   │
│                      │            │                          │           │                  │
│  ┌─────┐ ┌─────┐    │            │  ┌──────────────────┐    │           │  ┌─────┐         │
│  │ AMF │ │ NRF │    │            │  │  UPF-eMBB  (pod) │    │           │  │ gNB │         │
│  └─────┘ └─────┘    │            │  │  UPF-URLLC (pod) │    │           │  └─────┘         │
│  ┌──────────────┐    │            │  │  UPF-mMTC  (pod) │    │           │  ┌──────────────┐│
│  │ SMF ×3       │    │            │  └──────────────────┘    │           │  │ UE1 (eMBB)   ││
│  │ (eMBB/URLLC/ │    │            │  ┌──────────────────┐    │           │  │ UE2 (URLLC)  ││
│  │  mMTC)       │    │            │  │  QoS Orchestrator│    │           │  │ UE3 (mMTC)   ││
│  └──────────────┘    │            │  └──────────────────┘    │           │  └──────────────┘│
│  ┌──────────────┐    │            │  ┌──────────────────┐    │           │                  │
│  │ UDM/PCF/AUSF │    │            │  │ Prometheus+Grafana│    │           │  UERANSIM        │
│  └──────────────┘    │            │  └──────────────────┘    │           │                  │
└──────────────────────┘            └──────────────────────────┘           └──────────────────┘
```

### Network Slice Mapping

| Slice | Namespace | PFCP Port | GTP-U IP | Subnet | DNN | Shaping |
|-------|-----------|-----------|----------|--------|-----|---------|
| 🟢 eMBB | `embb` | 8805 | 192.168.49.171 | 10.45.0.0/24 | internet | 100 Mbit |
| 🟡 URLLC | `urllc` | 8806 | 192.168.49.172 | 10.46.0.0/24 | urllc | 50 Mbit + 1ms |
| 🟠 mMTC | `mmtc` | 8807 | 192.168.49.173 | 10.47.0.0/24 | iot | 1 Mbit |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **5G Core** | Open5GS v2.7 |
| **RAN Simulator** | UERANSIM v3.2 |
| **Orchestration** | Kubernetes (Minikube `--driver=none`) |
| **Containerization** | Docker |
| **Traffic Shaping** | Linux `tc` (HTB + netem) |
| **QoS Orchestrator** | Python 3.11 (multi-agent system) |
| **Monitoring** | Prometheus v2.51 |
| **Visualization** | Grafana v10.4 |
| **OS** | Ubuntu 22.04 LTS |

---

## 📁 Project Structure

```
kubernetes/
├── k8s/
│   ├── Dockerfile                          # UPF container image
│   ├── entrypoint.sh                       # TUN + NAT + tc shaping setup
│   ├── embb/
│   │   └── upf-embb.yaml                  # eMBB ConfigMap + Deployment
│   ├── urllc/
│   │   └── upf-urllc.yaml                 # URLLC ConfigMap + Deployment
│   ├── mmtc/
│   │   └── upf-mmtc.yaml                  # mMTC ConfigMap + Deployment
│   ├── orchestrator/
│   │   ├── config.py                       # SLA thresholds & control params
│   │   ├── perception_agent.py             # Prometheus + tc qdisc queries
│   │   ├── state_agent.py                  # Trend detection & oscillation
│   │   ├── planning_agent.py               # Decision engine + confidence
│   │   ├── execution_agent.py              # tc commands + verification
│   │   ├── orchestrator.py                 # Main 3s control loop
│   │   ├── Dockerfile                      # Python 3.11-slim + iproute2
│   │   ├── requirements.txt
│   │   └── orchestrator.yaml               # K8s namespace + deployment
│   └── monitoring/
│       ├── namespace.yaml                  # monitoring namespace
│       ├── tun-metrics-exporter.yaml       # Custom TUN stats exporter
│       ├── prometheus.yaml                 # Prometheus deployment
│       ├── grafana.yaml                    # Grafana + Slice dashboard
│       └── grafana-orchestrator-dashboard.yaml  # QoS Orchestrator dashboard
├── open5gs/
│   ├── smf-embb.yaml                      # SMF configs for each slice
│   ├── smf-urllc.yaml
│   └── smf-mmtc.yaml
└── report.tex                              # LaTeX deployment report
```

---

## 📦 Prerequisites

| Requirement | Version | Purpose |
|-------------|---------|---------|
| Ubuntu | 22.04 LTS | All VMs |
| Minikube | v1.32+ | Kubernetes on VM2 |
| Docker | v24+ | Container runtime |
| Open5GS | v2.7+ | 5G Core (VM1) |
| UERANSIM | v3.2+ | RAN simulator (VM3) |
| Python | 3.11+ | QoS Orchestrator |

### VM Requirements

| VM | Role | IP | Min Resources |
|----|------|-----|---------------|
| VM1 | Control Plane | 192.168.49.143 | 2 CPU, 4 GB RAM |
| VM2 | Data Plane (K8s) | 192.168.49.171 | 2 CPU, 4 GB RAM |
| VM3 | RAN (gNB + UEs) | 192.168.49.139 | 2 CPU, 2 GB RAM |

---

## 🚀 Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/<username>/5g-network-slicing.git
cd 5g-network-slicing
```

### 2. VM2 — Kubernetes Setup

```bash
# Start Minikube with bare-metal driver
minikube start --driver=none

# Create slice namespaces
kubectl create namespace embb
kubectl create namespace urllc
kubectl create namespace mmtc

# Add secondary IPs for URLLC/mMTC GTP-U
sudo ip addr add 192.168.49.172/24 dev ens33
sudo ip addr add 192.168.49.173/24 dev ens33
```

### 3. Build & Deploy UPFs

```bash
# Build UPF image
docker build -t open5gs-upf:local k8s/

# Deploy UPF pods
kubectl apply -f k8s/embb/upf-embb.yaml
kubectl apply -f k8s/urllc/upf-urllc.yaml
kubectl apply -f k8s/mmtc/upf-mmtc.yaml
```

### 4. Configure iptables

```bash
# Allow TUN → external traffic
for iface in ogstun-embb ogstun-urllc ogstun-mmtc; do
  sudo iptables -I FORWARD 1 -i $iface -o ens33 -j ACCEPT
  sudo iptables -I FORWARD 1 -i ens33 -o $iface \
      -m state --state RELATED,ESTABLISHED -j ACCEPT
done
```

### 5. Deploy Monitoring Stack

```bash
kubectl apply -f k8s/monitoring/namespace.yaml
kubectl apply -f k8s/monitoring/tun-metrics-exporter.yaml
kubectl apply -f k8s/monitoring/prometheus.yaml
kubectl apply -f k8s/monitoring/grafana.yaml
kubectl apply -f k8s/monitoring/grafana-orchestrator-dashboard.yaml
```

### 6. Deploy QoS Orchestrator

```bash
# Build orchestrator image
docker build -t qos-orchestrator:local k8s/orchestrator/

# Deploy
kubectl apply -f k8s/orchestrator/orchestrator.yaml
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PROMETHEUS_URL` | `http://localhost:30090` | Prometheus endpoint |
| `URLLC_RTT_SLA_MS` | `5.0` | URLLC RTT threshold (ms) |
| `EMBB_RATE_FLOOR` | `20` | Minimum eMBB rate (Mbit) |
| `EMBB_RATE_MAX` | `100` | Maximum eMBB rate (Mbit) |
| `LOOP_INTERVAL_SEC` | `3` | Control loop period (s) |
| `COOLDOWN_SEC` | `10` | Min seconds between actions |

---

## 💡 Usage

### Verify UPF Pods

```bash
kubectl get pods -A -l slice
```

Expected output:
```
NAMESPACE   NAME                         READY   STATUS
embb        upf-embb-68d8c9bc9-xxxxx    1/1     Running
urllc       upf-urllc-7fbf49c66c-xxxxx  1/1     Running
mmtc        upf-mmtc-84f689d5f5-xxxxx   1/1     Running
```

### Generate Slice Traffic (from VM3)

```bash
# eMBB — High bandwidth
curl --interface uesimtun0 -o /dev/null http://speedtest.tele2.net/100MB.zip &

# URLLC — Low latency
ping -I uesimtun1 -s 64 -i 0.01 8.8.8.8

# mMTC — IoT sensor
curl --interface uesimtun2 -X POST https://httpbin.org/post \
    -d '{"sensor":"temp","value":22.5}'
```

### Watch Orchestrator Logs

```bash
kubectl logs -f deployment/qos-orchestrator -n orchestrator
```

---

## 🤖 Autonomous QoS Orchestrator

The orchestrator is a **4-agent control loop** running every 3 seconds:

```
Perception → State → Planning → Execution → (repeat)
```

### Agent Responsibilities

| Agent | Role | Key Capabilities |
|-------|------|-------------------|
| **Perception** | Collect metrics | Prometheus queries, `tc` qdisc stats, `/proc/stat` |
| **State** | Track patterns | Sliding window, RTT trend detection, oscillation detection |
| **Planning** | Decide actions | Throttle/restore with confidence scoring, cooldown enforcement |
| **Execution** | Apply changes | `tc class change`, verification, impact evaluation |

### Decision Logic

```
IF urllc_rtt > 5ms AND trend == rising     → Throttle eMBB (-20 Mbit)
IF violations > 2                           → Throttle (more aggressive)
IF oscillation detected                     → Suppress actions (dampening)
IF stable > 60s AND rate < max              → Restore eMBB (+10 Mbit)
```

### Safety Constraints

- ⏱️ **Cooldown**: 10s minimum between actions
- 🔻 **Floor**: eMBB never drops below 20 Mbit
- 🔺 **Ceiling**: eMBB max 100 Mbit
- 🔁 **Anti-oscillation**: Detects and suppresses rapid toggling
- ♻️ **Auto-restore**: Gradual recovery after 60s of stability

---

## 📊 Monitoring & Dashboards

### Access Points

| Service | URL | Credentials |
|---------|-----|-------------|
| **Grafana** | `http://192.168.49.171:30300` | admin / admin |
| **Prometheus** | `http://192.168.49.171:30090` | — |
| **Orchestrator Metrics** | `http://192.168.49.171:9200/metrics` | — |
| **Orchestrator Status** | `http://192.168.49.171:9200/status` | — |

### Dashboard 1: 5G Network Slice Monitor

Per-slice throughput, packet rate, cumulative traffic, live bandwidth gauges, and error/drop tracking.

### Dashboard 2: QoS Orchestrator

eMBB rate gauge, URLLC RTT with SLA threshold line, violation count, stability score, oscillation flag, confidence gauge, throttle/restore action timeline, mMTC PDR.

---

## 📡 API & Metrics

### Orchestrator Metrics (Prometheus Format)

```
orchestrator_embb_rate_mbit        # Current eMBB tc rate
orchestrator_urllc_rtt_ms          # URLLC RTT measurement
orchestrator_embb_throughput_bps   # eMBB actual throughput
orchestrator_mmtc_pdr              # mMTC Packet Delivery Ratio
orchestrator_violation_count       # SLA violation counter
orchestrator_stability_seconds     # Consecutive stable seconds
orchestrator_oscillation           # Oscillation flag (0/1)
orchestrator_throttle_total        # Total throttle actions
orchestrator_restore_total         # Total restore actions
orchestrator_last_confidence       # Last decision confidence
```

### Status Endpoint

```bash
curl http://192.168.49.171:9200/status
```

```json
{
  "embb_current_rate": 100,
  "urllc_rtt_99": 1.0,
  "violation_count": 0,
  "stability_score": 120,
  "oscillation": 0,
  "last_action": "no_action",
  "last_confidence": 1.0,
  "last_reason": "SLA within bounds"
}
```

---

## 🧪 Testing

### Verify All Components

```bash
# Check pods
kubectl get pods -A

# Check metrics pipeline
curl -s http://192.168.49.171:9100/metrics | head -5
curl -s http://192.168.49.171:9200/metrics

# Check Prometheus targets
curl -s http://192.168.49.171:30090/api/v1/targets | python3 -m json.tool
```

### Functional Test: Autonomous Throttling

```bash
# 1. Generate heavy eMBB traffic (from VM3)
curl --interface uesimtun0 -o /dev/null http://speedtest.tele2.net/1GB.zip &

# 2. Watch orchestrator react (from VM2)
kubectl logs -f deployment/qos-orchestrator -n orchestrator

# 3. Stop traffic → observe auto-restore after 60s
kill %1
```

---

## 🚢 Deployment

### Production Considerations

- Make iptables rules persistent via `iptables-persistent` or systemd
- Add persistent storage for Prometheus (PVC instead of emptyDir)
- Configure Grafana with proper authentication
- Add Alertmanager for SLA violation notifications
- Use `iperf3` for controlled throughput testing

### Rebuild After Changes

```bash
# Rebuild UPF image
docker build -t open5gs-upf:local k8s/

# Rebuild orchestrator
docker build -t qos-orchestrator:local k8s/orchestrator/

# Rolling restart
kubectl rollout restart deployment/qos-orchestrator -n orchestrator
```

---

## 🗺️ Roadmap

- [ ] Per-UE traffic tracking (GTP-U TEID-level metrics)
- [ ] Alertmanager integration for SLA breach notifications
- [ ] ML-based predictive scaling (LSTM for traffic forecasting)
- [ ] Multi-cluster UPF deployment across edge sites
- [ ] Persistent storage for Prometheus TSDB
- [ ] Horizontal Pod Autoscaler for UPF replicas
- [ ] Integration with NWDAF (Network Data Analytics Function)
- [ ] Web-based orchestrator control panel

---

## 🤝 Contributing

Contributions are welcome! Here's how:

1. **Fork** the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'feat: add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open a **Pull Request**

### Guidelines

- Follow existing code style and conventions
- Add tests for new functionality
- Update documentation for any changed behavior
- Use [conventional commits](https://www.conventionalcommits.org/)

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.

---

## 👤 Contact

**Project Author** — [@your-username](https://github.com/your-username)

**Project Link:** [https://github.com/your-username/5g-network-slicing](https://github.com/your-username/5g-network-slicing)

---

<div align="center">

⭐ **Star this repo if you found it useful!** ⭐

</div>
