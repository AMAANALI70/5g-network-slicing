#!/bin/bash
# =============================================================================
#  18-Run Formal Campaign: 3 Load Levels × 3 Trials × 2 Orchestrators
#  Run order: all rule-based trials → all agentic trials (3 trials each)
#  Each trial runs levels low(1) → medium(2) → high(3) sequentially.
#  mec_restart is called once per trial (not per level).
# =============================================================================

set -uo pipefail   # no -e: a failed run should not abort the whole campaign

# ── Config ────────────────────────────────────────────────────────────────────
K8S_DIR="/home/kube-master/k8s"
RESULTS_DIR="$K8S_DIR/experiments/results/campaign"
LOG_DIR="$K8S_DIR/experiments/campaign_logs"
DWELL=1200                     # 20 minutes per level
LEVELS="1,2,3"                 # low, medium, high
AGENTIC_WARMUP_SEC=55          # Wait for Ollama LLM cold-start after fresh start
RB_WARMUP_SEC=15               # Rule-based orchestrator warm-up
RESTART_PAUSE_SEC=10           # Pause after mec_restart before starting orchestrator

mkdir -p "$RESULTS_DIR" "$LOG_DIR"

# ── Helpers ───────────────────────────────────────────────────────────────────
log()  { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_DIR/campaign.log"; }
warn() { echo "[$(date '+%H:%M:%S')] ⚠️  $*" | tee -a "$LOG_DIR/campaign.log"; }

stop_all_orchestrators() {
    # Kill by filename patterns
    pkill -f "phase3-orchestrator.py"       2>/dev/null || true
    pkill -f "orchestrator_agentic/main.py" 2>/dev/null || true
    pkill -f "main.py --fresh"              2>/dev/null || true
    pkill -f "main.py"                      2>/dev/null || true
    # Nuclear: kill whatever holds port 9200
    fuser -k 9200/tcp                       2>/dev/null || true
    sleep 3
    # Final check — confirm port is free
    if ss -tlnp 2>/dev/null | grep -q ":9200 "; then
        warn "Port 9200 still bound — second fuser kill..."
        fuser -k 9200/tcp 2>/dev/null || true
        sleep 3
    fi
    log "  → All orchestrators stopped (port 9200 free)"
}

do_mec_restart() {
    log "  → mec_restart.sh starting..."
    bash "$K8S_DIR/mec_restart.sh" >> "$LOG_DIR/mec_restart.log" 2>&1 || true
    log "  → mec_restart.sh done"
    sleep "$RESTART_PAUSE_SEC"
}

start_rule_based() {
    stop_all_orchestrators
    log "  → Starting rule-based orchestrator..."
    nohup python3 "$K8S_DIR/phase3-orchestrator.py" \
        > /tmp/orchestrator_ruleb.log 2>&1 &
    sleep "$RB_WARMUP_SEC"
    RTT=$(curl -s http://localhost:9200/metrics 2>/dev/null \
        | grep orchestrator_urllc_rtt_ms | awk '{print $2}')
    AGENTIC=$(curl -s http://localhost:9200/metrics 2>/dev/null \
        | grep orchestrator_agentic_mode | awk '{print $2}')
    if [ "${AGENTIC:-0}" = "1" ]; then
        warn "ABORT: agentic_mode=1 detected on port 9200 — rule-based failed to start!"
        warn "Attempting emergency fuser kill and restart..."
        fuser -k 9200/tcp 2>/dev/null || true; sleep 2
        nohup python3 "$K8S_DIR/phase3-orchestrator.py" \
            > /tmp/orchestrator_ruleb.log 2>&1 &
        sleep "$RB_WARMUP_SEC"
        AGENTIC=$(curl -s http://localhost:9200/metrics 2>/dev/null \
            | grep orchestrator_agentic_mode | awk '{print $2}')
        [ "${AGENTIC:-0}" = "1" ] && { warn "FATAL: rule-based still not running. Skipping trial."; return 1; }
    fi
    log "  → Rule-based up | RTT=${RTT}ms | agentic_mode=${AGENTIC:-0}"
}

start_agentic() {
    stop_all_orchestrators
    log "  → Starting agentic orchestrator (--fresh)..."
    cd "$K8S_DIR/orchestrator_agentic"
    nohup python3 main.py --fresh > /tmp/orchestrator_agentic.log 2>&1 &
    cd "$K8S_DIR"
    log "  → Waiting ${AGENTIC_WARMUP_SEC}s for Ollama warm-up..."
    sleep "$AGENTIC_WARMUP_SEC"
    RTT=$(curl -s http://localhost:9200/metrics 2>/dev/null \
        | grep orchestrator_urllc_rtt_ms | awk '{print $2}')
    LLM=$(curl -s http://localhost:9200/metrics 2>/dev/null \
        | grep orchestrator_llm_used | awk '{print $2}')
    log "  → Agentic up | RTT=${RTT}ms | llm_used=${LLM}"
}

run_levels() {
    local orch=$1
    local trial=$2
    log "  → experiment_runner: orchestrator=$orch trial=$trial levels=$LEVELS dwell=${DWELL}s"
    if python3 "$K8S_DIR/experiments/experiment_runner.py" \
        --levels  "$LEVELS" \
        --dwell   "$DWELL"  \
        --output  "$RESULTS_DIR" \
        --orchestrator "$orch" \
        2>&1 | tee -a "$LOG_DIR/trial_${orch}_${trial}.log"; then
        log "  ✅ Trial done: orchestrator=$orch trial=$trial"
    else
        warn "  ❌ Trial FAILED: orchestrator=$orch trial=$trial — continuing campaign"
    fi
}

# ── Main Campaign ─────────────────────────────────────────────────────────────
log "================================================================="
log "  18-Run Formal Campaign"
log "  Dwell: ${DWELL}s ($(( DWELL/60 )) min) per level | Levels: $LEVELS"
log "  Estimated duration: ~$(( (18 * DWELL + 6 * 120 + 3 * AGENTIC_WARMUP_SEC) / 60 )) min"
log "================================================================="

CAMPAIGN_START=$(date +%s)
TOTAL_RUNS=0

# ──────────────────────────────────────────────────────────────────────────────
# BLOCK A — Rule-Based (3 trials)
# ──────────────────────────────────────────────────────────────────────────────
log ""
log "════ BLOCK A: Rule-Based Orchestrator ════"

for TRIAL in 1 2 3; do
    log ""
    log "── Rule-Based Trial $TRIAL / 3 ──"
    do_mec_restart
    start_rule_based

    run_levels "rule_based" "$TRIAL"
    TOTAL_RUNS=$(( TOTAL_RUNS + 3 ))

    ELAPSED=$(( ($(date +%s) - CAMPAIGN_START) / 60 ))
    log "  ✅ Rule-Based Trial $TRIAL complete | Elapsed: ${ELAPSED}min | Total runs: $TOTAL_RUNS"
    sleep 5
done

log ""
log "════ BLOCK A done — Rule-Based all 3 trials complete ════"
log ""

# ──────────────────────────────────────────────────────────────────────────────
# BLOCK B — Agentic (3 trials)
# ──────────────────────────────────────────────────────────────────────────────
log "════ BLOCK B: Agentic Orchestrator ════"

for TRIAL in 1 2 3; do
    log ""
    log "── Agentic Trial $TRIAL / 3 ──"
    do_mec_restart
    start_agentic

    run_levels "agentic" "$TRIAL"
    TOTAL_RUNS=$(( TOTAL_RUNS + 3 ))

    ELAPSED=$(( ($(date +%s) - CAMPAIGN_START) / 60 ))
    log "  ✅ Agentic Trial $TRIAL complete | Elapsed: ${ELAPSED}min | Total runs: $TOTAL_RUNS"
    sleep 5
done

log ""
log "════ BLOCK B done — Agentic all 3 trials complete ════"

# ──────────────────────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────────────────────
ELAPSED_TOTAL=$(( ($(date +%s) - CAMPAIGN_START) / 60 ))
CSV_COUNT=$(ls "$RESULTS_DIR"/*.csv 2>/dev/null | wc -l)

log ""
log "================================================================="
log "  CAMPAIGN COMPLETE"
log "  Total runs: $TOTAL_RUNS / 18"
log "  Total time: ${ELAPSED_TOTAL} min"
log "  CSV files:  $CSV_COUNT"
log "  Results:    $RESULTS_DIR"
log "================================================================="
