# Section 9 — Orchestrators

## Rule-Based Orchestrator

- File: `/home/kube-master/k8s/phase3-orchestrator.py`
- Runtime: kubemaster (192.168.49.174), runs as bare Python process
- PID: managed by `mec_restart.sh`, logs to `/tmp/orchestrator_ruleb.log`
- Metrics: port 9200 (Prometheus text format)
- Loop interval: ~3s

### SLA Thresholds

| Metric | Threshold | Action on Violation |
|---|---|---|
| URLLC RTT | > 15ms | Throttle eMBB: `tc qdisc add dev ogstun-embb root tbf rate 50mbit` |
| eMBB throughput | < 20 Mbps | Scale up embb-app (kubectl scale) |
| mMTC PDR | < 99.5% | Scale up mmtc-app (kubectl scale) |

### Decision Logic

```
Every 3s loop:
  1. SSH to UERANSIM VM → tail urllc_*.log → parse RTT avg
  2. SSH to UERANSIM VM → tail embb_*.log → parse throughput
  3. SSH to UERANSIM VM → tail mmtc_*.log → parse msg count
  4. If URLLC RTT > 15ms for N violations:
       → throttle_embb(50mbit) via SSH to worker node
  5. If URLLC RTT < 15ms for M consecutive loops (recovery_streak):
       → restore_embb(1000mbit) via SSH to worker node
  6. Optionally: kubectl scale deployments
  7. Update Prometheus metrics, expose on :9200
```

### tc Commands Issued (SSH to worker node 192.168.49.172)

```bash
# Throttle
tc qdisc del dev ogstun-embb root 2>/dev/null || true
tc qdisc add dev ogstun-embb root tbf rate 50mbit burst 32kbit latency 400ms

# Restore
tc qdisc del dev ogstun-embb root
```

---

## Agentic Orchestrator

- Directory: `/home/kube-master/k8s/orchestrator_agentic/`
- Framework: LangGraph (stateful agent graph)
- LLM: Ollama local inference, model `llama3.2:3b` (frozen, not updated)
- Metrics: same port 9200 (mutually exclusive with rule-based)
- Memory: persistent episodic memory (vector store or structured JSON)

### Architecture — LangGraph Nodes

```
[Monitoring Agent]
  Input:  Prometheus metrics (RTT, throughput, PDR, tc_rate, state)
  Output: Structured observation dict (current_state, sla_status)

[State Agent]
  Input:  Observation dict + memory retrieval
  Output: Enriched state with historical context, past actions, patterns

[LLM Planning Agent]
  Input:  Enriched state + system prompt (frozen)
  Output: root_cause_assessment, recommended_action, lever_validity scores
  Model:  llama3.2:3b via Ollama (:11434)

[Validation Layer]
  Input:  Planned action + current state
  Checks: Wrong-Lever Avoidance (WLA), safety limits, contradiction detection
  Output: Approved/rejected action with reasoning

[Execution Agent]
  Input:  Validated action
  Output: tc shaping command or kubectl scale (same as rule-based)
  Method: SSH to worker node / kubectl API

[Memory Agent]
  Input:  Action + outcome (post-execution RTT delta)
  Output: Persisted episode to memory store
  Purpose: Future state lookups to improve planning
```

### CoT Trace Logging

Each agentic decision cycle writes a structured trace including:
- raw metrics at decision time
- LLM input prompt
- LLM raw output
- parsed action
- validation result
- execution outcome
- memory write record

Log location: `/tmp/cot_traces/` (or configured path in `cot_trace_logger.py`)

### Key Difference from Rule-Based

| Dimension | Rule-Based | Agentic |
|---|---|---|
| Decision logic | Hardcoded thresholds | LLM reasoning + memory |
| Adaptability | Fixed | Context-aware |
| Explainability | Deterministic | CoT traces |
| Latency | ~100ms/loop | ~2–5s/loop (LLM inference) |
| Wrong-lever risk | None (single lever) | Validated by WLA layer |
| Memory | None | Persistent episodic |

---

## Switching Between Orchestrators

Only one runs at a time on port 9200. Switching:
```bash
# Stop rule-based
pkill -f phase3-orchestrator.py

# Start agentic (with memory flush for formal runs)
python3 orchestrator_agentic/main.py --fresh

# Stop agentic, restore rule-based
pkill -f "orchestrator_agentic/main.py"
nohup python3 phase3-orchestrator.py > /tmp/orchestrator_ruleb.log 2>&1 &
```
