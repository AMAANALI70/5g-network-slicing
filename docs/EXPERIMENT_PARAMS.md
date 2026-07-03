# EXPERIMENT_PARAMS.md
# =====================================================================
# Frozen experiment parameters for Rule-Based vs Agentic comparison.
# Last updated: 2026-06-01
# Status: LOCKED — no changes permitted after first data collection run.
# =====================================================================

## SLA Thresholds (identical for both orchestrators)

| Parameter | Value | Justification |
|---|---|---|
| URLLC_RTT_SLA_MS | **20.0 ms** | Measured healthy avg: 14–16ms, max: 17–20ms. 20ms gives 4–6ms headroom above healthy max, triggers only on genuine congestion. |
| EMBB_MIN_THROUGHPUT_MBPS | 20.0 Mbps | Minimum acceptable eMBB delivery rate |
| MMTC_MIN_PDR | 0.995 | 99.5% packet delivery ratio |

## eMBB Rate Control (identical for both orchestrators)

| Parameter | Value | Justification |
|---|---|---|
| EMBB_RATE_MAX | **1000 Mbit** | Effectively unconstrained; normal eMBB is ~185 Mbps |
| EMBB_RATE_FLOOR | **50 Mbit** | Minimum throttle; low enough to relieve GTP-U queue pressure |

## Rule-Based-Specific Parameters

| Parameter | Value | Notes |
|---|---|---|
| EMBB_THROTTLE_STEP | 200 Mbit | 20% of range — proportionally identical to original 20/100 |
| EMBB_RESTORE_STEP | 100 Mbit | 10% of range |
| COOLDOWN_SEC | 15 s | Min time between actions |
| STABILITY_WINDOW_SEC | 60 s | Seconds of stable RTT before restore |
| LOOP_INTERVAL_SEC | 3 s | Rule-based runs fast; cooldown governs action rate |

## Agentic-Specific Parameters

| Parameter | Value | Notes |
|---|---|---|
| OLLAMA_MODEL | llama3.2:3b | Selected model; llama3.1:8b permanently rejected |
| LLM_TEMPERATURE | 0.2 | Low temperature for consistent structured output |
| LLM_MAX_TOKENS | 300 | Sufficient for JSON + reasoning; limits generation cost |
| COOLDOWN_SEC (in agent) | 15 s | Aligns with typical inference latency |
| LOOP_INTERVAL_SEC | 0 | Runs at natural inference rate (~15–20s/cycle) |
| MEMORY_SIZE | 10 | Last 10 decisions in context |

## Action Space (PRIMARY comparison — both orchestrators)

| Action | Rule-Based | Agentic |
|---|---|---|
| throttle_embb | ✅ | ✅ |
| restore_embb | ✅ | ✅ |
| no_action | ✅ | ✅ |
| patch_replicas | ❌ (slice agents inactive due to key mismatch) | ❌ (suppressed in code) |
| adjust_quota | ❌ (global agent uses wrong metric keys) | ❌ (not in agentic action space) |
| patch_limits | ❌ (slice agents inactive) | ❌ (not in agentic action space) |

Note: Both orchestrators effectively operate on the same {throttle, restore, no_action} space.
patch_replicas will be evaluated in a separate extended-capability experiment.

## Traffic Profiles

| Condition | eMBB Client Rate | Expected eMBB Throughput | Expected URLLC Pressure |
|---|---|---|---|
| Low | 50 Mbps target | ~40–60 Mbps | Minimal; RTT should stay well below SLA |
| Medium | 150 Mbps target | ~130–170 Mbps | Moderate; occasional RTT spikes near SLA |
| High | 250 Mbps target | ~180–220 Mbps | High; RTT regularly exceeds SLA without throttling |

## Trial Design

| Dimension | Value |
|---|---|
| Trials per orchestrator per condition | 3 |
| Run duration per trial | 20 minutes |
| Warm-up period (excluded from analysis) | 2 minutes |
| Order | Randomized within conditions |
| Total runs | 3 conditions × 3 trials × 2 orchestrators = 18 runs |
| Total data collection time | ~7 hours |

## Pre-Registered Statistical Tests

| Comparison | Test | α |
|---|---|---|
| URLLC RTT distribution (agentic vs rule-based, per condition) | Mann-Whitney U | 0.05 |
| SLA violation rate (violations/min) | Welch's t-test | 0.05 |
| Unnecessary throttle events | Mann-Whitney U | 0.05 |
| Overall violation rate (2 systems × 3 conditions) | Mixed ANOVA | 0.05 |
| Effect size | Cohen's d (continuous), φ (proportions) | — |

## Pre-Registered Success/Failure Criteria

**Agentic outperforms rule-based IF:**
- URLLC violation rate significantly lower (p < 0.05) under Medium OR High traffic
- AND unnecessary throttle events not significantly higher

**Agentic underperforms IF:**
- Violation rate significantly higher under any condition

**Equivalent IF:**
- No significant difference found across all conditions and metrics

**Any result is a valid scientific finding.** The objective is measurement, not optimization.

## Integrity Guardrails

- No parameter changes after first run
- All 18 runs must be completed and reported
- Runs cannot be selectively excluded
- If a run is aborted (e.g., PDU session drop), it must be noted and re-run
- llm_used=False cycles must be logged; if >5% of any run, that run is flagged for review

## Infrastructure Checklist (before each run)

- [ ] 9/9 PDU sessions active (3 eMBB + 3 URLLC + 3 mMTC)
- [ ] Ollama service running (agentic runs only)
- [ ] tc qdisc on ogstun-embb reset to 1000Mbit (clean start)
- [ ] Agent memory flushed (--fresh flag, agentic only)
- [ ] Traffic profile script configured to correct rate
- [ ] Prometheus scraping both orchestrators
- [ ] Log files timestamped and saved to experiments/
