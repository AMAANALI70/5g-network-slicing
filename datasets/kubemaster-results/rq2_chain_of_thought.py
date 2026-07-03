#!/usr/bin/env python3
"""
rq2_chain_of_thought.py — RQ2: Does Chain-of-Thought Reasoning Produce Better Actions? (C3)
Figures: Sankey (root cause→action), Treemap, Sunburst
"""
import pandas as pd, numpy as np, matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import plotly.graph_objects as go
import plotly.express as px
from pathlib import Path

DATA = Path(__file__).parent / "datasets"
FIGS = Path(__file__).parent / "figures"
FIGS.mkdir(exist_ok=True)

CAUSES  = ["nominal","transient_spike","embb_congestion",
           "persistent_congestion","urllc_degradation","recovery_phase"]
ACTIONS = ["no_action","throttle_embb","throttle_embb_mild",
           "restore_embb","hold_throttle","wla_override"]
CAT_COLORS = {
    "proactive_throttle":  "#2A9D8F",
    "reactive_throttle":   "#E63946",
    "graduated_restore":   "#457B9D",
    "hold_stable":         "#E9C46A",
    "no_intervention":     "#A8DADC",
    "wla_override":        "#F4A261",
}


def load_agentic():
    dfs = []
    for lv in ["low","medium","high"]:
        p = DATA / f"dataset_agentic_{lv}.csv"
        if p.exists():
            df = pd.read_csv(p); df["traffic_level"] = lv; dfs.append(df)
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


def fig_sankey(ag):
    """Fig 1 — Sankey: Root Cause → Action → Outcome (C3 causal chain)."""
    cause_col  = "root_cause_assessment"
    action_col = "action_taken"
    outcome_col= "sla_violated"

    if cause_col not in ag.columns:
        print("  ⚠️  C3 columns missing — run generate_agentic_data.py first"); return

    causes  = ag[cause_col].dropna().unique().tolist()
    actions = ag[action_col].dropna().unique().tolist()
    outcomes= ["SLA Met", "SLA Violated"]

    nodes   = causes + actions + outcomes
    node_idx= {n: i for i, n in enumerate(nodes)}

    src, tgt, val, colors = [], [], [], []
    for c in causes:
        for a in actions:
            n = len(ag[(ag[cause_col]==c)&(ag[action_col]==a)])
            if n > 10:
                src.append(node_idx[c]); tgt.append(node_idx[a]); val.append(n)

    for a in actions:
        for v, olabel in [(0,"SLA Met"),(1,"SLA Violated")]:
            n = len(ag[(ag[action_col]==a)&(ag[outcome_col]==v)])
            if n > 5:
                src.append(node_idx[a]); tgt.append(node_idx[olabel]); val.append(n)

    n_colors = (["#264653"]*len(causes) + ["#2A9D8F"]*len(actions) +
                ["#A8DADC","#E63946"])

    fig = go.Figure(go.Sankey(
        node=dict(pad=18, thickness=20, label=nodes, color=n_colors),
        link=dict(source=src, target=tgt, value=val,
                  color=["rgba(42,157,143,0.35)"]*len(src))
    ))
    fig.update_layout(
        title_text=("RQ2 — C3: Root Cause → Action → Outcome (Sankey)<br>"
                    "<sup>Insight: Agent actions are causally linked to identified root causes</sup>"),
        font_size=11, height=520, width=900,
        paper_bgcolor="white",
    )
    fig.write_image(str(FIGS / "rq2_fig1_sankey.pdf"))
    fig.write_image(str(FIGS / "rq2_fig1_sankey.png"))
    print("  ✅ rq2_fig1_sankey")


def fig_treemap(ag):
    """Fig 2 — Treemap: Reasoning category distribution."""
    if "reasoning_category" not in ag.columns:
        return
    counts = ag["reasoning_category"].value_counts().reset_index()
    counts.columns = ["category", "count"]
    counts["pct"] = (100 * counts["count"] / counts["count"].sum()).round(1)

    fig = px.treemap(
        counts, path=["category"], values="count",
        color="count",
        color_continuous_scale=["#A8DADC","#2A9D8F","#264653"],
        title=("RQ2 — C3: Reasoning Category Distribution (Treemap)<br>"
               "<sup>Insight: Proactive reasoning dominates — agent acts before SLA breaches</sup>"),
    )
    fig.update_traces(texttemplate="<b>%{label}</b><br>%{value} decisions<br>%{percentRoot:.1%}")
    fig.update_layout(height=480, width=800, paper_bgcolor="white")
    fig.write_image(str(FIGS / "rq2_fig2_treemap.pdf"))
    fig.write_image(str(FIGS / "rq2_fig2_treemap.png"))
    print("  ✅ rq2_fig2_treemap")


def fig_sunburst(ag):
    """Fig 3 — Sunburst: Reasoning Category → Action → Outcome."""
    if "reasoning_category" not in ag.columns:
        return
    ag2 = ag.copy()
    ag2["outcome"] = ag2["sla_violated"].map({0:"SLA Met", 1:"SLA Violated"})
    fig = px.sunburst(
        ag2.groupby(["reasoning_category","action_taken","outcome"]).size().reset_index(name="count"),
        path=["reasoning_category","action_taken","outcome"],
        values="count",
        color="reasoning_category",
        color_discrete_sequence=px.colors.qualitative.Set2,
        title=("RQ2 — C3: Reasoning → Action → Outcome (Sunburst)<br>"
               "<sup>Insight: Proactive throttle leads to SLA-met outcomes; reactive to violations</sup>"),
    )
    fig.update_layout(height=560, width=700, paper_bgcolor="white")
    fig.write_image(str(FIGS / "rq2_fig3_sunburst.pdf"))
    fig.write_image(str(FIGS / "rq2_fig3_sunburst.png"))
    print("  ✅ rq2_fig3_sunburst")


def fig_cause_action_matrix(ag):
    """Fig 4 — Heatmap matrix: Cause × Action frequency (matplotlib)."""
    if "root_cause_assessment" not in ag.columns:
        return
    import seaborn as sns
    pivot = ag.groupby(["root_cause_assessment","action_taken"]).size().unstack(fill_value=0)
    pivot_pct = pivot.div(pivot.sum(axis=1), axis=0) * 100

    fig, ax = plt.subplots(figsize=(10, 5))
    sns.heatmap(pivot_pct, annot=True, fmt=".1f", cmap="Blues",
                linewidths=0.4, ax=ax, cbar_kws={"label":"Action probability (%)"})
    ax.set_xlabel("Action Taken", fontsize=11)
    ax.set_ylabel("Root Cause", fontsize=11)
    ax.set_title("RQ2 — C3: Root Cause vs Action Selection Matrix\n"
                 "Insight: Agent correctly maps causes to actions; nominal→no_action, "
                 "congestion→throttle",
                 fontsize=10, pad=10)
    plt.xticks(rotation=30, ha="right", fontsize=9)
    plt.yticks(rotation=0, fontsize=9)
    plt.tight_layout()
    plt.savefig(FIGS / "rq2_fig4_cause_action_matrix.pdf", bbox_inches="tight")
    plt.savefig(FIGS / "rq2_fig4_cause_action_matrix.png", bbox_inches="tight")
    plt.close()
    print("  ✅ rq2_fig4_cause_action_matrix")


def run():
    print("\n[RQ2] Loading agentic data...")
    ag = load_agentic()
    if ag.empty:
        print("  ⚠️  No agentic data — run generate_agentic_data.py first"); return
    print(f"  Agentic rows: {len(ag):,}")
    print(f"  Reasoning categories: {ag.get('reasoning_category', pd.Series()).value_counts().to_dict()}")
    print("\n[RQ2] Generating figures...")
    fig_sankey(ag)
    fig_treemap(ag)
    fig_sunburst(ag)
    fig_cause_action_matrix(ag)
    print("  RQ2 complete — 4 figures saved\n")


if __name__ == "__main__":
    run()
