# System Architecture Audit — Index

Generated: 2026-06-03

All files are evidence-based from live system inspection.
No guesses or assumptions — every claim is backed by command output.

---

## Files

| File | Content |
|---|---|
| [01_physical_infrastructure.md](./01_physical_infrastructure.md) | 5 VMs, hardware specs, hypervisor, network topology |
| [02_kubernetes.md](./02_kubernetes.md) | Nodes, pods, services, deployments, resource quotas, scheduling |
| [03_open5gs_core.md](./03_open5gs_core.md) | All 5G NFs, slice selection mechanism |
| [04_ueransim.md](./04_ueransim.md) | gNB, 3 UEs, 9 PDU sessions, UE→slice→app mapping |
| [05_upf_architecture.md](./05_upf_architecture.md) | UPF pods, N3/N6 interfaces, tc enforcement point |
| [06_applications.md](./06_applications.md) | nginx, Node-RED, Mosquitto, InfluxDB — images, purpose, traffic locality |
| [07_traffic_paths.md](./07_traffic_paths.md) | End-to-end packet flows for eMBB, URLLC, mMTC |
| [08_monitoring.md](./08_monitoring.md) | Prometheus scrape targets, all metrics, Grafana, metric flow |
| [09_orchestrators.md](./09_orchestrators.md) | Rule-based and agentic orchestrator architecture |
| [10_traffic_control.md](./10_traffic_control.md) | tc hierarchy, shaping policy, observed behavior |
| [11_architecture_classification.md](./11_architecture_classification.md) | Evidence-based classification of the platform |

---

## Quick Reference

```
VMs:         5 (kubemaster, kube/worker, kube2/disabled, core, ueransim)
CPU:         Intel Xeon Gold 5418Y across all VMs
Hypervisor:  VMware
K8s:         v1.29.15, Flannel CNI, 3 nodes (1 schedulable worker)
5G Core:     Open5GS, full 5G SA, 3 per-slice SMFs
RAN:         UERANSIM — 1 gNB, 3 UE processes, 9 PDU sessions
Slices:      eMBB (SST=1), URLLC (SST=2), mMTC (SST=3)
UPFs:        3 pods (hostNetwork on kube worker), ogstun-embb/urllc/mmtc
Apps:        nginx (eMBB), Node-RED (URLLC), Mosquitto+InfluxDB (mMTC)
Monitoring:  Prometheus:30090, Grafana:30300, orchestrator:9200
TC:          TBF on ogstun-embb only — 1000 Mbit (normal) / 50 Mbit (throttled)
Platform:    MEC-Inspired 5G Network Slicing Research Testbed
```
