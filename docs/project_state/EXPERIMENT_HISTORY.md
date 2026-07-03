# EXPERIMENT HISTORY

---

## Campaign V1 — Main Campaign (Partial)

**Date:** 2026-06-04 ~21:00 IST to 2026-06-05 ~00:43 IST  
**Purpose:** 18-run factorial evaluation (3 levels × 3 trials × 2 orchestrators)  
**Script:** `experiments/run_campaign.sh`  
**Overall Result:** PARTIALLY VALID — crashed after LOW level for all 6 trials  

### What Ran
- RB LOW: 3 trials ✅  
- AG LOW: 3 trials ✅  
- RB MEDIUM: 0 trials (crashed)  
- AG MEDIUM: 1 trial (trial 3 only, after manual restart) ✅  
- RB HIGH: 0 trials  
- AG HIGH: 1 trial (trial 3 only) ✅  

### Failure Reason
`KeyError: 'expected_embb_mbps'` in `experiment_runner.py:compute_summary()` — the agentic orchestrator levels dict used `expected_embb_offered_mbps` but the summary function looked for `expected_embb_mbps`.  

**Fix:** Applied safe `.get()` fallback. See CHANGELOG.md.

### Data Quality
- RB/AG LOW: All valid (eMBB working, rows=394-396)  
- AG MEDIUM trial 3 (`exp_medium_agentic_20260605_000308.csv`): Valid, eMBB≈124 Mbps ✅  
- AG HIGH trial 3 (`exp_high_agentic_20260605_002337.csv`): Valid, eMBB≈110 Mbps ✅  

---

## Campaign V2 Supplemental — RB MEDIUM+HIGH

**Date:** 2026-06-05 ~10:14 IST to ~12:21 IST  
**Purpose:** Fill missing RB MEDIUM and HIGH cells (3 trials each)  
**Script:** `experiments/run_supplemental.sh` (BLOCK A: RB only)  
**Overall Result:** VALID ✅  

### What Ran
- RB MEDIUM: 3 trials ✅  
- RB HIGH: 3 trials ✅  

### Data Quality
All 6 files: rows=396, eMBB≈79-162 Mbps (client-measured via rule-based orchestrator).  
Note: RB orchestrator reads eMBB from client log files (not UPF Prometheus counter) — these numbers reflect client-measured download rates, not verified UPF wire rates.

### Files
```
exp_medium_rule_based_20260605_101405.csv  rows=396  eMBB≈162
exp_medium_rule_based_20260605_105732.csv  rows=396  eMBB≈82
exp_medium_rule_based_20260605_114100.csv  rows=396  eMBB≈79
exp_high_rule_based_20260605_103434.csv    rows=396  eMBB≈186
exp_high_rule_based_20260605_111802.csv    rows=396  eMBB≈81
exp_high_rule_based_20260605_120129.csv    rows=396  eMBB≈81
```

---

## Campaign V2 Supplemental — AG MEDIUM+HIGH (Attempt 1) — INVALID

**Date:** 2026-06-05 ~12:24 IST to ~13:24 IST  
**Purpose:** Fill missing AG MEDIUM and HIGH cells (2 trials)  
**Script:** `experiments/run_supplemental.sh` (BLOCK B: AG trial 1)  
**Overall Result:** INVALID ❌ — eMBB=0 throughout both levels  

### Failure
eMBB GTP tunnel broken from first measurement.  
```
t+ 15s | RTT=11.9ms | eMBB=0.0Mbps  (and every subsequent measurement)
```
UPF wire rate (independently verified): delta=0B/5s → confirmed ZERO traffic.

### Root Cause
See KNOWN_ISSUES.md ISSUE-001. The mec_restart at 12:21 IST restarted the UPF pod. PFCP session re-establishment placed stale session data on new UPF, but GTP-U bearers were not properly re-established before data collection started.

### Outcome
- Only 1 of 2 AG trials ran (script stopped after trial 1)
- Both files are invalid:
  - `exp_medium_agentic_20260605_122510.csv` — 376 rows, eMBB≈0 ❌  
  - `exp_high_agentic_20260605_124540.csv` — 362 rows, eMBB≈0 ❌  
- **Must be deleted before next run**

---

## Campaign V2 Supplemental — AG MEDIUM+HIGH (Attempt 2) — PENDING

**Date:** Planned  
**Purpose:** Collect 2 valid AG MEDIUM and 2 valid AG HIGH trials to complete the 3×2 factorial  
**Prerequisite:** Fix GTP tunnel (ISSUE-001) and verify eMBB > 10 Mbps before starting  
**Expected duration:** ~90 minutes (2 × mec_restart + 2 × 40 min dwell)  
**Status:** BLOCKED on GTP fix
