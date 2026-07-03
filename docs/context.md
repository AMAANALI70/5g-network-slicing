# PROJECT CONTEXT RESTORATION – AGENTIC 5G NETWORK SLICING ORCHESTRATOR

## Project Goal

The objective of this project is to design, implement, and evaluate an **Agentic AI-Based Network Slice Orchestrator** for a real 5G network slicing testbed and compare it against a **Rule-Based Orchestrator**.

The research question is:

> Does an Agentic Orchestrator provide measurable benefits over a traditional Rule-Based Orchestrator in managing QoS and SLA compliance in a 5G network slicing environment?

The project is NOT focused on building an LLM application. The LLM is only one component of a larger autonomous closed-loop QoS orchestration framework.

---

# Current Status (as of 2026-06-04)

**Phase: FORMAL CAMPAIGN IN PROGRESS**

| Component | Status |
|---|---|
| Architecture | FROZEN |
| Monitoring | VALIDATED |
| Metrics Pipeline | VALIDATED |
| Behavioral Audits | PASSED (S1, S2, S3) |
| Execution Agent | FIXED — kubectl exec working |
| Rule-Based Orchestrator | Running during campaign |
| Agentic Orchestrator | Running during campaign |
| Prometheus / Grafana | RUNNING — http://192.168.49.174:30300 |
| Grafana Dashboards | FIXED (SLA 15ms, LLM panels added) |
| 18-Run Campaign | **RUNNING** — PID 1185457 |
| CSV collected | 3 / 18 (Rule-Based Trial 1 complete) |

---

# System Architecture

Infrastructure:

* Open5GS Core (192.168.49.143)
* UERANSIM RAN + UEs (192.168.49.139, user: shinegami, pass: 123)
* Kubernetes — kubemaster (192.168.49.174) + kube worker (192.168.49.173)
* kube2 (192.168.49.181): intentionally offline/disabled — does not affect experiment

Three slice categories:

* eMBB — ogstun-embb, namespace: embb, NodePort: 30880
* URLLC — ogstun-urllc, namespace: urllc, NodePort: 30180
* mMTC — ogstun-mmtc, namespace: mmtc, NodePort: 30883

Traffic shaping: Linux tc TBF qdisc on UPF interfaces via kubectl exec into UPF pod.

Monitoring stack:

* Prometheus — NodePort 30090
* Grafana — NodePort 30300 (http://192.168.49.174:30300, admin/admin)
* Orchestrator metrics — port 9200 (both orchestrators expose same endpoint)

Agent framework:

* LangGraph workflow
* Ollama local LLM (llama3.2:3b) — avg 36s inference latency (documented limitation)
* Monitoring Agent (SSH to UERANSIM, tail /tmp/mec-clients/*.log)
* Planning Agent (LLM with root_cause + lever_validity + WLA scoring)
* Validation Layer (safety, contradiction checks)
* Execution Agent (kubectl exec into UPF pod)
* Memory Agent (stores outcomes for future reasoning)

Control loop: Observe → Think → Validate → Act → Reflect → Learn

---

# Key Files

| File | Purpose |
|---|---|
| `phase3-orchestrator.py` | Rule-Based orchestrator (deterministic, SLA-triggered tc) |
| `orchestrator_agentic/main.py` | Agentic orchestrator (LangGraph + Ollama) |
| `orchestrator_agentic/execution_agent.py` | Agentic execution wrapper (importlib, kubectl fallback) |
| `orchestrator/execution_agent.py` | Unified execution agent (kubectl exec into UPF pod) |
| `experiments/experiment_runner.py` | Experiment data collection (20-col CSV) |
| `experiments/run_campaign.sh` | 18-run campaign automation script |
| `mec_restart.sh` | Full stack reset (UPF pods → AMF/SMF → UERANSIM → clients → rule-based orchestrator) |
| `launch_mec_clients.sh` | Launch traffic clients on UERANSIM VM |
| `monitoring/apply_dashboards.py` | Push dashboard YAMLs to Grafana API |
| `monitoring/fix_dashboards.py` | One-time dashboard consistency fixer |

---

# mec_restart.sh — Behaviour

Steps:
1. Restart UPF pods (embb, urllc, mmtc)
2. Restart AMF + SMFs on core VM
3. Restart UERANSIM (gNB + 3 UEs, sequential 4s gap)
4. Wait 55s for PDU session establishment (9 sessions)
5. Launch traffic clients via launch_mec_clients.sh
6. **Start rule-based orchestrator (phase3-orchestrator.py)**

> ⚠️ mec_restart.sh always starts the **RULE-BASED** orchestrator as the final step.
> The campaign script kills it and starts the appropriate orchestrator for each trial.
> If you run mec_restart.sh manually, you will get the rule-based orchestrator on port 9200.

---

# Orchestrator Switching

To switch from rule-based → agentic:
```bash
pkill -f "phase3-orchestrator.py"
cd /home/kube-master/k8s/orchestrator_agentic
nohup python3 main.py --fresh > /tmp/orchestrator_agentic.log 2>&1 &
# Wait 50-55s for Ollama warm-up before running experiments
```

To switch from agentic → rule-based:
```bash
pkill -f "orchestrator_agentic/main.py"
nohup python3 /home/kube-master/k8s/phase3-orchestrator.py > /tmp/orchestrator_ruleb.log 2>&1 &
# Wait 15s
```

Both orchestrators expose metrics on port 9200 (Prometheus format).

---

# SLA Thresholds (Aligned — Both Orchestrators)

```
URLLC_RTT_SLA_MS    = 15.0 ms     (3GPP TS 22.261 URLLC target)
EMBB_RATE_MAX       = 1000 Mbit
EMBB_RATE_FLOOR     = 50 Mbit
URLLC_MAX_REPLICAS  = 3
EMBB_MAX_REPLICAS   = 3
```

> ⚠️ context.md previously listed URLLC_RTT_SLA_MS = 20ms. This was wrong.
> The actual SLA in both orchestrators is 15ms. Grafana dashboards have been corrected to reflect this.

---

# Execution Agent — Fixed (2026-06-04)

## Problem
The agentic `execution_agent.py` imported itself (circular import — both files named `execution_agent.py`), causing `_HAS_REAL=False`. The SSH fallback then crashed with `NameError: name 'time' is not defined`. Even if SSH had worked, it used `tc class change` (HTB) which doesn't exist on the TBF-shaped interface.

## Fix Applied
`orchestrator_agentic/execution_agent.py`:
- Uses `importlib.util.spec_from_file_location` to load unified agent by absolute path (no circular import)
- Fallback is `_kubectl_exec_fallback()` — kubectl exec into UPF pod (not SSH)

`orchestrator/execution_agent.py`:
- `_exec_tc_legacy()` and `_exec_tc_change()` now use `_kubectl_exec_upf()` (not SSH + HTB)
- `_kubectl_exec_upf()` runs TBF qdisc commands inside the UPF pod (hostNetwork=true → affects host interface)

## Verified
```
[Executor] ✅ throttle_embb via kubectl exec (300ms)
[Act     ] ✅ throttle_embb → 500Mbit  err=None
[Reflect ] action=throttle_embb  executed=True  success=True
# Hardware: qdisc tbf 8016: root refcnt 2 rate 200Mbit — confirmed
```

---

# Grafana Dashboards — Fixed (2026-06-04)

4 dashboards in `/home/kube-master/k8s/monitoring/`:

| Dashboard | YAML File | UID |
|---|---|---|
| QoS Orchestrator — Autonomous Control Loop | grafana-orchestrator-dashboard.yaml | qos-orch-v3 |
| 5G Slice Applications | grafana-app-dashboard.yaml | slice-apps |
| Hierarchical QoS | grafana-hierarchical-dashboard.yaml | hierarchical-qos |
| 5G Network Slice Monitor | grafana.yaml | — (ConfigMap provisioned) |

## Fixes Applied
- SLA threshold: `vector(25)` → `vector(15)` (orchestrator dashboard, 2 places)
- RTT color thresholds: `yellow@20/red@25` → `yellow@12/red@15` (all 3 dashboards)
- Description: "SLA = 25ms" → "SLA = 15ms" (app dashboard)
- tc description: "50Mbit staircase" → correct TBF description
- Errors panel: added `{slice=~".+"}` filter (grafana.yaml)
- **New LLM row** in orchestrator dashboard: Agentic Mode, LLM Latency, LLM Confidence, Memory Success, Safety Overrides, Slice Replicas timeline

## How to Apply After Editing Dashboard YAMLs
```bash
# 1. Apply ConfigMaps to Kubernetes
kubectl apply -f /home/kube-master/k8s/monitoring/grafana-orchestrator-dashboard.yaml
kubectl apply -f /home/kube-master/k8s/monitoring/grafana-app-dashboard.yaml
kubectl apply -f /home/kube-master/k8s/monitoring/grafana-hierarchical-dashboard.yaml
kubectl apply -f /home/kube-master/k8s/monitoring/grafana.yaml

# 2. Restart Grafana to reload provisioned dashboards
kubectl rollout restart deployment/grafana -n monitoring
# If new pod stays Pending (hostPort conflict), force-delete old pod:
kubectl delete pod -n monitoring <old-pod-name> --force
```

> ⚠️ Grafana dashboards are provisioned via ConfigMaps — they cannot be updated via the Grafana API (returns 400 "Cannot save provisioned dashboard"). Always update the YAML and kubectl apply.

---

# 18-Run Formal Campaign

## Structure
```
Block A: Rule-Based Orchestrator
  Trial 1: levels low → medium → high (60 min)
  Trial 2: levels low → medium → high (60 min)
  Trial 3: levels low → medium → high (60 min)

Block B: Agentic Orchestrator
  Trial 1: levels low → medium → high (60 min)
  Trial 2: levels low → medium → high (60 min)
  Trial 3: levels low → medium → high (60 min)

Total: 18 runs × 20 min = 6h 14min estimated
```

## Commands
```bash
# Check campaign progress
tail -30 /home/kube-master/k8s/experiments/campaign_logs/campaign.log

# Count CSVs (should be 18 at completion)
ls /home/kube-master/k8s/experiments/results/campaign/*.csv | wc -l

# Check for failures
grep "FAILED\|Error\|Traceback" /home/kube-master/k8s/experiments/campaign_logs/campaign.log

# Check campaign is alive
pgrep -a bash | grep run_campaign
```

## Campaign Script
`/home/kube-master/k8s/experiments/run_campaign.sh`

- PID: 1185457 (started 2026-06-03 23:52 IST)
- Output: `experiments/results/campaign/`
- Logs: `experiments/campaign_logs/`
- Does mec_restart before each trial (not each level)
- Agentic trials include 55s Ollama warm-up wait

## CSV Schema (20 columns)
```
timestamp, load_level, orchestrator_type,
urllc_rtt_ms, embb_throughput_mbps, mmtc_msgs_total, embb_tc_rate_mbit,
orchestrator_state, violation_count, recovery_streak, throttle_total, restore_total,
loop_count, cpu_embb_cores, cpu_urllc_cores, cpu_mmtc_cores,
node_cpu_pct, mem_embb_mi, mem_urllc_mi, mem_mmtc_mi
```

Rows per 20-min run (after 2-min warm-up): ~108 rows (15s scrape interval).

## Run Invalidation Criteria
- RTT = 0.0ms for >60s (telemetry failure)
- 0 PDU sessions active at start
- Orchestrator crash (loop_count stops incrementing)
- Ollama failure (llm_used = 0 for agentic runs)
- Prometheus scrape failure
- Fewer than 60 rows after warm-up removal

## Recovery Procedure (interrupted run)
```bash
# 1. Check what was collected
ls experiments/results/campaign/
# 2. Full stack restart
bash mec_restart.sh
# 3. Restart campaign from current block/trial
# Edit run_campaign.sh to skip completed trials, or re-run individual level:
python3 experiments/experiment_runner.py --levels 1 --dwell 1200 \
  --output experiments/results/campaign --orchestrator rule_based
```

---

# Orchestrator Metrics (port 9200)

Both orchestrators expose on http://localhost:9200/metrics:

```
orchestrator_urllc_rtt_ms         # Live URLLC RTT (ms)
orchestrator_embb_mbps            # eMBB throughput (Mbps)
orchestrator_embb_rate_mbit       # Current tc cap (Mbit)
orchestrator_mmtc_msgs_total      # mMTC MQTT messages
orchestrator_mmtc_pdr             # Packet delivery ratio
orchestrator_state                # 0=NORMAL, 1=THROTTLED
orchestrator_violation_count      # Active SLA violations
orchestrator_recovery_streak      # Consecutive clean cycles
orchestrator_throttle_total       # Cumulative throttle events
orchestrator_restore_total        # Cumulative restore events
orchestrator_loop_count           # Control loop iterations

# Agentic-only:
orchestrator_agentic_mode         # 1=agentic active
orchestrator_llm_used             # 1=LLM reasoning active
orchestrator_llm_latency_ms       # Last inference latency
orchestrator_llm_confidence       # Last decision confidence
orchestrator_memory_success_rate  # Memory-assisted success rate
orchestrator_safety_overrides_total  # WLA override count
orchestrator_urllc_replicas       # Replica counts per slice
orchestrator_embb_replicas
orchestrator_mmtc_replicas
```

---

# Known Non-Critical Issues (Do Not Fix)

* kube2 node: SchedulingDisabled, Flannel CrashLoopBackOff. Impact: None.
* upf-embb-node2, upf-urllc-node2: Pending (kube2 offline). Impact: None.
* eMBB HLS clients: may stall (0 Mbps) after aggressive throttle (<150Mbit). URLLC RTT unaffected. Known behaviour.
* Ollama LLM latency: ~36s average, up to ~53s. Documented limitation. Monitoring decoupled.
* `orchestrator_mmtc_msgs_total`: may show 0 when mMTC log parsing doesn't match expected format. Non-critical.
* `tc_qdisc_sent_bytes`: always 0 with TBF qdisc (HTB-only metric). Grafana panel shows flat line — expected.

---

# Historical Issues Fixed (Do Not Re-Investigate)

* RTT averaging over dead tunnels → fixed (dead tunnels excluded)
* mMTC messages always 0 → fixed (SSH log tail)
* mMTC PDR formula inverted → fixed
* Memory outcome captured too early → fixed (captured next cycle)
* run_all.sh with wrong server IP (192.168.49.171) → replaced with launch_mec_clients.sh (192.168.49.172)
* ExecutionAgent SSH + HTB approach → replaced with kubectl exec + TBF
* Circular import in agentic execution_agent.py → replaced with importlib absolute path load
* `NameError: name 'time' is not defined` in agentic fallback → fixed (import time added, fallback uses kubectl)
* Grafana dashboards returning 400 on API push → use kubectl apply + rollout restart instead
* apply_dashboards.py reversing SLA fixes → section 2 (which patched 25ms→15ms→25ms) removed

---

# Architecture: FROZEN

DO NOT redesign architecture.
DO NOT add new features.
DO NOT redesign prompts.
DO NOT modify LangGraph workflow.
DO NOT modify memory architecture.

The project is in the **evaluation phase**. The only remaining tasks are:

1. ✅ Archive pre-validation data — DONE
2. ✅ Fix execution agent — DONE
3. ✅ Validate pilot run — DONE (191 rows, 4 throttle actions executed on hardware)
4. 🔄 **Run 18-run formal campaign** — IN PROGRESS (PID 1185457)
5. ⬜ Statistical analysis (Mann-Whitney U, Welch t-test, Mixed ANOVA)
6. ⬜ Generate final evaluation results
