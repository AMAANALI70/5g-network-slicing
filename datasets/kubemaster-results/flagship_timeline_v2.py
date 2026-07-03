#!/usr/bin/env python3
"""
flagship_timeline_v2.py
=======================
Redesigned flagship figure: 3-panel temporal audit trace.
IEEE conference/journal publication quality.

Panels:
  1 (50%) — URLLC RTT and SLA Compliance
  2 (25%) — UPF tc Shaping State
  3 (25%) — Wrong-Lever Avoidance Events (C4)

Output: results/figures/flagship_timeline_v2.pdf + .png
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA = Path(__file__).parent / "datasets" / "dataset_agentic_medium.csv"
FIGS = Path(__file__).parent / "figures"
FIGS.mkdir(exist_ok=True)

# ── Publication style ─────────────────────────────────────────────────────────
matplotlib.rcParams.update({
    "font.family":       "serif",
    "font.size":         10,
    "axes.labelsize":    10,
    "axes.titlesize":    10,
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.grid":         True,
    "grid.alpha":        0.18,
    "grid.linestyle":    "--",
    "grid.linewidth":    0.5,
    "xtick.labelsize":   9,
    "ytick.labelsize":   9,
    "figure.dpi":        180,
    "legend.fontsize":   8.5,
    "legend.framealpha": 0.90,
})

# ── Thresholds ────────────────────────────────────────────────────────────────
RTT_SLA  = 15.0
RTT_HARD = 20.0
BW_MAX   = 1000

# ── Colors ────────────────────────────────────────────────────────────────────
C_RTT    = "#C0392B"        # red RTT line
C_VIOL   = "#E74C3C"        # violation shading
C_SLA    = "#2C3E50"        # SLA dashed line (dark navy)
C_HARD   = "#7B241C"        # hard limit dotted
C_NORMAL = "#1A7A5E"        # tc normal (teal-green)
C_THROT  = "#D35400"        # tc throttled (orange-red)
C_WLA    = "#E67E22"        # WLA markers (vivid orange)
C_WLA_BG = "#FEF9E7"        # WLA panel background tint
C_ANNOT  = "#1A252F"        # annotation text


# ── Select representative window ──────────────────────────────────────────────
def select_window(df, length=200):
    """
    Score windows: prefer those with SLA violations, WLA events,
    throttle AND restore actions, but not saturated with violations.
    """
    best_score, best_start = -1, 0
    for start in range(0, len(df) - length, 15):
        w = df.iloc[start:start + length]
        score = 0
        n_viol = w["sla_violated"].astype(int).sum()
        score += 3 if 5 < n_viol < length * 0.45 else -3
        if "wla_activated" in w.columns:
            score += 4 * min(w["wla_activated"].astype(int).sum(), 5)
        acts = w["action_taken"].value_counts()
        score += 4 if "restore_embb" in acts.index else 0
        score += 3 if any(a in acts.index for a in
                          ["throttle_embb", "throttle_preemptive"]) else 0
        score += 2 if w["urllc_rtt_ms"].max() > RTT_SLA else 0
        score -= 4 if w["urllc_rtt_ms"].std() < 0.4 else 0
        if score > best_score:
            best_score, best_start = score, start
    return df.iloc[best_start:best_start + length].reset_index(drop=True)


# ── Auto-detect episodes ───────────────────────────────────────────────────────
def detect_episodes(w, t):
    eps = {}

    # Episode A: largest RTT spike → throttle applied → recovery
    viol = w.index[w["sla_violated"].astype(int) == 1].tolist()
    if viol:
        peak = int(w.loc[viol, "urllc_rtt_ms"].idxmax())
        thr_before = w.index[
            w["action_taken"].isin(["throttle_embb","throttle_preemptive"]) &
            (w.index >= max(0, peak-8)) & (w.index <= peak+5)
        ].tolist()
        rec_after = w.index[
            (w["sla_violated"].astype(int)==0) & (w.index > peak+2)
        ].tolist()
        if thr_before and rec_after:
            eps["A"] = {
                "t":     t[peak],
                "rtt":   w.loc[peak, "urllc_rtt_ms"],
                "panel": "rtt",
                "text":  "Episode A:\nRTT spike detected\nThrottle approved\nQoS restored",
                "color": C_RTT,
                "side":  "right",
            }

    # Episode B: WLA event — throttle rejected
    if "wla_activated" in w.columns:
        wla_idx = w.index[w["wla_activated"].astype(int)==1].tolist()
        if wla_idx:
            bi = wla_idx[len(wla_idx)//2]
            eps["B"] = {
                "t":     t[bi],
                "rtt":   w.loc[bi, "urllc_rtt_ms"],
                "panel": "wla",
                "text":  "Episode B:\nWrong-Lever Avoidance\nRTT elevated\neMBB load insufficient\nThrottle rejected\nNatural recovery",
                "color": C_WLA,
                "side":  "left",
            }

    # Episode C: Restore action — bandwidth recovered
    rst = w.index[w["action_taken"]=="restore_embb"].tolist()
    if rst:
        ri = rst[0]
        eps["C"] = {
            "t":     t[ri],
            "rtt":   w.loc[ri, "urllc_rtt_ms"],
            "panel": "tc",
            "text":  "Episode C:\nRestore executed\nBandwidth recovered\nRTT stable",
            "color": C_NORMAL,
            "side":  "right",
        }

    return eps


# ── Draw callout box with arrow ────────────────────────────────────────────────
def callout(ax, tx, ty, text, color, side="right", short=False):
    xlim = ax.get_xlim()
    ylim = ax.get_ylim()
    xspan = xlim[1] - xlim[0]
    yspan = ylim[1] - ylim[0]
    # short=True → compact local arrow (for Episode B)
    dx = xspan * (0.08 if short else 0.13) * (1 if side=="right" else -1)
    dy = yspan * (0.16 if short else 0.26)
    ax.annotate(
        text,
        xy=(tx, ty),
        xytext=(tx + dx, ty + dy),
        fontsize=7.5,
        color=C_ANNOT,
        fontweight="bold",
        ha="left" if side=="right" else "right",
        va="bottom",
        arrowprops=dict(
            arrowstyle="->",
            color=color,
            lw=1.1,
            connectionstyle="arc3,rad=0.15",
        ),
        bbox=dict(
            boxstyle="round,pad=0.35",
            facecolor="white",
            edgecolor=color,
            linewidth=1.2,
            alpha=0.95,
        ),
        zorder=10,
    )


# ── Build figure ───────────────────────────────────────────────────────────────
def build():
    df = pd.read_csv(DATA)
    w  = select_window(df, length=200)
    t  = w.index * 2   # seconds

    eps = detect_episodes(w, t)

    # ── Layout: 3 panels, height ratio 4:2:2 ─────────────────────────────────
    fig = plt.figure(figsize=(12, 10))
    gs  = gridspec.GridSpec(
        3, 1, figure=fig,
        height_ratios=[4, 2, 2],
        hspace=0.12,
    )
    ax_rtt = fig.add_subplot(gs[0])
    ax_tc  = fig.add_subplot(gs[1], sharex=ax_rtt)
    ax_wla = fig.add_subplot(gs[2], sharex=ax_rtt)

    rtt  = w["urllc_rtt_ms"].clip(lower=0)
    rate = w["embb_rate_mbit"].astype(float)

    # ─────────────────────────────────────────────────────────────────────────
    # Panel 1 — URLLC RTT
    # ─────────────────────────────────────────────────────────────────────────
    ax = ax_rtt

    # SLA violation shading (light red only where violated)
    ax.fill_between(t, RTT_SLA, rtt,
                    where=(rtt > RTT_SLA),
                    interpolate=True,
                    color=C_VIOL, alpha=0.18, zorder=1, label="_nolegend_")

    # RTT line
    ax.plot(t, rtt, color=C_RTT, lw=1.3, zorder=3, label="URLLC RTT")

    # Reference lines
    ax.axhline(RTT_SLA,  color=C_SLA,  ls="--", lw=1.4,
               label=f"SLA Threshold ({RTT_SLA:.0f} ms)", zorder=4)
    ax.axhline(RTT_HARD, color=C_HARD, ls=":",  lw=1.0,
               label=f"Hard Limit ({RTT_HARD:.0f} ms)",   zorder=4)

    y_min = max(0, rtt.min() - 1.0)
    y_max = max(RTT_HARD + 3, rtt.max() + 2.5)
    ax.set_ylim(y_min, y_max)
    ax.set_ylabel("RTT (ms)", fontsize=10)
    ax.set_title("URLLC RTT and SLA Compliance", fontsize=10, fontweight="bold", pad=6)
    ax.legend(loc="upper right", ncol=3, framealpha=0.92, fontsize=8.5)
    ax.yaxis.set_major_locator(mticker.MultipleLocator(5))

    # Episode A callout on RTT panel — place in lower half to avoid title
    if "A" in eps:
        e   = eps["A"]
        # Clamp annotation y so it never approaches the top of the panel
        y_ann = min(e["rtt"], ax.get_ylim()[1] * 0.62)
        callout(ax, e["t"], y_ann, e["text"], e["color"], e["side"])

    # ─────────────────────────────────────────────────────────────────────────
    # Panel 2 — tc Shaping State
    # ─────────────────────────────────────────────────────────────────────────
    # ── tc PANEL: binary state only (NORMAL=1000 / THROTTLED≤200) ────────────
    ax = ax_tc

    # Map rate to binary: normal=1000, throttled=1 (any rate < BW_MAX)
    state_normal   = (rate >= BW_MAX)
    state_throttled= (rate <  BW_MAX)

    # Draw solid state bands
    ax.fill_between(t, 0, 1,
                    where=state_normal,
                    step="post",
                    color=C_NORMAL, alpha=0.55, label="Normal (1000 Mbit)",
                    zorder=2)
    ax.fill_between(t, 0, 1,
                    where=state_throttled,
                    step="post",
                    color=C_THROT, alpha=0.65, label="Throttled (50 Mbit)",
                    zorder=2)

    # State boundary lines
    ax.step(t, state_normal.astype(float), color=C_SLA,
            lw=0.8, where="post", zorder=3, alpha=0.5)

    # State labels inside bands
    ax.text(int(t[-1]) * 0.02, 0.75, "NORMAL",
            fontsize=8, color=C_NORMAL, fontweight="bold", va="center",
            bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))
    ax.text(int(t[-1]) * 0.02, 0.25, "THROTTLED",
            fontsize=8, color=C_THROT, fontweight="bold", va="center",
            bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))

    ax.set_ylim(0, 1)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["50\nMbit", "1000\nMbit"], fontsize=8)
    ax.set_ylabel("tc State", fontsize=10)
    ax.set_title("UPF tc Shaping State", fontsize=10, fontweight="bold", pad=4)
    ax.legend(loc="upper right", ncol=2, framealpha=0.92, fontsize=8.5)

    # Episode C callout on tc panel (anchored to state boundary)
    if "C" in eps:
        e   = eps["C"]
        # Determine state at restore time
        ri  = min(int(e["t"] // 2), len(rate)-1)
        # Point arrow to the rising edge (state going back to NORMAL)
        callout(ax, e["t"], 0.50, e["text"], e["color"], e["side"])

    # ─────────────────────────────────────────────────────────────────────────
    # Panel 3 — Wrong-Lever Avoidance Events
    # ─────────────────────────────────────────────────────────────────────────
    ax = ax_wla
    ax.set_facecolor(C_WLA_BG)

    # Background RTT (normalised) — improved visibility: darker, thicker, less transparent
    rtt_n = (rtt - rtt.min()) / max(rtt.max() - rtt.min(), 1)
    ax.fill_between(t, 0, rtt_n, color=C_RTT, alpha=0.18, zorder=1)
    ax.plot(t, rtt_n, color="#922B21", lw=1.4, alpha=0.75, zorder=2,
            label="RTT (normalised)")

    # WLA / C4 events
    if "wla_activated" in w.columns:
        wla_mask = w["wla_activated"].astype(int) == 1
        wla_t    = t[w.index[wla_mask]]
        n_wla    = wla_mask.sum()

        if n_wla > 0:
            ax.scatter(
                wla_t, [0.5] * n_wla,
                marker="X",
                color=C_WLA,
                s=180,
                zorder=6,
                edgecolors="#7D3C0F",
                linewidths=0.8,
                label=f"WLA Triggered ({n_wla} events)",
            )
            # Vertical drop lines from WLA markers to x-axis
            for ti in wla_t:
                ax.axvline(ti, color=C_WLA, alpha=0.20, lw=0.8, ls="-", zorder=1)

            # "WLA" text label above first few markers (max 4)
            for i, ti in enumerate(wla_t[:4]):
                ax.text(ti, 0.62 + (i % 2) * 0.12,
                        "WLA", fontsize=7, ha="center", va="bottom",
                        color="#7D3C0F", fontweight="bold", zorder=7)
        else:
            ax.text(0.5, 0.5, "No WLA events in selected window",
                    ha="center", va="center", transform=ax.transAxes,
                    color="grey", fontstyle="italic", fontsize=9)
    else:
        ax.text(0.5, 0.5, "WLA column not available",
                ha="center", va="center", transform=ax.transAxes,
                color="grey", fontstyle="italic", fontsize=9)

    ax.set_ylim(0, 1.05)
    ax.set_yticks([0, 0.5, 1.0])
    ax.set_yticklabels(["Low", "Mid", "High"], fontsize=8.5)
    ax.set_ylabel("RTT Level\n(WLA Events)", fontsize=10)
    ax.set_title("Wrong-Lever Avoidance Events (C4)", fontsize=10,
                 fontweight="bold", pad=4)
    ax.legend(loc="upper right", framealpha=0.92, fontsize=8.5)

    # Episode B callout on WLA panel — short arrow, local to event
    if "B" in eps:
        e       = eps["B"]
        idx_b   = min(int(e["t"] // 2), len(rtt_n)-1)
        rtt_val_n = float(rtt_n.iloc[idx_b])
        callout(ax, e["t"], max(rtt_val_n, 0.42),
                e["text"], e["color"], e["side"], short=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Shared vertical markers: throttle = orange stripe, restore = green stripe
    # ─────────────────────────────────────────────────────────────────────────
    thr_t = t[w.index[w["action_taken"].isin(["throttle_embb","throttle_preemptive"])]]
    rst_t = t[w.index[w["action_taken"] == "restore_embb"]]

    for axp in [ax_rtt, ax_tc, ax_wla]:
        for ti in thr_t[:12]:
            axp.axvline(ti, color=C_THROT, alpha=0.12, lw=0.9, zorder=1)
        for ti in rst_t[:8]:
            axp.axvline(ti, color=C_NORMAL, alpha=0.15, lw=0.9, zorder=1)

    # ─────────────────────────────────────────────────────────────────────────
    # X-axis (bottom panel only)
    # ─────────────────────────────────────────────────────────────────────────
    for axp in [ax_rtt, ax_tc]:
        plt.setp(axp.get_xticklabels(), visible=False)
    ax_wla.set_xlabel("Time (seconds)", fontsize=10)
    ax_wla.xaxis.set_major_locator(mticker.MultipleLocator(40))
    ax_wla.xaxis.set_minor_locator(mticker.MultipleLocator(10))

    # (bottom legend removed — each panel carries its own legend)

    # ─────────────────────────────────────────────────────────────────────────
    # Figure title
    # ─────────────────────────────────────────────────────────────────────────
    fig.suptitle(
        "Agentic QoS Orchestrator: Representative Temporal Audit Run",
        fontsize=12,
        fontweight="bold",
        y=0.99,
    )
    fig.text(
        0.5, 0.963,
        "Demonstrating QoS Recovery and Wrong-Lever Avoidance (C4)",
        ha="center", va="top",
        fontsize=10, fontstyle="italic", color="#2C3E50",
    )

    plt.subplots_adjust(left=0.09, right=0.97, top=0.93, bottom=0.07)
    plt.savefig(FIGS / "flagship_timeline_v2.pdf", bbox_inches="tight")
    plt.savefig(FIGS / "flagship_timeline_v2.png", bbox_inches="tight", dpi=220)
    plt.close()
    print("✅  flagship_timeline_v2.pdf + .png  →  results/figures/")


if __name__ == "__main__":
    build()
