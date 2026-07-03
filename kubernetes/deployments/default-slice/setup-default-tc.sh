#!/bin/bash
# ============================================================
# setup-default-tc.sh
# Applies HTB traffic shaping on ogstun-embb (kube worker)
# to isolate default/best-effort traffic from dedicated eMBB traffic.
#
# Traffic Classification (by UE source IP):
#   10.45.0.0/16 (eMBB UEs)     → HTB class 1:10  (up to 100mbit, prio 1)
#   all other / default          → HTB class 1:20  (hard cap 20mbit, prio 2)
#
# Usage:
#   bash setup-default-tc.sh [apply|remove|status]
# ============================================================

WORKER_USER="kube"
WORKER_HOST="192.168.49.171"
WORKER_PASS="kube"          # set to actual password
IFACE="ogstun-embb"
EMBB_RATE="100mbit"
DEFAULT_RATE="20mbit"

ssh_run() {
    sshpass -p "$WORKER_PASS" ssh \
        -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
        "$WORKER_USER@$WORKER_HOST" "$1"
}

case "${1:-apply}" in
  apply)
    echo "[default-tc] Applying HTB+filter on $IFACE..."
    ssh_run "
      # ── Remove any existing root qdisc ──────────────────────
      sudo tc qdisc del dev $IFACE root 2>/dev/null || true

      # ── Root HTB qdisc ──────────────────────────────────────
      sudo tc qdisc add dev $IFACE root handle 1: htb default 20

      # ── Root class: total bandwidth budget ──────────────────
      sudo tc class add dev $IFACE parent 1: classid 1:1 htb rate 1000mbit ceil 1000mbit

      # ── Class 1:10 → eMBB dedicated slice (high prio) ───────
      sudo tc class add dev $IFACE parent 1:1 classid 1:10 htb \
        rate $EMBB_RATE ceil 1000mbit prio 1

      # ── Class 1:20 → Default best-effort (hard cap) ─────────
      sudo tc class add dev $IFACE parent 1:1 classid 1:20 htb \
        rate $DEFAULT_RATE ceil $DEFAULT_RATE prio 2

      # ── fq_codel on each leaf ────────────────────────────────
      sudo tc qdisc add dev $IFACE parent 1:10 handle 10: fq_codel
      sudo tc qdisc add dev $IFACE parent 1:20 handle 20: fq_codel

      # ── Filter: eMBB UE IPs (10.45.0.0/16) → class 1:10 ────
      sudo tc filter add dev $IFACE parent 1: protocol ip \
        prio 1 u32 match ip src 10.45.0.0/16 flowid 1:10

      # ── Default filter: everything else → class 1:20 ────────
      sudo tc filter add dev $IFACE parent 1: protocol ip \
        prio 2 u32 match u32 0 0 flowid 1:20

      echo 'HTB shaping applied on $IFACE'
      sudo tc -s qdisc show dev $IFACE
    "
    ;;

  remove)
    echo "[default-tc] Removing tc rules from $IFACE..."
    ssh_run "sudo tc qdisc del dev $IFACE root 2>/dev/null && echo 'Removed' || echo 'No rules found'"
    ;;

  status)
    echo "[default-tc] Current tc on $IFACE:"
    ssh_run "
      echo '── qdiscs ──────────────────────────'
      sudo tc -s qdisc show dev $IFACE
      echo '── classes ─────────────────────────'
      sudo tc -s class show dev $IFACE
      echo '── filters ─────────────────────────'
      sudo tc filter show dev $IFACE
    "
    ;;

  update-embb-rate)
    # Called by orchestrator to change eMBB rate dynamically
    NEW_RATE="${2:-100mbit}"
    echo "[default-tc] Updating eMBB class rate → $NEW_RATE"
    ssh_run "sudo tc class change dev $IFACE parent 1:1 classid 1:10 htb rate $NEW_RATE ceil 1000mbit prio 1"
    ;;

  *)
    echo "Usage: $0 [apply|remove|status|update-embb-rate <rate>]"
    exit 1
    ;;
esac
