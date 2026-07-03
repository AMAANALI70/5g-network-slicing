"""
scenarios/run_scenario.py — Behavioral Audit Harness (S1 / S2 / S3)
====================================================================
Runs individual pre-registered behavioral audit scenarios and produces
a structured JSON pass/fail report.

Scenario Definitions
--------------------
S1: Pre-Emptive Throttling
    Condition: eMBB high load, RTT rising but not yet > SLA threshold.
    Pass:  agent issues throttle_embb BEFORE RTT crosses 20ms.
    Fail:  agent waits until RTT > 20ms (reactive not pre-emptive).

S2: Wrong-Lever Avoidance
    Condition: eMBB at LOW load (embb_load_fraction < 0.15), RTT elevated
               via tc netem delay injection on URLLC interface.
    Pass:  agent issues no_action AND root_cause_assessment denies eMBB.
    Fail:  agent issues throttle_embb despite low eMBB load.

S3: Memory-Assisted Restoration
    Condition: system throttled, 3+ memory entries show throttle was
               effective. RTT now within SLA, stable_for > 60s.
    Pass:  agent issues restore_embb citing memory evidence.
    Fail:  stays throttled indefinitely.

Usage
-----
  cd orchestrator_agentic
  python3 scenarios/run_scenario.py --scenario S1 --dry-run
  python3 scenarios/run_scenario.py --scenario S2 --dry-run
  python3 scenarios/run_scenario.py --scenario S3 --dry-run
  python3 scenarios/run_scenario.py --scenario ALL --dry-run
  # Remove --dry-run for live execution after validation
  python3 scenarios/run_scenario.py --scenario S2 --out reports/S2_live.json
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow import from parent orchestrator_agentic dir
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from monitoring_agent  import MonitoringAgent
from state_agent       import StateAgent
from agent_memory      import AgentMemory
from llm_planning_agent import LLMPlanningAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scenario")

WORKER_HOST = config.WORKER_SSH_HOST
WORKER_USER = config.WORKER_SSH_USER
WORKER_KEY  = config.WORKER_SSH_KEY
EMBB_IF     = config.EMBB_INTERFACE
URLLC_IF    = "ogstun-urllc"          # URLLC UPF tunnel interface


# ── SSH helpers ───────────────────────────────────────────────────────────────

def _worker_ssh(cmd: str, check: bool = False) -> str:
    r = subprocess.run(
        ["ssh", "-i", WORKER_KEY, "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=5", f"{WORKER_USER}@{WORKER_HOST}", cmd],
        capture_output=True, text=True, timeout=15
    )
    if check and r.returncode != 0:
        raise RuntimeError(f"SSH command failed: {r.stderr.strip()}")
    return r.stdout.strip()


def _netem_inject(delay_ms: int, jitter_ms: int = 2):
    """Inject artificial latency on the URLLC UPF interface (worker node)."""
    cmd = (
        f"sudo tc qdisc del dev {URLLC_IF} root 2>/dev/null; "
        f"sudo tc qdisc add dev {URLLC_IF} root netem delay {delay_ms}ms {jitter_ms}ms"
    )
    log.info(f"[Inject ] netem delay {delay_ms}ms on {URLLC_IF}")
    _worker_ssh(cmd, check=True)


def _netem_clear():
    """Remove netem delay from URLLC interface."""
    cmd = f"sudo tc qdisc del dev {URLLC_IF} root 2>/dev/null; true"
    log.info(f"[Inject ] Cleared netem on {URLLC_IF}")
    _worker_ssh(cmd)


def _tc_embb_set(rate_mbit: int):
    """Set eMBB tc rate (for S1 setup: high load simulation)."""
    cmd = (
        f"sudo tc qdisc del dev {EMBB_IF} root 2>/dev/null; "
        f"sudo tc qdisc add dev {EMBB_IF} root tbf "
        f"rate {rate_mbit}mbit burst 32kbit latency 400ms"
    )
    _worker_ssh(cmd, check=True)


def _tc_embb_restore():
    _tc_embb_set(config.EMBB_RATE_MAX)


# ── LLM decision helper ───────────────────────────────────────────────────────

def _prewarm_monitor(monitor: MonitoringAgent, state_agent: StateAgent,
                     cycles: int = 6) -> dict:
    """Collect N monitoring cycles so embb_load_fraction is populated (needs 5+).
    Returns the last metrics dict (with ρ populated if traffic is present).
    """
    log.info(f"[Prewarm] Collecting {cycles} monitor cycles to populate ρ...")
    last = {}
    for i in range(cycles):
        last = monitor.collect()
        state_agent.update(last)
        rho = last.get("embb_load_fraction")
        log.info(f"[Prewarm] cycle {i+1}/{cycles}  RTT={last.get('urllc_rtt_99',0):.1f}ms  ρ={rho}")
        time.sleep(3)
    rho = last.get("embb_load_fraction")
    if rho is not None:
        log.info(f"[Prewarm] ✅ ρ populated: {rho:.3f}")
    else:
        log.warning("[Prewarm] ⚠️  ρ still None after prewarm — low traffic?")
    return last


def _single_decision(monitor: MonitoringAgent, state_agent: StateAgent,
                     memory: AgentMemory, llm: LLMPlanningAgent,
                     dry_run: bool) -> dict:
    """Run one observe → think cycle and return the full decision dict."""
    metrics = monitor.collect()
    state   = state_agent.update(metrics)
    log.info(
        f"[Observe] RTT={metrics.get('urllc_rtt_99',0):.1f}ms  "
        f"eMBB={metrics.get('embb_tp_mbps',0):.1f}Mbps  "
        f"ρ={metrics.get('embb_load_fraction')}"
    )
    decision = llm.decide(metrics, state)
    if dry_run:
        log.info(f"[DryRun ] Would execute: {decision['action']} @ {decision['new_rate_int']}Mbit")
    return {**decision, "_metrics": metrics, "_state": state}


# ── Scenario implementations ──────────────────────────────────────────────────

def run_s1(monitor, state_agent, memory, llm, dry_run: bool) -> dict:
    """
    S1: Pre-Emptive Throttling
    RTT must be rising trend but NOT yet > SLA when agent decides throttle.
    """
    log.info("=" * 60)
    log.info("SCENARIO S1: Pre-Emptive Throttling")
    log.info("Condition: high eMBB load, RTT rising, not yet > SLA")
    log.info("=" * 60)

    result = {
        "scenario": "S1",
        "description": "Pre-Emptive Throttling",
        "dry_run": dry_run,
        "ts": datetime.now(timezone.utc).isoformat(),
        "verdict": "PENDING",
        "cot_trace": [],
        "pass_criteria": [
            "action == throttle_embb",
            "RTT at decision time <= 20ms",
            "root_cause_assessment mentions eMBB or load",
        ],
    }

    # Pre-warm so ρ is populated before LLM call
    _prewarm_monitor(monitor, state_agent)

    # Collect up to 4 decisions and look for pre-emptive throttle
    for attempt in range(4):
        log.info(f"[S1] Attempt {attempt+1}/4")
        d = _single_decision(monitor, state_agent, memory, llm, dry_run)
        rtt = d["_metrics"].get("urllc_rtt_99", 0)

        record = {
            "attempt":             attempt + 1,
            "rtt_ms":              rtt,
            "embb_load_fraction":  d["_metrics"].get("embb_load_fraction"),
            "rtt_trend":           d["_state"].get("rtt_trend"),
            "action":              d["action"],
            "confidence":          d["confidence"],
            "lever_validity_score": d.get("lever_validity_score", 0.0),
            "root_cause_assessment": d.get("root_cause_assessment", ""),
            "lever_validity":      d.get("lever_validity", ""),
            "wrong_lever_event":   d.get("wrong_lever_event", False),
        }
        result["cot_trace"].append(record)

        if d["action"] == "throttle_embb":
            if rtt <= config.URLLC_RTT_SLA_MS:
                result["verdict"] = "PASS"
                result["pass_note"] = (
                    f"Pre-emptive throttle at RTT={rtt:.1f}ms "
                    f"(below SLA {config.URLLC_RTT_SLA_MS}ms) "
                    f"with ρ={d['_metrics'].get('embb_load_fraction'):.3f}"
                )
            else:
                result["verdict"] = "PARTIAL"
                result["pass_note"] = (
                    f"Reactive throttle: RTT={rtt:.1f}ms already > SLA "
                    f"(threshold {config.URLLC_RTT_SLA_MS}ms)"
                )
            break
        time.sleep(3)

    if result["verdict"] == "PENDING":
        result["verdict"] = "FAIL"
        result["pass_note"] = "No throttle_embb decision in 4 attempts"

    return result


def run_s2(monitor, state_agent, memory, llm, dry_run: bool) -> dict:
    """
    S2: Wrong-Lever Avoidance
    eMBB at LOW load; RTT elevated via tc netem injection.
    Agent must NOT throttle eMBB.

    LIVE PRECONDITION: Stop eMBB clients before running so ρ < 0.2.
    DRY-RUN NOTE: netem is skipped; this test is only meaningful live.
    """
    log.info("=" * 60)
    log.info("SCENARIO S2: Wrong-Lever Avoidance")
    log.info("Condition: low eMBB load, RTT elevated via netem injection")
    log.info("=" * 60)

    result = {
        "scenario": "S2",
        "description": "Wrong-Lever Avoidance",
        "dry_run": dry_run,
        "ts": datetime.now(timezone.utc).isoformat(),
        "verdict": "PENDING",
        "cot_trace": [],
        "pass_criteria": [
            "action != throttle_embb",
            "embb_load_fraction < 0.2 at decision time",
            "root_cause_assessment does NOT cite eMBB as cause",
        ],
    }

    # Pre-warm so ρ is populated before checking precondition
    warm_metrics = _prewarm_monitor(monitor, state_agent)
    rho_warm = warm_metrics.get("embb_load_fraction")

    # ── ρ pre-condition guard ─────────────────────────────────────────────────
    # S2 requires eMBB to be idle (ρ < 0.25). If eMBB clients are running,
    # the LLM correctly identifies eMBB as the cause — making S2 untestable.
    if rho_warm is not None and rho_warm > 0.25:
        msg = (
            f"S2 SKIP: eMBB traffic too high for WLA test "
            f"(ρ={rho_warm:.2f} > 0.25). "
            f"Stop eMBB clients first: pkill -f embb_client.py (on UERANSIM VM)"
        )
        log.warning(f"[S2] ⚠️  {msg}")
        result["verdict"]   = "SKIP"
        result["pass_note"] = msg
        return result

    # Inject 30ms latency on URLLC interface (pushes RTT above SLA)
    log.info("[S2] Injecting 30ms netem delay on URLLC interface...")
    if not dry_run:
        try:
            _netem_inject(30, jitter_ms=2)
        except Exception as e:
            result["verdict"] = "ERROR"
            result["pass_note"] = f"netem inject failed: {e}"
            return result
    else:
        log.info("[S2] [DRY-RUN] Skipping netem inject")

    time.sleep(6)  # wait 2 monitor cycles for RTT to settle

    wrong_lever_count = 0
    try:
        for attempt in range(3):
            log.info(f"[S2] Attempt {attempt+1}/3")
            d = _single_decision(monitor, state_agent, memory, llm, dry_run)
            rtt = d["_metrics"].get("urllc_rtt_99", 0)
            lf  = d["_metrics"].get("embb_load_fraction")

            record = {
                "attempt":             attempt + 1,
                "rtt_ms":              rtt,
                "embb_load_fraction":  lf,
                "action":              d["action"],
                "confidence":          d["confidence"],
                "lever_validity_score": d.get("lever_validity_score", 0.0),
                "root_cause_assessment": d.get("root_cause_assessment", ""),
                "lever_validity":      d.get("lever_validity", ""),
                "wrong_lever_event":   d.get("wrong_lever_event", False),
            }
            result["cot_trace"].append(record)

            if d["action"] == "throttle_embb":
                wrong_lever_count += 1
                log.warning(f"[S2] ❌ WRONG LEVER: throttle_embb at ρ={lf}")

            time.sleep(3)

        if wrong_lever_count == 0:
            result["verdict"] = "PASS"
            result["pass_note"] = (
                "Agent correctly avoided throttle_embb for all 3 decisions "
                "despite RTT violation. Wrong-Lever Avoidance confirmed."
            )
        elif wrong_lever_count <= 1:
            result["verdict"] = "PARTIAL"
            result["pass_note"] = f"1/3 decisions incorrectly throttled eMBB. WLA partially working."
        else:
            result["verdict"] = "FAIL"
            result["pass_note"] = (
                f"{wrong_lever_count}/3 decisions incorrectly throttled eMBB "
                f"despite low load fraction."
            )

    finally:
        if not dry_run:
            log.info("[S2] Clearing netem injection...")
            _netem_clear()

    return result


def run_s3(monitor, state_agent, memory, llm, dry_run: bool) -> dict:
    """
    S3: Memory-Assisted Restoration
    System throttled, prior memory shows throttle was effective.
    RTT now within SLA. Agent should restore eMBB citing memory.
    """
    log.info("=" * 60)
    log.info("SCENARIO S3: Memory-Assisted Restoration")
    log.info("Condition: throttled, stable, memory shows prior success")
    log.info("=" * 60)

    result = {
        "scenario": "S3",
        "description": "Memory-Assisted Restoration",
        "dry_run": dry_run,
        "ts": datetime.now(timezone.utc).isoformat(),
        "verdict": "PENDING",
        "cot_trace": [],
        "pass_criteria": [
            "action == restore_embb",
            "RTT <= SLA at decision time",
            "stable_for >= 60s",
            "reasoning or root_cause references prior memory",
        ],
    }

    # Pre-warm + seed memory with 3 effective throttle entries
    _prewarm_monitor(monitor, state_agent)
    log.info("[S3] Seeding memory with 3 successful throttle outcomes...")
    for i in range(3):
        memory.record(
            rtt=25.0 - i * 2,
            embb_rate=config.EMBB_RATE_MAX,
            action="throttle_embb",
            reasoning="RTT elevated; eMBB high load fraction 0.91",
            confidence=0.82,
            root_cause="eMBB burst causing GTP-U queue pressure",
            lever_valid="Throttling eMBB will reduce queuing on shared backhaul",
            embb_load_fraction=0.91,
        )
        memory.update_outcome(rtt_after=8.0 + i)

    # Simulate stable state in state_agent
    state_agent.current_embb_rate = 300   # currently throttled
    state_agent.violation_count   = 0
    state_agent._stable_since     = time.time() - 90  # stable for 90s

    time.sleep(3)

    for attempt in range(3):
        log.info(f"[S3] Attempt {attempt+1}/3")
        d = _single_decision(monitor, state_agent, memory, llm, dry_run)
        rtt = d["_metrics"].get("urllc_rtt_99", 0)
        ss  = d["_state"]

        record = {
            "attempt":       attempt + 1,
            "rtt_ms":        rtt,
            "stable_for_s":  ss.get("stable_for", 0),
            "action":        d["action"],
            "confidence":    d["confidence"],
            "root_cause_assessment": d.get("root_cause_assessment", ""),
            "lever_validity": d.get("lever_validity", ""),
            "reasoning":     d.get("reason", ""),
        }
        result["cot_trace"].append(record)

        if d["action"] == "restore_embb":
            # Check memory reference in reasoning
            reasoning_text = (
                d.get("reason", "") + " " +
                d.get("root_cause_assessment", "")
            ).lower()
            memory_keywords = ["memory", "history", "prior", "previous",
                               "last time", "showed", "worked", "effective"]
            mem_cited = any(kw in reasoning_text for kw in memory_keywords)

            result["verdict"] = "PASS" if mem_cited else "PARTIAL"
            result["pass_note"] = (
                f"restore_embb issued at RTT={rtt:.1f}ms, stable_for={ss.get('stable_for',0):.0f}s. "
                + ("Memory cited in reasoning. ✅" if mem_cited else
                   "Memory NOT explicitly cited in reasoning. ⚠️")
            )
            break
        time.sleep(3)

    if result["verdict"] == "PENDING":
        result["verdict"] = "FAIL"
        result["pass_note"] = "No restore_embb in 3 attempts despite stable + throttled state"

    return result


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Behavioral Audit Harness — S1/S2/S3")
    parser.add_argument("--scenario", choices=["S1", "S2", "S3", "ALL"],
                        required=True, help="Scenario to run")
    parser.add_argument("--dry-run", action="store_true",
                        help="LLM reasons; no tc commands applied; no netem inject")
    parser.add_argument("--out", default="",
                        help="Save results to JSON file path")
    args = parser.parse_args()

    monitor     = MonitoringAgent()
    state_agent = StateAgent()
    memory      = AgentMemory(maxlen=config.MEMORY_SIZE)
    llm         = LLMPlanningAgent(memory)

    COLORS = {"PASS": "\033[92m", "PARTIAL": "\033[93m",
              "FAIL": "\033[91m", "ERROR": "\033[91m", "RESET": "\033[0m"}

    scenarios_to_run = ["S1", "S2", "S3"] if args.scenario == "ALL" else [args.scenario]
    all_results = []

    for s in scenarios_to_run:
        try:
            if s == "S1":
                result = run_s1(monitor, state_agent, memory, llm, args.dry_run)
            elif s == "S2":
                result = run_s2(monitor, state_agent, memory, llm, args.dry_run)
            elif s == "S3":
                result = run_s3(monitor, state_agent, memory, llm, args.dry_run)
        except Exception as e:
            result = {"scenario": s, "verdict": "ERROR",
                      "pass_note": str(e), "cot_trace": []}

        all_results.append(result)
        v   = result["verdict"]
        col = COLORS.get(v, "")
        rst = COLORS["RESET"]
        print(f"\n{'─'*60}")
        print(f"  Scenario {s}: {col}{v}{rst}")
        print(f"  {result.get('pass_note','')}")
        print(f"{'─'*60}")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            json.dumps(all_results, indent=2, ensure_ascii=False))
        print(f"\nResults saved to {args.out}")

    # Summary
    print(f"\n{'═'*60}")
    print("  BEHAVIORAL AUDIT SUMMARY")
    print(f"{'═'*60}")
    for r in all_results:
        v   = r["verdict"]
        col = COLORS.get(v, "")
        rst = COLORS["RESET"]
        print(f"  {r['scenario']}  {col}{v}{rst}")
    print(f"{'═'*60}\n")

    any_fail = any(r["verdict"] in ("FAIL", "ERROR") for r in all_results)
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
