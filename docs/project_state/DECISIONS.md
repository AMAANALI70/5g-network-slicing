# DECISIONS

All frozen decisions for Campaign V2. Do not revisit unless evidence demands it.

---

## Architecture

| Decision | Value | Reason | Date |
|----------|-------|--------|------|
| Orchestrator comparison | Rule-based vs Agentic | Core research question | Pre-campaign |
| LLM model | `llama3.2:3b` (via Ollama) | Fits in testbed RAM; fastest inference | 2026-05-31 |
| LLM endpoint | `http://localhost:11434` | Local Ollama on kube-master | 2026-05-31 |

---

## Experimental Design

| Decision | Value | Reason | Date |
|----------|-------|--------|------|
| Load levels | LOW / MEDIUM / HIGH | 3-point factorial | Pre-campaign |
| Trials per cell | 3 | Statistical minimum for mean + std dev | Pre-campaign |
| Dwell time | 1200s (20 min) per level | Enough for orchestrator convergence | Pre-campaign |
| Sampling interval | 3s | experiment_runner poll rate | Pre-campaign |
| Expected rows per file | ~396 (1200/3 × header) | 3s × 396 = 1188s ≈ 20 min | Pre-campaign |

---

## SLA Thresholds

| Metric | SLA | Enforcement |
|--------|-----|-------------|
| URLLC RTT | ≤ 15 ms | Both orchestrators enforce this |
| eMBB throughput | ≥ 20 Mbps (LOW), ≥ 60 Mbps (MED), ≥ 80 Mbps (HIGH) | Orchestrator target, not hard SLA |
| tc rate floor | 50 Mbit | Rule-based minimum throttle |
| tc rate ceiling | 1000 Mbit | tc HTB max |

---

## Traffic Generation

| Slice | Client | Interface binding | Load scaling |
|-------|--------|-------------------|--------------|
| eMBB | `embb_client.py` | `curl --interface <IF>` on uesimtun | HLS quality: 360p/720p/1080p |
| URLLC | `urllc_client.py` | Direct UDP on uesimtun | Rate: 1.0/2.0/4.0 Hz |
| mMTC | `mmtc_client.py` | MQTT on uesimtun | Multiplier: 1.0/2.0/4.0x |

---

## Metrics Pipeline

| Metric | Source | Orchestrator |
|--------|--------|-------------|
| `orchestrator_embb_mbps` | `irate(tun_tx_bytes{interface="ogstun-embb"}[30s])*8/1e6` via Prometheus | **Agentic only** |
| `orchestrator_embb_mbps` | SSH log tail of `embb_client.py` logs | **Rule-based only** |
| `orchestrator_urllc_rtt_ms` | URLLC client log tail (RTT from UDP probes) | Both |

> ⚠️ This asymmetry in eMBB measurement source is a known limitation. RB measures client-side rate (any path); AG measures UPF wire rate (GTP only). Direct comparison of eMBB values between RB and AG should be treated with caution.

---

## Load Level Definitions

| Level | eMBB Quality | URLLC Rate | mMTC Mult | Offered eMBB |
|-------|-------------|------------|-----------|-------------|
| LOW (1) | 360p | 1.0 Hz | 1.0x | ~370 Mbps |
| MEDIUM (2) | 720p | 2.0 Hz | 2.0x | ~720 Mbps |
| HIGH (3) | 1080p | 4.0 Hz | 4.0x | ~860 Mbps |

---

## Infrastructure

| Component | Decision | Value |
|-----------|----------|-------|
| eMBB UPF secondary IP | Fixed | 192.168.49.173 |
| nginx HLS NodePort | Fixed | 30880 |
| URLLC echo NodePort | Fixed | 30180 |
| mMTC MQTT NodePort | Fixed | 30883 |
| Prometheus NodePort | Fixed | 30090 |
| Orchestrator metrics port | Fixed | 9200 |
| UERANSIM VM IP | Fixed | 192.168.49.139 |
| 5G core VM IP | Fixed | 192.168.49.143 |
