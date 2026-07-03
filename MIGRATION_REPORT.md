# 5G Network Slicing — Codebase Migration Report

**Date:** 2026-07-02  
**Executed on:** kubemaster (192.168.49.174)  
**Destination:** `/home/kube-master/5g-network-slicing/`  

---

## 1. VM Discovery Summary

| VM Label | Hostname | IP | User | Status | Notes |
|----------|----------|----|------|--------|-------|
| kubemaster | kubemaster | 192.168.49.174 | kube-master | ✅ Local | K8s control plane |
| kube / y2 | kube | 192.168.49.171 | kube | ✅ Reachable | K8s worker, Ollama |
| kube2 | kube2 | 192.168.49.181 | kube2 | ❌ Offline | Worker node offline |
| shinegami / cloney2 | shinegami | 192.168.49.143 | shinegami | ✅ Reachable | Open5GS 5G core |
| shinegami / y2-ue | shinegami | 192.168.49.139 | shinegami | ✅ Reachable | UERANSIM + MEC |

> **kube2 (192.168.49.181) was offline.** Its manifests were covered via Kubernetes API export from kubemaster. No source-code content was expected on this node (pure worker).

---

## 2. Files Copied Per VM

### kubemaster (Local — /home/kube-master/k8s/)

| Source | Destination | Files |
|--------|------------|-------|
| `orchestrator_agentic/` | `orchestrator/` | ~40 files (main.py, agents, prompts, scenarios) |
| `monitoring/` | `monitoring/` | 13 files (Prometheus, Grafana, exporters) |
| `embb/`, `urllc/`, `mmtc/` | `kubernetes/deployments/` | 12 YAML files |
| `default-slice/` | `kubernetes/deployments/default-slice/` | 3 YAML files |
| `experiments/` | `experiments/` | 758 files (215 MB) |
| `results/` | `datasets/kubemaster-results/` | figures + CSVs |
| `report/` | `docs/research/report/` | LaTeX main.tex + assets |
| `paper/` | `docs/research/paper/` | journal_draft2.tex + assets |
| `phase3-orchestrator.py` | `orchestrator/` | Rule-based orchestrator v3 |
| `phase3-monitor.sh` | `scripts/` | Monitoring script |
| `baseline_audit.py` | `orchestrator/` | Baseline audit script |
| `mec_restart.sh` | `mec/scripts/` | MEC restart automation |
| `routing/` | `automation/routing/` | 3 files |
| `ghost/` | `mec/servers/ghost/` | Ghost app assets |
| `apps/` | `mec/servers/apps/` | App server code |
| `ue-clients/` | `mec/clients/kubemaster/` | UE client scripts |
| `inventory/` | `automation/inventory/` | Inventory scripts |
| `project_state/` | `docs/project_state/` | State snapshots |

### kube VM (192.168.49.171)

| Source | Destination | Files |
|--------|------------|-------|
| `agentic-ai-demo/` (git repo) | `orchestrator/agentic-demo/` | 16 files (agents, prompts, graph, tools) |
| `kubernetes/k8s/` | `kubernetes/kube-vm/` | Open5GS SMF configs + UPF YAMLs |
| `embb/`, `mmtc/`, `urllc/` Dockerfiles | `mec/servers/` | Docker app images |
| `embb.yaml`, `mmtc.yaml`, `urllc.yaml` | `kubernetes/deployments/` | Slice v1 manifests |
| TC qdisc rules | `traffic-control/kube-vm-tc-rules.txt` | Live TC state export |
| pip freeze | `docs/kube-vm-pip-freeze.txt` | Python deps |

**Ollama model:** `qwen3:8b` (5.2 GB) — remains on kube VM, not copied to repo (binary)

### shinegami @ 192.168.49.143 (Open5GS VM)

| Source | Destination | Files |
|--------|------------|-------|
| `/etc/open5gs/` | `open5gs/configs/` | 24 YAML files (amf, 3x smf, 3x upf, ausf, nrf, etc.) |
| `UERANSIM/config/` | `ueransim/configs/shinegami-143/` | 8 YAML configs |
| `UERANSIM/trained_models/` | `ml-models/trained/` | 22 files (.pt, .pkl, .png) |
| `datasets1/` | `datasets/shinegami-143/` | 27 MB datasets |
| `kubernetes/` | `kubernetes/shinegami-143/` | K8s YAMLs + app code |
| pip freeze | `docs/shinegami-143-pip-freeze.txt` | Python deps |

### shinegami @ 192.168.49.139 (MEC/UE VM)

| Source | Destination | Files |
|--------|------------|-------|
| `mec-clients/` | `mec/clients/` | 22 files (embb/urllc/mmtc v1+v2 clients) |
| `mec-scripts/` | `traffic-control/mec-scripts/` | 6 TC scripts |
| `model/` | `ml-models/training/` | ML pipeline + outputs |
| `datasets1/` | `datasets/shinegami-139/` | 676 MB datasets |
| `UERANSIM/config/` | `ueransim/configs/shinegami-139/` | 5 YAML configs |
| pip freeze | `docs/shinegami-139-pip-freeze.txt` | Python deps |

### Kubernetes Cluster (via kubectl)

| Resource | Destination | Count |
|----------|------------|-------|
| Namespaces | `kubernetes/exported/namespaces/` | 8 |
| Deployments | `kubernetes/exported/deployments/` | 6 per-ns files |
| Services | `kubernetes/exported/services/` | 6 per-ns files |
| Configmaps | `kubernetes/exported/configmaps/` | 5 per-ns files |
| Daemonsets | `kubernetes/exported/daemonsets/` | 1 |
| PVCs | `kubernetes/exported/pvc/` | 1 |
| PVs | `kubernetes/exported/pv/` | 1 |
| Jobs | `kubernetes/exported/jobs/` | 1 |
| Cronjobs | `kubernetes/exported/cronjobs/` | 1 |
| Ingress | `kubernetes/exported/ingress/` | 1 |
| Statefulsets | `kubernetes/exported/statefulsets/` | 1 |

---

## 3. Final Repository Statistics

| Directory | Files | Size |
|-----------|-------|------|
| orchestrator/ | 53 | 25 MB |
| kubernetes/ | 86 | 207 MB |
| open5gs/ | 42 | 308 KB |
| ueransim/ | 21 | 104 KB |
| monitoring/ | 13 | 156 KB |
| traffic-control/ | 6 | 40 KB |
| mec/ | 135 | 21 MB |
| ml-models/ | 49 | 11 MB |
| datasets/ | 97 | 695 MB |
| experiments/ | 758 | 207 MB |
| automation/ | 16 | 88 KB |
| scripts/ | 1 | 16 KB |
| docs/ | 48 | 9.5 MB |
| **TOTAL** | **1,347** | **~1.2 GB** |

---

## 4. Repository Tree (Top Level)

```
5g-network-slicing/
├── README.md                    ✅ Generated
├── LICENSE                      ✅ MIT
├── .gitignore                   ✅ Generated
├── requirements.txt             ✅ Aggregated
├── .env.example                 ✅ Template
├── orchestrator/                ✅ LangGraph multi-agent orchestrator
├── kubernetes/                  ✅ Manifests + kubectl export
├── open5gs/                     ✅ 24 config files
├── ueransim/                    ✅ gNB + UE configs for 3 slices
├── monitoring/                  ✅ Prometheus + Grafana dashboards
├── traffic-control/             ✅ TC/HTB scripts
├── mec/                         ✅ MEC clients + servers
├── ml-models/                   ✅ TCN models + training pipeline
├── datasets/                    ✅ 695 MB experiment data
├── experiments/                 ✅ Experiment scripts + results
├── automation/                  ✅ SSH automation + startup scripts
├── scripts/                     ✅ Helper utilities
└── docs/                        ✅ LaTeX reports + setup guides
```

---

## 5. Duplicates Detected & Resolved

| Item | VMs | Resolution |
|------|-----|-----------|
| UERANSIM configs | shinegami-143 + shinegami-139 | Both kept in separate subdirs |
| Open5GS configs | shinegami-143 + shinegami-139 | 143 used as primary (running core), 139 as `configs-vm139/` |
| datasets1/ | shinegami-143 + shinegami-139 | Both kept separately (different content) |
| kubernetes YAMLs | kube VM + kubemaster | Merged — kubemaster authoritative, kube-vm preserved as `kube-vm/` |
| orchestrator code | kube `agentic-demo/` + kubemaster `orchestrator_agentic/` | Both preserved — agentic-demo is experimental, orchestrator_agentic is production |

---

## 6. Missing / Unresolved Components

| Item | Status | Notes |
|------|--------|-------|
| kube2 VM files | ⚠️ MISSING | VM was offline — worker only, no unique project files expected |
| Open5GS subscriber database | ⚠️ Not exported | MongoDB data on shinegami-143 not backed up |
| Ollama model binary | ℹ️ Not copied | qwen3:8b (5.2GB) — reference via `ollama pull qwen3:8b` |
| Kubernetes Secrets | ⚠️ Placeholders only | Sensitive data (tokens, certs) not included — regenerate |
| `smf.yaml` / `upf.yaml` | ⚠️ Empty | Slice-specific configs exist (smf-embb, etc.) — standard smf.yaml was empty |
| UERANSIM binaries | ℹ️ Not copied | Source code in UERANSIM/src — rebuild with `make` |
| Grafana data (InfluxDB) | ℹ️ Not exported | Historical time-series data not backed up |
| cron jobs | ✅ | kubemaster-crontab.txt (empty — no active crons) |

---

## 7. Git Repository Status

```
Repository: /home/kube-master/5g-network-slicing/
Branch: master
Commits: 1
Files committed: ~1,200
```

---

## 8. Manual Actions Required Before GitHub Push

### Critical (required)

1. **Add `.env` to `.gitignore`** (already done — verify no secrets are committed):
   ```bash
   git -C /home/kube-master/5g-network-slicing log --all --full-history -- '*.env'
   ```

2. **Add remote origin**:
   ```bash
   cd /home/kube-master/5g-network-slicing
   git remote add origin https://github.com/<your-org>/5g-network-slicing.git
   git push -u origin master
   ```

3. **Redact kubeconfig** — the copied `kubernetes/configs/kubeconfig-template.yaml` contains cluster certificate data. Replace tokens/certs before pushing:
   ```bash
   # Remove actual credentials from kubeconfig before committing
   # Use placeholder values or omit entirely
   ```

4. **Large datasets** — 695 MB of CSV datasets exceed GitHub's 100MB file limit. Options:
   - Use **Git LFS**: `git lfs track "datasets/**/*.csv"`
   - Or add `datasets/` to `.gitignore` and host separately
   
5. **Backup MongoDB** (Open5GS subscriber database):
   ```bash
   sshpass -p '123' ssh shinegami@192.168.49.143 \
     'mongodump --db open5gs --out /tmp/open5gs-db && tar czf /tmp/open5gs-db.tar.gz /tmp/open5gs-db'
   sshpass -p '123' scp shinegami@192.168.49.143:/tmp/open5gs-db.tar.gz \
     /home/kube-master/5g-network-slicing/open5gs/subscriber-db-backup.tar.gz
   ```

### Recommended (before sharing)

6. **Add GitHub Actions CI** — add `.github/workflows/` for linting/testing

7. **Add Git LFS configuration** for `.pt`, `.pkl` model files

8. **Rename branch to `main`**:
   ```bash
   git -C /home/kube-master/5g-network-slicing branch -m master main
   ```

9. **Add `CHANGELOG.md`** documenting experiment phases

10. **Verify UERANSIM configs** match the running Open5GS AMF address (192.168.49.143)

---

## 9. Environment Summary

| Component | Version | VM |
|-----------|---------|-----|
| Python | 3.10.12 | all VMs |
| Kubernetes | 1.29.15 | kubemaster + kube |
| Open5GS | 2.7.x | shinegami-143 |
| UERANSIM | 3.4.x | shinegami-139, shinegami-143 |
| LangGraph | ≥0.2.0 | kubemaster |
| Ollama | latest | kube VM |
| Ollama Model | qwen3:8b | kube VM |
| Prometheus | latest | kubemaster + shinegami-139 |
| Grafana | latest | kubemaster |
| Flannel CNI | latest | kubemaster + kube |

---

*Migration completed: 2026-07-02 | Total transfer: ~1.2 GB | 1,347 files*
