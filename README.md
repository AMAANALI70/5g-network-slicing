# Autonomous QoS-Aware 5G Network Slice Orchestration

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Kubernetes 1.29](https://img.shields.io/badge/kubernetes-1.29-326CE5.svg)](https://kubernetes.io/)
[![Open5GS](https://img.shields.io/badge/Open5GS-5G%20Core-green.svg)](https://open5gs.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-orange.svg)](https://langchain-ai.github.io/langgraph/)

> **A fully autonomous, LLM-driven agentic framework for real-time QoS-aware 5G network slice orchestration across a physical 5-VM testbed.**

---

## 🏗 Architecture Overview:

This project implements a **Hierarchical Multi-Agent Orchestration System** for 5G network slicing across three distinct slice types:

| Slice | Type | QoS Requirements |
|-------|------|------------------|
| eMBB | Enhanced Mobile Broadband | High throughput (≥50 Mbps) |
| URLLC | Ultra-Reliable Low Latency | Latency ≤5ms, Reliability ≥99.999% |
| mMTC | Massive Machine-Type Comms | High density, low power |

### Physical VM Topology

<img width="9226" height="5642" alt="system_archie_final" src="https://github.com/user-attachments/assets/98e03845-750a-4c19-b346-d1635befaded" />



```
┌─────────────────────────────────────────────────────────────────────┐
│                        5G Testbed (VMware)                           │
│                       192.168.49.0/24                                │
│                                                                       │
│  ┌─────────────────────┐      ┌───────────────────────────────────┐  │
│  │  kubemaster          │      │  kube (Worker Node 1)            │  │
│  │  192.168.49.174     │      │  192.168.49.171                  │  │
│  │                     │      │                                   │  │
│  │  • Kubernetes CP    │◄────►│  • Kubernetes Worker             │  │
│  │  • LangGraph Orch.  │      │  • UPF Pods (embb/urllc/mmtc)   │  │
│  │  • Prometheus       │      │  • MEC App Pods                  │  │
│  │  • Grafana          │      │  • TC/HTB QoS Rules              │  │
│  │  • Ollama (LLM)     │      │  • Ollama (qwen3:8b)             │  │
│  └─────────────────────┘      └───────────────────────────────────┘  │
│                                                                       │
│  ┌───────────────────────────────┐   ┌──────────────────────────┐    │
│  │  shinegami / cloney2          │   │  shinegami / y2           │   │
│  │  192.168.49.143               │   │  192.168.49.139           │   │
│  │                               │   │                           │   │
│  │  • Open5GS 5G Core            │   │  • UERANSIM (gNB + UEs)  │   │
│  │    - AMF, SMF (x3), UPF(x3)   │   │  • MEC Clients (traffic) │   │
│  │    - AUSF, NRF, UDM, UDR      │   │  • Traffic Control       │   │
│  │  • SMF per slice               │   │  • Dataset Collection    │   │
│  │  • Prometheus Node Exporter   │   │  • ML Training           │   │
│  └───────────────────────────────┘   └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Orchestrator Architecture (LangGraph OTAR Cycle)

```
┌──────────────────────────────────────────────────────────┐
│          LangGraph Agentic Orchestrator                   │
│                                                           │
│    ┌─────────┐   ┌─────────┐   ┌─────────┐             │
│    │ OBSERVE  │──►│  THINK  │──►│   ACT   │             │
│    │ Agent   │   │ Agent   │   │  Agent  │             │
│    └─────────┘   └─────────┘   └─────────┘             │
│         ▲                            │                   │
│         │        ┌─────────┐         │                   │
│         └────────│ REFLECT │◄────────┘                   │
│                  │ Agent   │                             │
│                  └─────────┘                             │
│                       │                                   │
│              Wrong-Lever Avoidance (WLA)                 │
│              Chain-of-Thought Logging                     │
└──────────────────────────────────────────────────────────┘
```

---

## 📁 Repository Structure

```
5g-network-slicing/
│
├── orchestrator/          # LangGraph multi-agent QoS orchestrator
│   ├── agents/            # Perception, State, Planning, Execution agents
│   ├── prompts/           # LLM system prompts
│   ├── memory/            # Agent memory / CoT trace logging
│   ├── validation/        # WLA (Wrong-Lever Avoidance) logic
│   ├── monitoring/        # Metrics collection agents
│   ├── execution/         # Action execution layer
│   ├── scenarios/         # Test scenarios (S1, S2, S3)
│   ├── main.py            # Orchestrator entry point
│   └── requirements.txt   # Orchestrator Python dependencies
│
├── kubernetes/
│   ├── namespaces/        # Namespace definitions
│   ├── deployments/       # UPF, MEC app deployments per slice
│   ├── services/          # Service definitions
│   ├── configs/           # kubeconfig, flannel, coredns
│   └── exported/          # Live cluster state (kubectl -o yaml)
│
├── open5gs/
│   └── configs/           # All Open5GS YAML configs
│                          # (amf, smf-embb/urllc/mmtc, upf-*, ausf, nrf...)
│
├── ueransim/
│   ├── configs/           # gNB and UE config YAMLs per slice
│   └── scripts/           # Startup/restart scripts
│
├── monitoring/
│   ├── prometheus/        # prometheus.yaml, scrape configs
│   ├── grafana/           # Dashboard definitions (4 dashboards)
│   └── exporters/         # tun-metrics-exporter deployment
│
├── traffic-control/       # tc/HTB qdisc shaping scripts
│   └── mec-scripts/       # MEC traffic control (low/medium/high)
│
├── mec/
│   ├── clients/           # MEC app clients (embb/urllc/mmtc v1+v2)
│   ├── servers/           # MEC app Dockerfiles and server code
│   └── scripts/           # MEC management scripts
│
├── ml-models/
│   ├── training/          # TCN model training pipeline
│   ├── trained/           # Pre-trained TCN models (.pt + scalers)
│   └── evaluation/        # Evaluation scripts and results
│
├── datasets/              # Experiment datasets (CSV/JSON)
│   ├── shinegami-143/     # Core network telemetry
│   ├── shinegami-139/     # UE-side and MEC telemetry (676MB+)
│   └── kubemaster-results/ # Orchestrator evaluation results
│
├── experiments/           # Experiment scripts and raw results
├── automation/            # SSH automation, startup scripts, crontabs
├── scripts/               # General helper utilities
│
├── docs/
│   ├── architecture/      # Architecture diagrams
│   ├── setup/             # VM setup and installation guides
│   └── research/          # LaTeX reports and journal papers
│
├── README.md              # This file
├── requirements.txt       # Aggregated Python dependencies
├── .gitignore
└── LICENSE
```

---

## 🚀 Quick Start

### Prerequisites

- 5 VMs (or equivalent) running Ubuntu 22.04+
- Kubernetes 1.29 cluster (kubeadm + flannel)
- Open5GS 2.7+ installed on core network VM
- UERANSIM 3.4+ on RAN VM
- Ollama with qwen3:8b model on orchestrator/worker VMs
- Python 3.10+

### 1. Clone & Setup

```bash
git clone https://github.com/<your-org>/5g-network-slicing.git
cd 5g-network-slicing
pip install -r requirements.txt
```

### 2. Deploy Kubernetes Infrastructure

```bash
# Apply namespaces
kubectl apply -f kubernetes/namespaces/

# Deploy UPF pods per slice
kubectl apply -f kubernetes/deployments/embb/
kubectl apply -f kubernetes/deployments/urllc/
kubectl apply -f kubernetes/deployments/mmtc/

# Deploy monitoring
kubectl apply -f monitoring/prometheus/
kubectl apply -f monitoring/grafana/
kubectl apply -f monitoring/exporters/
```

### 3. Configure Open5GS

Copy configs to the Open5GS VM (192.168.49.143):

```bash
# On the Open5GS VM:
sudo cp open5gs/configs/*.yaml /etc/open5gs/
sudo systemctl restart open5gs-amfd open5gs-smfd-embb open5gs-smfd-urllc \
  open5gs-smfd-mmtc open5gs-upfd-embb open5gs-upfd-urllc open5gs-upfd-mmtc
```

### 4. Start UERANSIM

```bash
# On the UERANSIM VM (192.168.49.139):
cd /home/shinegami/UERANSIM
./build/nr-gnb -c config/gnb.yaml &
./build/nr-ue -c config/ue-embb.yaml &
./build/nr-ue -c config/ue-urllc.yaml &
./build/nr-ue -c config/ue-mmtc.yaml &
```

### 5. Launch MEC Clients

```bash
# On MEC VM (192.168.49.139):
cd mec/clients/
bash launch_mec_clients_v2.sh
```

### 6. Start Orchestrator

```bash
cd orchestrator/
python main.py
```

---

## 🔬 Experiments & Scenarios

Three test scenarios are pre-configured:

| Scenario | Description | Config |
|----------|-------------|--------|
| S1 | eMBB congestion — high throughput demand | `scenarios/s1_embb_congestion.json` |
| S2 | URLLC latency spike — strict QoS violation | `scenarios/s2_urllc_latency.json` |
| S3 | mMTC overload — device density surge | `scenarios/s3_mmtc_overload.json` |

Run a scenario:
```bash
python orchestrator/main.py --scenario S1
```

---

## 📊 Monitoring

Access dashboards:
- **Prometheus**: `http://192.168.49.174:30090`
- **Grafana**: `http://192.168.49.174:30300`
  - Slice QoS Dashboard
  - Orchestrator Metrics Dashboard
  - Hierarchical Agent Dashboard
  - App Performance Dashboard

---

## 🤖 LLM Configuration

The orchestrator uses Groq-hosted LLMs (default) or local Ollama:

```env
# .env file
GROQ_API_KEY=your_key_here
OLLAMA_BASE_URL=http://localhost:11434  # for local inference
LLM_PROVIDER=groq  # or 'ollama'
MODEL_NAME=qwen3:8b  # for Ollama
```

Available Ollama models (pre-downloaded):
- **kube VM**: `qwen3:8b` (5.2 GB)

---

## 🏋️ ML Models

Pre-trained TCN (Temporal Convolutional Network) models for each slice:

```
ml-models/trained/
├── embb_tcn.pt          # eMBB throughput prediction
├── urllc_tcn.pt         # URLLC latency prediction
├── mmtc_tcn.pt          # mMTC connection density prediction
├── embb_tcn_scaler.pkl  # Feature scaler
├── urllc_tcn_scaler.pkl
└── mmtc_tcn_scaler.pkl
```

Retrain models:
```bash
cd ml-models/training/
python run_tcn_pipeline.py --slice embb --dataset ../../datasets/
```

---

## 📋 VM Credentials (Lab Environment)

> ⚠️ **SECURITY NOTE**: These credentials are for the isolated lab environment only. Do NOT use in production.

| VM | IP | User | Purpose |
|----|----|------|---------|
| kubemaster | 192.168.49.174 | kube-master | K8s control plane + orchestrator |
| kube (y2) | 192.168.49.171 | kube | K8s worker + Ollama |
| shinegami (cloney2) | 192.168.49.143 | shinegami | Open5GS 5G core |
| shinegami (y2-ue) | 192.168.49.139 | shinegami | UERANSIM + MEC clients |

---

## 📚 Documentation

| Document | Location |
|----------|----------|
| VM Setup Guide | `docs/setup/VM_SETUP.md` |
| Kubernetes Setup | `docs/setup/KUBERNETES.md` |
| Open5GS Setup | `docs/setup/OPEN5GS.md` |
| UERANSIM Setup | `docs/setup/UERANSIM.md` |
| Monitoring Setup | `docs/setup/MONITORING.md` |
| Orchestrator Guide | `docs/setup/ORCHESTRATOR.md` |
| Research Report | `docs/research/report/main.tex` |
| Journal Draft | `docs/research/paper/journal_draft2.tex` |

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgements

- [Open5GS](https://open5gs.org/) — Open-source 5G Core Network
- [UERANSIM](https://github.com/aligungr/UERANSIM) — 5G UE and RAN Simulator
- [LangGraph](https://langchain-ai.github.io/langgraph/) — Multi-agent orchestration framework
- [Ollama](https://ollama.ai/) — Local LLM inference
- Kubernetes, Prometheus, Grafana communities
