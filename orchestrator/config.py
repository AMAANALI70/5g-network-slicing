"""
config.py — Agentic Orchestrator Configuration
Loads all settings from .env file (never hardcode credentials).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from same directory as this file
_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path)

def _require(key: str) -> str:
    val = os.environ.get(key, "")
    if not val or val == f"your_{key.lower()}_here":
        raise EnvironmentError(
            f"\n[config] Missing required env var: {key}\n"
            f"  1. Copy .env.example → .env\n"
            f"  2. Fill in your {key}\n"
            f"  3. Re-run the orchestrator"
        )
    return val

def _get(key: str, default) -> str:
    return os.environ.get(key, str(default))

# ── LLM ────────────────────────────────────────────────
OLLAMA_HOST    = _get("OLLAMA_HOST",  "http://localhost:11434")
OLLAMA_MODEL   = _get("OLLAMA_MODEL", "llama3.2:3b")
# Groq kept as optional fallback (quota exhausted — not required)
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
LLM_MODEL      = _get("LLM_MODEL",       "llama3.2:3b")
LLM_TEMPERATURE= float(_get("LLM_TEMPERATURE", 0.2))
LLM_MAX_TOKENS = int(_get("LLM_MAX_TOKENS", 300))

# ── SLA ──────────────────────────────────────────────────
URLLC_RTT_SLA_MS     = float(_get("URLLC_RTT_SLA_MS",     20.0))
EMBB_MIN_TP_MBPS     = float(_get("EMBB_MIN_THROUGHPUT_MBPS", 20.0))
MMTC_MIN_PDR         = float(_get("MMTC_MIN_PDR",         0.995))

# ── eMBB Rate Control ─────────────────────────────────────
EMBB_RATE_MAX   = int(_get("EMBB_RATE_MAX_MBIT",   1000))
EMBB_RATE_FLOOR = int(_get("EMBB_RATE_FLOOR_MBIT",   50))
EMBB_INTERFACE  = _get("EMBB_INTERFACE", "ogstun-embb")

# ── Network ───────────────────────────────────────────────
WORKER_SSH_USER = _get("WORKER_SSH_USER", "kube")
WORKER_SSH_HOST = _get("WORKER_SSH_HOST", "192.168.49.171")
WORKER_SSH_KEY  = _get("WORKER_SSH_KEY",  "/root/.ssh/id_rsa")

UERANSIM_USER   = _get("UERANSIM_SSH_USER", "shinegami")
UERANSIM_HOST   = _get("UERANSIM_SSH_HOST", "192.168.49.139")
UERANSIM_PASS   = _get("UERANSIM_SSH_PASS", "123")

# ── Control Loop ──────────────────────────────────────────
LOOP_INTERVAL_SEC = int(_get("LOOP_INTERVAL_SEC", 3))
MEMORY_SIZE       = int(_get("MEMORY_SIZE",       10))
METRICS_PORT      = int(_get("METRICS_PORT",      9200))

# ── Prometheus ────────────────────────────────────────────
PROMETHEUS_URL    = _get("PROMETHEUS_URL", "http://localhost:30090")

# ── Derived / constant ────────────────────────────────────
RTT_TREND_WINDOW  = 4      # samples for slope calculation
RECOVERY_STREAK   = 3      # consecutive good RTTs to release throttle
OSCILLATION_HOLD  = 5      # min samples before switching state
