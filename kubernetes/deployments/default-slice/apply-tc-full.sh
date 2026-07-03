#!/bin/bash
# ============================================================
# apply-tc-full.sh — Full tc setup for ALL UPF interfaces
# Run on the KUBE WORKER (kube@192.168.49.171) with sudo.
#
# ogstun-embb : HTB root → class 1:10 eMBB (100mbit) + class 1:20 default (20mbit)
# ogstun-urllc: HTB with priority scheduling (already set, verify only)
# ogstun-mmtc : already HTB (verify only)
#
# This script is IDEMPOTENT — safe to re-run after reboots.
# ============================================================

set -e

echo "=== Applying tc rules ==="

# ── ogstun-embb : HTB with eMBB + default-slice classes ─────────────────────
IFACE="ogstun-embb"
echo ""
echo "[1] $IFACE"

sudo tc qdisc del dev $IFACE root 2>/dev/null || true

sudo tc qdisc  add dev $IFACE root handle 1: htb default 20
sudo tc class  add dev $IFACE parent 1:  classid 1:1  htb rate 1000mbit ceil 1000mbit
sudo tc class  add dev $IFACE parent 1:1 classid 1:10 htb rate 100mbit  ceil 1000mbit prio 1
sudo tc class  add dev $IFACE parent 1:1 classid 1:20 htb rate 20mbit   ceil 20mbit   prio 2
sudo tc qdisc  add dev $IFACE parent 1:10 handle 10: fq_codel
sudo tc qdisc  add dev $IFACE parent 1:20 handle 20: fq_codel

# Filter: eMBB UE source IPs (10.45.0.0/16) → class 1:10
sudo tc filter add dev $IFACE parent 1: protocol ip prio 1 u32 \
  match ip src 10.45.0.0/16 flowid 1:10
# Default → class 1:20
sudo tc filter add dev $IFACE parent 1: protocol ip prio 2 u32 \
  match u32 0 0 flowid 1:20

echo "  eMBB class 1:10 → 100mbit | default class 1:20 → 20mbit"
sudo tc class show dev $IFACE

# ── Verify ogstun-urllc and ogstun-mmtc are still set ───────────────────────
echo ""
echo "[2] ogstun-urllc:"
sudo tc qdisc show dev ogstun-urllc

echo ""
echo "[3] ogstun-mmtc:"
sudo tc qdisc show dev ogstun-mmtc

echo ""
echo "=== All done. Verify PREROUTING DNAT for default-slice ==="
sudo iptables -t nat -L PREROUTING -n | grep 30800 || echo "  WARNING: DNAT rule for 30800 missing — re-add manually"
