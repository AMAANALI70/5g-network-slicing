# Section 2 — Kubernetes Architecture

## Nodes

```
NAME         STATUS                     ROLES           AGE   VERSION    INTERNAL-IP
kube         Ready                      worker          52d   v1.29.15   192.168.49.173
kube2        Ready,SchedulingDisabled   worker          52d   v1.29.15   192.168.49.181
kubemaster   Ready                      control-plane   52d   v1.29.15   192.168.49.174
```

Node labels:
- kube, kube2: `role=mec`, `node-role.kubernetes.io/worker=worker`
- kubemaster: `role=control`, taint `node-role.kubernetes.io/control-plane:NoSchedule`
- kube2: taint `node.kubernetes.io/unschedulable:NoSchedule`

Flannel VXLAN overlay: pod CIDR `10.244.0.0/16`, VNI=1

---

## Namespaces

| Namespace | Purpose |
|---|---|
| embb | eMBB slice — UPF + nginx app |
| urllc | URLLC slice — UPF + Node-RED |
| mmtc | mMTC slice — UPF + Mosquitto + InfluxDB |
| monitoring | Prometheus + Grafana + tun-metrics-exporter |
| orchestrator | qos-orchestrator service (ClusterIP) |
| default-slice | Default / fallback app |
| kube-system | K8s system components |
| kube-flannel | Flannel CNI |

---

## Pod Inventory (Running)

| Namespace | Pod | Node | IP |
|---|---|---|---|
| embb | upf-embb-5d448f6f78-nr6s5 | kube | 192.168.49.173 (hostNet) |
| embb | embb-app-78fdbdbc8-gtf4p | kube | 10.244.2.53 |
| urllc | upf-urllc-5bc8dfb7f6-98kjn | kube | 192.168.49.173 (hostNet) |
| urllc | urllc-app-76dbdf578c-qdl5l | kube | 10.244.2.56 |
| urllc | urllc-app-76dbdf578c-lgcg7 | kube | 10.244.2.61 |
| mmtc | upf-mmtc-8549b975ff-s65rl | kube | 192.168.49.173 (hostNet) |
| mmtc | mmtc-app-77899f7894-n9dxw | kube | 10.244.2.58 |
| mmtc | influxdb-7b4c95fd84-9zd8z | kube | 10.244.2.55 |
| monitoring | prometheus-f8687d7d5-4qvdx | kubemaster | 10.244.0.36 |
| monitoring | grafana-5cc7d4f67c-dstmv | kubemaster | 192.168.49.174 (hostNet) |
| monitoring | tun-metrics-exporter-dts47 | kube | 192.168.49.173 (hostNet) |
| default-slice | default-app-6c7cf49ff7-2qld2 | kube | 10.244.2.57 |
| kube-system | metrics-server-5b669d5f6f-d5w8v | kube | 10.244.2.54 |

> All UPF pods use `hostNetwork: true`. They bind directly to the worker node's
> network interfaces and create ogstun-embb/urllc/mmtc tunnel devices on the host.

---

## Services

| Namespace | Service | Type | Port Mapping |
|---|---|---|---|
| embb | embb-app | NodePort | 8080 → 30880 |
| embb | upf-embb-metrics | ClusterIP | 9090 |
| urllc | urllc-app | NodePort | 1880 → 30180 |
| urllc | upf-urllc-metrics | ClusterIP | 9091 |
| mmtc | mmtc-app | NodePort | 1883 → 30883, 9001 → 30901 |
| mmtc | influxdb | NodePort | 8086 → 30886 |
| monitoring | prometheus | NodePort | 9090 → 30090 |
| monitoring | grafana | NodePort | 3000 → 30300 |
| orchestrator | qos-orchestrator | ClusterIP | 9200 |

---

## Deployments

| Namespace | Deployment | Ready | Notes |
|---|---|---|---|
| embb | upf-embb | 1/1 | hostNetwork UPF |
| embb | embb-app | 1/1 | nginx HLS server |
| urllc | upf-urllc | 1/1 | hostNetwork UPF |
| urllc | urllc-app | 2/2 | Node-RED (scaled to 2 during pilot) |
| mmtc | upf-mmtc | 1/1 | hostNetwork UPF |
| mmtc | mmtc-app | 1/3 | Mosquitto (desired 3, constrained by quota) |
| mmtc | influxdb | 1/1 | Time-series DB |
| monitoring | prometheus | 1/1 | |
| monitoring | grafana | 1/1 | |

---

## Resource Quotas

| Namespace | CPU Requests / Limit | Memory Requests / Limit | Pods |
|---|---|---|---|
| embb | 400m / 1600m (max 2200m) | 768Mi / 2Gi (max 8Gi) | 3/20 |
| urllc | 600m / 2000m (max 3/6) | 768Mi / 2Gi (max 3/6Gi) | 4/20 |
| mmtc | 200m / 1000m (max 1100m) | 384Mi / 1536Mi (max 6Gi) | 3/20 |
| default-slice | 50m / 250m (max 500m) | 32Mi / 128Mi | — |

> mmtc-quota was patched from 900m→1100m CPU limit to allow upf-mmtc scheduling.
> embb and urllc quotas have substantial headroom for autoscaling.

---

## Scheduling Rules

- All UPF pods: `hostNetwork: true` — must land on a worker with N3 reachability
- kubemaster: `NoSchedule` taint — only system pods + monitoring land here
- kube2: `NoSchedule` (unschedulable) — nothing schedules here currently
- kube: only schedulable worker — receives all slice workloads
- No explicit nodeAffinity or nodeSelector observed on slice pods
  (UPFs land on kube by default since it is the only schedulable worker)
