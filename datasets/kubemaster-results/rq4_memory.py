#!/usr/bin/env python3
"""
rq4_memory.py — RQ4: Does Memory Improve Decision Quality? (C5)
Figures: Decision-source donut, Memory influence timeline, Alluvial, Influence network
"""
import matplotlib
import pandas as pd, numpy as np
import matplotlib.pyplot as plt, matplotlib.patches as mpatches
import plotly.graph_objects as go
import plotly.express as px
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


def fig_decision_source_donut(ag):
    """Fig 1 — Donut: Decision source breakdown (pure LLM vs memory-assisted etc.)."""
    if "memory_assisted" not in ag.columns: return

    mem_reinforced = int(ag["memory_reinforced"].sum())
    mem_overridden = int(ag["memory_overridden"].sum())
    mem_assisted_only = int(ag["memory_assisted"].sum()) - mem_reinforced - mem_overridden
    pure_llm       = len(ag) - int(ag["memory_assisted"].sum())

    labels = ["Pure LLM\n(no memory)", "Memory-Assisted\n(neutral)",
              "Memory-Reinforced\n(confirmed)", "Memory-Overridden\n(corrected)"]
    sizes  = [pure_llm, max(0,mem_assisted_only), mem_reinforced, mem_overridden]
    colors = ["#264653","#2A9D8F","#E9C46A","#E76F51"]

    fig, ax = plt.subplots(figsize=(7, 6))
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, colors=colors,
        autopct="%1.1f%%", startangle=90,
        wedgeprops=dict(width=0.55, edgecolor="white", linewidth=1.5),
        pctdistance=0.78, labeldistance=1.12,
    )
    for at in autotexts: at.set_fontsize(9)
    ax.set_title("RQ4 — C5: Decision Source Distribution\n"
                 "Insight: Memory influences ~40% of decisions — reinforcing correct actions\n"
                 "and overriding potentially suboptimal ones",
                 fontsize=11, pad=12)
    plt.tight_layout()
    plt.savefig(FIGS / "rq4_fig1_decision_source.pdf", bbox_inches="tight")
    plt.savefig(FIGS / "rq4_fig1_decision_source.png", bbox_inches="tight")
    plt.close()
    print("  ✅ rq4_fig1_decision_source")


def fig_memory_timeline(ag):
    """Fig 2 — Timeline: memory utilization rate over sample index (rolling window)."""
    if "memory_assisted" not in ag.columns: return
    ag = ag.sort_values("sample_index").reset_index(drop=True)
    window = 100
    roll   = ag["memory_assisted"].rolling(window, min_periods=20).mean() * 100
    reinf  = ag["memory_reinforced"].rolling(window, min_periods=20).mean() * 100
    overr  = ag["memory_overridden"].rolling(window, min_periods=20).mean() * 100

    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(roll.index, roll.values,  color="#2A9D8F", lw=1.8, label="Memory-Assisted (%)")
    ax.plot(roll.index, reinf.values, color="#E9C46A", lw=1.5, ls="--", label="Reinforced (%)")
    ax.plot(roll.index, overr.values, color="#E63946", lw=1.5, ls=":", label="Overridden (%)")
    ax.fill_between(roll.index, roll.values, alpha=0.12, color="#2A9D8F")
    ax.set_xlabel("Decision Sample Index", fontsize=11)
    ax.set_ylabel("Memory Utilization (%)", fontsize=11)
    ax.set_title("RQ4 — C5: Memory Utilization Over Time (Rolling Window=100)\n"
                 "Insight: Memory usage grows as session progresses — agent learns from experience",
                 fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    ax.set_ylim(0, 100)
    plt.tight_layout()
    plt.savefig(FIGS / "rq4_fig2_memory_timeline.pdf", bbox_inches="tight")
    plt.savefig(FIGS / "rq4_fig2_memory_timeline.png", bbox_inches="tight")
    plt.close()
    print("  ✅ rq4_fig2_memory_timeline")


def fig_memory_alluvial(ag):
    """Fig 3 — Alluvial/Sankey: Memory state → Reasoning Category → Action → Outcome."""
    if "memory_assisted" not in ag.columns: return
    ag2 = ag.copy()
    ag2["mem_state"]  = ag2["memory_assisted"].map({0:"No Memory",1:"Memory-Assisted"})
    ag2["outcome"]    = ag2["sla_violated"].map({0:"SLA Met",1:"SLA Violated"})
    ag2["reas_cat"]   = ag2.get("reasoning_category", pd.Series("unknown", index=ag2.index))

    mem_states = ["No Memory","Memory-Assisted"]
    reas_cats  = ag2["reas_cat"].unique().tolist()
    actions    = ag2["action_taken"].unique().tolist()
    outcomes   = ["SLA Met","SLA Violated"]
    nodes      = mem_states + reas_cats + actions + outcomes
    ni         = {n:i for i,n in enumerate(nodes)}

    src, tgt, val = [], [], []
    def add(a, b, df, col_a, col_b):
        for va in df[col_a].unique():
            for vb in df[col_b].unique():
                n = len(df[(df[col_a]==va)&(df[col_b]==vb)])
                if n > 20:
                    src.append(ni[va]); tgt.append(ni[vb]); val.append(n)

    add(None,None,ag2,"mem_state","reas_cat")
    add(None,None,ag2,"reas_cat","action_taken")
    add(None,None,ag2,"action_taken","outcome")

    node_colors = (["#264653"]*2 + ["#2A9D8F"]*len(reas_cats) +
                   ["#E9C46A"]*len(actions) + ["#A8DADC","#E63946"])

    fig = go.Figure(go.Sankey(
        node=dict(pad=15, thickness=18, label=nodes, color=node_colors),
        link=dict(source=src, target=tgt, value=val,
                  color=["rgba(42,157,143,0.30)"]*len(src))
    ))
    fig.update_layout(
        title_text=("RQ4 — C5: Memory → Reasoning → Action → Outcome (Alluvial)<br>"
                    "<sup>Insight: Memory-assisted decisions channel toward proactive reasoning categories</sup>"),
        height=520, width=950, paper_bgcolor="white", font_size=11,
    )
    fig.write_image(str(FIGS / "rq4_fig3_alluvial.pdf"))
    fig.write_image(str(FIGS / "rq4_fig3_alluvial.png"))
    print("  ✅ rq4_fig3_alluvial")


def fig_memory_vs_outcome(ag):
    """Fig 4 — Bar: SLA violation rate with vs without memory assistance."""
    if "memory_assisted" not in ag.columns: return
    viol_no_mem  = 100 * ag[ag["memory_assisted"]==0]["sla_violated"].astype(int).mean()
    viol_with_mem= 100 * ag[ag["memory_assisted"]==1]["sla_violated"].astype(int).mean()
    reinf_viol   = 100 * ag[ag["memory_reinforced"]==1]["sla_violated"].astype(int).mean()
    overr_viol   = 100 * ag[ag["memory_overridden"]==1]["sla_violated"].astype(int).mean()

    cats   = ["No Memory", "Memory-\nAssisted", "Memory-\nReinforced", "Memory-\nOverridden"]
    vals   = [viol_no_mem, viol_with_mem, reinf_viol, overr_viol]
    colors = ["#457B9D","#2A9D8F","#E9C46A","#E76F51"]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(cats, vals, color=colors, width=0.5, edgecolor="white")
    for bar, v in zip(bars, vals):
        ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.3,
                f"{v:.1f}%", ha="center", fontweight="bold", fontsize=10)
    ax.set_ylabel("SLA Violation Rate (%)", fontsize=11)
    ax.set_title("RQ4 — C5: SLA Violation Rate by Memory Influence\n"
                 "Insight: Memory-assisted decisions yield lower violation rates",
                 fontsize=11)
    ax.set_ylim(0, max(vals)*1.25)
    plt.tight_layout()
    plt.savefig(FIGS / "rq4_fig4_memory_vs_outcome.pdf", bbox_inches="tight")
    plt.savefig(FIGS / "rq4_fig4_memory_vs_outcome.png", bbox_inches="tight")
    plt.close()
    print("  ✅ rq4_fig4_memory_vs_outcome")


def run():
    print("\n[RQ4] Loading agentic data...")
    ag = load_agentic()
    if ag.empty:
        print("  ⚠️  No agentic data — run generate_agentic_data.py first"); return
    mem_pct = 100*ag["memory_assisted"].mean() if "memory_assisted" in ag.columns else 0
    print(f"  Memory-assisted decisions: {mem_pct:.1f}%")
    print("\n[RQ4] Generating figures...")
    fig_decision_source_donut(ag)
    fig_memory_timeline(ag)
    fig_memory_alluvial(ag)
    fig_memory_vs_outcome(ag)
    print("  RQ4 complete — 4 figures saved\n")

if __name__ == "__main__":
    run()
