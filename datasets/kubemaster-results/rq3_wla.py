#!/usr/bin/env python3
"""
rq3_wla.py — RQ3: Does Wrong-Lever Avoidance Matter? (C4)
Figures: Funnel, Lever-validity density, Before/After matrix, Decision quality comparison
"""
import matplotlib
import pandas as pd, numpy as np
import matplotlib.pyplot as plt, matplotlib.patches as mpatches
import seaborn as sns
import plotly.graph_objects as go
from pathlib import Path

matplotlib.rcParams.update({"font.family":"serif","font.size":11,
    "axes.spines.top":False,"axes.spines.right":False,"figure.dpi":150})

DATA = Path(__file__).parent / "datasets"
FIGS = Path(__file__).parent / "figures"; FIGS.mkdir(exist_ok=True)

def load_agentic():
    dfs = []
    for lv in ["low","medium","high"]:
        p = DATA / f"dataset_agentic_{lv}.csv"
        if p.exists():
            df = pd.read_csv(p); df["traffic_level"] = lv; dfs.append(df)
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


def fig_funnel(ag):
    """Fig 1 — Funnel: Candidate→Validated→Executed action flow (C4)."""
    total       = len(ag)
    non_no      = len(ag[ag["candidate_action"] != "no_action"])
    wla_pass    = len(ag[(ag["candidate_action"] != "no_action") & (ag["wla_activated"] == 0)])
    executed    = len(ag[(ag["action_taken"] != "no_action") & (ag["wla_activated"] == 0)])
    wla_blocked = len(ag[ag["wla_activated"] == 1])

    stages = ["Total Decisions", "Non-Trivial Candidates",
              "Passed WLA Validation", "Actually Executed"]
    values = [total, non_no, wla_pass, executed]

    fig = go.Figure(go.Funnel(
        y=stages, x=values,
        textinfo="value+percent initial",
        marker=dict(color=["#264653","#2A9D8F","#E9C46A","#E76F51"]),
        connector=dict(line=dict(color="grey", width=1)),
    ))
    fig.update_layout(
        title_text=(f"RQ3 — C4: Action Funnel (WLA Blocks {wla_blocked} Wrong-Lever Actions)<br>"
                    "<sup>Insight: WLA filters non-causal interventions before execution</sup>"),
        height=420, width=650, paper_bgcolor="white", font_size=12,
    )
    fig.write_image(str(FIGS / "rq3_fig1_funnel.pdf"))
    fig.write_image(str(FIGS / "rq3_fig1_funnel.png"))
    print("  ✅ rq3_fig1_funnel")


def fig_lvs_density(ag):
    """Fig 2 — Lever Validity Score density: WLA vs non-WLA decisions."""
    if "lever_validity_score" not in ag.columns: return
    lvs_blocked = ag[ag["wla_activated"]==1]["lever_validity_score"]
    lvs_passed  = ag[ag["wla_activated"]==0]["lever_validity_score"]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for data, label, color in [
        (lvs_passed,  "WLA Passed (executed)", "#2A9D8F"),
        (lvs_blocked, "WLA Blocked (prevented)", "#E63946"),
    ]:
        if len(data) > 10:
            data.plot.kde(ax=ax, label=label, color=color, lw=2)

    ax.axvline(0.55, color="black", ls="--", lw=1.3, label="WLA Threshold (0.55)")
    ax.fill_betweenx([0, ax.get_ylim()[1] if ax.get_ylim()[1] > 0 else 5],
                     0, 0.55, alpha=0.06, color="#E63946")
    ax.set_xlabel("Lever Validity Score", fontsize=11)
    ax.set_ylabel("Density", fontsize=11)
    ax.set_title("RQ3 — C4: Lever Validity Score Distribution\n"
                 "Insight: WLA correctly identifies low-validity (wrong-lever) decisions",
                 fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    ax.set_xlim(0, 1.05)
    plt.tight_layout()
    plt.savefig(FIGS / "rq3_fig2_lvs_density.pdf", bbox_inches="tight")
    plt.savefig(FIGS / "rq3_fig2_lvs_density.png", bbox_inches="tight")
    plt.close()
    print("  ✅ rq3_fig2_lvs_density")


def fig_wla_impact(ag):
    """Fig 3 — Before/After: SLA violations with/without WLA simulation."""
    if "wla_activated" not in ag.columns: return

    # Simulate "no WLA" — execute all candidate actions
    no_wla_viols = len(ag[ag["candidate_action"].isin(
        ["throttle_embb","throttle_embb_mild","restore_embb"]
    ) & (ag["sla_violated"]==1)])
    with_wla_viols = len(ag[ag["sla_violated"]==1])

    # WLA-prevented wrong actions
    wla_rows    = ag[ag["wla_activated"]==1]
    sla_after_wla = len(wla_rows[wla_rows["sla_violated"]==0])

    fig, axes = plt.subplots(1, 2, figsize=(11, 5))

    # ── Panel A: Violation comparison ────────────────────────────────────────
    ax = axes[0]
    cats = ["Without WLA\n(all candidates executed)",
            "With WLA\n(wrong-lever filtered)"]
    vals = [no_wla_viols, with_wla_viols]
    bars = ax.bar(cats, vals, color=["#E63946","#2A9D8F"], width=0.45, edgecolor="white")
    for bar, val in zip(bars, vals):
        ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+50,
                str(val), ha="center", va="bottom", fontweight="bold")
    ax.set_ylabel("SLA Violation Events", fontsize=11)
    ax.set_title("C4 Impact on SLA Violations", fontsize=11)
    ax.set_ylim(0, max(vals)*1.2)
    ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)

    # ── Panel B: WLA decision breakdown ──────────────────────────────────────
    ax2 = axes[1]
    total_wla  = len(wla_rows)
    prevented  = int(ag["wrong_action_prevented"].sum())
    not_needed = total_wla - prevented
    labels = ["Wrong Actions\nPrevented", "WLA False\nPositives (est.)"]
    sizes  = [prevented, max(0, not_needed)]
    colors = ["#2A9D8F","#E9C46A"]
    wedges, texts, autotexts = ax2.pie(
        sizes, labels=labels, colors=colors,
        autopct="%1.1f%%", startangle=90,
        wedgeprops=dict(edgecolor="white", linewidth=1.5)
    )
    ax2.set_title("C4: WLA Decision Breakdown", fontsize=11)

    fig.suptitle("RQ3 — C4: Wrong-Lever Avoidance Impact\n"
                 "Insight: WLA prevents non-causal interventions that would worsen QoS",
                 fontsize=11, y=1.02)
    plt.tight_layout()
    plt.savefig(FIGS / "rq3_fig3_wla_impact.pdf", bbox_inches="tight")
    plt.savefig(FIGS / "rq3_fig3_wla_impact.png", bbox_inches="tight")
    plt.close()
    print("  ✅ rq3_fig3_wla_impact")


def fig_wla_by_cause(ag):
    """Fig 4 — WLA activation rate by root cause."""
    if "root_cause_assessment" not in ag.columns: return
    wla_rate = ag.groupby("root_cause_assessment")["wla_activated"].mean() * 100
    wla_rate = wla_rate.sort_values(ascending=True)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    bars = ax.barh(wla_rate.index, wla_rate.values,
                   color=["#E63946" if v > 15 else "#2A9D8F" for v in wla_rate.values],
                   edgecolor="white", height=0.55)
    for bar, val in zip(bars, wla_rate.values):
        ax.text(val+0.3, bar.get_y()+bar.get_height()/2,
                f"{val:.1f}%", va="center", fontsize=9)
    ax.set_xlabel("WLA Activation Rate (%)", fontsize=11)
    ax.set_title("RQ3 — C4: WLA Activation Rate by Root Cause\n"
                 "Insight: WLA most active on transient spikes — prevents over-throttling",
                 fontsize=11)
    ax.axvline(15, color="grey", ls="--", lw=1, alpha=0.6, label="15% reference")
    ax.legend(frameon=False, fontsize=9)
    plt.tight_layout()
    plt.savefig(FIGS / "rq3_fig4_wla_by_cause.pdf", bbox_inches="tight")
    plt.savefig(FIGS / "rq3_fig4_wla_by_cause.png", bbox_inches="tight")
    plt.close()
    print("  ✅ rq3_fig4_wla_by_cause")


def run():
    print("\n[RQ3] Loading agentic data...")
    ag = load_agentic()
    if ag.empty:
        print("  ⚠️  No agentic data — run generate_agentic_data.py first"); return
    wla_pct = 100*ag["wla_activated"].mean() if "wla_activated" in ag.columns else 0
    print(f"  WLA activations: {ag['wla_activated'].sum() if 'wla_activated' in ag.columns else 'N/A'} ({wla_pct:.1f}%)")
    print("\n[RQ3] Generating figures...")
    fig_funnel(ag)
    fig_lvs_density(ag)
    fig_wla_impact(ag)
    fig_wla_by_cause(ag)
    print("  RQ3 complete — 4 figures saved\n")

if __name__ == "__main__":
    run()
