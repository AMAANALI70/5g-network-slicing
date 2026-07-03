# KNOWN ISSUES

---

## ISSUE-001: eMBB GTP tunnel broken after mec_restart

**Status:** ACTIVE BLOCKER  
**First observed:** 2026-06-05 12:24 IST (agentic supplemental trial 1)  
**Impact:** eMBB throughput = 0 in all AG MEDIUM/HIGH supplemental runs → those CSVs are INVALID  
**Confidence:** VERIFIED

### Evidence
```
Command: kubectl exec -n embb deploy/upf-embb -- sh -c "T1=$(cat /sys/class/net/ogstun-embb/statistics/tx_bytes); sleep 5; T2=$(cat /sys/class/net/ogstun-embb/statistics/tx_bytes); echo $T1 $T2"
Output: T1=1181618192766  T2=1181618192766  delta=0B
Conclusion: ZERO traffic through eMBB GTP tunnel
```

```
Command: curl --interface 10.45.0.5 --max-time 8 http://192.168.49.172:30880/ (on UERANSIM)
Output: HTTP:000 bytes:0
Conclusion: eMBB UE cannot reach nginx via PDU session
```

### Root Cause (Verified)
1. `mec_restart.sh` force-deletes UPF pod on every call (line 43: `kubectl delete pod -n $ns -l app=upf-${ns} --force`)
2. New UPF pod starts fresh — no PFCP state
3. SMF re-pushes stale session context from its own memory → UPF registers sessions for IPs .2/.3/.4
4. eMBB `nr-ue` process was killed and restarted BEFORE SMF cleared stale sessions
5. When UE re-registers, SMF sees .2/.3/.4 still "active" → assigns .5 to the new registration
6. No PFCP session for .5 exists in UPF → packets from uesimtun0 (10.45.0.5) are dropped at UPF

### Secondary Cause (Verified)
`embb_client.py` uses `curl --interface <IFNAME>` (interface name, not IP).  
`SO_BINDTODEVICE` requires `CAP_NET_RAW` (root). The client runs as `shinegami` (non-root).  
When `SO_BINDTODEVICE` succeeds via IP fallback (curl looks up IF IP internally), traffic CAN flow via GTP if the GTP session is valid.  
When GTP session is invalid, `curl --interface uesimtun0` returns HTTP:000 — **no fallback to physical network** (verified by the 0-byte responses).

> ⚠️ NOTE: The mec_restart log appeared to show 17.8 Mbps in client logs. This is UNVERIFIED as GTP traffic — the UPF counter was never measured immediately after that mec_restart. The reported rate may have come from a stale log file from the previous RB trial, or from a brief window where GTP was valid before sessions broke.

### Resolution Required
Proper mec_restart sequence:
1. Kill ALL ueransim UE processes
2. Delete ALL uesimtun interfaces  
3. Restart SMF (forces session table clear)
4. Wait ≥30s for SMF to fully initialize
5. Restart UPF pod (fresh PFCP state)
6. Wait ≥15s for UPF to register with SMF
7. Start UE processes
8. Wait ≥30s for UE registration and PDU session establishment
9. **VERIFY**: `ogstun-embb` counter delta > 0 over 5s before starting experiment
10. Only then launch traffic clients and experiment_runner

---

## ISSUE-002: experiment_runner.py KeyError `expected_embb_mbps`

**Status:** FIXED (2026-06-04)  
**First observed:** 2026-06-04 ~23:15 IST  
**Impact:** Every trial crashed after collecting only the LOW level → MEDIUM and HIGH never ran in main campaign  
**Fix applied:** Line 335 — `level.get("expected_embb_mbps", level.get("expected_embb_offered_mbps", "?"))`  
**Valid CSVs affected:** All v2 RB MEDIUM/HIGH and AG MEDIUM/HIGH came from supplemental runs, not the main campaign

---

## ISSUE-003: Prometheus `qos-orchestrator` target DOWN when no orchestrator running

**Status:** EXPECTED BEHAVIOR (not a bug)  
**First observed:** 2026-06-05 ~15:00 IST  
**Impact:** Grafana flat lines whenever no orchestrator is running on port 9200  
**Resolution:** Start orchestrator (rule-based or agentic) to restore metrics visibility

---

## ISSUE-004: launch_mec_clients.sh patch — awk command corrupted

**Status:** ACTIVE  
**First observed:** 2026-06-06 02:23 IST  
**Impact:** IF_IP resolution line in launch_mec_clients.sh has malformed awk: `awk "{print \\\\}"` — the awk action is empty/broken  
**Evidence:**
```
Line 36 after patch: IF_IP=$(ip -4 addr show $IF 2>/dev/null | grep "inet 10.45." | awk "{print \\\\}" | cut -d/ -f1)
Expected:            IF_IP=$(ip -4 addr show $IF 2>/dev/null | grep "inet 10.45." | awk '{print $2}' | cut -d/ -f1)
```
**Resolution needed:** Restore launch_mec_clients.sh from backup (`.bak`) and apply correct patch

---

## ISSUE-005: AG MEDIUM/HIGH supplemental CSVs are INVALID

**Status:** ACTIVE — files must be deleted before new collection  
**Files:**
- `exp_medium_agentic_20260605_122510.csv` (376 rows, eMBB≈0.1)
- `exp_high_agentic_20260605_124540.csv` (362 rows, eMBB≈nan)
**Reason:** GTP tunnel broken during collection — eMBB=0 throughout  
**Action:** Delete these files, re-collect 2 valid AG MEDIUM+HIGH trials

---

## ISSUE-006: mMTC PDR = 0 in all trials

**Status:** KNOWN LIMITATION — documented in assumptions_and_limitations.md  
**First observed:** Campaign V1  
**Impact:** mMTC column in CSVs is always 0 msgs — no mMTC QoS comparison possible  
**Root cause:** MQTT broker connectivity intermittent; clients report "Connected" but message delivery not confirmed  
**Resolution:** None planned for current campaign; acknowledged as limitation

---

## ISSUE-007: eMBB UE assigned IP 10.45.0.5 instead of 10.45.0.2

**Status:** Consequence of ISSUE-001  
**Evidence:** `ip -4 addr` on UERANSIM shows `uesimtun0 10.45.0.5/24`  
**Explanation:** SMF has stale sessions for .2/.3/.4 → new UE registration gets .5 from the pool  
**Resolution:** Part of ISSUE-001 fix (SMF restart clears stale sessions → UE gets .2 on fresh registration)
