#!/bin/bash
# ================================================================
# phase3-monitor.sh — 5G MEC Live Contention Monitor
# Reads ONLY currently-active client processes on UERANSIM VM.
# Detects live uesimtun→subnet mapping dynamically every refresh.
# ================================================================

UERANSIM="shinegami@192.168.49.139"
PASS="123"
LOG_DIR="/tmp/mec-clients"
REFRESH=5
SLA_RTT=25   # ms — URLLC SLA threshold

SSH="sshpass -p $PASS ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 $UERANSIM"

C_GRN='\033[0;32m'; C_YEL='\033[1;33m'; C_RED='\033[0;31m'
C_CYN='\033[0;36m'; C_MAG='\033[0;35m'; C_WHT='\033[1;37m'; NC='\033[0m'

# ── Helper: pad/truncate string to exact width ─────────────────
pad() { printf "%-${2}s" "${1:0:$2}"; }

clear_screen() { printf '\033[2J\033[H'; }

while true; do
  clear_screen
  NOW=$(date '+%Y-%m-%d %H:%M:%S')

  # ── Fetch everything in ONE ssh call ─────────────────────────
  RAW=$($SSH bash << 'REMOTE' 2>/dev/null
LOG_DIR=/tmp/mec-clients

echo "=IFACES="
# Live uesimtunX → subnet mapping
ip -4 addr show | awk '
  /^[0-9]+:/ { iface=$2; gsub(/:$/,"",iface) }
  /inet 10\.4[567]\./ && /uesimtun/ { print iface, $2 }
'

echo "=PROCS="
# Which log files have a live process attached?
for script in embb_client urllc_client mmtc_client; do
  pids=$(pgrep -f "${script}.py" 2>/dev/null)
  for pid in $pids; do
    iface=$(tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null | grep -oP 'uesimtun\d+')
    [ -n "$iface" ] && echo "${script}:${iface}:${pid}"
  done
done

echo "=LOGS="
# Latest line from every embb/urllc/mmtc log
for f in $LOG_DIR/embb_client_uesimtun*.log \
          $LOG_DIR/urllc_client_uesimtun*.log \
          $LOG_DIR/mmtc_client_uesimtun*.log; do
  [ -f "$f" ] || continue
  bn=$(basename "$f" .log)
  last=$(tail -1 "$f" 2>/dev/null)
  [ -n "$last" ] && echo "${bn}::${last}"
done
REMOTE
  )

  # ── Parse sections ────────────────────────────────────────────
  IFACES=$(echo "$RAW" | awk '/^=IFACES=/{p=1;next} /^=/{p=0} p')
  PROCS=$(echo  "$RAW" | awk '/^=PROCS=/{p=1;next}  /^=/{p=0} p')
  LOGS=$(echo   "$RAW" | awk '/^=LOGS=/{p=1;next}   /^=/{p=0} p')

  # Build subnet→slice map
  declare -A TUN_SLICE
  while read -r iface cidr; do
    ip="${cidr%%/*}"
    case "$ip" in
      10.45.*) TUN_SLICE[$iface]="embb"  ;;
      10.46.*) TUN_SLICE[$iface]="urllc" ;;
      10.47.*) TUN_SLICE[$iface]="mmtc"  ;;
    esac
  done <<< "$IFACES"

  # Build active process set: script:iface → pid
  declare -A ACTIVE
  while IFS=: read -r script iface pid; do
    [ -n "$iface" ] && ACTIVE["${script}:${iface}"]="$pid"
  done <<< "$PROCS"

  # Build log map: logname → last line
  declare -A LOGMAP
  while IFS='::' read -r key line; do
    [ -n "$key" ] && LOGMAP["$key"]="$line"
  done <<< "$LOGS"

  # ── Header ───────────────────────────────────────────────────
  printf "${C_WHT}╔══════════════════════════════════════════════════════════════╗${NC}\n"
  printf "${C_WHT}║${NC}        5G MEC LIVE CONTENTION MONITOR — Phase 3             ${C_WHT}║${NC}\n"
  printf "${C_WHT}║${NC}  %-62s${C_WHT}║${NC}\n" "$NOW"
  printf "${C_WHT}╠══════════════════════════════════════════════════════════════╣${NC}\n"

  # ── eMBB ─────────────────────────────────────────────────────
  printf "${C_WHT}║${NC}  ${C_CYN}📺 eMBB — HLS Video  [SLA: ≥20 Mbps]${NC}                        ${C_WHT}║${NC}\n"

  EMBB_COUNT=0
  for iface in $(echo "$IFACES" | awk '$2~/10\.45\./{print $1}' | sort); do
    key="embb_client:${iface}"
    logkey="embb_client_${iface}"
    LINE="${LOGMAP[$logkey]}"
    RUNNING="${ACTIVE[$key]}"

    if [ -z "$RUNNING" ]; then
      printf "${C_WHT}║${NC}    ${C_YEL}%-12s  ○ no active process${NC}%-26s${C_WHT}║${NC}\n" "$iface" ""
      continue
    fi

    if echo "$LINE" | grep -q "Mbps"; then
      RATE=$(echo "$LINE" | grep -oP 'rate=\K[\d.]+')
      QUAL=$(echo "$LINE" | grep -oP '\[\K[^\]]+')
      TOTAL=$(echo "$LINE" | grep -oP 'total=\K[\w.]+')
      RATE_INT=${RATE%.*}
      if [ "${RATE_INT:-0}" -ge 20 ] 2>/dev/null; then
        STATUS="${C_GRN}✓${NC}"
      else
        STATUS="${C_YEL}⚠ low TP${NC}"
      fi
      printf "${C_WHT}║${NC}    ${C_GRN}%-12s${NC}  [%-6s] %6sMbps  %-10s %b  ${C_WHT}║${NC}\n" \
        "$iface" "$QUAL" "$RATE" "$TOTAL" "$STATUS"
      EMBB_COUNT=$((EMBB_COUNT+1))
    elif echo "$LINE" | grep -q "Cannot\|failed\|Error"; then
      printf "${C_WHT}║${NC}    ${C_RED}%-12s  ✗ GTP unreachable%-30s${NC}${C_WHT}║${NC}\n" "$iface" ""
    else
      printf "${C_WHT}║${NC}    ${C_YEL}%-12s  … starting up%-33s${NC}${C_WHT}║${NC}\n" "$iface" ""
    fi
  done

  printf "${C_WHT}╠══════════════════════════════════════════════════════════════╣${NC}\n"

  # ── URLLC ────────────────────────────────────────────────────
  printf "${C_WHT}║${NC}  ${C_CYN}⚡ URLLC — HTTP Telemetry  [SLA: RTT ≤${SLA_RTT}ms]${NC}                ${C_WHT}║${NC}\n"

  URLLC_OK=0; URLLC_BREACH=0
  for iface in $(echo "$IFACES" | awk '$2~/10\.46\./{print $1}' | sort); do
    key="urllc_client:${iface}"
    logkey="urllc_client_${iface}"
    LINE="${LOGMAP[$logkey]}"
    RUNNING="${ACTIVE[$key]}"

    if [ -z "$RUNNING" ]; then
      printf "${C_WHT}║${NC}    ${C_YEL}%-12s  ○ no active process%-29s${C_WHT}║${NC}\n" "$iface" ""
      continue
    fi

    if echo "$LINE" | grep -q "RTT avg"; then
      AVG=$(echo "$LINE" | grep -oP 'avg=\K[\d.]+')
      MAX=$(echo "$LINE" | grep -oP 'max=\K[\d.]+')
      MSGS=$(echo "$LINE" | grep -oP 'msgs=\K\d+' | head -1)
      FAILS=$(echo "$LINE" | grep -oP 'fails=\K\d+' | head -1)
      AVG_INT=${AVG%.*}
      if [ "${AVG_INT:-0}" -le "$SLA_RTT" ] 2>/dev/null; then
        STATUS="${C_GRN}✓ ${AVG}ms${NC}"
        URLLC_OK=$((URLLC_OK+1))
      else
        STATUS="${C_RED}⚠ SLA BREACH ${AVG}ms${NC}"
        URLLC_BREACH=$((URLLC_BREACH+1))
      fi
      printf "${C_WHT}║${NC}    ${C_GRN}%-12s${NC}  msgs=%-5s fails=%-5s RTT max=%-6s %b${C_WHT}║${NC}\n" \
        "$iface" "${MSGS:-?}" "${FAILS:-?}" "${MAX}ms" "$STATUS"
    else
      printf "${C_WHT}║${NC}    ${C_YEL}%-12s  … starting up%-33s${NC}${C_WHT}║${NC}\n" "$iface" ""
    fi
  done

  printf "${C_WHT}╠══════════════════════════════════════════════════════════════╣${NC}\n"

  # ── mMTC ─────────────────────────────────────────────────────
  printf "${C_WHT}║${NC}  ${C_CYN}📡 mMTC — MQTT Sensors  [SLA: PDR ≥99.5%%]${NC}                   ${C_WHT}║${NC}\n"

  MMTC_TOTAL=0
  for iface in $(echo "$IFACES" | awk '$2~/10\.47\./{print $1}' | sort); do
    key="mmtc_client:${iface}"
    logkey="mmtc_client_${iface}"
    LINE="${LOGMAP[$logkey]}"
    RUNNING="${ACTIVE[$key]}"

    if [ -z "$RUNNING" ]; then
      printf "${C_WHT}║${NC}    ${C_YEL}%-12s  ○ no active process%-29s${C_WHT}║${NC}\n" "$iface" ""
      continue
    fi

    if echo "$LINE" | grep -q "msgs published"; then
      MSGS=$(echo "$LINE" | grep -oP '\d+ msgs' | grep -oP '\d+')
      DEV=$(echo "$LINE" | grep -oP '\(dev-[^)]+\)')
      printf "${C_WHT}║${NC}    ${C_GRN}%-12s${NC}  %-12s  %-6s msgs  ${C_GRN}✓${NC}%-10s${C_WHT}║${NC}\n" \
        "$iface" "$DEV" "$MSGS" ""
      MMTC_TOTAL=$((MMTC_TOTAL + MSGS))
    elif echo "$LINE" | grep -qiE "connect|starting|warning"; then
      printf "${C_WHT}║${NC}    ${C_YEL}%-12s  … connecting%-36s${NC}${C_WHT}║${NC}\n" "$iface" ""
    else
      printf "${C_WHT}║${NC}    ${C_YEL}%-12s  … starting up%-33s${NC}${C_WHT}║${NC}\n" "$iface" ""
    fi
  done

  printf "${C_WHT}╠══════════════════════════════════════════════════════════════╣${NC}\n"

  # ── Interface Summary ─────────────────────────────────────────
  EMBB_IFACES=$(echo "$IFACES" | grep -c "10\.45\." || echo 0)
  URLLC_IFACES=$(echo "$IFACES" | grep -c "10\.46\." || echo 0)
  MMTC_IFACES=$(echo "$IFACES" | grep -c "10\.47\." || echo 0)
  printf "${C_WHT}║${NC}  ${C_MAG}Tunnels: eMBB=%-2s  URLLC=%-2s  mMTC=%-2s${NC}%-27s${C_WHT}║${NC}\n" \
    "$EMBB_IFACES" "$URLLC_IFACES" "$MMTC_IFACES" ""

  # ── Orchestrator status ───────────────────────────────────────
  ORCH_METRIC=$(curl -s --max-time 1 http://localhost:9200/metrics 2>/dev/null | grep "^orchestrator_loop_count" | awk '{print $2}')
  ORCH_RTT=$(curl -s --max-time 1 http://localhost:9200/metrics 2>/dev/null | grep "^orchestrator_urllc_rtt_ms" | awk '{print $2}')
  ORCH_EMBB=$(curl -s --max-time 1 http://localhost:9200/metrics 2>/dev/null | grep "^orchestrator_embb_mbps" | awk '{print $2}')
  ORCH_MODE=$(curl -s --max-time 1 http://localhost:9200/metrics 2>/dev/null | grep "^orchestrator_agentic_mode" | awk '{print $2}')

  if [ -n "$ORCH_METRIC" ]; then
    MODE_STR="Rule-based"
    [ "${ORCH_MODE:-0}" = "1" ] && MODE_STR="Agentic (LLM)"
    printf "${C_WHT}╠══════════════════════════════════════════════════════════════╣${NC}\n"
    printf "${C_WHT}║${NC}  ${C_GRN}🤖 Orchestrator RUNNING${NC}  [%s]  cycle=%-4s         ${C_WHT}║${NC}\n" \
      "$MODE_STR" "$ORCH_METRIC"
    printf "${C_WHT}║${NC}     RTT=%-6sms  eMBB=%-8sMbps  Violations=%-8s${C_WHT}║${NC}\n" \
      "${ORCH_RTT:-?}" "${ORCH_EMBB:-?}" \
      "$(curl -s --max-time 1 http://localhost:9200/metrics 2>/dev/null | grep "^orchestrator_violation_count" | awk '{print $2}')"
  else
    printf "${C_WHT}╠══════════════════════════════════════════════════════════════╣${NC}\n"
    printf "${C_WHT}║${NC}  ${C_RED}🤖 Orchestrator: NOT RUNNING${NC}  (run: cd orchestrator_agentic && python3 main.py)${C_WHT}║${NC}\n"
  fi

  printf "${C_WHT}╚══════════════════════════════════════════════════════════════╝${NC}\n"
  printf "\n  ${C_YEL}Refresh every ${REFRESH}s  |  Ctrl+C to stop${NC}\n"

  unset TUN_SLICE ACTIVE LOGMAP
  declare -A TUN_SLICE ACTIVE LOGMAP

  sleep "$REFRESH"
done
