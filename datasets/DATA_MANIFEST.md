# Dataset Manifest

## Overview

The full dataset is **~696 MB** and is NOT committed to this repository due to GitHub's 100MB file limit.  
Datasets are stored locally on kubemaster at `/home/kube-master/5g-network-slicing/datasets/` and on the source VMs.

## Dataset Contents

### shinegami-139/ (646 MB) — UE-side + MEC Telemetry

Collected on the UERANSIM/MEC VM (192.168.49.139).

| Subdirectory | Description | Approx. Size |
|-------------|-------------|--------------|
| `static1/ue_qos_static_ran.csv` | UE QoS static RAN scenario (raw) | 562 MB |
| `static1/ue_qos_static_ran_trimmed.csv` | Trimmed version | ~50 MB |
| `predictive/` | Predictive controller experiment logs | ~30 MB |
| Other CSV files | Various experiment runs | remaining |

**Key columns:** timestamp, slice_type, ue_id, throughput_mbps, latency_ms, packet_loss_pct, jitter_ms, rssi_dbm, sinr_db

### shinegami-143/ (26 MB) — Core Network Telemetry

Collected on the Open5GS VM (192.168.49.143).

| Subdirectory | Description |
|-------------|-------------|
| `predictive/` | Core network metrics + research controller logs |
| Various CSVs | SMF/UPF session telemetry |

### kubemaster-results/ (24 MB) — Orchestrator Evaluation

Results from the agentic orchestrator evaluation campaigns.

| Subdirectory | Description |
|-------------|-------------|
| `figures/` | Publication-quality plots (.pdf + .png) |
| Campaign CSVs | Per-scenario QoS measurement records |

## Reproducing the Dataset

```bash
# Re-collect from shinegami VMs
sshpass -p '123' rsync -av shinegami@192.168.49.143:/home/shinegami/datasets1/ ./shinegami-143/
sshpass -p '123' rsync -av shinegami@192.168.49.139:/home/shinegami/datasets1/ ./shinegami-139/

# Or re-run the collection pipeline
cd ../experiments/
python experiment_collector.py --duration 3600 --slices embb urllc mmtc
```

## Archive Location

A compressed archive of all datasets is available at:
- kubemaster: `/home/kube-master/k8s/results.zip` (16.5 MB compressed results)

## Citation

If using this dataset, please cite the associated paper:
> "Autonomous QoS-Aware 5G Network Slice Orchestration using LangGraph Multi-Agent Systems" (2026)
