"""
graph.py — LangGraph Agentic Workflow
Defines the 5-node observe→think→validate→act→reflect loop.
"""
import logging
import time
from typing import TypedDict, Optional, Any

from langgraph.graph import StateGraph, END

import config
from agent_memory import AgentMemory
from llm_planning_agent import LLMPlanningAgent

log = logging.getLogger("graph")


# ── State schema ─────────────────────────────────────────────────────────────
class AgentState(TypedDict):
    # Inputs (filled by observe node)
    metrics:        dict
    state_snapshot: dict

    # LLM decision (filled by think node)
    action:              str
    new_rate_int:        int
    reason:              str
    confidence:          float
    llm_used:            bool
    decision_latency_ms: float

    # Phase 1 CoT fields (filled by think node)
    root_cause_assessment: str
    lever_validity:        str
    wrong_lever_event:     bool
    lever_validity_score:  float

    # Safety (filled by validate node)
    safe:           bool
    safety_reason:  str

    # Execution (filled by act node)
    executed:       bool
    exec_success:   bool
    exec_error:     Optional[str]
    exec_ms:        Optional[float]   # SSH command latency

    # Outcome (filled by reflect node)
    rtt_after:              Optional[float]
    _needs_outcome_update:  bool   # flag: next observe should update prev entry


# ── Node implementations ──────────────────────────────────────────────────────

def observe_node(state: AgentState, monitor, state_agent, memory) -> AgentState:
    """Collect current network metrics and orchestrator state."""
    # FIX: update previous decision's rtt_after with current (post-action) RTT
    # This must run BEFORE collecting new metrics so we capture the outcome
    if state.get("_needs_outcome_update", False):
        prev_rtt = state.get("metrics", {}).get("urllc_rtt_99", 0)
        if prev_rtt > 0:
            memory.update_outcome(prev_rtt)

    try:
        metrics        = monitor.collect()
        state_snapshot = state_agent.update(metrics)
        log.info(
            f"[Observe ] RTT={metrics.get('urllc_rtt_99', 0):.1f}ms  "
            f"eMBB={metrics.get('embb_tp', 0)/1e6:.1f}Mbps  "
            f"dead={metrics.get('urllc_dead_tunnels', 0)}  "
            f"trend={state_snapshot.get('rtt_trend','?')}"
        )
    except Exception as e:
        log.error(f"[Observe ] Collection error: {e}")
        metrics        = {"urllc_rtt_99": 0, "embb_tp": 0, "mmtc_pdr": 1.0,
                         "drops": 0, "cpu": 0, "urllc_dead_tunnels": 0}
        state_snapshot = {"rtt_trend": "stable", "violation_count": 0,
                         "stable_for": 0, "oscillation": False,
                         "current_embb_rate": config.EMBB_RATE_MAX,
                         "last_action": "none"}
    return {**state, "metrics": metrics, "state_snapshot": state_snapshot,
            "_needs_outcome_update": False}


def think_node(state: AgentState, llm_agent: LLMPlanningAgent) -> AgentState:
    """LLM reasons about current state and decides action."""
    decision = llm_agent.decide(state["metrics"], state["state_snapshot"])
    return {
        **state,
        "action":                decision["action"],
        "new_rate_int":          decision["new_rate_int"],
        "reason":                decision["reason"],
        "confidence":            decision["confidence"],
        "llm_used":              decision.get("llm_used", True),
        "decision_latency_ms":   decision.get("decision_latency_ms", 0),
        # Phase 1 CoT fields
        "root_cause_assessment": decision.get("root_cause_assessment", ""),
        "lever_validity":        decision.get("lever_validity", ""),
        "wrong_lever_event":     decision.get("wrong_lever_event", False),
        "lever_validity_score":  decision.get("lever_validity_score", 0.0),
    }


def validate_node(state: AgentState, safety) -> AgentState:
    """SafetyGate: block dangerous LLM decisions."""
    action      = state["action"]
    new_rate    = state["new_rate_int"]
    metrics     = state["metrics"]

    safe        = True
    safety_reason = "OK"

    # Never go below floor
    if new_rate < config.EMBB_RATE_FLOOR:
        safe          = False
        safety_reason = f"Rate {new_rate} below floor {config.EMBB_RATE_FLOOR}Mbit"

    # Never go above ceiling
    if new_rate > config.EMBB_RATE_MAX:
        safe          = False
        safety_reason = f"Rate {new_rate} above ceiling {config.EMBB_RATE_MAX}Mbit"

    # Extra safety check via existing SafetyGate if available
    if safety is not None:
        try:
            gate_ok = safety.check(action, new_rate, metrics)
            if not gate_ok:
                safe          = False
                safety_reason = "SafetyGate blocked action"
        except Exception:
            pass  # SafetyGate optional

    if not safe:
        log.warning(f"[Validate] BLOCKED: {safety_reason}")

    return {**state, "safe": safe, "safety_reason": safety_reason}


def act_node(state: AgentState, executor) -> AgentState:
    """Apply the decision via ExecutionAgent (tc ssh command)."""
    decision = {
        "action":       state["action"],
        "new_rate":     f"{state['new_rate_int']}mbit",
        "new_rate_int": state["new_rate_int"],
        "confidence":   state["confidence"],
        "reason":       state["reason"],
    }

    executed    = False
    exec_success= False
    exec_error  = None
    outcome     = {}   # always defined; populated only when action is executed

    if state["action"] != "no_action":
        try:
            outcome      = executor.execute(decision, state["metrics"])
            executed     = outcome.get("action_executed", False)
            exec_success = outcome.get("success", False)
            exec_error   = outcome.get("error")
            status       = "✅" if exec_success else "❌"
            log.info(
                f"[Act     ] {status} {state['action']} → "
                f"{state['new_rate_int']}Mbit  err={exec_error}"
            )
        except Exception as e:
            exec_error = str(e)
            log.error(f"[Act     ] Execution exception: {e}")
    else:
        log.info(f"[Act     ] no_action — holding at {state['new_rate_int']}Mbit")

    return {
        **state,
        "executed":     executed,
        "exec_success": exec_success,
        "exec_error":   exec_error,
        "exec_ms":      outcome.get("exec_ms"),   # None when no_action or on error
    }


def reflect_node(state: AgentState, memory: AgentMemory, state_agent) -> AgentState:
    """Flag that next observe cycle should capture post-action RTT outcome."""
    action_taken = state.get("action", "no_action")

    # Only request outcome capture when an action was actually executed
    needs_update = (action_taken != "no_action" and state.get("executed", False))

    log.info(
        f"[Reflect ] action={action_taken}  "
        f"executed={state['executed']}  "
        f"success={state['exec_success']}  "
        f"latency={state['decision_latency_ms']}ms  "
        f"outcome_pending={needs_update}"
    )

    # Record action in state_agent for oscillation tracking etc.
    if action_taken not in ("no_action", "none") and state.get("executed", False):
        state_agent.record_action(
            action=action_taken,
            new_rate=state.get("new_rate_int", config.EMBB_RATE_MAX),
        )

    return {**state, "_needs_outcome_update": needs_update}


# ── Graph factory ──────────────────────────────────────────────────────────────

def build_graph(monitor, state_agent, memory: AgentMemory,
                safety, executor) -> Any:
    """Compile and return the LangGraph workflow."""
    llm_agent = LLMPlanningAgent(memory)

    graph = StateGraph(AgentState)

    # Add nodes with closures injecting dependencies
    graph.add_node("observe",  lambda s: observe_node(s, monitor, state_agent, memory))
    graph.add_node("think",    lambda s: think_node(s, llm_agent))
    graph.add_node("validate", lambda s: validate_node(s, safety))
    graph.add_node("act",      lambda s: act_node(s, executor))
    graph.add_node("reflect",  lambda s: reflect_node(s, memory, state_agent))

    # Edges
    graph.set_entry_point("observe")
    graph.add_edge("observe",  "think")
    graph.add_edge("think",    "validate")

    # Conditional: safe → act → reflect; unsafe → reflect (skip execution)
    graph.add_conditional_edges(
        "validate",
        lambda s: "act" if s.get("safe", True) else "reflect",
        {"act": "act", "reflect": "reflect"},
    )
    graph.add_edge("act",     "reflect")
    graph.add_edge("reflect", END)

    compiled = graph.compile()
    log.info("[Graph  ] LangGraph workflow compiled: observe→think→validate→act→reflect")
    return compiled, llm_agent
