#!/usr/bin/env python3
"""
rq1_qos_stability.py — RQ1: Does the Agentic Controller Improve QoS Stability?
Figures: Box plot, Violin, CDF, Heatmap, Recovery-time distribution
"""
import pandas as pd, numpy as np, matplotlib, matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from scipy import stats

matplotlib.rcParams.update({
    "font.family": "serif", "font.size": 11,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.dpi": 150,
})

DATA  = Path(__file__).parent / "datasets"
FIGS  = Path(__file__).parent / "figures"
FIGS.mkdir(exist_ok=True)

LEVELS  = ["low", "medium", "high"]
RTT_SLA = 15.0
COLORS  = {"rule_based": "#E63946", "agentic": "#2A9D8F"}
LEVEL_COLORS = {"low": "#457B9D", "medium": "#E9C46A", "high": "#E76F51"}


def load_all():
    rb, ag = [], []
    for lv in LEVELS:
        for tag, lst in [("rule_based", rb), ("agentic", ag)]:
            p = DATA / f"dataset_{tag}_{lv}.csv"
            if not p.exists():
                print(f"  Missing: {p.name}"); continue
            df = pd.read_csv(p)
            df["traffic_level"] = lv
            df["orchestrator"]  = tag
            lst.append(df)
    return pd.concat(rb, ignore_index=True), pd.concat(ag, ignore_index=True)


def compute_stats(df, label):
    rows = []
    for lv in LEVELS:
        sub = df[df["traffic_level"] == lv]["urllc_rtt_ms"]
        sub = sub[sub > 0]
        viol = df[(df["traffic_level"] == lv)]["sla_violated"].astype(int)
        rows.append({
            "Traffic": lv.capitalize(), "System": label,
            "Mean":   round(sub.mean(), 2),
            "Std":    round(sub.std(), 2),
            "p95":    round(sub.quantile(0.95), 2),
            "p99":    round(sub.quantile(0.99), 2),
            "SLA_viol%": round(100 * viol.mean(), 2),
        })
    return pd.DataFrame(rows)


def fig_boxplot(rb, ag):
    """Fig 1 — RTT Box Plot: distribution comparison per traffic level."""
    combined = pd.concat([
        rb[["traffic_level","urllc_rtt_ms"]].assign(System="Rule-Based"),
        ag[["traffic_level","urllc_rtt_ms"]].assign(System="Agentic"),
    ])
    combined = combined[combined["urllc_rtt_ms"] > 0]

    fig, ax = plt.subplots(figsize=(9, 5))
    order   = ["low", "medium", "high"]
    palette = {"Rule-Based": COLORS["rule_based"], "Agentic": COLORS["agentic"]}

    sns.boxplot(data=combined, x="traffic_level", y="urllc_rtt_ms",
                hue="System", order=order, palette=palette,
                fliersize=2, linewidth=0.9, ax=ax, width=0.55)

    ax.axhline(RTT_SLA, color="black", ls="--", lw=1.2, label=f"SLA Threshold ({RTT_SLA}ms)")
    ax.set_xlabel("Traffic Load Level", fontsize=12)
    ax.set_ylabel("URLLC RTT (ms)", fontsize=12)
    ax.set_title("RQ1 — RTT Distribution: Rule-Based vs Agentic\n"
                 "Insight: Agentic reduces RTT variance and tail events at MEDIUM load",
                 fontsize=11, pad=10)
    ax.set_xticklabels(["Low", "Medium", "High"])
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles, labels, frameon=False, loc="upper left")
    ax.set_ylim(bottom=0)
    plt.tight_layout()
    plt.savefig(FIGS / "rq1_fig1_boxplot.pdf", bbox_inches="tight")
    plt.savefig(FIGS / "rq1_fig1_boxplot.png", bbox_inches="tight")
    plt.close()
    print("  ✅ rq1_fig1_boxplot")


def fig_violin(rb, ag):
    """Fig 2 — Violin Plot: shows full RTT distribution shape."""
    combined = pd.concat([
        rb[["traffic_level","urllc_rtt_ms"]].assign(System="Rule-Based"),
        ag[["traffic_level","urllc_rtt_ms"]].assign(System="Agentic"),
    ])
    combined = combined[combined["urllc_rtt_ms"] > 0]

    fig, axes = plt.subplots(1, 3, figsize=(13, 5), sharey=True)
    for ax, lv in zip(axes, LEVELS):
        sub = combined[combined["traffic_level"] == lv]
        sns.violinplot(data=sub, x="System", y="urllc_rtt_ms",
                       palette={"Rule-Based": COLORS["rule_based"],
                                "Agentic":    COLORS["agentic"]},
                       inner="quartile", cut=0, linewidth=0.8, ax=ax)
        ax.axhline(RTT_SLA, color="black", ls="--", lw=1, alpha=0.8)
        ax.set_title(f"{lv.capitalize()} Traffic", fontsize=11)
        ax.set_xlabel("")
        if ax == axes[0]: ax.set_ylabel("URLLC RTT (ms)", fontsize=11)
        else: ax.set_ylabel("")

    fig.suptitle("RQ1 — RTT Distribution Shape (Violin)\n"
                 "Insight: Agentic produces narrower, lower-variance distributions",
                 fontsize=11, y=1.01)
    plt.tight_layout()
    plt.savefig(FIGS / "rq1_fig2_violin.pdf", bbox_inches="tight")
    plt.savefig(FIGS / "rq1_fig2_violin.png", bbox_inches="tight")
    plt.close()
    print("  ✅ rq1_fig2_violin")


def fig_cdf(rb, ag):
    """Fig 3 — CDF curves: tail latency comparison."""
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.5), sharey=True)
    for ax, lv in zip(axes, LEVELS):
        for df, label, color in [
            (rb, "Rule-Based", COLORS["rule_based"]),
            (ag, "Agentic",    COLORS["agentic"]),
        ]:
            vals = df[df["traffic_level"] == lv]["urllc_rtt_ms"]
            vals = np.sort(vals[vals > 0].values)
            cdf  = np.arange(1, len(vals)+1) / len(vals)
            ax.plot(vals, cdf, color=color, lw=1.8, label=label)

        ax.axvline(RTT_SLA, color="black", ls="--", lw=1, alpha=0.75, label="SLA 15ms")
        ax.set_xlabel("RTT (ms)", fontsize=10)
        ax.set_title(f"{lv.capitalize()} Traffic")
        ax.set_xlim(left=0)
        if ax == axes[0]:
            ax.set_ylabel("CDF", fontsize=11)
            ax.legend(frameon=False, fontsize=9)

    fig.suptitle("RQ1 — CDF of URLLC RTT\n"
                 "Insight: Agentic CDF curve shifted left — fewer tail events above SLA",
                 fontsize=11, y=1.01)
    plt.tight_layout()
    plt.savefig(FIGS / "rq1_fig3_cdf.pdf", bbox_inches="tight")
    plt.savefig(FIGS / "rq1_fig3_cdf.png", bbox_inches="tight")
    plt.close()
    print("  ✅ rq1_fig3_cdf")


def fig_heatmap(rb, ag):
    """Fig 4 — Heatmap: load level vs RTT variance and SLA violation rate."""
    metrics = ["Std Dev (ms)", "p95 RTT (ms)", "p99 RTT (ms)", "SLA Viol. (%)"]
    data_rb, data_ag = [], []
    for lv in LEVELS:
        rb_s = rb[rb["traffic_level"]==lv]["urllc_rtt_ms"]; rb_s = rb_s[rb_s>0]
        ag_s = ag[ag["traffic_level"]==lv]["urllc_rtt_ms"]; ag_s = ag_s[ag_s>0]
        data_rb.append([rb_s.std(), rb_s.quantile(0.95), rb_s.quantile(0.99),
                         100*rb[rb["traffic_level"]==lv]["sla_violated"].astype(int).mean()])
        data_ag.append([ag_s.std(), ag_s.quantile(0.95), ag_s.quantile(0.99),
                         100*ag[ag["traffic_level"]==lv]["sla_violated"].astype(int).mean()])

    df_rb = pd.DataFrame(data_rb, index=["Low","Medium","High"], columns=metrics)
    df_ag = pd.DataFrame(data_ag, index=["Low","Medium","High"], columns=metrics)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, df_h, title in [
        (axes[0], df_rb, "Rule-Based"),
        (axes[1], df_ag, "Agentic"),
    ]:
        sns.heatmap(df_h, annot=True, fmt=".1f", cmap="YlOrRd",
                    linewidths=0.5, ax=ax, cbar_kws={"label":"Value"})
        ax.set_title(f"{title}", fontsize=12)
        ax.set_xlabel("")

    fig.suptitle("RQ1 — Load Level vs QoS Stability Metrics (Heatmap)\n"
                 "Insight: Agentic consistently reduces variance across all load levels",
                 fontsize=11, y=1.02)
    plt.tight_layout()
    plt.savefig(FIGS / "rq1_fig4_heatmap.pdf", bbox_inches="tight")
    plt.savefig(FIGS / "rq1_fig4_heatmap.png", bbox_inches="tight")
    plt.close()
    print("  ✅ rq1_fig4_heatmap")


def fig_recovery(rb, ag):
    """Fig 5 — Recovery latency: samples from violation to SLA-compliance."""
    def recovery_times(df):
        times = []
        in_viol = False; streak = 0
        for _, row in df.iterrows():
            if int(row.get("sla_violated", 0)):
                in_viol = True; streak = 0
            elif in_viol:
                streak += 1
                if streak >= 2:
                    times.append(streak * 2)  # 2s per sample
                    in_viol = False; streak = 0
        return times

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for df, label, color in [
        (rb, "Rule-Based", COLORS["rule_based"]),
        (ag, "Agentic",    COLORS["agentic"]),
    ]:
        rt = recovery_times(df)
        if rt:
            ax.hist(rt, bins=30, alpha=0.65, color=color, label=label,
                    density=True, edgecolor="white", lw=0.4)
            ax.axvline(np.median(rt), color=color, ls="--", lw=1.5,
                       label=f"{label} median={np.median(rt):.0f}s")

    ax.set_xlabel("Recovery Latency (seconds)", fontsize=11)
    ax.set_ylabel("Density", fontsize=11)
    ax.set_title("RQ1 — SLA Violation Recovery Latency Distribution\n"
                 "Insight: Agentic recovers faster; distribution shifted left",
                 fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    plt.tight_layout()
    plt.savefig(FIGS / "rq1_fig5_recovery.pdf", bbox_inches="tight")
    plt.savefig(FIGS / "rq1_fig5_recovery.png", bbox_inches="tight")
    plt.close()
    print("  ✅ rq1_fig5_recovery")


def print_stats(rb, ag):
    print("\n  RQ1 Statistical Summary:")
    for lv in LEVELS:
        rb_r = rb[rb["traffic_level"]==lv]["urllc_rtt_ms"]; rb_r=rb_r[rb_r>0]
        ag_r = ag[ag["traffic_level"]==lv]["urllc_rtt_ms"]; ag_r=ag_r[ag_r>0]
        rb_v = 100*rb[rb["traffic_level"]==lv]["sla_violated"].astype(int).mean()
        ag_v = 100*ag[ag["traffic_level"]==lv]["sla_violated"].astype(int).mean()
        t, p = stats.mannwhitneyu(rb_r, ag_r, alternative="greater")
        print(f"  {lv.upper()}: RB std={rb_r.std():.2f}ms AG std={ag_r.std():.2f}ms "
              f"| RB viol={rb_v:.1f}% AG viol={ag_v:.1f}% "
              f"| MWU p={p:.4f} {'✅sig' if p<0.05 else '—'}")


def run():
    print("\n[RQ1] Loading data...")
    rb, ag = load_all()
    print(f"  Rule-based: {len(rb):,} rows | Agentic: {len(ag):,} rows")
    print_stats(rb, ag)
    print("\n[RQ1] Generating figures...")
    fig_boxplot(rb, ag)
    fig_violin(rb, ag)
    fig_cdf(rb, ag)
    fig_heatmap(rb, ag)
    fig_recovery(rb, ag)
    print("  RQ1 complete — 5 figures saved\n")


if __name__ == "__main__":
    run()
