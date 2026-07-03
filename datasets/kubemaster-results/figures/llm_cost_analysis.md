# LLM Cost and Utilisation — Analysis Report

## Methodology

### Part A — LLM Invocation Statistics
- **Source**: `experiments/results/campaign/exp_*_agentic_*.csv`
- `loop_count` = total decision cycles executed by orchestrator
- `throttle_total` + `restore_total` = total execution actions taken
- LLM calls = loop_count (one LLM call per orchestration cycle, confirmed by code)
- **Total cycles across all agentic runs**: 1,041
- **Total execution actions**: 464
- **Action rate**: 44.6% of cycles resulted in action

### Part B — Token Usage
- **Source**: `results/datasets/dataset_agentic_medium.csv`, column: `tokens_used`
- **WARNING**: These are ESTIMATED token counts, not real API logs.
  Token counts were not instrumented in the live campaign collector.
- **Mean tokens/decision**: 320
- **Assumption**: 70% input (prompt) / 30% output (completion)

### Part C — Cost Estimation
- Based on public API pricing rates (June 2026)
- **Important**: Groq was used locally in this study — no real API cost was incurred.
  Costs shown are equivalent commercial deployment costs.

| Provider | Per Decision | Per Run | Per Hour |
|----------|-------------|---------|---------|
| Groq (llama-3.3-70b) | $0.000208 | $0.2167 | $0.2498 |
| GPT-4o (equivalent) | $0.002562 | $2.6666 | $3.0739 |
| Claude Sonnet (equiv.) | $0.002113 | $2.2000 | $2.5360 |

### Part D — Decision Latency Decomposition
- **Source**: `results/datasets/dataset_agentic_medium.csv`, column: `decision_latency_ms`
- `decision_latency_ms` is the real end-to-end logged latency.
- Stage decomposition is an **architectural estimate** based on known bounds:
  | Stage | Estimate | Basis |
  |-------|----------|-------|
  | Monitoring (Prometheus) | ~8ms | Typical scrape interval |
  | Memory retrieval | ~5ms | In-process sliding window |
  | Execution (tc via SSH) | ~7ms | Measured SSH+tc overhead |
  | LLM inference | Remainder | = total - 20ms fixed |

## Assumptions
1. Loop interval: 3 seconds (configured in orchestrator)
2. Token split: 70% input, 30% output
3. Groq llama-3.3-70b-versatile pricing: $0.59/1M input, $0.79/1M output
4. Stage decomposition is estimated, not instrumented

## Data Integrity Statement
- Part A metrics derived from real campaign log counters
- Part B token counts are estimated (column generated, not API-logged)
- Part C costs are hypothetical commercial equivalents
- Part D total latency is real; stage breakdown is estimated