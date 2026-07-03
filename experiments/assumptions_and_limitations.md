# Assumptions and Limitations

**Document:** Phase 1 Architecture Freeze  
**Date:** 2026-06-01

This document records all known assumptions and limitations of the current system
before final experimental data collection begins.

---

## A. Measurement Assumptions

### A1 — RTT Measurement via SSH Log Tailing
**Assumption:** URLLC RTT is measured by SSH-tailing the last line of `urllc_uesimtun*.log` on the UERANSIM host. This reflects the 99th-percentile RTT within the UERANSIM HTTP client's rolling window.

**Implication:** The measured RTT includes:
- GTP-U encapsulation/decapsulation delay in the UPF pod
- Kubernetes CNI networking overhead
- Worker node scheduling jitter

**Limitation:** SSH polling adds ~50–200ms collection latency per cycle. This means the RTT value seen by the LLM is always 3–6 seconds stale relative to the actual network state. **This does not affect correctness** since the monitoring thread runs at 3s intervals and the LLM acts on macroscopic trends, not instantaneous samples.

### A2 — eMBB Throughput via Prometheus irate (30s window)
**Assumption:** eMBB throughput is derived from `irate(tun_tx_bytes{interface="ogstun-embb"}[30s])`.

**Limitation:** `irate` with a 30s window smooths out sub-second bursts. Peak burst throughput may be 20–40% higher than the reported value. The `embb_load_fraction` metric uses the raw packet counter from `/proc`, which is more responsive.

### A3 — mMTC PDR Measured Per-Tunnel, Not Per-Message
**Assumption:** mMTC Packet Delivery Ratio is computed as `ok_tunnels / total_tunnels` (fraction of mMTC TUN interfaces that have published at least 1 message in the last log line).

**Limitation:** This is a binary tunnel-level measurement. A tunnel that published 1/100 messages appears identical to one that published 100/100. True per-message PDR would require log format changes in the mMTC client. **Impact:** PDR metric will appear 1.0 in most conditions and is not sensitive enough to detect mild mMTC degradation. This is noted but not addressed pre-experiment.

### A4 — embb_load_fraction Cold-Start Guard
**Assumption:** `embb_load_fraction` returns `None` until 5 non-zero packet rate samples are collected (cold-start guard).

**Implication:** During the first ~15 seconds of orchestrator startup, the LLM receives `N/A` for `embb_load_fraction` and must rely on `embb_pkt_rate` direction instead. **Mitigation:** Always wait 60s after `mec_restart.sh` before starting an experiment trial.

---

## B. Control Architecture Assumptions

### B1 — tc HTB Applied to Egress Only (UPF → UE Direction)
**Assumption:** `tc class change` is applied to the `ogstun-embb` interface in the egress direction (UPF → UE, i.e. downlink).

**Limitation:** Uplink traffic (UE → UPF) is not shaped. For the current test scenario (HLS video streaming, predominantly downlink), this is the correct direction. Any future uplink-heavy application would require separate qdisc configuration.

### B2 — Single Worker Node (No Multi-Node UPF)
**Assumption:** All three UPF pods (eMBB, URLLC, mMTC) run on a single worker node (`192.168.49.171`).

**Limitation:** There is no UPF redundancy or load balancing. A worker node failure terminates all three slices simultaneously. Horizontal UPF scaling would require resolving PFCP/GTP-U port conflicts and kernel TUN device name collisions (documented in `mec_restart.sh` comments).

### B3 — LLM Inference Latency Accepted as Design Constraint
**Assumption:** The current system accepts 20–35 second LLM inference latency per cycle as acceptable for the macroscopic QoS control timescale.

**Limitation:** URLLC SLA violations that are resolved within a single 3-second monitoring interval may recover before the LLM can even observe them. The decoupled monitoring thread mitigates this by providing continuous RTT tracking independent of the LLM cycle. **Known gap:** Very short-lived spikes (<6s) are never actioned by the LLM but are still counted as SLA violations in the metrics.

### B4 — Memory Ring Buffer Does Not Persist Across Restarts
**Assumption:** Agent memory is in-process only (Python deque). It is lost when the orchestrator process restarts.

**Implication:** Each trial starts with a clean slate (enforced by `--fresh`). Cross-session learning is not implemented. This is by design for experimental repeatability.

---

## C. Experimental Limitations

### C1 — Small Sample Size (3 Trials per Condition)
**Limitation:** With only 3 trials per condition, statistical power is low. Mann-Whitney U tests at n=3 per group have limited sensitivity. **Mitigation:** This is an M.Tech dissertation level experiment; 3 trials per condition is appropriate for the scope. Results are treated as indicative rather than definitive.

### C2 — Controlled Lab Environment (Not Production)
**Limitation:** The testbed uses UERANSIM (emulated UEs, not real UE hardware) and Open5GS (software-only 5GC, no hardware acceleration). Real-world deployment would introduce additional sources of variance (radio channel, real UE firmware, RF interference).

### C3 — Fixed Traffic Generator (No Adaptive Application)
**Limitation:** The eMBB HLS traffic generator does not adapt to network conditions (no ABR logic). A real video player would reduce bitrate when throughput drops, masking the impact of eMBB throttling. **Implication:** The throughput loss measured in this experiment is an upper bound; real adaptive video clients would experience lower perceived degradation.

### C4 — LLM Non-Determinism
**Limitation:** Even at temperature=0.2, the LLM output is not fully deterministic. Identical input states may produce different reasoning traces and actions across trials. **Mitigation:** Averaged over 30-minute trials with ~60–80 LLM cycles, the stochastic variation is averaged out. Individual cycle traces are logged for post-hoc inspection.

### C5 — Prometheus Scrape Interval (15s) vs Monitor Interval (3s)
**Limitation:** Prometheus scrapes the orchestrator at 15-second intervals, while the monitoring thread updates every 3 seconds. Short-lived metric spikes (3–12s duration) may be missed in the Prometheus time-series. **Mitigation:** All high-resolution data is in `cot_traces.jsonl` (one record per LLM cycle, ~25–30s resolution).

---

## D. Safety Constraints in Force

| Constraint | Implementation | Rationale |
|---|---|---|
| eMBB rate floor: 50 Mbit | `EMBB_RATE_FLOOR` in config | Prevents complete eMBB starvation |
| LLM cooldown: 15s | `_cooldown_sec` in LLMPlanningAgent | Prevents rapid oscillation |
| Contradiction detection | `llm_planning_agent._parse_response()` | WLA — halves confidence on wrong lever |
| Redundant-action guard | ValidationGate | Skips tc call if rate unchanged |
| Dead-tunnel guard | Validation + monitoring | Blocks decisions when monitoring unreliable |
| Fallback to rule-based | `_rule_based_fallback()` | LLM timeout > 60s → deterministic safety net |

---

## E. Campaign v2 Throughput Ceiling — Bottleneck Analysis

**Date:** 2026-06-04  
**Context:** Phase C pilot measured 135–189 Mbps despite a 1 Gbit/s tc rate on `ogstun-embb`.

### E1 — Why is the ceiling ~190 Mbps, not 1 Gbps?

Four potential bottlenecks were investigated:

| Layer | Value | Bottleneck? |
|-------|-------|-------------|
| `tc tbf` rate on `ogstun-embb` | 1000 Mbit (set after orchestrator stopped) | **No** — not the constraint |
| GTP-U encapsulation overhead | 36 B / 1400 B MTU = 2.5% | **No** — negligible |
| UPF pod CPU during transfer | 454–456 m cores at 190 Mbps | **No** — <50% utilised |
| **nginx-hls pod CPU limit** | **500 m cores (hard K8s limit)** | **Yes — primary bottleneck** |

**Conclusion:** The nginx pod's CPU budget caps static-file serving at approximately **250 Mbps**. With three concurrent UE connections and GTP overhead, the observed ceiling of ~190–199 Mbps (≈76–80% of the nginx limit) is consistent with this constraint.

### E2 — How load differentiation actually works in v2

Since the tc rate and UPF are not the binding constraints, the three load levels are differentiated by **eMBB session/break duty cycle**:

| Level | Quality | Duty cycle | Observed mean | Std dev | Mechanism |
|-------|---------|-----------|---------------|---------|-----------|
| Low   | 360p    | ~37%      | 135.3 Mbps    | 57.3    | Long breaks (20–40 s) reduce average |
| Med   | 720p    | ~72%      | 175.9 Mbps    | 17.3    | Moderate breaks (8–15 s) |
| High  | 1080p   | ~86%      | 189.3 Mbps    | 7.9     | Short breaks (3–8 s), near-continuous |

**Cohen's d effect sizes (all large):**
- Low vs High: d = 1.32
- Low vs Med: d = 0.96
- Med vs High: d = 1.00

### E3 — Implications for the experiment

1. **The load factor is the eMBB duty cycle, not bitrate per segment.** Larger segments (1080p = 4.72 MB) download faster per session but don't increase the ceiling. Differentiation comes from how long the UE rests between sessions.

2. **The 360p high variance (CV = 42%) is expected and desirable.** It reflects natural on/off traffic — a realistic IoT/streaming mix. The agentic orchestrator must handle this variance, which tests adaptability beyond what a constant-rate load could.

3. **The throughput ceiling is a testbed property, not a bug.** Increasing the nginx CPU limit to 2000 m would raise the ceiling to ~1 Gbps but would not change the experimental comparison (both orchestrators see the same ceiling). The ceiling is documented as an assumption, not a flaw.

4. **The URLLC RTT response to eMBB load is valid regardless of the ceiling.** GTP queue pressure builds when the UPF processes eMBB traffic above ~100 Mbps. The orchestrator's throttle response to RTT elevation — which is what the experiment measures — is not affected by whether the ceiling is 190 Mbps or 1 Gbps.

### E4 — Reporting guidance

In the paper, describe load levels as:
> "Three offered-load levels are implemented via eMBB session duty cycles of approximately 37%, 72%, and 86%, producing mean UPF throughputs of 135, 176, and 189 Mbps respectively (measured at the `ogstun-embb` interface via Prometheus `tun_tx_bytes` counters). The testbed ceiling of ~190 Mbps is bounded by the nginx pod's 500 m-core CPU allocation; tc shaping (1 Gbit/s) and GTP overhead (2.5%) are not binding constraints."
