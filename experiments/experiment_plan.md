# Experiment Plan: Rule-Based vs Agentic 5G QoS Orchestrator

**Status:** Frozen for data collection  
**Date:** 2026-06-01  
**Version:** 1.0 (pre-registered)

---

## 1. Hypothesis

**H1 (SLA Compliance):**  
The Agentic Orchestrator achieves higher URLLC SLA compliance ($C_{\text{sla}}$) than the Rule-Based controller across mixed-load traffic conditions.

**H2 (Wrong-Lever Avoidance):**  
The Agentic Orchestrator correctly abstains from eMBB throttling when `embb_load_fraction < 0.2` at a higher rate than the Rule-Based controller (Rule-Based never abstains; Agentic should abstain ≥ 3× per session).

**H3 (eMBB Preservation):**  
The Agentic Orchestrator causes significantly less eMBB throughput loss than Rule-Based during equivalent URLLC congestion events.

**H4 (Recovery Latency):**  
Agentic mean recovery latency $T_{\text{rec}}$ is < 50% of Rule-Based $T_{\text{rec}}$ due to Memory-Assisted decision making.

---

## 2. Experimental Conditions

| Factor | Rule-Based | Agentic |
|---|---|---|
| Controller | Threshold logic (`orchestrator/`) | LangGraph + LLM (`orchestrator_agentic/`) |
| SLA threshold | RTT < 20ms | RTT < 20ms |
| eMBB rate floor | 50 Mbit | 50 Mbit |
| eMBB rate ceiling | 1000 Mbit | 1000 Mbit |
| Memory | None | 10-entry ring buffer |
| CoT reasoning | None | Mandatory JSON schema |

---

## 3. Traffic Profiles

All three scenarios use real UERANSIM traffic (no netem for final runs).

### Profile A — Mixed Normal Load (Baseline)
- eMBB: HLS video streaming, ~280 Mbps peak, natural bursty pattern
- URLLC: HTTP POST 10 req/s, 32-byte payload
- mMTC: MQTT publish 1 msg/s per UE (3 UEs)
- Duration: 30 minutes

### Profile B — High eMBB Stress (Congestion Test)
- Same as A but eMBB iperf3 burst injected every 5 minutes (60s bursts)
- Designed to trigger URLLC SLA violations repeatedly
- Duration: 30 minutes

### Profile C — Low eMBB, Elevated RTT (Wrong-Lever Test)
- eMBB at ~10% load (idle video app)
- URLLC traffic identical to A
- Duration: 15 minutes (S2 verification only)

---

## 4. Measurement Protocol

### Trial Structure
- **3 trials** per condition (Rule-Based A, B; Agentic A, B)
- **30 minutes** per trial
- **15-minute warm-up** discarded from analysis
- **Fresh memory** flag (`--fresh`) before each Agentic trial
- **60-second settling time** after `mec_restart.sh` before any trial starts

### Data Collection
All metrics collected automatically via:
1. `logs/cot_traces.jsonl` — one record per LLM cycle
2. Prometheus scrape (15s interval) → persistent time-series
3. Grafana dashboard screenshots at t=0, 15, 30 minutes

---

## 5. Primary Metrics

| Metric | Formula | Unit |
|---|---|---|
| SLA Compliance $C_{\text{sla}}$ | `1 - N_violations / N_cycles` | ratio |
| Recovery Latency $T_{\text{rec}}$ | `t_clear - t_breach` | seconds |
| eMBB Throughput Loss | `Σ (r_max - r(t)) × Δt` | Gbps·min |
| Action Efficiency $\eta$ | `correct_throttles / total_throttles` | ratio |
| WLA Events Caught | `wla_total` from cot_traces | count |
| Lever Validity Score | `mean(lever_validity_score)` | 0–1 |
| LLM Decision Latency | `mean(llm_ms)` | ms |
| Monitor Cycle Latency | `mean(collect_ms)` | ms |

---

## 6. Analysis Plan

1. **Descriptive statistics**: mean ± std for each metric per condition
2. **Mann-Whitney U test** (non-parametric, 3 trials each): H1, H3, H4
3. **Proportion test**: H2 (WLA events Agentic vs 0 for Rule-Based)
4. **Significance threshold**: p < 0.05

---

## 7. Behavioral Audit (Pre-Experiment Verification)

Before main data collection, all three scenarios must pass:

| Scenario | Condition | Pass Criterion | Tool |
|---|---|---|---|
| S1 | High eMBB load, rising RTT | `throttle_embb` before RTT > 20ms | `run_scenario.py --scenario S1` |
| S2 | Low eMBB load, elevated RTT | `no_action` despite RTT violation | `run_scenario.py --scenario S2` |
| S3 | Throttled + stable + memory | `restore_embb` citing prior outcomes | `run_scenario.py --scenario S3` |

**Gate:** All S1/S2/S3 must show PASS or PARTIAL before proceeding to main runs.

---

## 8. Infrastructure Checklist (Before Each Trial)

```bash
# 1. Restart testbed
./mec_restart.sh

# 2. Wait 60s, verify UEs attached
kubectl get pods -A | grep -E "upf|ueransim"

# 3. Validate observability pipeline
cd orchestrator_agentic && python3 validate_metrics_pipeline.py --once

# 4. Start appropriate controller
# Rule-Based:
python3 orchestrator/main.py

# Agentic (fresh memory):
python3 orchestrator_agentic/main.py --fresh

# 5. Record trial start timestamp (for Grafana time range)
echo "Trial start: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

---

## 9. Deliverables

| Deliverable | Location |
|---|---|
| CoT trace JSONL (per trial) | `orchestrator_agentic/logs/cot_traces.*.jsonl` |
| Behavioral audit reports | `experiments/reports/S1_*.json`, `S2_*.json`, `S3_*.json` |
| Prometheus time-series | Grafana export (PNG + CSV) |
| KPI summary table | `experiments/kpi_summary.csv` (post-analysis) |
