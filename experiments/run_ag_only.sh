#!/bin/bash
# run_ag_only.sh — Targeted AG-only supplemental
# Purpose: Collect 2 valid AG MEDIUM+HIGH trials
# Precondition: mec_restart already done (GTP verified working)
# Protocol: Per DECISIONS.md — do NOT modify thresholds/traffic/orchestration logic
#
# Uses same experiment_runner.py + agentic orchestrator as main campaign.
# GTP is verified BEFORE each trial via ogstun-embb counter test.

set -euo pipefail

K8S_DIR="/home/kube-master/k8s"
LOG_DIR="$K8S_DIR/experiments/campaign_logs"
RESULTS="$K8S_DIR/experiments/results/campaign"
DWELL=1200
LEVELS="2,3"
AG_TRIALS=2

log()  { echo "[$(date '+%H:%M:%S')]  $*"; }
warn() { echo "[$(date '+%H:%M:%S')] WARN: $*" >&2; }
die()  { echo "[$(date '+%H:%M:%S')] FATAL: $*" >&2; exit 1; }

# ── Verify GTP is working before starting data collection ──────────────────
verify_gtp() {
    log "  [GTP CHECK] Reading ogstun-embb counter..."
    local R1 R2 DELTA
    R1=$(kubectl exec -n embb deploy/upf-embb -- \
         cat /sys/class/net/ogstun-embb/statistics/tx_bytes 2>/dev/null || echo 0)
    sleep 5
    R2=$(kubectl exec -n embb deploy/upf-embb -- \
         cat /sys/class/net/ogstun-embb/statistics/tx_bytes 2>/dev/null || echo 0)
    DELTA=$(( R2 - R1 ))
    log "  [GTP CHECK] delta=$DELTA bytes in 5s"
    if [ "$DELTA" -gt 10000 ]; then
        log "  [GTP CHECK] PASS ✅ — GTP carrying ${DELTA}B/5s"
        return 0
    else
        warn "[GTP CHECK] FAIL ❌ — No traffic through UPF. delta=$DELTA"
        return 1
    fi
}

# ── mec_restart ───────────────────────────────────────────────────────────
do_mec_restart() {
    log "  → mec_restart.sh starting..."
    bash "$K8S_DIR/mec_restart.sh" >> "$LOG_DIR/mec_restart.log" 2>&1 || true
    log "  → mec_restart.sh done"
    # Stop the rule-based orchestrator that mec_restart starts
    pkill -f "phase3-orchestrator.py" 2>/dev/null || true
    pkill -f "orchestrator_agentic/main.py" 2>/dev/null || true
    fuser -k 9200/tcp 2>/dev/null || true
    sleep 3
    log "  → All orchestrators stopped"
}

# ── Wait for agentic orchestrator to be healthy ────────────────────────────
wait_for_agentic() {
    local MAX=90 T=0
    log "  → Waiting for agentic orchestrator (max ${MAX}s)..."
    while [ $T -lt $MAX ]; do
        LLM=$(curl -s --max-time 2 http://localhost:9200/metrics 2>/dev/null | \
              grep '^orchestrator_llm_used ' | awk '{print $2}')
        RTT=$(curl -s --max-time 2 http://localhost:9200/metrics 2>/dev/null | \
              grep '^orchestrator_urllc_rtt_ms ' | awk '{print $2}')
        if [ -n "$LLM" ]; then
            log "  → Agentic up | RTT=${RTT}ms | llm_used=${LLM}"
            return 0
        fi
        sleep 5; T=$((T+5))
    done
    warn "Agentic health check timed out after ${MAX}s"
    return 1
}

# ─────────────────────────────────────────────────────────────────────────────
log "════ AG-ONLY SUPPLEMENTAL: $AG_TRIALS trials × MEDIUM+HIGH ════"
log "  GTP pre-verified at campaign start"
log "  Estimated duration: ~$(( AG_TRIALS * (2+2+40) )) min"
log "  Results dir: $RESULTS"
log ""

for TRIAL in $(seq 1 $AG_TRIALS); do
    log ""
    log "══ Agentic Trial $TRIAL / $AG_TRIALS ══"

    # Step 1: mec_restart (fresh GTP state)
    do_mec_restart

    # Step 2: Verify GTP before starting experiment
    log "  [EVIDENCE GATE] Verifying GTP before starting data collection..."
    GTP_OK=false
    for ATTEMPT in 1 2 3; do
        if verify_gtp; then
            GTP_OK=true
            break
        fi
        if [ $ATTEMPT -lt 3 ]; then
            warn "GTP check attempt $ATTEMPT failed. Waiting 30s and retrying..."
            sleep 30
        fi
    done

    if [ "$GTP_OK" != "true" ]; then
        die "GTP not working after 3 attempts. Cannot collect valid data. Aborting trial $TRIAL."
    fi

    # Step 3: Start agentic orchestrator
    log "  → Starting agentic orchestrator (--fresh)..."
    cd "$K8S_DIR/orchestrator_agentic"
    nohup python3 main.py --fresh >> "$LOG_DIR/agentic_orch.log" 2>&1 &
    ORCH_PID=$!
    log "  → Orchestrator PID=$ORCH_PID"

    # Step 4: Wait for Ollama + orchestrator warmup
    log "  → Waiting 55s for Ollama warm-up..."
    sleep 55

    # Step 5: Health check
    wait_for_agentic || die "Agentic orchestrator not healthy before trial $TRIAL"

    # Step 6: Run experiment
    log "  → experiment_runner: orchestrator=agentic trial=$TRIAL levels=$LEVELS dwell=${DWELL}s"
    cd "$K8S_DIR"
    python3 experiments/experiment_runner.py \
        --orchestrator agentic \
        --levels "$LEVELS" \
        --dwell "$DWELL" \
        --output "$RESULTS" \
        2>&1

    # Step 7: Stop orchestrator
    kill $ORCH_PID 2>/dev/null || true
    fuser -k 9200/tcp 2>/dev/null || true
    sleep 5
    log "  → Trial $TRIAL complete"
done

log ""
log "════ AG-ONLY SUPPLEMENTAL COMPLETE ════"
log "  Check results in: $RESULTS"
python3 - << 'PYEOF'
import os, glob, csv
from collections import defaultdict
DIR='/home/kube-master/k8s/experiments/results/campaign/'
from datetime import datetime
cutoff = datetime(2026, 6, 6, 6, 0, 0)
grid = defaultdict(list)
for f in sorted(glob.glob(DIR+'*.csv')):
    if datetime.fromtimestamp(os.path.getmtime(f)) < cutoff: continue
    n = os.path.basename(f)
    lvl = 'LOW' if '_low_' in n else ('MEDIUM' if '_medium_' in n else 'HIGH')
    orch = 'RB' if 'rule' in n else 'AG'
    rows = sum(1 for _ in open(f)) - 1
    embb = [float(r.get('embb_throughput_mbps',0) or 0) for r in csv.DictReader(open(f)) if r.get('embb_throughput_mbps') not in ('','None')]
    avg = sum(embb)/len(embb) if embb else 0
    grid[(orch,lvl)].append((rows, avg))
print("\n  Final data grid:")
for orch in ['RB','AG']:
    for lvl in ['LOW','MEDIUM','HIGH']:
        items = grid[(orch,lvl)]
        print(f"    {orch} {lvl}: {len(items)}/3  " + "  ".join(f"(rows={r}, eMBB≈{e:.0f})" for r,e in items))
PYEOF
