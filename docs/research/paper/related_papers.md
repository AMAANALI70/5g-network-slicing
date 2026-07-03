# Related Papers for Comparative Study
## Agentic AI-Based 5G Network Slice Orchestrator

---

## 📚 Full Literature Pool (10+ Papers)

### 1. PCLANSA — Proactive Closed-Loop LSTM for 5G Slicing
| Field | Detail |
|---|---|
| **Authors** | N. P. Tran, O. Delgado, B. Jaumard |
| **Title** | Proactive Service Assurance in 5G and B5G Networks: A Closed-Loop Algorithm for End-to-End Network Slices |
| **Venue** | *IEEE Transactions on Network and Service Management*, vol. 22, no. 4, 2025 |
| **Approach** | LSTM-based traffic prediction + reactive VNF scaling |
| **Testbed** | Simulated (OMNeT++ / NS-3) |
| **Key Results** | 54.85% eMBB resource savings, 57.1% URLLC savings vs static |
| **Causal Reasoning** | ❌ No |
| **Memory** | ❌ No (stateless per-cycle) |
| **Training Required** | ✅ Yes — offline LSTM training on traffic traces |
| **Limitation** | Cannot handle novel congestion patterns without retraining; no root-cause attribution |

---

### 2. MicroOpt — DNN + Gradient Optimization for Slice Resources
| Field | Detail |
|---|---|
| **Authors** | M. Sulaiman, M. Ahmadi, B. Sun, M. A. Salahuddin, R. Boutaba, A. Saleh |
| **Title** | MicroOpt: Model-Driven Slice Resource Optimization in 5G and Beyond Networks |
| **Venue** | *IEEE Transactions on Network and Service Management*, vol. 22, no. 5, 2025 |
| **Approach** | DNN slice model + gradient-based optimization + Lagrangian decomposition |
| **Testbed** | Live 5G open-source testbed with real traffic traces |
| **Key Results** | 21.9% lower resource consumption vs SOTA; ms-level QoS prediction |
| **Causal Reasoning** | ❌ No (black-box DNN) |
| **Memory** | ❌ No |
| **Training Required** | ✅ Yes — offline DNN training per-slice |
| **Limitation** | DNN must be retrained per topology; no causal audit trail |

---

### 3. DRL Autoscaling — Reinforcement Learning for Kubernetes 5G
| Field | Detail |
|---|---|
| **Authors** | G. C. P. Reddy |
| **Title** | Reinforcement Learning-Driven Kubernetes Autoscaling for High-Throughput 5G Network Functions |
| **Venue** | *World Journal of Advanced Engineering Technology and Sciences (WJAETS)*, vol. 14, no. 1, 2025 |
| **Approach** | Deep Q-Network for pod scaling decisions in Kubernetes |
| **Testbed** | Kubernetes cluster simulation |
| **Key Results** | 71.7% faster slice deployment, 35% higher utilization, 22% lower latency vs threshold |
| **Causal Reasoning** | ❌ No |
| **Memory** | ✅ Episodic (replay buffer) |
| **Training Required** | ✅ Yes — extensive episodic training |
| **Limitation** | High sample complexity; cannot explain decisions; no cross-slice causal reasoning |

---

### 4. Full Dynamic Orchestration — K8s 5G Core (free5GC)
| Field | Detail |
|---|---|
| **Authors** | F. H. Grings, L. B. D. Silveira, K. V. Cardoso, S. L. Correa, L. R. Prade, C. B. Both |
| **Title** | Full Dynamic Orchestration in 5G Core Network Slicing over a Cloud-Native Platform |
| **Venue** | *Proc. IEEE GLOBECOM*, 2022 |
| **Approach** | Kubernetes-integrated controller for dynamic 5G core reconfiguration |
| **Testbed** | Live free5GC testbed on Kubernetes |
| **Key Results** | 47.5% reduction in slice reconfiguration requests vs partial orchestration |
| **Causal Reasoning** | ❌ No |
| **Memory** | ❌ No |
| **Training Required** | ❌ No (rule-based controller) |
| **Limitation** | No AI reasoning; does not handle QoS violations; reactive only |

---

### 5. K8s MANO for eMBB+URLLC Coexistence
| Field | Detail |
|---|---|
| **Authors** | S. Novanana, A. Kliks, A. S. Arifin, G. Wibisono |
| **Title** | Provisioning of Coexisting eMBB and URLLC Services in 5G Network Slicing with Kubernetes-based MANO |
| **Venue** | *Proc. IEEE COMNETSAT*, 2024 |
| **Approach** | Kubernetes MANO with dedicated SMF+UPF per slice |
| **Testbed** | Live free5GC + UERANSIM + OpenStack |
| **Key Results** | 20.2–22.1 Gbps stable throughput; fewer retransmissions with dedicated isolation |
| **Causal Reasoning** | ❌ No |
| **Memory** | ❌ No |
| **Training Required** | ❌ No (static provisioning) |
| **Limitation** | Static resource assignment; no adaptive QoS control loop |

---

### 6. LLM-Based Network Management — Intent to Config
| Field | Detail |
|---|---|
| **Authors** | J. Park, H. Yoon, S. Lee |
| **Title** | LLM-Based Network Management: From Intent Specification to Configuration Generation |
| **Venue** | *Proc. IEEE INFOCOM*, 2024 |
| **Approach** | LLM for natural language intent → network configuration generation |
| **Testbed** | Simulated; no live 5G core |
| **Key Results** | Demonstrated intent parsing accuracy; qualitative evaluation only |
| **Causal Reasoning** | ✅ Partial (intent-to-config NL reasoning) |
| **Memory** | ❌ No episodic operational memory |
| **Training Required** | ❌ No (prompt-based) |
| **Limitation** | No closed-loop control; no live QoS enforcement; no empirical SLA metrics |

---

### 7. LLM + ETSI MANO — Conceptual Slicing Framework
| Field | Detail |
|---|---|
| **Authors** | A. Dandoush, V. Kumarskandpriya, M. Uddin, U. Khalil |
| **Title** | Large Language Models Meet Network Slicing Management and Orchestration |
| **Venue** | *arXiv preprint arXiv:2403.13721*, 2024 |
| **Approach** | Conceptual framework: LLM + multi-agent + ETSI MANO + 3GPP slicing |
| **Testbed** | ❌ No experimental validation |
| **Key Results** | Conceptual architecture only; no empirical results |
| **Causal Reasoning** | ✅ Conceptual |
| **Memory** | ❌ Not implemented |
| **Training Required** | ❌ No |
| **Limitation** | No implementation; no live testbed; unvalidated performance claims |

---

### 8. Agentic AI 6G Control Plane — MCP + Open5GS
| Field | Detail |
|---|---|
| **Authors** | E. Bandara, R. Gore et al. |
| **Title** | An Agentic AI Control Plane for 6G Network Slice Orchestration, Monitoring, and Trading |
| **Venue** | *arXiv preprint arXiv:2602.13227*, 2026 |
| **Approach** | Model Context Protocol (MCP) + LLM fine-tuning for 6G slice control |
| **Testbed** | Live Open5GS + Ericsson RAN + Kubernetes |
| **Key Results** | Successful tool invocation; qualitative slice orchestration |
| **Causal Reasoning** | ✅ Partial |
| **Memory** | ❌ No episodic memory |
| **Training Required** | ✅ Yes — LLM fine-tuning required |
| **Limitation** | Requires fine-tuning; no wrong-lever avoidance; no memory subsystem |

---

### 9. MonArch — Scalable Monitoring for Cloud-Native 5G
| Field | Detail |
|---|---|
| **Authors** | N. Saha, N. Shahriar, R. Boutaba, A. Saleh |
| **Title** | MonArch: Network Slice Monitoring Architecture for Cloud-Native 5G Deployments |
| **Venue** | *IEEE Transactions on Network and Service Management*, vol. 19, no. 4, 2022 |
| **Approach** | Hierarchical monitoring architecture using Prometheus + InfluxDB |
| **Testbed** | Cloud-native 5G testbed |
| **Key Results** | 5-second scrape interval optimal accuracy-overhead balance |
| **Causal Reasoning** | ❌ No |
| **Memory** | ❌ No |
| **Training Required** | ❌ No |
| **Limitation** | Monitoring-only; no orchestration or QoS enforcement loop |

---

### 10. Prediction-Assisted Dynamic Network Slicing
| Field | Detail |
|---|---|
| **Authors** | H. Zhou, W. Xu, J. Chen, W. Wang |
| **Title** | Prediction-Assisted Dynamic Network Slicing |
| **Venue** | *IEEE Network*, vol. 35, no. 2, pp. 152–160, 2021 |
| **Approach** | Holt-Winters exponential smoothing for traffic prediction + dynamic slicing |
| **Testbed** | Simulation |
| **Key Results** | Reduced SLA violation rate vs. static provisioning; improved utilization |
| **Causal Reasoning** | ❌ No |
| **Memory** | ❌ No |
| **Training Required** | ❌ No (statistical model) |
| **Limitation** | Assumes stationary traffic; cannot reason about root cause or cross-slice effects |

---

### 11. Drift-Aware Adaptive Scheduling (O-RAN) *(Akshat et al.)*
| Field | Detail |
|---|---|
| **Authors** | A. Dodwad, N. Huggi, Abhishek M., R. A. Magadum, Narayan D. G. |
| **Title** | Drift-Aware Adaptive Scheduling in 5G Open RAN using Unsupervised Anomaly Detection |
| **Venue** | KLE Technological University (under submission), 2025 |
| **Approach** | Isolation Forest anomaly detection (unsupervised) + dynamic MAC scheduler tuning via Near-RT RIC xApp on FlexRIC/OAI |
| **Testbed** | Live O-RAN testbed (OpenAirInterface + FlexRIC) |
| **Key Results** | 15% throughput improvement, Jain's Fairness Index = 0.9994 |
| **Causal Reasoning** | ❌ No (statistical anomaly detection) |
| **Memory** | ❌ No |
| **Training Required** | ❌ No (unsupervised) |
| **Limitation** | RAN-only (no core/slice control); no cross-slice causal reasoning; no LLM |

---

### 12. ML-Based Resource Orchestration for 5G Slicing
| Field | Detail |
|---|---|
| **Authors** | N. Salhab, R. Langar, R. Boutaba |
| **Title** | Machine Learning-Based Resource Orchestration for 5G Network Slicing |
| **Venue** | *IEEE Transactions on Network and Service Management*, vol. 19, no. 4, 2022 |
| **Approach** | Supervised ML (SVM / Random Forest) for admission control and resource scaling |
| **Testbed** | Simulation |
| **Key Results** | Improved slice acceptance rate; reduced blocking probability |
| **Causal Reasoning** | ❌ No |
| **Memory** | ❌ No |
| **Training Required** | ✅ Yes — labeled dataset |
| **Limitation** | Requires labeled training data; no real-time closed-loop QoS enforcement |

---

## ✅ 3 Best Papers for Comparative Study

### Selection Rationale

| # | Paper | Why Best for Comparison |
|---|---|---|
| **1** | **PCLANSA** (Tran et al., 2025) | Most directly comparable: proactive, closed-loop, 5G slicing, has quantitative SLA/resource metrics on eMBB+URLLC. Represents the *predictive ML* paradigm. |
| **2** | **MicroOpt** (Sulaiman et al., 2025) | Live testbed evaluation, same IEEE TNSM venue-class, quantitative results (21.9% improvement). Represents the *model-driven optimization* paradigm. |
| **3** | **DRL Autoscaling** (Reddy, 2025) | Kubernetes-based (same infrastructure class), has latency/utilization metrics. Represents the *reinforcement learning* paradigm. |

### Comparative Metrics Table (for paper)

| Dimension | PCLANSA | MicroOpt | DRL Autoscaling | **Proposed (Ours)** |
|---|---|---|---|---|
| Approach | LSTM prediction | DNN + gradient | Deep Q-Network | LLM + CoT + WLA |
| Live 5G Testbed | ❌ Simulation | ✅ Yes | ❌ Simulation | ✅ Yes (Open5GS+K8s) |
| Causal Reasoning | ❌ No | ❌ No | ❌ No | ✅ Yes (C3 CoT) |
| Operational Memory | ❌ No | ❌ No | ✅ Replay buffer | ✅ Episodic (C5) |
| Wrong-Lever Avoidance | ❌ No | ❌ No | ❌ No | ✅ Yes (C4 ρ_eMBB) |
| Training Required | ✅ Offline LSTM | ✅ Offline DNN | ✅ Episodic DRL | ❌ None |
| SLA Compliance | N/A (simulation) | N/A | N/A | **96.3%** |
| Recovery Time | N/A | N/A | N/A | **4.2 s** |
| Throughput Preservation | 54.85% resource saving | 21.9% less resources | 35% better util. | **98.5%** |
| Decision Latency | ms (statistical) | ms (DNN inference) | ms (DRL inference) | 233 ms (LLM) |
| Auditable Decisions | ❌ No | ❌ No | ❌ No | ✅ Yes (CoT trace) |
