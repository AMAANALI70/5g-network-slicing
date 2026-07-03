"""
QoS Orchestrator — Configuration
SLA thresholds, rate limits, and control parameters.
"""

# ── Prometheus ────────────────────────────────────────────────
PROMETHEUS_URL = "http://localhost:30090"
QUERY_RANGE = "15s"          # rate() window

# ── SLA Thresholds ────────────────────────────────────────────
URLLC_RTT_SLA_MS      = 5.0       # Max acceptable URLLC RTT (ms)
EMBB_MIN_THROUGHPUT   = 20_000_000  # 20 Mbit/s in bytes/sec (2.5 MB/s)
MMTC_MIN_PDR          = 0.995     # 99.5% packet delivery ratio

# ── eMBB Rate Control ─────────────────────────────────────────
EMBB_RATE_MAX         = 100       # 100 Mbit — default ceiling
EMBB_RATE_FLOOR       = 20        # 20 Mbit — never go below
EMBB_THROTTLE_STEP    = 20        # Reduce by 20 Mbit per action
EMBB_RESTORE_STEP     = 10        # Restore by 10 Mbit per action
EMBB_INTERFACE        = "ogstun-embb"
EMBB_CLASSID          = "1:1"

# ── URLLC Interface ───────────────────────────────────────────
URLLC_INTERFACE       = "ogstun-urllc"

# ── Control Loop ──────────────────────────────────────────────
LOOP_INTERVAL_SEC     = 3         # Control loop period
COOLDOWN_SEC          = 10        # Min seconds between actions
STABILITY_WINDOW_SEC  = 60        # Seconds of stability before restore
HISTORY_SIZE          = 20        # Sliding window size (20 × 3s = 60s)

# ── Oscillation Detection ─────────────────────────────────────
OSCILLATION_WINDOW    = 6         # Check last 6 actions
OSCILLATION_THRESHOLD = 4         # If 4+ direction changes → oscillating

# ── Metrics Server ────────────────────────────────────────────
METRICS_PORT          = 9200      # Prometheus exporter port
