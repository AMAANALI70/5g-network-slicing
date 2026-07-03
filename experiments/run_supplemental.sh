#!/usr/bin/env bash
# run_supplemental.sh — fills the MEDIUM+HIGH gap from the main campaign
# RB:      3 trials × levels 2,3
# Agentic: 2 trials × levels 2,3
# ETA: ~3.5 hours from launch

set -euo pipefail

K8S_DIR="/home/kube-master/k8s"
RESULTS_DIR="$K8S_DIR/experiments/results/campaign"
LOG_DIR="$K8S_DIR/experiments/campaign_logs"
DWELL=1200
RB_WARMUP_SEC=15
RESTART_PAUSE_SEC=10
AG_WARMUP_SEC=55
AG_TRIALS=2    # only need 2 more (already have 1)
RB_TRIALS=3    # need all 3
LEVELS="2,3"   # MEDIUM + HIGH only

mkdir -p "$RESULTS_DIR" "$LOG_DIR"

log()  { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_DIR/supplemental.log"; }
warn() { echo "[$(date '+%H:%M:%S')] ⚠️  $*" | tee -a "$LOG_DIR/supplemental.log"; }

stop_all_orchestrators() {
    pkill -f "phase3-orchestrator.py"       2>/dev/null || true
    pkill -f "orchestrator_agentic/main.py" 2>/dev/null || true
    sleep 3
    fuser -k 9200/tcp 2>/dev/null || true
    sleep 2
    log "  → All orchestrators stopped"
}

do_mec_restart() {
    log "  → mec_restart.sh starting..."
    bash "$K8S_DIR/mec_restart.sh" >> "$LOG_DIR/mec_restart.log" 2>&1 || true
    log "  → mec_restart.sh done"
    stop_all_orchestrators
}

wait_for_rb() {
    local max=30 n=0
    while (( n < max )); do
        RTT=$(curl -s http://localhost:9200/metrics 2>/dev/null | \
              grep '^orchestrator_urllc_rtt_ms ' | awk '{print $2}')
        AG=$(curl -s http://localhost:9200/metrics 2>/dev/null | \
             grep '^orchestrator_agentic_mode ' | awk '{print $2}')
        if [[ -n "$RTT" && "$AG" == "0" ]]; then
            log "  → Rule-based up | RTT=${RTT}ms | agentic_mode=${AG}"
            return 0
        fi
        sleep 3; (( n++ ))
    done
    warn "Rule-based health check timed out"
}

wait_for_agentic() {
    local max=40 n=0
    while (( n < max )); do
        LLM=$(curl -s http://localhost:9200/metrics 2>/dev/null | \
              grep '^orchestrator_llm_used ' | awk '{print $2}')
        RTT=$(curl -s http://localhost:9200/metrics 2>/dev/null | \
              grep '^orchestrator_urllc_rtt_ms ' | awk '{print $2}')
        if [[ -n "$RTT" && "${LLM:-0}" == "1" ]]; then
            log "  → Agentic up | RTT=${RTT}ms | llm_used=${LLM}"
            return 0
        fi
        sleep 3; (( n++ ))
    done
    warn "Agentic health check timed out"
}

log "================================================================="
log "  SUPPLEMENTAL CAMPAIGN — MEDIUM + HIGH levels only"
log "  RB: $RB_TRIALS trials  |  Agentic: $AG_TRIALS trials"
log "  Dwell: ${DWELL}s (20 min) per level | Levels: $LEVELS"
log "  Estimated duration: ~$(( (RB_TRIALS*(2+1+40) + AG_TRIALS*(2+2+40)) )) min"
log "================================================================="

TOTAL_RUNS=0

# ═══ BLOCK A: Rule-Based MEDIUM + HIGH ═══
log ""
log "════ BLOCK A: Rule-Based Orchestrator (MEDIUM + HIGH) ════"

for TRIAL in $(seq 1 $RB_TRIALS); do
    log ""
    log "── Rule-Based Trial $TRIAL / $RB_TRIALS ──"

    do_mec_restart
    sleep $RESTART_PAUSE_SEC

    log "  → Starting rule-based orchestrator..."
    nohup python3 "$K8S_DIR/phase3-orchestrator.py" \
        >> "$LOG_DIR/orchestrator_rb_sup.log" 2>&1 &
    sleep $RB_WARMUP_SEC
    wait_for_rb

    log "  → experiment_runner: orchestrator=rule_based trial=$TRIAL levels=$LEVELS dwell=${DWELL}s"
    python3 "$K8S_DIR/experiments/experiment_runner.py" \
        --orchestrator rule_based \
        --levels "$LEVELS" \
        --dwell $DWELL \
        --output "$RESULTS_DIR" \
        2>&1 | tee -a "$LOG_DIR/supplemental.log" && \
        log "  ✅ Rule-Based Trial $TRIAL complete" || \
        warn "  ❌ Trial FAILED: orchestrator=rule_based trial=$TRIAL — continuing"

    stop_all_orchestrators
    (( TOTAL_RUNS += 2 ))
    log "  ✅ Trial done | Total level-runs: $TOTAL_RUNS"
done

log ""
log "════ BLOCK A done — Rule-Based MEDIUM+HIGH complete ════"

# ═══ BLOCK B: Agentic MEDIUM + HIGH ═══
log ""
log "════ BLOCK B: Agentic Orchestrator (MEDIUM + HIGH) ════"

for TRIAL in $(seq 1 $AG_TRIALS); do
    log ""
    log "── Agentic Trial $TRIAL / $AG_TRIALS ──"

    do_mec_restart
    sleep $RESTART_PAUSE_SEC

    log "  → Starting agentic orchestrator (--fresh)..."
    nohup python3 "$K8S_DIR/orchestrator_agentic/main.py" \
        --fresh \
        >> "$LOG_DIR/orchestrator_ag_sup.log" 2>&1 &
    log "  → Waiting ${AG_WARMUP_SEC}s for Ollama warm-up..."
    sleep $AG_WARMUP_SEC
    wait_for_agentic

    log "  → experiment_runner: orchestrator=agentic trial=$TRIAL levels=$LEVELS dwell=${DWELL}s"
    python3 "$K8S_DIR/experiments/experiment_runner.py" \
        --orchestrator agentic \
        --levels "$LEVELS" \
        --dwell $DWELL \
        --output "$RESULTS_DIR" \
        2>&1 | tee -a "$LOG_DIR/supplemental.log" && \
        log "  ✅ Agentic Trial $TRIAL complete" || \
        warn "  ❌ Trial FAILED: orchestrator=agentic trial=$TRIAL — continuing"

    stop_all_orchestrators
    (( TOTAL_RUNS += 2 ))
    log "  ✅ Trial done | Total level-runs: $TOTAL_RUNS"
done

log ""
log "════ BLOCK B done — Agentic MEDIUM+HIGH complete ════"

log ""
log "================================================================="
log "  SUPPLEMENTAL COMPLETE"
log "  Total level-runs: $TOTAL_RUNS / 10"
log "  CSV files: $(ls $RESULTS_DIR/*.csv 2>/dev/null | wc -l)"
log "  Results: $RESULTS_DIR"
log "================================================================="
