#!/usr/bin/env python3
"""
run_all.py — Master Results Runner
====================================
Generates the full Results & Discussion chapter figures in one command.

Usage:
    pip install pandas numpy matplotlib seaborn plotly scipy kaleido
    python3 results/run_all.py

Output:
    results/datasets/   ← all CSVs (rule_based + agentic, all 3 levels)
    results/figures/    ← all figures (PDF + PNG)
"""
import subprocess, sys, os
from pathlib import Path

RESULTS_DIR  = Path(__file__).parent
FIGURES_DIR  = RESULTS_DIR / "figures"
DATASETS_DIR = RESULTS_DIR / "datasets"
FIGURES_DIR.mkdir(exist_ok=True)
DATASETS_DIR.mkdir(exist_ok=True)

STEPS = [
    ("Step 1/9 — Generating RULE-BASED datasets (low / medium / high)...",
     [sys.executable, str(RESULTS_DIR / "generate_rule_based_data.py")]),

    ("Step 2/9 — Generating AGENTIC datasets   (C3 / C4 / C5 fields)...",
     [sys.executable, str(RESULTS_DIR / "generate_agentic_data.py")]),

    ("Step 3/9 — RQ1: QoS Stability figures...",
     [sys.executable, str(RESULTS_DIR / "rq1_qos_stability.py")]),

    ("Step 4/9 — RQ2: Chain-of-Thought (C3) figures...",
     [sys.executable, str(RESULTS_DIR / "rq2_chain_of_thought.py")]),

    ("Step 5/9 — RQ3: Wrong-Lever Avoidance (C4) figures...",
     [sys.executable, str(RESULTS_DIR / "rq3_wla.py")]),

    ("Step 6/9 — RQ4: Memory-Assisted Decision (C5) figures...",
     [sys.executable, str(RESULTS_DIR / "rq4_memory.py")]),

    ("Step 7/9 — RQ5: Cost of Intelligence figures...",
     [sys.executable, str(RESULTS_DIR / "rq5_cost.py")]),

    ("Step 8/9 — Flagship Radar + Comparison Matrix...",
     [sys.executable, str(RESULTS_DIR / "flagship_radar.py")]),

    ("Step 9/9 — Additional Supplementary Figures (A1–A8)...",
     [sys.executable, str(RESULTS_DIR / "rq_additional.py")]),
]


def check_deps():
    required = ["pandas","numpy","matplotlib","seaborn","plotly","scipy","kaleido"]
    missing  = []
    for pkg in required:
        try: __import__(pkg)
        except ImportError: missing.append(pkg)
    if missing:
        print(f"  Installing: {' '.join(missing)} ...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q"] + missing, check=True)
    print("  ✅ All dependencies present")


def run_step(desc, cmd):
    print(f"\n{'─'*58}")
    print(f"  {desc}")
    print(f"{'─'*58}")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(RESULTS_DIR.parent)
    r = subprocess.run(cmd, env=env, cwd=str(RESULTS_DIR))
    if r.returncode != 0:
        print(f"  ❌ Failed (returncode={r.returncode}) — continuing")
        return False
    return True


def print_summary():
    print(f"\n{'='*58}")
    print(f"  RESULTS SUMMARY")
    print(f"{'='*58}")

    csvs = sorted(DATASETS_DIR.glob("*.csv"))
    print(f"\n  Datasets ({len(csvs)} files → results/datasets/):")
    for c in csvs:
        rows = sum(1 for _ in open(c)) - 1
        print(f"    📄 {c.name:<42} {rows:>6} rows")

    figs = sorted(FIGURES_DIR.glob("*.png"))
    print(f"\n  Figures ({len(figs)} PNG → results/figures/):")
    for cat, prefix in [
        ("RQ1 — QoS Stability",         "rq1_"),
        ("RQ2 — Chain-of-Thought (C3)", "rq2_"),
        ("RQ3 — WLA (C4)",              "rq3_"),
        ("RQ4 — Memory (C5)",           "rq4_"),
        ("RQ5 — Cost of Intelligence",  "rq5_"),
        ("Flagship",                    "flagship"),
        ("Additional Supplementary",    "a"),
    ]:
        group = [f.name for f in figs if f.name.startswith(prefix)]
        if group:
            print(f"\n    {cat}:")
            for g in group:
                print(f"      📊 {g}")

    print(f"\n  ✅ Open results/figures/ for publication-ready figures.")
    print(f"{'='*58}\n")


def main():
    print("=" * 58)
    print("  5G Orchestrator — Results Generation Pipeline")
    print("  Rule-Based vs Agentic: C3 / C4 / C5 Analysis")
    print("=" * 58)
    print("\n[0/8] Checking dependencies...")
    check_deps()

    passed = 0
    for desc, cmd in STEPS:
        ok = run_step(desc, cmd)
        if ok: passed += 1

    print_summary()
    print(f"  Steps completed: {passed}/{len(STEPS)}")


if __name__ == "__main__":
    main()
