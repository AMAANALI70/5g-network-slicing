# Section 8 — Monitoring Stack

## Prometheus

- Pod: `prometheus-f8687d7d5-4qvdx` (kubemaster, 10.244.0.36)
- Image: `prom/prometheus:v2.51.0`
- NodePort: 30090 (accessible at http://192.168.49.174:30090)
- Scrape interval: 5s global

### Scrape Targets

| Job | Target | Metrics Collected |
|---|---|---|
| `qos-orchestrator` | 192.168.49.174:9200 | URLLC RTT, eMBB throughput, mMTC msg count, tc rate, state, violation/throttle/restore/loop counters |
| `tun-metrics` | 192.168.49.172:9100 | Tunnel-level per-interface byte counters |
| `embb-nginx` | 192.168.49.172:30880/status | nginx active connections, requests/s |
| `kubelet-cadvisor` | 192.168.49.174:10250, 192.168.49.172:10250 | Container CPU, memory by namespace (embb/urllc/mmtc) |
| `kubelet-resource` | 192.168.49.174:10250, 192.168.49.172:10250 | Node CPU, memory resource metrics |

### tun-metrics-exporter

- DaemonSet pod on kube: `tun-metrics-exporter-dts47`
- Image: `python:3.11-slim`
- Custom Python exporter reading per-uesimtun interface byte counters
- Exposed on port 9100 (ClusterIP `tun-metrics-exporter`)

---

## Orchestrator Metrics (port 9200)

Exported by `phase3-orchestrator.py` (rule-based) or `orchestrator_agentic/main.py` (agentic) — same port, mutually exclusive.

| Metric | Type | Description |
|---|---|---|
| `orchestrator_urllc_rtt_ms` | gauge | URLLC avg RTT parsed from urllc_client.py logs |
| `orchestrator_embb_mbps` | gauge | eMBB aggregate throughput (sum across all eMBB tunnels) |
| `orchestrator_mmtc_msgs_total` | gauge | Total MQTT messages published (cumulative) |
| `orchestrator_embb_rate_mbit` | gauge | Current tc bandwidth cap on ogstun-embb (1000=unthrottled) |
| `orchestrator_state` | gauge | 0=NORMAL, 1=THROTTLED |
| `orchestrator_violation_count` | gauge | Consecutive SLA violation counter (resets on recovery) |
| `orchestrator_recovery_streak` | gauge | Consecutive below-SLA loop counter |
| `orchestrator_throttle_total` | counter | Total throttle events since start |
| `orchestrator_restore_total` | counter | Total restore events since start |
| `orchestrator_loop_count` | counter | Total orchestrator loop iterations |
| `orchestrator_embb_replicas` | gauge | Current embb-app replica count |
| `orchestrator_mmtc_replicas` | gauge | Current mmtc-app replica count |

---

## Grafana

- Pod: `grafana-5cc7d4f67c-dstmv` (kubemaster, hostNetwork)
- Image: `grafana/grafana:10.4.1`
- NodePort: 30300 (http://192.168.49.174:30300)
- Datasource: Prometheus at http://192.168.49.174:30090

Dashboards configured:
1. **5G MEC Slice Overview** — URLLC RTT, eMBB throughput, mMTC msgs, tc rate, orchestrator state
2. **Kubernetes Resource Usage** — CPU/memory by namespace (from cAdvisor)
3. **Node Metrics** — Worker node CPU and memory

---

## Metric Flow (End-to-End)

```
urllc_client.py logs RTT samples to /tmp/mec-clients/urllc_uesimtunX.log
  ↓
phase3-orchestrator.py SSHes to UERANSIM VM, tails log files every 3s
  ↓
Parses: RTT avg, eMBB rate, mMTC msg count
  ↓
Updates in-memory state dict
  ↓
Exposes via HTTP server on :9200 (Prometheus text format)
  ↓
Prometheus scrapes :9200 every 5s
  ↓
Grafana queries Prometheus (live panels, 5s refresh)
  ↓
experiment_runner.py queries Prometheus API at :30090 every 3s
  ↓
Writes to CSV: experiments/results/exp_{level}_{orchestrator}_{ts}.csv
```
