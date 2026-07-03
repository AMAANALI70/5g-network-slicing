"""
llm_planning_agent.py — Ollama LLM Decision Node
=================================================
Primary backend: Ollama local inference (llama3.2:3b).
Fallback: rule-based logic if Ollama is unavailable.

Groq is retained as a commented reference; re-enable by swapping
_call_llm() back to _call_groq() and setting GROQ_API_KEY.
"""
import json
import logging
import time
import urllib.request
import urllib.error
from typing import Optional

import config
from prompt import SYSTEM_PROMPT, build_user_prompt
from agent_memory import AgentMemory

log = logging.getLogger("llm_agent")


class LLMPlanningAgent:
    """
    Calls Ollama LLM to decide orchestration action.
    Falls back to rule-based logic if Ollama fails or times out.
    """

    def __init__(self, memory: AgentMemory):
        self.memory = memory
        self._last_action_time = 0.0
        self._cooldown_sec     = 15   # min seconds between non-no_action decisions
        log.info(f"[LLMAgent] Initialized — backend=Ollama  model={config.OLLAMA_MODEL}"
                 f"  host={config.OLLAMA_HOST}")

    # ── Public interface ──────────────────────────────────────────────────────

    def decide(self, metrics: dict, state: dict) -> dict:
        """
        Main entry point. Returns decision dict compatible with ExecutionAgent.
        Memory context is passed to the LLM prompt AND recorded in the decision
        dict so cot_trace_logger can capture it (A3 fix).
        """
        t0 = time.time()

        memory_entries    = self.memory.get_recent(5)
        memory_text       = self.memory.format_for_prompt(n=5)
        memory_entry_count = len(memory_entries)
        memory_has_history = memory_entry_count > 0
        user_prompt = build_user_prompt(metrics, state, memory_text)

        try:
            decision = self._call_ollama(user_prompt)
            decision["llm_used"] = True
        except Exception as e:
            log.warning(f"[LLMAgent] Ollama call failed: {e} — falling back to rule-based")
            decision = self._rule_based_fallback(metrics, state)
            decision["llm_used"]         = False
            decision["prompt_tokens"]    = 0
            decision["completion_tokens"]= 0
            decision["total_tokens"]     = 0
            decision["model_name"]       = "fallback"

        # Hard safety clamp
        decision = self._enforce_constraints(decision, state)

        latency_ms = round((time.time() - t0) * 1000, 1)
        decision["decision_latency_ms"]   = latency_ms
        # A3 — memory context captured for CoT trace logging
        decision["memory_context_summary"] = memory_text
        decision["memory_entry_count"]     = memory_entry_count
        decision["memory_has_history"]     = memory_has_history
        decision.setdefault("llm_used", True)

        log.info(
            f"[LLMAgent] action={decision['action']}  "
            f"rate={decision['new_rate_int']}Mbit  "
            f"conf={decision['confidence']:.2f}  "
            f"latency={latency_ms}ms  llm={decision['llm_used']}  "
            f"mem_entries={memory_entry_count}  "
            f"tokens={decision.get('total_tokens',0)}"
        )
        log.info(f"[LLMAgent] reasoning: {decision['reason']}")

        # Record in memory (outcome filled next cycle by reflect node)
        self.memory.record(
            rtt                = metrics.get("urllc_rtt_99", 0),
            embb_rate          = state.get("current_embb_rate", config.EMBB_RATE_MAX),
            action             = decision["action"],
            reasoning          = decision["reason"],
            confidence         = decision["confidence"],
            root_cause         = decision.get("root_cause_assessment", ""),
            lever_valid        = decision.get("lever_validity", ""),
            embb_load_fraction = metrics.get("embb_load_fraction"),
        )

        return decision

    # ── Ollama backend ────────────────────────────────────────────────────────

    def _call_ollama(self, user_prompt: str) -> dict:
        """
        POST to Ollama /api/chat with json format enforcement.
        Timeout: 60s — accommodates ~15s inference with margin.
        """
        payload = json.dumps({
            "model":   config.OLLAMA_MODEL,
            "stream":  False,
            "format":  "json",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            "options": {
                "temperature": config.LLM_TEMPERATURE,
                "num_predict": 400,   # raised: CoT fields add ~100 tokens
            }
        }).encode()

        req = urllib.request.Request(
            f"{config.OLLAMA_HOST}/api/chat",
            data    = payload,
            headers = {"Content-Type": "application/json"},
            method  = "POST",
        )

        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = json.loads(resp.read().decode())

        content = raw["message"]["content"].strip()
        parsed  = json.loads(content)

        # B2 — extract token counts from Ollama response
        eval_tok   = raw.get("eval_count", 0)
        prompt_tok = raw.get("prompt_eval_count", 0)
        total_tok  = eval_tok + prompt_tok
        eval_dur   = raw.get("eval_duration", 1) / 1e9
        gen_rate   = eval_tok / max(eval_dur, 0.001)
        model_name = raw.get("model", config.OLLAMA_MODEL)

        log.debug(
            f"[LLMAgent] tokens prompt={prompt_tok} completion={eval_tok} "
            f"total={total_tok} gen_rate={gen_rate:.1f}t/s"
        )

        result = self._parse_response(parsed)
        result["prompt_tokens"]     = prompt_tok
        result["completion_tokens"] = eval_tok
        result["total_tokens"]      = total_tok
        result["model_name"]        = model_name
        return result

    def _parse_response(self, parsed: dict) -> dict:
        """Validate and normalise the LLM JSON response, including Phase 1 CoT fields."""
        action     = parsed.get("action", "no_action")
        reason     = parsed.get("reasoning", parsed.get("reason", "LLM decision"))
        confidence = float(parsed.get("confidence", 0.7))

        # ── Phase 1 CoT fields ────────────────────────────────────────────────
        root_cause  = parsed.get("root_cause_assessment", "")
        lever_valid = parsed.get("lever_validity", "")

        if root_cause:
            log.info(f"[LLMAgent] root_cause:  {root_cause}")
        if lever_valid:
            log.info(f"[LLMAgent] lever_valid: {lever_valid}")

        # Detect contradiction: root_cause denies eMBB congestion but action
        # selects throttle_embb.  Downgrade confidence so the safety gate can
        # catch marginal cases and so experiment logs are annotated.
        _deny_kw = ["not embb", "embb is not", "embb not", "low load",
                    "nearly idle", "not the cause", "cannot help",
                    "wrong lever", "unlikely", "idle"]
        contradiction = (
            action == "throttle_embb"
            and bool(root_cause)
            and any(kw in root_cause.lower() for kw in _deny_kw)
        )
        if contradiction:
            log.warning(
                "[LLMAgent] CONTRADICTION: root_cause denies eMBB congestion "
                "but action=throttle_embb — downgrading confidence to 0.35"
            )
            confidence = min(confidence, 0.35)

        # ── WLA scoring (Phase 1) ─────────────────────────────────────────────
        # wrong_lever_event: boolean — True when model tried to throttle eMBB
        #   but its own root_cause assessment denied eMBB as the cause.
        # lever_validity_score: 0.0-1.0 — post-contradiction-adjusted confidence.
        #   High score = model correctly identified lever; low = contradiction caught.
        wrong_lever_event    = contradiction   # bool; see contradiction block above
        lever_validity_score = round(confidence, 3)  # already halved if contradiction

        if wrong_lever_event:
            log.warning(
                f"[LLMAgent] WLA EVENT: wrong_lever_event=True  "
                f"lever_validity_score={lever_validity_score:.3f}"
            )

        # ── patch_replicas disabled for primary comparison ────────────────────
        if action == "patch_replicas":
            log.info("[LLMAgent] patch_replicas suppressed (primary comparison mode)")
            action = "no_action"
            reason = reason + " [patch_replicas disabled]"

        # ── tc shaping actions ────────────────────────────────────────────────
        # Guard: model may output "new_rate_mbit": null for no_action — use
        # 'or' chain so None values fall through to the config default.
        new_rate = int(
            parsed.get("new_rate_mbit") or
            parsed.get("new_rate_int") or
            config.EMBB_RATE_MAX
        )


        if action not in ("throttle_embb", "restore_embb", "no_action"):
            log.warning(f"[LLMAgent] Unknown action '{action}' — defaulting to no_action")
            action   = "no_action"
            new_rate = config.EMBB_RATE_MAX

        return {
            "action":                action,
            "new_rate":              f"{new_rate}mbit",
            "new_rate_int":          new_rate,
            "reason":                reason,
            "confidence":            confidence,
            "root_cause_assessment": root_cause,
            "lever_validity":        lever_valid,
            "contradiction":         contradiction,
            "wrong_lever_event":     wrong_lever_event,
            "lever_validity_score":  lever_validity_score,
        }

    # ── Safety constraints ────────────────────────────────────────────────────

    def _enforce_constraints(self, decision: dict, state: dict) -> dict:
        """Hard safety: clamp rate to [FLOOR, MAX], enforce cooldown."""
        action = decision["action"]
        rate   = decision.get("new_rate_int", config.EMBB_RATE_MAX)
        rate   = max(config.EMBB_RATE_FLOOR, min(config.EMBB_RATE_MAX, rate))

        now = time.time()
        if action != "no_action":
            if (now - self._last_action_time) < self._cooldown_sec:
                remaining = self._cooldown_sec - (now - self._last_action_time)
                log.info(f"[LLMAgent] Cooldown active ({remaining:.0f}s remaining) "
                         f"— overriding to no_action")
                decision["action"]  = "no_action"
                decision["reason"] += f" [cooldown {remaining:.0f}s]"
                rate = state.get("current_embb_rate", config.EMBB_RATE_MAX)
            else:
                self._last_action_time = now

        decision["new_rate_int"] = rate
        decision["new_rate"]     = f"{rate}mbit"
        return decision

    # ── Rule-based fallback ───────────────────────────────────────────────────

    @staticmethod
    def _rule_based_fallback(metrics: dict, state: dict) -> dict:
        """Minimal fallback when Ollama is unavailable."""
        rtt        = metrics.get("urllc_rtt_99", 0.0)
        cur_rate   = state.get("current_embb_rate", config.EMBB_RATE_MAX)
        stable_for = state.get("stable_for", 0)

        if rtt > config.URLLC_RTT_SLA_MS:
            new_rate = max(config.EMBB_RATE_FLOOR, cur_rate // 2)
            return {
                "action": "throttle_embb", "new_rate": f"{new_rate}mbit",
                "new_rate_int": new_rate, "confidence": 0.6,
                "reason": f"[FALLBACK] RTT={rtt:.1f}ms > SLA; halving eMBB rate",
            }
        elif stable_for > 60 and cur_rate < config.EMBB_RATE_MAX:
            new_rate = min(config.EMBB_RATE_MAX, cur_rate + 200)
            return {
                "action": "restore_embb", "new_rate": f"{new_rate}mbit",
                "new_rate_int": new_rate, "confidence": 0.5,
                "reason": f"[FALLBACK] Stable {stable_for:.0f}s; restoring eMBB",
            }
        return {
            "action": "no_action", "new_rate": f"{cur_rate}mbit",
            "new_rate_int": cur_rate, "confidence": 0.8,
            "reason": "[FALLBACK] SLA within bounds; no action",
        }
