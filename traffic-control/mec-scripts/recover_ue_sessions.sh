#!/bin/bash
# =============================================================
# recover_ue_sessions.sh  (deployed to UERANSIM: ~/mec-scripts/)
#
# Architecture: 3 UEs × 3 PDU sessions = 9 tunnels total
#   - 3 eMBB (10.45.x.x), 3 URLLC (10.46.x.x), 3 mMTC (10.47.x.x)
#   - nr-ue runs as ROOT (via sudo), so recovery needs sudo -S
#
# Key fixes:
#   - sudo pkill (user pkill can't kill root nr-ue processes)
#   - sudo -S with password piped in (no TTY needed)
#   - Deduplication: 3 unique config files = 3 restarts
#   - Manual uesimtun cleanup if tunnels don't drop after kill
# =============================================================

SUDO_PASS="123"          # shinegami sudo password
REQUIRED_EMBB=3
REQUIRED_URLLC=3
REQUIRED_MMTC=3
TUNNEL_WAIT=150
LOG_FILE="/tmp/ue_recovery.log"
CMD_FILE="/tmp/nr_ue_restart.sh"

_sudo() { echo "$SUDO_PASS" | sudo -S "$@" 2>/dev/null; }

echo "[recovery $(date '+%H:%M:%S')] === UE Session Recovery Starting ===" | tee -a "$LOG_FILE"

# ── Phase 1: Kill all client apps (as user, no sudo needed) ───────────────────
echo "[recovery] Phase 1: Stopping client apps..." | tee -a "$LOG_FILE"
pkill -f 'embb_client.py|urllc_client.py|mmtc_client.py' 2>/dev/null
pkill -f 'iperf3 -c' 2>/dev/null
sleep 1

# ── Phase 2: Detect unique nr-ue processes ────────────────────────────────────
echo "[recovery] Phase 2: Detecting unique nr-ue processes..." | tee -a "$LOG_FILE"

# pgrep -f finds ALL PIDs with 'nr-ue' in cmdline (sudo parent + root child + actual binary)
# We deduplicate by config file — 1 unique config = 1 UE
declare -A SEEN_CONFIGS
echo "#!/bin/bash" > "$CMD_FILE"
echo "SUDO_PASS='$SUDO_PASS'" >> "$CMD_FILE"
echo "" >> "$CMD_FILE"

NR_UE_COUNT=0
for PID in $(pgrep -f 'nr-ue' 2>/dev/null); do
    FULL_CMD=$(cat /proc/$PID/cmdline 2>/dev/null | tr '\0' ' ' | sed 's/[[:space:]]*$//')
    [ -z "$FULL_CMD" ] && continue
    echo "$FULL_CMD" | grep -qE 'grep|pgrep|recover_ue|bash' && continue

    # Extract config file as deduplication key
    CONFIG=$(echo "$FULL_CMD" | grep -oE '\./config/ue-[a-z]+\.yaml' | head -1)
    [ -z "$CONFIG" ] && continue

    [ -n "${SEEN_CONFIGS[$CONFIG]}" ] && continue
    SEEN_CONFIGS[$CONFIG]=1

    CWD=$(readlink -f /proc/$PID/cwd 2>/dev/null || echo "$HOME")
    NR_UE_COUNT=$((NR_UE_COUNT + 1))

    echo "[recovery]   UE #$NR_UE_COUNT: config=$CONFIG  cwd=$CWD" | tee -a "$LOG_FILE"

    # Write restart command — pipe sudo password in, use setsid to detach from SSH
    cat >> "$CMD_FILE" << RESTART
echo "[restart] UE #${NR_UE_COUNT}: $CONFIG" >> "$LOG_FILE"
(cd '$CWD' && echo "\$SUDO_PASS" | setsid sudo -S ./build/nr-ue -c $CONFIG >>'$LOG_FILE' 2>&1 &)
sleep 2
RESTART
done

echo "[recovery]   Unique UEs detected: $NR_UE_COUNT" | tee -a "$LOG_FILE"

if [ "$NR_UE_COUNT" -eq 0 ]; then
    echo "[recovery] ✗ FATAL: No nr-ue processes found." | tee -a "$LOG_FILE"
    echo "[recovery]   Active processes:" | tee -a "$LOG_FILE"
    pgrep -a -f 'nr-ue' | tee -a "$LOG_FILE"
    exit 2
fi

# ── Phase 3: Kill nr-ue — must use sudo (they run as root) ────────────────────
echo "[recovery] Phase 3: Killing nr-ue (sudo required — they run as root)..." | tee -a "$LOG_FILE"
_sudo pkill -SIGTERM -f 'nr-ue' 2>/dev/null
sleep 3
_sudo pkill -9 -f 'nr-ue' 2>/dev/null
sleep 2

# Verify processes are dead
STILL_RUNNING=$(pgrep -c -f 'nr-ue' 2>/dev/null || echo 0)
echo "[recovery]   nr-ue processes still alive: $STILL_RUNNING (should be 0)" | tee -a "$LOG_FILE"

# Manually remove any leftover uesimtun interfaces (safety net)
echo "[recovery]   Cleaning up leftover uesimtun interfaces..." | tee -a "$LOG_FILE"
for IFACE in $(ip link show | grep -oP 'uesimtun\d+'); do
    echo "[recovery]     Removing $IFACE" | tee -a "$LOG_FILE"
    _sudo ip link delete "$IFACE" 2>/dev/null
done

sleep 3
REMAINING=$(ip -4 addr 2>/dev/null | grep -cE 'inet 10\.4[567]\.' || echo 0)
echo "[recovery]   GTP tunnel IPs remaining: $REMAINING (expected 0)" | tee -a "$LOG_FILE"

# Clear stale client logs
rm -f /tmp/mec-clients/*.log

# ── Phase 4: Restart UEs ──────────────────────────────────────────────────────
echo "[recovery] Phase 4: Restarting $NR_UE_COUNT UE(s)..." | tee -a "$LOG_FILE"
chmod +x "$CMD_FILE"
bash "$CMD_FILE"

echo "[recovery]   Giving 10s for initial nr-ue startup..." | tee -a "$LOG_FILE"
sleep 10

# Verify nr-ue is running (check as root since sudo spawned them)
RUNNING=$(_sudo pgrep -c -f 'nr-ue' 2>/dev/null || pgrep -c -f 'nr-ue' 2>/dev/null || echo 0)
echo "[recovery]   nr-ue processes running: $RUNNING (expected: $NR_UE_COUNT)" | tee -a "$LOG_FILE"

if [ "$RUNNING" -eq 0 ]; then
    echo "[recovery] ✗ nr-ue failed to start. Check log: tail $LOG_FILE" | tee -a "$LOG_FILE"
    tail -10 "$LOG_FILE"
    exit 1
fi

# ── Phase 5: Wait for all 9 GTP tunnels ──────────────────────────────────────
echo "[recovery] Phase 5: Waiting for 9 GTP tunnels (max ${TUNNEL_WAIT}s)..." | tee -a "$LOG_FILE"
echo "[recovery]   Expected: 3 eMBB (10.45.x.x) + 3 URLLC (10.46.x.x) + 3 mMTC (10.47.x.x)" | tee -a "$LOG_FILE"

DEADLINE=$(($(date +%s) + TUNNEL_WAIT))
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
    EMBB_COUNT=$(ip -4 addr 2>/dev/null | grep -c 'inet 10\.45\.' || echo 0)
    URLLC_COUNT=$(ip -4 addr 2>/dev/null | grep -c 'inet 10\.46\.' || echo 0)
    MMTC_COUNT=$(ip -4 addr 2>/dev/null | grep -c 'inet 10\.47\.' || echo 0)
    TOTAL=$((EMBB_COUNT + URLLC_COUNT + MMTC_COUNT))
    SECS_LEFT=$((DEADLINE - $(date +%s)))

    echo "[recovery]   Tunnels: eMBB=$EMBB_COUNT/$REQUIRED_EMBB  URLLC=$URLLC_COUNT/$REQUIRED_URLLC  mMTC=$MMTC_COUNT/$REQUIRED_MMTC  total=$TOTAL/9  (${SECS_LEFT}s left)" | tee -a "$LOG_FILE"

    if [ "$EMBB_COUNT" -ge "$REQUIRED_EMBB" ] && \
       [ "$URLLC_COUNT" -ge "$REQUIRED_URLLC" ] && \
       [ "$MMTC_COUNT" -ge "$REQUIRED_MMTC" ]; then
        echo "[recovery] ✓ All 9 GTP tunnels restored!" | tee -a "$LOG_FILE"
        ip -4 addr | grep 'inet 10\.4[567]\.' | awk '{print "  " $2, $NF}' | tee -a "$LOG_FILE"
        echo "[recovery] === Recovery Successful ===" | tee -a "$LOG_FILE"
        exit 0
    fi
    sleep 10
done

echo "[recovery] ✗ TIMEOUT: $TOTAL/9 tunnels after ${TUNNEL_WAIT}s" | tee -a "$LOG_FILE"
exit 1
