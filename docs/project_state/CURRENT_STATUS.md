# CURRENT STATUS
**Last updated:** 2026-06-06 12:27 IST  
**Updated by:** Antigravity AI assistant

---

## 5-Minute Summary for New Engineers

This project runs an 18-run factorial evaluation comparing a **rule-based** vs **agentic (LLM-driven)** 5G QoS orchestrator across 3 load levels (LOW/MEDIUM/HIGH) × 3 trials each. The testbed is an Open5GS 5G core on Kubernetes with UERANSIM UEs.

---

## Campaign Completion

| Cell | RB Valid | AG Valid | Status |
|------|----------|----------|--------|
| LOW | 3/3 ✅ | 3/3 ✅ | Complete |
| MEDIUM | 3/3 ✅ | **1/2 ❌** | Needs 2 more AG runs |
| HIGH | 3/3 ✅ | **1/2 ❌** | Needs 2 more AG runs |

**Total valid runs: 16 / 18**  
Missing: 2 valid AG MEDIUM + 2 valid AG HIGH runs (4 runs × 20 min = 80 min data + overhead)

> Note: 2 AG MEDIUM and 2 AG HIGH files exist but are INVALID (eMBB≈0.0 throughout).  
> Files: `exp_medium_agentic_20260605_122510.csv`, `exp_high_agentic_20260605_124540.csv`  
> These must be DELETED and re-collected.

---

## Current System State (Verified 2026-06-06 12:27 IST)

| Component | State | Evidence |
|-----------|-------|---------|
| Orchestrator (port 9200) | ❌ DOWN | `fuser 9200/tcp` → free |
| Prometheus | ✅ UP | `/api/v1/targets` returns `[up]` for 4 targets |
| `qos-orchestrator` Prometheus target | ❌ DOWN | Returns `[down]` — orchestrator not running |
| UPF-eMBB pod | ✅ Running (20h) | `kubectl get pod -n embb` |
| UPF-URLLC pod | ✅ Running (23h) | `kubectl get pod -n urllc` |
| eMBB GTP wire rate | ❌ **0.00 Mbps** | `ogstun-embb` counter delta = 0B over 5s |
| eMBB UE (nr-ue) | ⚠️ Running, IP=10.45.0.5 | `ps aux` + `ip addr` on UERANSIM |
| eMBB clients | ⚠️ 3 running, but producing 0 traffic | `pgrep embb_client` |
| URLLC UE | ✅ Running | `ip addr` shows `uesimtun1 10.46.0.5/24` |
| Ollama | ✅ Running (PID 1099) | `ps aux` |
| Supplemental campaign | ❌ STOPPED | No supplemental process running |
| Grafana dashboard | ❌ Flat lines | `qos-orchestrator` target down |

---

## Active Blocker

**eMBB GTP tunnel broken** — traffic from eMBB UEs is not reaching the UPF.

### Evidence
```
Command: kubectl exec -n embb deploy/upf-embb -- cat /sys/class/net/ogstun-embb/statistics/tx_bytes (×2, 5s apart)
Output:  T1=1181618192766  T2=1181618192766  delta=0B
Conclusion: VERIFIED ZERO — no traffic traversing ogstun-embb
```

```
Command: curl --interface 10.45.0.5 --max-time 8 http://192.168.49.172:30880/ on UERANSIM
Output:  HTTP:000 bytes:0
Conclusion: eMBB UE cannot reach nginx via its PDU session
```

### Root Cause (Verified)
- eMBB UE re-registered after last `mec_restart` and received IP **10.45.0.5** (stale sessions .2/.3/.4 still in SMF caused IP pool exhaustion at .5)
- UPF logs show **no PFCP session for 10.45.0.5** was created
- The UPF has sessions for .2/.3/.4 (from PFCP push after restart), but these UEs' `nr-ue` processes are dead
- Traffic from uesimtun0 (10.45.0.5) hits a GTP path with no active bearer → silently dropped

### Root Cause of Root Cause
`mec_restart.sh` force-deletes UPF pods (`kubectl delete pod -n embb -l app=upf-embb --force`) on every run. When the UPF restarts, the SMF re-pushes stale PDU session context. The UE process restart has a timing race — if the UE registers before the SMF clears its stale sessions, the UE gets a new IP from the next available slot.

---

## What Grafana Shows (and Why)

Grafana panels showing `orchestrator_embb_mbps`, `orchestrator_urllc_rtt_ms`, etc. are all flat because the **Prometheus target `qos-orchestrator` is DOWN** — no orchestrator is running on port 9200.

---

## Next Required Actions

1. **Delete invalid AG CSV files** (before any new run)  
2. **Fix GTP path** via proper mec_restart sequence (see KNOWN_ISSUES.md)  
3. **Verify GTP is live** before starting experiment (UPF counter delta > 0)  
4. **Collect 2 × (AG MEDIUM + AG HIGH)** = 2 trials  
5. **Update EXPERIMENT_HISTORY.md** when complete

---

## File Locations

| Item | Path |
|------|------|
| Campaign CSVs | `/home/kube-master/k8s/experiments/results/campaign/` |
| Campaign logs | `/home/kube-master/k8s/experiments/campaign_logs/` |
| Supplemental log | `campaign_logs/supplemental.log` |
| Experiment runner | `experiments/experiment_runner.py` |
| Supplemental script | `experiments/run_supplemental.sh` |
| mec_restart script | `mec_restart.sh` |
| Agentic orchestrator | `orchestrator_agentic/main.py` |
| Rule-based orchestrator | `phase3-orchestrator.py` |
