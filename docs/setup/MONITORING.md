# Monitoring Setup (Prometheus + Grafana)

## Access

- **Prometheus**: http://192.168.49.174:30090
- **Grafana**: http://192.168.49.174:30300 (admin/admin)

## Deploy

```bash
kubectl apply -f monitoring/prometheus/
kubectl apply -f monitoring/grafana/
kubectl apply -f monitoring/exporters/
```

## Dashboards

| Dashboard | Purpose |
|-----------|---------|
| Slice QoS Dashboard | Per-slice throughput, latency, packet loss |
| Orchestrator Dashboard | Agent decisions, WLA scores, action counts |
| Hierarchical Dashboard | Multi-level slice hierarchy view |
| App Performance Dashboard | MEC application metrics |

## Scrape Targets

- `kube-worker:9100` — node exporter (tun metrics)
- `open5gs-vm:9090` — Prometheus on Open5GS VM
- `orchestrator-svc:9200` — Orchestrator metrics

## Apply Dashboards

```bash
cd monitoring/
python apply_dashboards.py
```
