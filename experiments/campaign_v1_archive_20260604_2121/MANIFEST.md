# Campaign v1 Archive

**Archived:** 2026-06-04T15:51:02Z
**Reason:** Pre-v2 archive — v1 had 4 validity gaps (traffic equivalence bug, measurement
heterogeneity, memory logging bug, WLA inactivity). All fixed in v2 hardening phase.

## v1 Validity Gaps (now fixed)
- A1: Low/Med/High were operationally identical (same traffic)
- A2: Rule-based used SSH log parsing; agentic used Prometheus UPF counter
- A3: memory_context_summary silently dropped from CoT traces
- A4: WLA never exercised adversarially

## v2 Changes
See: /home/kube-master/k8s/experiments/assumptions_and_limitations.md §E
