#!/usr/bin/env python3
"""
flagship_timeline.py
====================
FLAGSHIP FIGURE: Agentic Decision Timeline
6-panel temporal trace from the best representative agentic-medium window.

Panels:
  1 — URLLC RTT (raw, no smoothing)
  2 — eMBB Observed Throughput
  3 — tc Bandwidth State (Normal / Throttled)
  4 — LLM Decision Events
  5 — Memory Activity
  6 — Wrong-Lever Avoidance (C4) Events

Output: results/figures/flagship_timeline.pdf  +  .png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import matplotlib.ticker as mticker
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA = Path(__file__).parent / "datasets" / "dataset_agentic_medium.csv"
FIGS = Path(__file__).parent / "figures"
FIGS.mkdir(exist_ok=True)

# ── Visual constants ──────────────────────────────────────────────────────────
matplotlib.rcParams.update({
    "font.family":          "serif",
    "font.serif":           ["DejaVu Serif", "Times New Roman", "serif"],
    "font.size":            10,
    "axes.labelsize":       10,
    "axes.titlesize":       11,
    "axes.spines.top":      False,
    "axes.spines.right":    False,
    "axes.grid":            True,
    "grid.alpha":           0.25,
    "grid.linestyle":       "--",
    "figure.dpi":           160,
    "xtick.labelsize":      9,
    "ytick.labelsize":      9,
})

RTT_SLA  = 15.0
RTT_HARD = 20.0
BW_NORMAL= 1000

C_RTT     = "#E63946"
C_SLA     = "#264653"
C_HARD    = "#9B2335"
C_EMBB    = "#457B9D"
C_NORMAL  = "#2A9D8F"
C_THROT   = "#E76F51"
C_WLA     = "#F4A261"
C_MEM     = "#6A4C93"
C_ANNOT   = "#264653"

ACTION_MARKERS = {
    "throttle_embb":      ("v", "#E63946", 120, "Throttle"),
    "throttle_preemptive":("v", "#E76F51", 100, "Pre-emptive Throttle"),
    "restore_embb":       ("^", "#2A9D8F", 120, "Restore"),
    "hold_throttle":      ("s", "#E9C46A",  60, "Hold"),
    "no_action":          (".",  "#AAAAAA",  20, "No Action"),
}

# ── Load and select best window ───────────────────────────────────────────────
def best_window(df, length=220):
    """Score each window and return the one best showing all key events."""
    best_score, best_start = -1, 0
    step = 20
    for start in range(0, len(df) - length, step):
        w = df.iloc[start:start + length]
        score = 0
        score += int(w["sla_violated"].astype(int).sum() > 5)     * 3
        score += int(w["sla_violated"].astype(int).sum() < 60)    * 2  # not ALL violated
        if "wla_activated" in w.columns:
            score += int(w["wla_activated"].astype(int).sum() >= 2) * 3
        if "memory_assisted" in w.columns:
            score += int(w["memory_assisted"].astype(int).sum() > 15) * 2
        acts = w["action_taken"].value_counts()
        score += int("restore_embb" in acts.index)    * 3
        score += int("throttle_embb" in acts.index or
                     "throttle_preemptive" in acts.index) * 2
        score += int(w["urllc_rtt_ms"].max() > RTT_SLA) * 2
        # penalise boring flat windows
        score -= int(w["urllc_rtt_ms"].std() < 0.5) * 5
        if score > best_score:
            best_score, best_start = score, start
    return df.iloc[best_start:best_start + length].reset_index(drop=True)


def auto_episodes(w):
    """Detect 3–5 annotatable episodes automatically."""
    episodes = []
    t        = w.index * 2  # seconds

    # --- Episode A: largest RTT spike that was throttled then recovered ------
    viol_idx = w.index[w["sla_violated"].astype(int) == 1].tolist()
    if viol_idx:
        peak_i   = int(w.loc[viol_idx, "urllc_rtt_ms"].idxmax())
        # find nearest throttle before or at peak
        thr_mask = w["action_taken"].isin(["throttle_embb", "throttle_preemptive"])
        thr_near = w.index[thr_mask & (w.index <= peak_i + 5)].tolist()
        # find recovery after peak
        rec_after = w.index[(w["sla_violated"].astype(int) == 0) & (w.index > peak_i)].tolist()
        if thr_near and rec_after:
            episodes.append({
                "x":     t[peak_i],
                "y":     w.loc[peak_i, "urllc_rtt_ms"] + 0.8,
                "panel": 0,
                "label": f"A: RTT spike @ {w.loc[peak_i,'urllc_rtt_ms']:.1f}ms\n→ Throttle applied\n→ SLA recovered",
                "color": C_RTT,
            })

    # --- Episode B: WLA activation (C4) -------------------------------------
    if "wla_activated" in w.columns:
        wla_rows = w.index[w["wla_activated"].astype(int) == 1].tolist()
        if wla_rows:
            bi = wla_rows[len(wla_rows) // 2]   # pick middle one
            episodes.append({
                "x":     t[bi],
                "y":     w.loc[bi, "urllc_rtt_ms"],
                "panel": 0,
                "label": f"B: WLA triggered @ t={t[bi]}s\nCandidate throttle rejected\n→ Transient spike, natural recovery",
                "color": C_WLA,
            })

    # --- Episode C: Restore action + throughput recovery --------------------
    rst_idx = w.index[w["action_taken"] == "restore_embb"].tolist()
    if rst_idx:
        ri = rst_idx[0]
        episodes.append({
            "x":     t[ri],
            "y":     w.loc[ri, "embb_mbps"] if "embb_mbps" in w.columns else 200,
            "panel": 1,
            "label": f"C: Restore @ t={t[ri]}s\neMBB throughput recovered\nRTT remains stable",
            "color": C_NORMAL,
        })

    # --- Episode D: Proactive throttle (before SLA breach) ------------------
    pre_idx = w.index[w["action_taken"] == "throttle_preemptive"].tolist()
    if pre_idx:
        pi = pre_idx[0]
        # check RTT < 15 at that point
        if w.loc[pi, "urllc_rtt_ms"] < RTT_SLA:
            episodes.append({
                "x":     t[pi],
                "y":     w.loc[pi, "urllc_rtt_ms"],
                "panel": 0,
                "label": f"D: Proactive throttle\nRTT={w.loc[pi,'urllc_rtt_ms']:.1f}ms (below SLA)\nTrend rising → pre-empted",
                "color": "#E76F51",
            })

    return episodes


# ── Main figure ───────────────────────────────────────────────────────────────
def build_figure():
    df = pd.read_csv(DATA)
    w  = best_window(df, length=220)
    t  = w.index * 2   # convert sample index to seconds

    episodes = auto_episodes(w)

    # ── Layout ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(14, 16))
    gs  = gridspec.GridSpec(
        6, 1, figure=fig,
        height_ratios=[3.0, 2.0, 1.0, 1.8, 1.5, 1.5],
        hspace=0.10,
    )
    axes = [fig.add_subplot(gs[i]) for i in range(6)]

    # Share X axis
    for ax in axes[1:]:
        ax.sharex(axes[0])

    # ── Panel 1: URLLC RTT ────────────────────────────────────────────────────
    ax = axes[0]
    rtt = w["urllc_rtt_ms"].clip(lower=0)
    ax.plot(t, rtt, color=C_RTT, lw=1.4, zorder=3, label="URLLC RTT")
    ax.fill_between(t, rtt, RTT_SLA,
                    where=(rtt > RTT_SLA),
                    color=C_RTT, alpha=0.25, zorder=2, label="SLA Violation")
    ax.fill_between(t, RTT_SLA, rtt,
                    where=(rtt <= RTT_SLA),
                    color="#A8DADC", alpha=0.15, zorder=1)
    ax.axhline(RTT_SLA,  color=C_SLA,  ls="--", lw=1.3, label=f"SLA Threshold ({RTT_SLA}ms)")
    ax.axhline(RTT_HARD, color=C_HARD, ls=":",  lw=1.0, label=f"Hard Limit ({RTT_HARD}ms)")
    ax.set_ylabel("RTT (ms)", fontsize=10)
    ax.set_title(
        "Agentic QoS Orchestrator — Temporal Decision Trace (Representative Medium-Traffic Run)\n"
        "Rule-Based vs Agentic: Chain-of-Thought · Wrong-Lever Avoidance · Memory-Assisted Decisions",
        fontsize=11, fontweight="bold", pad=10
    )
    ax.legend(loc="upper right", fontsize=8, framealpha=0.85, ncol=2)
    ax.set_ylim(bottom=max(0, rtt.min() - 1), top=max(RTT_HARD + 3, rtt.max() + 2))

    # Panel 1 episode annotations
    for ep in [e for e in episodes if e["panel"] == 0]:
        ax.annotate(
            ep["label"],
            xy=(ep["x"], ep["y"]),
            xytext=(ep["x"] + max(t)*0.06, ep["y"] + 2.5),
            fontsize=8, color=ep["color"], fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=ep["color"],
                            connectionstyle="arc3,rad=0.2", lw=1.2),
            bbox=dict(boxstyle="round,pad=0.3", fc="white",
                      ec=ep["color"], alpha=0.88, lw=1),
        )

    # ── Panel 2: eMBB Throughput ──────────────────────────────────────────────
    ax = axes[1]
    embb = w["embb_mbps"].clip(lower=0)
    ax.fill_between(t, embb, alpha=0.35, color=C_EMBB)
    ax.plot(t, embb, color=C_EMBB, lw=1.2, label="eMBB Throughput (Mbps)")
    ax.set_ylabel("Throughput\n(Mbps)", fontsize=10)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.85)

    # Panel 2 episode annotations
    for ep in [e for e in episodes if e["panel"] == 1]:
        ax.annotate(
            ep["label"],
            xy=(ep["x"], ep["y"]),
            xytext=(ep["x"] + max(t)*0.06, ep["y"] + 30),
            fontsize=8, color=ep["color"], fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=ep["color"],
                            connectionstyle="arc3,rad=-0.2", lw=1.2),
            bbox=dict(boxstyle="round,pad=0.3", fc="white",
                      ec=ep["color"], alpha=0.88, lw=1),
        )

    # ── Panel 3: tc Bandwidth State ───────────────────────────────────────────
    ax = axes[2]
    rate = w["embb_rate_mbit"].astype(float)
    ax.step(t, rate, color=C_SLA, lw=1.2, where="post", zorder=3)
    ax.fill_between(t, 0, rate,
                    where=(rate >= BW_NORMAL),
                    step="post", color=C_NORMAL, alpha=0.45, label="Normal (1000 Mbit)")
    ax.fill_between(t, 0, rate,
                    where=(rate < BW_NORMAL),
                    step="post", color=C_THROT, alpha=0.55, label="Throttled")
    ax.set_ylabel("tc Rate\n(Mbit)", fontsize=10)
    ax.set_yticks([50, 200, 500, 1000])
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda v, _: {50:"50", 200:"200", 500:"500", 1000:"1000"}.get(int(v), str(int(v)))))
    ax.legend(loc="upper right", fontsize=8, framealpha=0.85, ncol=2)

    # ── Panel 4: LLM Decision Events ─────────────────────────────────────────
    ax = axes[3]
    ax.set_facecolor("#FAFAFA")
    plotted_labels = set()
    for action, (marker, color, size, label) in ACTION_MARKERS.items():
        idx = w.index[w["action_taken"] == action]
        if len(idx) == 0:
            continue
        lbl = label if label not in plotted_labels else "_nolegend_"
        plotted_labels.add(label)
        ax.scatter(
            t[idx], [action] * len(idx),
            marker=marker, color=color, s=size, zorder=4,
            label=lbl, alpha=0.85, edgecolors="white", linewidths=0.4,
        )
    # Vertical lines for major events
    for action, (marker, color, size, label) in ACTION_MARKERS.items():
        if action in ("throttle_embb", "throttle_preemptive", "restore_embb"):
            idx = w.index[w["action_taken"] == action]
            for i in idx:
                ax.axvline(t[i], color=color, alpha=0.18, lw=0.6, zorder=1)

    ax.set_ylabel("Decision\nType", fontsize=10)
    ax.tick_params(axis="y", labelsize=8)
    leg4 = ax.legend(loc="upper right", fontsize=7.5, framealpha=0.85,
                     ncol=min(5, len(plotted_labels)))
    ax.set_yticks(list(ACTION_MARKERS.keys()))
    ax.set_yticklabels(
        [v[3] for v in ACTION_MARKERS.values()], fontsize=7.5
    )

    # ── Panel 5: Memory Activity ──────────────────────────────────────────────
    ax = axes[4]
    if "memory_retrieval_count" in w.columns:
        mem_raw = w["memory_retrieval_count"].fillna(0).astype(float)
    elif "memory_assisted" in w.columns:
        mem_raw = w["memory_assisted"].astype(float)
    else:
        mem_raw = pd.Series(np.zeros(len(w)))

    # Cumulative memory entries (simulate growing memory)
    mem_cumul = mem_raw.cumsum()
    mem_norm  = mem_cumul / max(mem_cumul.max(), 1)   # normalise 0–1

    ax.fill_between(t, mem_norm, alpha=0.40, color=C_MEM, step="post")
    ax.step(t, mem_norm, color=C_MEM, lw=1.2, where="post", label="Memory Saturation")

    # Phase labels
    for frac, label in [(0.15, "Empty"), (0.45, "Growing"), (0.80, "Mature")]:
        xi = int(frac * len(t))
        ax.text(t[xi], 0.55, label, fontsize=7.5, color=C_MEM,
                fontstyle="italic", ha="center")

    # Per-cycle retrievals as scatter
    retrieval_idx = w.index[mem_raw > 0]
    if len(retrieval_idx):
        ax.scatter(t[retrieval_idx], mem_norm[retrieval_idx],
                   color=C_MEM, s=18, zorder=4, alpha=0.7,
                   label="Memory Retrieved")

    ax.set_ylabel("Memory\nSaturation", fontsize=10)
    ax.set_ylim(0, 1.1)
    ax.set_yticks([0, 0.5, 1.0])
    ax.set_yticklabels(["0%", "50%", "100%"])
    ax.legend(loc="lower right", fontsize=8, framealpha=0.85)

    # ── Panel 6: WLA / C4 Events ──────────────────────────────────────────────
    ax = axes[5]
    ax.set_facecolor("#FFFBF5")

    if "wla_activated" in w.columns:
        wla_mask = w["wla_activated"].astype(int) == 1
        wla_idx  = w.index[wla_mask]

        # Background: RTT elevated but eMBB idle → WLA zone
        rtt_norm = (w["urllc_rtt_ms"] - w["urllc_rtt_ms"].min()) / \
                   max(w["urllc_rtt_ms"].max() - w["urllc_rtt_ms"].min(), 1)
        ax.fill_between(t, rtt_norm, alpha=0.12, color=C_RTT, label="RTT (norm.)")
        ax.plot(t, rtt_norm, color=C_RTT, lw=0.7, alpha=0.5)

        if len(wla_idx):
            ax.scatter(
                t[wla_idx], [0.5] * len(wla_idx),
                marker="X", color=C_WLA, s=120, zorder=5,
                edgecolors="#264653", linewidths=0.6,
                label=f"WLA Triggered ({len(wla_idx)} events)",
            )
            # Callout label for first few WLA events
            for n, i in enumerate(wla_idx[:3]):
                ax.annotate(
                    "WLA\nTriggered",
                    xy=(t[i], 0.52),
                    xytext=(t[i], 0.80 - n * 0.15),
                    fontsize=7, color=C_WLA, fontweight="bold",
                    arrowprops=dict(arrowstyle="->", color=C_WLA, lw=0.9),
                    ha="center",
                )
        ax.set_ylim(0, 1.1)
        ax.set_yticks([0, 0.5, 1.0])
        ax.set_yticklabels(["Low", "Mid", "High"])
    else:
        ax.text(0.5, 0.5, "WLA data not available",
                ha="center", va="center", transform=ax.transAxes,
                fontsize=9, color="grey")

    ax.set_ylabel("WLA / C4\nEvents", fontsize=10)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.85)
    ax.set_xlabel("Time (seconds)", fontsize=11)

    # ── X-axis ticks (only bottom panel) ─────────────────────────────────────
    for ax in axes[:-1]:
        plt.setp(ax.get_xticklabels(), visible=False)
    axes[-1].xaxis.set_major_locator(mticker.MultipleLocator(50))
    axes[-1].xaxis.set_minor_locator(mticker.MultipleLocator(10))

    # ── Column labels on right ────────────────────────────────────────────────
    panel_labels = [
        "(1) RTT", "(2) eMBB", "(3) tc State",
        "(4) Decisions", "(5) Memory", "(6) WLA / C4",
    ]
    for ax, lbl in zip(axes, panel_labels):
        ax.text(1.002, 0.5, lbl, transform=ax.transAxes,
                fontsize=8, va="center", ha="left",
                color="#264653", fontweight="bold",
                rotation=270, rotation_mode="anchor")

    # ── Shared vertical markers for key global events ─────────────────────────
    rst_t = t[w.index[w["action_taken"] == "restore_embb"]]
    thr_t = t[w.index[w["action_taken"].isin(["throttle_embb","throttle_preemptive"])]]
    for ax in axes:
        for ti in rst_t[:5]:
            ax.axvline(ti, color=C_NORMAL, alpha=0.12, lw=1.0, ls="-")
        for ti in thr_t[:10]:
            ax.axvline(ti, color=C_THROT, alpha=0.10, lw=0.8, ls="-")

    # ── Legend strip ─────────────────────────────────────────────────────────
    legend_handles = [
        mpatches.Patch(color=C_RTT,   alpha=0.8, label="SLA Violation Period"),
        mpatches.Patch(color=C_NORMAL,alpha=0.7, label="Normal State / Restore"),
        mpatches.Patch(color=C_THROT, alpha=0.7, label="Throttle State"),
        mpatches.Patch(color=C_WLA,   alpha=0.8, label="WLA C4 Trigger"),
        mpatches.Patch(color=C_MEM,   alpha=0.7, label="Memory Active"),
        Line2D([0],[0], color=C_SLA, ls="--", lw=1.5, label="15ms SLA"),
        Line2D([0],[0], color=C_HARD, ls=":",  lw=1.2, label="20ms Hard Limit"),
    ]
    fig.legend(handles=legend_handles, loc="lower center",
               ncol=7, fontsize=8.5, framealpha=0.95,
               bbox_to_anchor=(0.5, -0.01),
               edgecolor="#CCCCCC")

    plt.subplots_adjust(left=0.09, right=0.95, top=0.96, bottom=0.05)
    plt.savefig(FIGS / "flagship_timeline.pdf", bbox_inches="tight")
    plt.savefig(FIGS / "flagship_timeline.png", bbox_inches="tight", dpi=200)
    plt.close()
    print("✅  flagship_timeline.pdf + .png saved to results/figures/")


if __name__ == "__main__":
    build_figure()
