"""
prompt.py — LLM Prompt Templates for Agentic 5G Orchestrator

Design philosophy:
  The system prompt defines WHAT the orchestrator is and WHAT it can do.
  It does NOT encode decision thresholds or graduated response rules.
  The LLM must reason from context, not execute a lookup table.

Phase 1 changes:
  - OUTPUT FORMAT now requires root_cause_assessment and lever_validity
    BEFORE the action field. This forces explicit causal reasoning rather
    than direct pattern-to-action mapping.
  - build_user_prompt exposes embb_load_fraction so the model can evaluate
    eMBB load relative to its observed operating range, not as a raw number.
  - Memory guidance strengthened: model must explicitly reference prior
    outcomes before choosing an action.
"""
import importlib.util, os as _os

# Explicitly load the local config.py (not orchestrator/config.py)
_cfg_path = _os.path.join(_os.path.dirname(__file__), "config.py")
_spec = importlib.util.spec_from_file_location("agentic_config", _cfg_path)
_cfg  = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cfg)

URLLC_RTT_SLA_MS = _cfg.URLLC_RTT_SLA_MS
EMBB_RATE_FLOOR  = _cfg.EMBB_RATE_FLOOR
EMBB_RATE_MAX    = _cfg.EMBB_RATE_MAX
EMBB_MIN_TP_MBPS = _cfg.EMBB_MIN_TP_MBPS
MMTC_MIN_PDR     = _cfg.MMTC_MIN_PDR


SYSTEM_PROMPT = f"""You are an autonomous 5G network QoS orchestrator managing a live testbed with three network slices sharing a GTP-U data plane.

SLICES:
  URLLC (10.46.x tunnels) — Industrial HTTP telemetry. Latency-critical. SLA: RTT < {URLLC_RTT_SLA_MS}ms
  eMBB  (10.45.x tunnels) — HLS video streaming. Throughput-critical. SLA: > {EMBB_MIN_TP_MBPS}Mbps
  mMTC  (10.47.x tunnels) — MQTT IoT sensors. Delivery-critical. SLA: PDR > {MMTC_MIN_PDR*100:.0f}%

PHYSICAL ARCHITECTURE:
  All three slices share the same GTP-U backhaul on the worker node (192.168.49.172).
  eMBB video traffic is the dominant consumer of bandwidth (~150-200Mbps at peak load).
  When eMBB actively bursts (high load fraction), GTP-U queue depth increases, raising URLLC RTT.
  The UPF-eMBB pod processes all eMBB GTP packets and is CPU-intensive (~700-800mCPU at peak).
  IMPORTANT: tc shaping on eMBB only helps if eMBB is currently contributing to queue pressure.
  If eMBB load fraction is low (e.g. < 0.2), eMBB is not the congestion source — throttling it cannot reduce URLLC RTT.

YOUR CONTROL LEVER (primary comparison):
  eMBB bandwidth shaping (tc-htb applied to ogstun-embb on worker node).
  Range: {EMBB_RATE_FLOOR}Mbit (hard minimum) to {EMBB_RATE_MAX}Mbit (unconstrained).
  Effect: Throttling eMBB reduces queuing pressure on the shared GTP backhaul → URLLC RTT decreases.
  Speed: Fast (sub-second). Reversible.
  Actions: throttle_embb (reduce rate), restore_embb (increase rate), no_action (hold)

REASONING APPROACH — follow these steps in order:

  STEP 1 — MEMORY CHECK:
    Read RECENT DECISION HISTORY carefully.
    If the last action was throttle_embb: did RTT improve afterward? If yes → consider restore_embb if stable.
    If the last restore led to RTT spike → do not restore yet.
    If no history → proceed to Step 2.

  STEP 2 — ROOT CAUSE IDENTIFICATION:
    Is RTT elevated? Check embb_load_fraction first.
    If embb_load_fraction > 0.5: eMBB is actively bursting — it is plausibly causing queue pressure.
    If embb_load_fraction < 0.2: eMBB is nearly idle — tc shaping CANNOT help — use no_action.
    If embb_load_fraction is N/A (insufficient history): USE embb_tp_mbps as the WLA signal.
      → If embb_tp < 5Mbps: eMBB is INACTIVE — throttling it CANNOT reduce URLLC RTT.
        The RTT elevation is caused by an external factor (network delay, routing, netem).
        CORRECT action: no_action — do NOT throttle eMBB.
      → If embb_tp > 50Mbps: eMBB is actively transmitting — treat as potential congestion source.

  STEP 3 — LEVER VALIDITY:
    Will throttle_embb actually address the identified root cause?
    Only throttle if: RTT is elevated AND eMBB is the plausible cause (high load fraction or rising trend).
    Only restore if: RTT is within SLA AND system has been stable AND prior throttle was effective.

  PRIORITY: URLLC RTT protection > mMTC delivery > eMBB throughput preservation.

OUTPUT FORMAT — JSON only, no markdown, no text outside the JSON object.
You MUST include root_cause_assessment and lever_validity before action.

{{
  "root_cause_assessment": "<one sentence: what is causing the observed RTT behaviour, referencing embb_load_fraction and memory evidence>",
  "lever_validity": "<one sentence: whether throttle_embb can address the identified cause, and why>",
  "action": "throttle_embb" | "restore_embb" | "no_action",
  "new_rate_mbit": <integer {EMBB_RATE_FLOOR}–{EMBB_RATE_MAX}>,
  "reasoning": "<one sentence: what you observed, root cause, and why this action addresses it>",
  "confidence": <float 0.0–1.0>
}}"""


def build_user_prompt(metrics: dict, state: dict, memory_text: str) -> str:
    rtt        = metrics.get("urllc_rtt_99", 0.0)
    rtt_max    = metrics.get("urllc_rtt_max", rtt)
    embb_tp    = metrics.get("embb_tp_mbps", metrics.get("embb_tp", 0) / 1e6)
    embb_pkt   = metrics.get("embb_pkt_rate", 0.0)
    embb_cpu   = metrics.get("embb_pod_cpu_m", 0.0)
    embb_frac  = metrics.get("embb_load_fraction", None)  # None = cold-start
    mmtc_pdr   = metrics.get("mmtc_pdr", 1.0)
    mmtc_msgs  = metrics.get("mmtc_msgs_total", 0)
    fails      = metrics.get("urllc_fails", 0)
    dead_tun   = metrics.get("urllc_dead_tunnels", 0)
    loss_rate  = metrics.get("urllc_loss_rate", 0.0)
    cpu        = metrics.get("cpu", 0)

    trend      = state.get("rtt_trend", "stable")
    violations = state.get("violation_count", 0)
    stable_for = state.get("stable_for", 0)
    oscillating= state.get("oscillation", False)
    cur_rate   = state.get("current_embb_rate", EMBB_RATE_MAX)
    last_action= state.get("last_action", "none")
    urllc_rep  = state.get("urllc_replicas", 1)
    embb_rep   = state.get("embb_replicas", 1)
    mmtc_rep   = state.get("mmtc_replicas", 1)

    # SLA status strings
    rtt_sla  = "✅ WITHIN SLA" if rtt <= URLLC_RTT_SLA_MS else f"❌ VIOLATED (+{rtt - URLLC_RTT_SLA_MS:.1f}ms)"
    if embb_tp == 0.0:
        embb_sla = "INACTIVE (0 Mbps) — eMBB is NOT transmitting; throttling will have NO effect"
    elif embb_tp >= EMBB_MIN_TP_MBPS:
        embb_sla = "✅ OK"
    else:
        embb_sla = f"⚠️ LOW ({embb_tp:.1f}Mbps)"
    mmtc_sla = "✅ OK" if mmtc_pdr >= MMTC_MIN_PDR else f"⚠️ DEGRADED ({mmtc_pdr:.2f})"
    dead_str = f"⚠️ {dead_tun} DEAD" if dead_tun > 0 else "OK"

    # embb_load_fraction display
    if embb_frac is None:
        frac_str = "N/A (< 5 samples — use embb_tp_mbps as WLA signal instead)"
    else:
        pct = embb_frac * 100
        if embb_frac >= 0.7:
            tag = "HIGH — likely congestion source"
        elif embb_frac >= 0.3:
            tag = "MODERATE"
        else:
            tag = "LOW — unlikely congestion source; tc shaping will not reduce RTT"
        frac_str = f"{embb_frac:.2f} ({pct:.0f}% of session peak) ← {tag}"

    # Computed WLA alert — injected when eMBB is demonstrably idle
    wla_alert = ""
    if embb_tp < 5.0:
        wla_alert = f"""
⚠️  WLA ALERT: eMBB throughput = {embb_tp:.1f}Mbps — eMBB is IDLE.
    Throttling eMBB (throttle_embb) will have ZERO effect on URLLC RTT.
    The RTT elevation is caused by an external factor (netem delay, routing, or core network latency).
    REQUIRED action for this state: no_action
    Do NOT issue throttle_embb when eMBB is transmitting < 5Mbps.
"""

    prompt = f"""CURRENT NETWORK STATE (snapshot at decision time):{wla_alert}

  URLLC (latency-critical):
    RTT avg:       {rtt:.2f}ms     {rtt_sla}
    RTT max:       {rtt_max:.2f}ms
    RTT trend:     {trend}
    Dead tunnels:  {dead_tun}/3    {dead_str}
    Tunnel fails:  {fails} (cumulative since last log line)
    Loss rate:     {loss_rate:.1%} of tunnels unreachable

  eMBB (throughput):
    Throughput:    {embb_tp:.1f}Mbps   {embb_sla}
    Packet rate:   {embb_pkt:.0f} pkt/s
    Load fraction: {frac_str}
    Pod CPU:       {embb_cpu:.0f}mCPU
    tc rate limit: {cur_rate}Mbit

  mMTC (IoT delivery):
    PDR (tunnels): {mmtc_pdr:.2f}     {mmtc_sla}
    Msgs total:    {mmtc_msgs}

  Infrastructure:
    Master CPU:    {cpu}%
    Replicas:      urllc-app={urllc_rep}  embb-app={embb_rep}  mmtc-app={mmtc_rep}

  Orchestration:
    Violation cnt: {violations} (cumulative)
    Stable for:    {stable_for:.0f}s
    Oscillating:   {oscillating}
    Last action:   {last_action}

RECENT DECISION HISTORY (newest first, includes RTT outcome after action):
{memory_text}

Follow the 3-step reasoning approach. Output JSON only."""

    return prompt
