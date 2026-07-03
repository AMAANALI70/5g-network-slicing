# CHANGELOG

Format: Date | File | Change | Reason | Impact

---

## 2026-06-04

### experiment_runner.py — KeyError fix
**File:** `/home/kube-master/k8s/experiments/experiment_runner.py`  
**Lines:** 335, 362-363  
**Change:** Replaced `level["expected_embb_mbps"]` with `level.get("expected_embb_mbps", level.get("expected_embb_offered_mbps", "?"))`  
**Reason:** Agentic orchestrator level configs use `expected_embb_offered_mbps` (not `expected_embb_mbps`). Rule-based uses `expected_embb_mbps`. The mismatch caused a `KeyError` crash in `compute_summary()` after every trial.  
**Impact:** Campaign V1 crashed after LOW level for all 6 trials. Fix required supplemental campaign for MEDIUM+HIGH data.

---

## 2026-06-05

### launch_mec_clients.sh — PARTIAL PATCH (malformed, needs repair)
**File:** `/home/shinegami/mec-clients/launch_mec_clients.sh` on UERANSIM VM  
**Backup:** `launch_mec_clients.sh.bak` (original preserved)  
**Change attempted:** Modify eMBB client launch to pass interface IP instead of interface name to avoid `SO_BINDTODEVICE` root requirement  
**Reason:** `curl --interface <IFNAME>` requires root; running as `shinegami` (non-root) may cause undefined binding behavior  
**Result:** PARTIALLY APPLIED — awk command on line 36 is malformed (`awk "{print \\\\}"` instead of `awk '{print $2}'`). Line 37 correctly uses `${IF_IP:-$IF}` but IF_IP is never correctly resolved.  
**Impact:** Current `launch_mec_clients.sh` has a corrupted IF_IP resolution. The `${IF_IP:-$IF}` fallback means it will still use `$IF` (interface name), so behavior is UNCHANGED from before the patch.  
**Action required:** Restore from `.bak` and apply correct patch.

### mec_restart.sh — NOT MODIFIED
No changes made. mec_restart.sh force-deletes UPF pods (line 43) — this is an existing design choice that contributes to GTP instability. Do not modify without explicit decision.

---

## 2026-06-06

### project_state/ — Created
**Files created:**
- `project_state/CURRENT_STATUS.md`
- `project_state/KNOWN_ISSUES.md`
- `project_state/DECISIONS.md`
- `project_state/EXPERIMENT_HISTORY.md`
- `project_state/CHANGELOG.md`
**Reason:** Enforce engineering discipline — evidence-based workflow, no assumptions  
**Impact:** Project state now tracked persistently

### 2026-06-06 — ISSUE-001 RESOLVED: mec_restart.sh fixed GTP-U TEID mismatch

**Root cause confirmed:** GTP-U TEID mismatch from accumulated restart cycles.  
**Evidence:** uesimtun0 TX=600B, ogstun-embb RX=0B during curl test (packet dropped at UPF TEID lookup).  
**Fix applied:** Full mec_restart.sh execution:
- All uesimtun interfaces deleted (clears stale routing)
- SMF restarted (clears stale PDU session table)
- All UPF pods force-deleted and recreated (fresh PFCP state)
- UEs restarted with fresh registration (consistent TEID assignment)
**Validation:** ogstun-embb TX delta=50,985,070 bytes in 5s → 81.58 Mbps REAL GTP TRAFFIC ✅

**Invalid CSVs deleted:**
- `exp_medium_agentic_20260605_122510.csv` (376 rows, eMBB≈0) — DELETED
- `exp_high_agentic_20260605_124540.csv` (362 rows, eMBB≈0) — DELETED

**launch_mec_clients.sh:** Restored from backup (launch_mec_clients.sh.bak). ISSUE-004 closed.

### 2026-06-06 — run_ag_only.sh created

**File:** `experiments/run_ag_only.sh`  
**Reason:** `run_supplemental.sh` was running unnecessary RB Block A (3 trials × 40 min = 2+ hours wasted). We already have 3/3 valid RB MEDIUM/HIGH. A targeted script saves ~130 minutes.  
**Key addition:** Mandatory GTP verification gate before each trial (ogstun-embb counter delta test). Trial is aborted (not started) if GTP check fails 3× — prevents collecting invalid zero-eMBB data again.  
**Impact:** AG-only supplemental launched at 12:59:40 IST June 6. Estimated complete: ~14:27 IST.

### 2026-06-06 — run_daemon.py created

**File:** `experiments/run_daemon.py`  
**Reason:** `bash script &` approach was killed when run_command tool shell terminated. Double-fork daemonization survives shell exit.  
**Impact:** Enables background script launching from the assistant.

### 2026-06-06 — Literature Survey Updated in LaTeX Report

**Files modified:**
- `report/ch1_introduction.tex` (Literature Survey section)
- `report/ch6_conclusion.tex` (References bibliography)
**Changes:**
- Removed all 8 old literature survey papers.
- Integrated 8 new papers: Bandara et al. (2026), Grings et al. (2022), Novanana et al. (2024), Reddy (2025), Dandoush et al. (2024), Sulaiman et al. (2024), Saha et al. (2022), and Tran et al. (2025).
- Compiled clean output using `pdflatex` to produce the updated `main.pdf`.
**Impact:** Successfully aligned the major report's literature survey with the requested state-of-the-art publications.

### 2026-06-06 — PDF Viewer Extension Installed

**Extension:** `tomoki1207.pdf`  
**Reason:** Installed extension to view PDF outputs (like the compiled `main.pdf`) directly within the Antigravity editor as requested.  
**Impact:** `tomoki1207.pdf` (v1.2.2) is now active in the environment.

### 2026-06-06 — PDF Parser Extension Installed

**Extension:** `babyfox1306.pdf-forge`  
**Reason:** Installed extension to parse and extract code, text, and tables from PDF files directly within the Antigravity editor.  
**Impact:** `babyfox1306.pdf-forge` (v1.0.3) is now active in the environment.



## 2026-06-07

### report/ch3_system_design.tex — Redesigned System Architecture Diagram
**File:** `/home/kube-master/k8s/report/ch3_system_design.tex`  
**Change:** Replaced the simple 4-block system architecture diagram (`fig:testbed_arch`) with a comprehensive multi-layered TikZ diagram.  
**Reason:** Make report architecture diagrams accurate to the actual implementation (KubeMaster control plane, KubeWorker data plane, Open5GS VM, UERANSIM VM, decoupled observability flow).  
**Impact:** Document compiled successfully into `main.pdf` with no rendering issues.

### reports/report.tex — Updated Agentic AI Architecture Diagram
**File:** `/home/kube-master/k8s/reports/report.tex`  
**Change:** Replaced the old 9-agent diagram in `fig:agent` with the current LangGraph 5-node/6-component control loop (State Coordinator, Monitoring Agent, State Agent, Ollama Planner, Agent Memory, Validation Gate, Execution Agent, CoT Trace Logger).  
**Reason:** Align report visualizations with the current multi-agent LangGraph orchestrator implementation.  
**Impact:** Recompiled successfully using `pdflatex -jobname=architectures` to update `architectures.pdf`.

### reports/report.tex — Updated High-Level, Low-Level, K8s, and Obs diagrams
**File:** `/home/kube-master/k8s/reports/report.tex`  
**Change:** Updated old QoS Multi-Agent / Coordination Agent / SLA Agents / Enforcement Agents references to LangGraph Agentic QoS Orchestrator, Monitoring & State Agents, and Validation & Exec Agents across high-level, low-level, Kubernetes deployment, and observability diagrams.  
**Reason:** Align all system-level architecture diagrams with the current LangGraph-based multi-threaded control loop.  
**Impact:** Recompiled successfully using `pdflatex -jobname=architectures` to update `architectures.pdf`.

### reports/report.tex & system_architecture_report.md — Complete Agentic Migration
**Files modified:**
- `/home/kube-master/k8s/reports/report.tex` (Title Page & System Operation Flow diagram)
- `/home/kube-master/Downloads/system_architecture_report.md` (Layer 7 details & Mermaid diagram)
**Changes:**
- Title page updated from "9-Agent" to "LangGraph Agentic QoS Orchestration".
- Flow diagram (`fig:flow`) updated from SLA/Decision/Enforcement Agents to Monitoring & State/LLM Planner/Execution Agents.
- Mermaid diagram updated to show all individual agents (Monitoring, State, LLM Planner, Validation, Execution, Memory) and the decoupled metrics cache loop.
- Regenerated the high-res PNG previews for `architectures.pdf` pages.
**Impact:** Both report PDFs and Markdown files are entirely up-to-date with no references to legacy architectures.

### reports/report.tex — Correct VM Topology Architecture
**Files modified:**
- `/home/kube-master/k8s/reports/report.tex`
**Changes:**
- Corrected `fig:lowlevel` to accurately depict the **5-VM** topology: `kubemaster`, `kube`, `Core VM (shinegami)`, `UERANSIM VM (shinegami)`.
- Moved `upf-mmtc` and `mmtc-app` to the active `kube` worker node (where all slices actually run), dropping them from the idle `kube2` node.
- Moved Open5GS Control Plane functions (AMF, SMF, PCF, etc.) out of `kubemaster` and into the dedicated `Core VM`.
- Updated `fig:k8s` to remove unused `kube2` node overlays and accurately represent `tun-metrics-exporter` running solely on `kube`.
- Updated the Title Page infrastructure text to `5-VM VMware Testbed (3x K8s, 1x 5G Core, 1x RAN)`.
- Recompiled both `architectures.pdf` and `main.pdf` and regenerated PNG previews.
**Impact:** The architecture diagrams now accurately reflect the physical inventory placement and 5-node testbed layout.
