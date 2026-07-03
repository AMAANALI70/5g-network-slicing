# Section 10 — Traffic Control Layer

## Enforcement Point

All tc shaping is applied on the `kube` worker node (192.168.49.171/173),
specifically on the `ogstun-embb` interface — the N6 egress of the eMBB UPF.

The orchestrator (running on kubemaster) SSHes to the worker to issue tc commands.
SSH target: `192.168.49.172` (secondary IP of the kube worker node).

---

## Current tc State (ogstun-embb)

At baseline / restored state:
```
qdisc fq_codel 0: dev ogstun root refcnt 2
  limit 10240p flows 1024 quantum 1500 target 5ms interval 100ms
  memory_limit 32Mb ecn drop_batch 64
```
(Default kernel qdisc — no shaping applied, full wire speed ~1 Gbps effective)

When throttled by orchestrator:
```
qdisc tbf 8001: dev ogstun-embb root refcnt 2
  rate 50Mbit burst 32Kb lat 400ms
```

---

## Shaping Policy

| State | Interface | qdisc | Rate | Effect |
|---|---|---|---|---|
| NORMAL | ogstun-embb | none (fq_codel default) | ~1 Gbps | Full eMBB throughput |
| THROTTLED | ogstun-embb | tbf | 50 Mbit | eMBB capped at 50 Mbps |
| URLLC / mMTC | ogstun-urllc, ogstun-mmtc | none | Unrestricted | Never shaped |

**Shaping type: TBF (Token Bucket Filter)**
- `rate 50mbit` — sustained rate cap
- `burst 32kbit` — burst allowance (minimal, tight cap)
- `latency 400ms` — max queue delay before drop

---

## tc qdisc show (current, from UERANSIM VM which hosts ogstun)

```
qdisc fq_codel 0: dev ogstun root refcnt 2
  limit 10240p flows 1024 quantum 1500 target 5ms interval 100ms
  memory_limit 32Mb ecn drop_batch 64
```
(No active shaping — ogstun is restored after the pilot run)

On kubemaster (no shaping relevant to data plane):
```
qdisc fq_codel 0: dev ens33 root  (default)
qdisc noqueue: dev flannel.1, cni0, veth* (virtual — no shaping)
```

---

## Observed tc Behavior (from pilot run)

During the pilot (10-min medium load, rule-based):

| Event | Time | RTT Before | tc State | RTT After |
|---|---|---|---|---|
| Throttle 1 | t+15s | 15.7ms | 1000→50 Mbit | 12.5ms |
| Restore 1 | t+60s | 12.5ms | 50→1000 Mbit | 14.3ms |
| Throttle 2 | t+315s | 22.7ms | 1000→50 Mbit | 17.1ms |
| Restore 2 | t+345s | 12.9ms | 50→1000 Mbit | 14.2ms |
| Throttle 3 | t+495s | 16.1ms | 1000→50 Mbit | 12.5ms |
| Restore 3 | t+525s | 12.5ms | 50→1000 Mbit | 14.6ms |
| Throttle 4 | t+570s | 25.8ms | 1000→50 Mbit | 12.4ms |

Total throttle events: 4 (in 10 minutes at medium load).
Recovery time after throttle: typically 15–30s.

---

## Limitations of Current tc Design

1. **Single lever**: Only eMBB bandwidth is shaped. No per-UE or per-flow shaping.
2. **Binary**: Only two states — full (1000 Mbit) and throttled (50 Mbit). No graduated shaping.
3. **No URLLC/mMTC shaping**: URLLC and mMTC interfaces have no tc rules.
4. **Coarse granularity**: All eMBB UEs affected simultaneously (not per-UE).
5. **SSH latency**: tc commands execute via SSH, adding ~50–100ms to action latency.
