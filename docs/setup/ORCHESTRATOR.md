# LangGraph Agentic Orchestrator

## Overview

The orchestrator implements the OTAR (Observe-Think-Act-Reflect) agentic loop using LangGraph with 4 specialized agents.

## Agents

| Agent | File | Responsibility |
|-------|------|---------------|
| Perception Agent | `agents/perception_agent.py` | Collect metrics from Prometheus |
| State Agent | `agents/state_agent.py` | Assess QoS state per slice |
| Planning Agent | `agents/planning_agent.py` | LLM-driven action planning |
| Execution Agent | `agents/execution_agent.py` | Apply Kubernetes scaling / TC rules |

## Wrong-Lever Avoidance (WLA)

WLA scores each proposed action to prevent cross-slice interference:
- Score ≥ 0.7: Action approved
- Score < 0.7: Action blocked, alternative proposed

## Running

```bash
cd orchestrator/
cp .env.example .env  # add your GROQ_API_KEY
python main.py

# With specific scenario
python main.py --scenario S1 --duration 300

# Validate pipeline
python validate_metrics_pipeline.py
```

## Metrics Endpoint

The orchestrator exposes metrics at `http://kubemaster:9200/metrics` (Prometheus-compatible).

## Logs

CoT traces are saved to `orchestrator/logs/` per run.
