#!/bin/bash
# =============================================================
# realign_clients.sh — Slice-Aware UE Client Launcher
# =============================================================
# Run this on the UERANSIM VM (192.168.49.139) to:
#   1. Kill all stale traffic client processes
#   2. Detect which uesimtunX maps to which slice subnet
#   3. Launch ONLY the correct client per interface
#
# Slice subnet mapping:
#   10.45.0.0/24 → eMBB  → embb_client.py
#   10.46.0.0/24 → URLLC → urllc_client.py
#   10.47.0.0/24 → mMTC  → mmtc_client.py
# =============================================================

set -uo pipefail

SERVER_IP="${1:-192.168.49.172}"
CLIENTS_DIR="${HOME}/mec-clients"
LOG_DIR="/tmp/mec-clients"
EMBB_PORT=30880
URLLC_PORT=30180
MMTC_PORT=30883
PYTHON_BIN="python3"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }

mkdir -p "$LOG_DIR"

# ── Step 1: Kill all stale clients ──────────────────────────
info "Killing stale traffic clients..."
pkill -f "embb_client.py"  2>/dev/null && warn "  Killed embb_client"  || true
pkill -f "urllc_client.py" 2>/dev/null && warn "  Killed urllc_client" || true
pkill -f "mmtc_client.py"  2>/dev/null && warn "  Killed mmtc_client"  || true
pkill -f "mmtc_fixed.py"   2>/dev/null && warn "  Killed mmtc_fixed"   || true
sleep 2

# ── Step 2: Detect interface→subnet mapping ──────────────────
info "Scanning uesimtun interfaces..."
declare -a EMBB_IFACES URLLC_IFACES MMTC_IFACES

# Parse only uesimtunX interfaces (not ogstun which is the UPF gateway)
while read -r inet ip_cidr scope global iface_name; do
    [ "$inet" = "inet" ] || continue
    [[ "$iface_name" == uesimtun* ]] || continue   # ← KEY FIX: skip ogstun
    ip_addr="${ip_cidr%%/*}"

    case "$ip_addr" in
        10.45.*) EMBB_IFACES+=("$iface_name");  info "  eMBB  ← $iface_name ($ip_addr)" ;;
        10.46.*) URLLC_IFACES+=("$iface_name"); info "  URLLC ← $iface_name ($ip_addr)" ;;
        10.47.*) MMTC_IFACES+=("$iface_name");  info "  mMTC  ← $iface_name ($ip_addr)" ;;
    esac
done < <(ip -4 addr show | awk '
    /^[0-9]+:/ { iface = $2; gsub(/:/, "", iface) }
    /inet 10\.4[567]\./ { print "inet", $2, "scope", "global", iface }
')

# ── Step 3: Verify interface count ──────────────────────────
TOTAL=$((${#EMBB_IFACES[@]} + ${#URLLC_IFACES[@]} + ${#MMTC_IFACES[@]}))
info "Found: ${#EMBB_IFACES[@]} eMBB, ${#URLLC_IFACES[@]} URLLC, ${#MMTC_IFACES[@]} mMTC interfaces (total=$TOTAL)"

if [ "$TOTAL" -eq 0 ]; then
    warn "No tunnel interfaces found! Are the UEs connected?"
    warn "Run: cd ~/UERANSIM/build && sudo ./nr-ue -c ~/UERANSIM/config/ue1.yaml &"
    exit 1
fi

# ── Step 4: Launch correct clients (nohup+disown = survive SSH exit) ────
info "Launching slice-aligned traffic clients against $SERVER_IP..."

launch() {
    local script="$1" iface="$2" port="$3"
    local log="$LOG_DIR/${script%_client.py}_${iface}.log"
    # Truncate old log so we get fresh output
    > "$log"
    nohup $PYTHON_BIN "$CLIENTS_DIR/${script}.py" "$iface" "$SERVER_IP" "$port" \
        >> "$log" 2>&1 &
    local pid=$!
    disown $pid
    info "  Started ${script} on $iface (PID=$pid) → $log"
}

# eMBB — HLS video (1 client per eMBB interface)
for iface in "${EMBB_IFACES[@]}"; do  launch embb_client  "$iface" "$EMBB_PORT";  done
# URLLC — HTTP RTT telemetry
for iface in "${URLLC_IFACES[@]}"; do launch urllc_client "$iface" "$URLLC_PORT"; done
# mMTC — MQTT sensors
for iface in "${MMTC_IFACES[@]}"; do  launch mmtc_client  "$iface" "$MMTC_PORT";  done

# ── Step 5: Write supervisor script (auto-restart on crash) ──────────────
cat > "$LOG_DIR/watchdog.sh" << WATCHDOG
#!/bin/bash
# Auto-restarts clients that die. Run: nohup bash $LOG_DIR/watchdog.sh &
SERVER=$SERVER_IP
CLIENTS_DIR=${CLIENTS_DIR}
LOG_DIR=${LOG_DIR}
EMBB_IFACES=(${EMBB_IFACES[*]:-})
URLLC_IFACES=(${URLLC_IFACES[*]:-})
MMTC_IFACES=(${MMTC_IFACES[*]:-})
while true; do
    for iface in \${EMBB_IFACES[@]}; do
        pgrep -f "embb_client.py.*\$iface" > /dev/null || {
            echo "[watchdog] Restarting embb_client on \$iface"
            nohup python3 \$CLIENTS_DIR/embb_client.py \$iface \$SERVER $EMBB_PORT >> \$LOG_DIR/embb_\${iface}.log 2>&1 &
            disown
        }
    done
    for iface in \${URLLC_IFACES[@]}; do
        pgrep -f "urllc_client.py.*\$iface" > /dev/null || {
            echo "[watchdog] Restarting urllc_client on \$iface"
            nohup python3 \$CLIENTS_DIR/urllc_client.py \$iface \$SERVER $URLLC_PORT >> \$LOG_DIR/urllc_\${iface}.log 2>&1 &
            disown
        }
    done
    for iface in \${MMTC_IFACES[@]}; do
        pgrep -f "mmtc_client.py.*\$iface" > /dev/null || {
            echo "[watchdog] Restarting mmtc_client on \$iface"
            nohup python3 \$CLIENTS_DIR/mmtc_client.py \$iface \$SERVER $MMTC_PORT >> \$LOG_DIR/mmtc_\${iface}.log 2>&1 &
            disown
        }
    done
    sleep 30
done
WATCHDOG
chmod +x "$LOG_DIR/watchdog.sh"
# Start watchdog (if not already running)
pgrep -f "watchdog.sh" > /dev/null || { nohup bash "$LOG_DIR/watchdog.sh" > "$LOG_DIR/watchdog.log" 2>&1 & disown; info "  Watchdog started (PID=$!)"; }

sleep 5
echo ""
info "=== Client Status (first log lines) ==="
for f in "$LOG_DIR"/*.log; do
    [ -f "$f" ] && echo "  $(basename "$f"): $(tail -1 "$f" 2>/dev/null || echo '(empty)')"
done

info "✅ Client realignment complete."
info "   Monitor: tail -f $LOG_DIR/*.log"
