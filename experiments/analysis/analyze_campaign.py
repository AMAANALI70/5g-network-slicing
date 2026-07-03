#!/usr/bin/env python3
"""
Full Campaign Analysis Pipeline
Steps: Integrity → Descriptive → Quality → Statistical → Figures
"""
import os, sys, glob, warnings
import pandas as pd
import numpy as np
from scipy import stats
from pathlib import Path

warnings.filterwarnings("ignore")

RESULTS_DIR = Path("/home/kube-master/k8s/experiments/results/campaign")
OUT_DIR     = Path("/home/kube-master/k8s/experiments/analysis/output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SLA_MS        = 15.0    # actual system SLA
SLA_MS_ALT    = 20.0    # user-specified alternative
WARMUP_SEC    = 120     # rows before this timestamp offset are excluded
SAMPLE_INT_S  = 3       # approximate row interval

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("  STEP 1 — DATASET INTEGRITY AUDIT")
print("="*70)

files = sorted([f for f in RESULTS_DIR.glob("*.csv") if "invalidated" not in str(f)])
print(f"\nCSV files found: {len(files)}  (expected: 18)\n")

runs = []
for f in files:
    df = pd.read_csv(f, parse_dates=["timestamp"])
    meta = dict(
        file      = f.name,
        orch      = df["orchestrator_type"].iloc[0],
        level     = df["load_level"].iloc[0],
        total_rows= len(df),
        t_start   = df["timestamp"].iloc[0],
        t_end     = df["timestamp"].iloc[-1],
        duration_s= (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).total_seconds(),
        raw_df    = df,
    )
    # warm-up exclusion: drop first WARMUP_SEC seconds
    t0 = df["timestamp"].iloc[0]
    df_clean = df[df["timestamp"] >= t0 + pd.Timedelta(seconds=WARMUP_SEC)].copy()
    meta["clean_rows"] = len(df_clean)
    meta["clean_df"]   = df_clean

    # missing value check in key columns
    KEY_COLS = ["urllc_rtt_ms","embb_throughput_mbps","embb_tc_rate_mbit",
                "orchestrator_state","throttle_total","restore_total",
                "load_level","orchestrator_type"]
    meta["missing"] = {c: df_clean[c].isna().sum() for c in KEY_COLS}
    meta["any_missing"] = any(v > 0 for v in meta["missing"].values())
    runs.append(meta)

# Print run inventory table
hdr = f"{'#':>2} {'Orch':12} {'Level':8} {'Total':>6} {'Clean':>6} {'Duration':>10} {'Missing?':>8}  File"
print(hdr)
print("-"*len(hdr))
for i, r in enumerate(runs, 1):
    dur = f"{r['duration_s']/60:.1f}min"
    miss = "YES ⚠" if r["any_missing"] else "no"
    print(f"{i:2d} {r['orch']:12} {r['level']:8} {r['total_rows']:6d} {r['clean_rows']:6d} {dur:>10}  {miss:>8}  {r['file']}")

# Check balance
from collections import Counter
combos = Counter((r["orch"], r["level"]) for r in runs)
print(f"\nRun balance: {dict(combos)}")
expected = {("rule_based","low"):3,("rule_based","medium"):3,("rule_based","high"):3,
            ("agentic","low"):3,("agentic","medium"):3,("agentic","high"):3}
ok = all(combos[k]==v for k,v in expected.items())
print(f"Balance check: {'✅ PASS' if ok else '❌ FAIL'}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("  STEP 2 — DESCRIPTIVE STATISTICS")
print("="*70)

# Build master dataframe (post-warmup only)
master = pd.concat([r["clean_df"].assign(file=r["file"]) for r in runs], ignore_index=True)
master["urllc_rtt_ms"]       = pd.to_numeric(master["urllc_rtt_ms"],      errors="coerce")
master["embb_throughput_mbps"] = pd.to_numeric(master["embb_throughput_mbps"], errors="coerce")
master["embb_tc_rate_mbit"]  = pd.to_numeric(master["embb_tc_rate_mbit"], errors="coerce")
master["sla_violation"]      = (master["urllc_rtt_ms"] > SLA_MS).astype(int)
master["sla_violation_alt"]  = (master["urllc_rtt_ms"] > SLA_MS_ALT).astype(int)

# Per-run stats
print(f"\n--- Per-Run RTT Statistics (post-warmup, SLA={SLA_MS}ms) ---")
hdr2 = f"{'Orch':12} {'Level':8} {'N':>5} {'Mean':>8} {'Med':>8} {'Std':>8} {'Min':>8} {'Max':>8} {'Viol%15':>9} {'Viol%20':>9}"
print(hdr2); print("-"*len(hdr2))

per_run_stats = []
for r in runs:
    df = r["clean_df"].copy()
    df["urllc_rtt_ms"] = pd.to_numeric(df["urllc_rtt_ms"], errors="coerce")
    rtt = df["urllc_rtt_ms"].dropna()
    n   = len(rtt)
    v15 = (rtt > SLA_MS).mean() * 100
    v20 = (rtt > SLA_MS_ALT).mean() * 100
    embb_mean = pd.to_numeric(df["embb_throughput_mbps"], errors="coerce").mean()
    tc_mean   = pd.to_numeric(df["embb_tc_rate_mbit"], errors="coerce").mean()
    thr = pd.to_numeric(df["throttle_total"], errors="coerce")
    res = pd.to_numeric(df["restore_total"],  errors="coerce")
    throttle_cnt = thr.max() - thr.min() if len(thr) > 0 else 0
    restore_cnt  = res.max() - res.min() if len(res) > 0 else 0
    per_run_stats.append(dict(orch=r["orch"], level=r["level"], file=r["file"],
        n=n, mean=rtt.mean(), med=rtt.median(), std=rtt.std(),
        min=rtt.min(), max=rtt.max(), viol15=v15, viol20=v20,
        embb_mean=embb_mean, tc_mean=tc_mean,
        throttle_cnt=throttle_cnt, restore_cnt=restore_cnt))
    print(f"{r['orch']:12} {r['level']:8} {n:5d} {rtt.mean():8.2f} {rtt.median():8.2f} "
          f"{rtt.std():8.2f} {rtt.min():8.2f} {rtt.max():8.2f} {v15:9.1f} {v20:9.1f}")

# Aggregated by orch × level
print(f"\n--- Aggregated by Orchestrator × Load Level ---")
grp = master.groupby(["orchestrator_type","load_level"])
agg = grp["urllc_rtt_ms"].agg(["mean","median","std","min","max"]).round(2)
agg["viol_pct_15ms"]  = (grp["sla_violation"].mean() * 100).round(1)
agg["viol_pct_20ms"]  = (grp["sla_violation_alt"].mean() * 100).round(1)
agg["embb_mbps_mean"] = grp["embb_throughput_mbps"].mean().round(1)
agg["tc_rate_mean"]   = grp["embb_tc_rate_mbit"].mean().round(1)
print(agg.to_string())

# Save to CSV
prs = pd.DataFrame(per_run_stats)
prs.to_csv(OUT_DIR / "per_run_stats.csv", index=False)
agg.to_csv(OUT_DIR / "aggregated_stats.csv")
print(f"\nSaved: per_run_stats.csv, aggregated_stats.csv")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("  STEP 3 — DATASET QUALITY REVIEW")
print("="*70)

print("\nQuality flags:")
for r in per_run_stats:
    flags = []
    if r["n"] < 300:
        flags.append(f"LOW ROWS ({r['n']})")
    if r["max"] > 500:
        flags.append(f"RTT SPIKE ({r['max']:.0f}ms)")
    if r["viol15"] > 80:
        flags.append(f"HIGH VIOL ({r['viol15']:.0f}%)")
    status = "  ⚠  " + ", ".join(flags) if flags else "  ✅ OK"
    print(f"  {r['orch']:12} {r['level']:8} {status}")

print(f"\nnode_cpu_pct: all NaN → excluded from analysis")
print(f"mmtc_msgs_total: cumulative counter → converted to per-run delta only")
print(f"embb_throughput_mbps=0: HLS burst gaps (expected) → kept in dataset")
print(f"RTT=0: SSH read miss → rows with RTT==0 filtered in stats below")

# Filter RTT==0 check
zero_rtt = (master["urllc_rtt_ms"] == 0).sum()
total    = len(master)
print(f"\nRTT=0 rows: {zero_rtt}/{total} ({100*zero_rtt/total:.1f}%) → excluded from RTT stats")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("  STEP 4 — STATISTICAL ANALYSIS")
print("="*70)

# Filter RTT=0 for stats
mstat = master[master["urllc_rtt_ms"] > 0].copy()

rb  = mstat[mstat["orchestrator_type"] == "rule_based"]["urllc_rtt_ms"].values
ag  = mstat[mstat["orchestrator_type"] == "agentic"]["urllc_rtt_ms"].values

print(f"\n  rule_based: n={len(rb)}, mean={rb.mean():.2f}ms, std={rb.std():.2f}ms")
print(f"  agentic:    n={len(ag)}, mean={ag.mean():.2f}ms, std={ag.std():.2f}ms")

# Mann-Whitney U
mwu_stat, mwu_p = stats.mannwhitneyu(rb, ag, alternative="two-sided")
print(f"\n[Mann-Whitney U]  U={mwu_stat:.0f}  p={mwu_p:.4e}  {'*SIGNIFICANT*' if mwu_p<0.05 else 'ns'}")

# Welch's t-test
t_stat, t_p = stats.ttest_ind(rb, ag, equal_var=False)
print(f"[Welch t-test  ]  t={t_stat:.3f}  p={t_p:.4e}  {'*SIGNIFICANT*' if t_p<0.05 else 'ns'}")

# Cohen's d
pooled_std = np.sqrt((rb.std()**2 + ag.std()**2) / 2)
cohens_d   = (rb.mean() - ag.mean()) / pooled_std
print(f"[Cohen's d     ]  d={cohens_d:.3f}  ({'large' if abs(cohens_d)>0.8 else 'medium' if abs(cohens_d)>0.5 else 'small'} effect)")

# Per load level
print(f"\n--- Per Load Level ---")
level_results = []
for level in ["low","medium","high"]:
    rb_l = mstat[(mstat["orchestrator_type"]=="rule_based") & (mstat["load_level"]==level)]["urllc_rtt_ms"].values
    ag_l = mstat[(mstat["orchestrator_type"]=="agentic")    & (mstat["load_level"]==level)]["urllc_rtt_ms"].values
    u, p = stats.mannwhitneyu(rb_l, ag_l, alternative="two-sided")
    d    = (rb_l.mean() - ag_l.mean()) / np.sqrt((rb_l.std()**2 + ag_l.std()**2)/2)
    sig  = "**" if p < 0.01 else "*" if p < 0.05 else "ns"
    print(f"  {level:8}: RB={rb_l.mean():.2f}ms  AG={ag_l.mean():.2f}ms  "
          f"U={u:.0f}  p={p:.4e}  d={d:.3f}  {sig}")
    level_results.append(dict(level=level, rb_mean=rb_l.mean(), ag_mean=ag_l.mean(),
                               U=u, p=p, cohens_d=d, sig=sig))

# SLA violation rate comparison
print(f"\n--- SLA Violation Rate (RTT > {SLA_MS}ms) ---")
rb_viol = mstat[mstat["orchestrator_type"]=="rule_based"]["sla_violation"].mean()*100
ag_viol = mstat[mstat["orchestrator_type"]=="agentic"]["sla_violation"].mean()*100
print(f"  rule_based: {rb_viol:.1f}%   agentic: {ag_viol:.1f}%   diff: {rb_viol-ag_viol:+.1f}pp")

# Throttle counts per run
print(f"\n--- Throttle/Restore Counts ---")
rb_thr = np.mean([r["throttle_cnt"] for r in per_run_stats if r["orch"]=="rule_based"])
ag_thr = np.mean([r["throttle_cnt"] for r in per_run_stats if r["orch"]=="agentic"])
rb_res = np.mean([r["restore_cnt"]  for r in per_run_stats if r["orch"]=="rule_based"])
ag_res = np.mean([r["restore_cnt"]  for r in per_run_stats if r["orch"]=="agentic"])
print(f"  Throttles/run:  RB={rb_thr:.1f}  AG={ag_thr:.1f}")
print(f"  Restores/run:   RB={rb_res:.1f}  AG={ag_res:.1f}")

# Mixed ANOVA (using pingouin if available, else skip)
try:
    import pingouin as pg
    print(f"\n--- Mixed ANOVA (orchestrator×load_level) ---")
    # Need subject-level means (per trial)
    for r in runs:
        r["clean_df"]["trial"] = r["file"]
    trial_means = []
    for r in runs:
        df = r["clean_df"][r["clean_df"]["urllc_rtt_ms"] > 0]
        trial_means.append(dict(
            subject = r["file"],
            orch    = r["orch"],
            level   = r["level"],
            rtt     = pd.to_numeric(df["urllc_rtt_ms"], errors="coerce").mean()
        ))
    tm = pd.DataFrame(trial_means)
    # pingouin mixed ANOVA: between=orch, within=level, subject=subject
    aov = pg.mixed_anova(data=tm, dv="rtt", between="orch", within="level", subject="subject")
    print(aov[["Source","F","p-unc","np2"]].to_string(index=False))
    aov.to_csv(OUT_DIR/"mixed_anova.csv", index=False)
except ImportError:
    print("\n  [pingouin not installed — Mixed ANOVA skipped]")
    print("  Run: pip3 install pingouin")

# Save stat results
pd.DataFrame(level_results).to_csv(OUT_DIR/"stat_per_level.csv", index=False)

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("  STEP 5 — FIGURES")
print("="*70)

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    COLORS = {"rule_based": "#2196F3", "agentic": "#FF5722"}
    LEVELS = ["low","medium","high"]

    # ── Fig 1: RTT box plots per load level ──────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(14, 5), sharey=True)
    fig.suptitle("URLLC RTT Distribution by Load Level", fontsize=14, fontweight="bold")
    for ax, level in zip(axes, LEVELS):
        data = {}
        for orch in ["rule_based","agentic"]:
            d = mstat[(mstat["orchestrator_type"]==orch)&(mstat["load_level"]==level)]["urllc_rtt_ms"].values
            data[orch] = d
        bp = ax.boxplot([data["rule_based"], data["agentic"]],
                        labels=["Rule-Based","Agentic"],
                        patch_artist=True, notch=True,
                        medianprops=dict(color="white",linewidth=2))
        for patch, key in zip(bp["boxes"], ["rule_based","agentic"]):
            patch.set_facecolor(COLORS[key])
            patch.set_alpha(0.8)
        ax.axhline(SLA_MS, color="red", linestyle="--", linewidth=1.5, label=f"SLA {SLA_MS}ms")
        ax.set_title(f"{level.capitalize()} Load", fontweight="bold")
        ax.set_ylabel("RTT (ms)" if ax == axes[0] else "")
        ax.set_ylim(0, min(200, mstat["urllc_rtt_ms"].quantile(0.99)*1.1))
        ax.grid(axis="y", alpha=0.3)
        # Add significance marker
        res = [r for r in level_results if r["level"]==level]
        if res and res[0]["sig"] != "ns":
            ax.text(1.5, ax.get_ylim()[1]*0.92, res[0]["sig"], ha="center", fontsize=14, color="black")
    axes[0].legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(OUT_DIR/"fig1_rtt_boxplot.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Saved: fig1_rtt_boxplot.png")

    # ── Fig 2: SLA violation rate bar chart ──────────────────────────────
    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(LEVELS))
    w = 0.35
    for i, orch in enumerate(["rule_based","agentic"]):
        viols = []
        for level in LEVELS:
            d = mstat[(mstat["orchestrator_type"]==orch)&(mstat["load_level"]==level)]["sla_violation"].mean()*100
            viols.append(d)
        bars = ax.bar(x + (i-0.5)*w, viols, w, label=orch.replace("_"," ").title(),
                      color=COLORS[orch], alpha=0.85)
        for bar, v in zip(bars, viols):
            ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.5,
                    f"{v:.1f}%", ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.set_xticks(x); ax.set_xticklabels([l.capitalize() for l in LEVELS])
    ax.set_xlabel("Load Level"); ax.set_ylabel("SLA Violation Rate (%)")
    ax.set_title(f"SLA Violation Rate (RTT > {SLA_MS}ms)", fontweight="bold")
    ax.legend(); ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT_DIR/"fig2_sla_violation_rate.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Saved: fig2_sla_violation_rate.png")

    # ── Fig 3: RTT CDF ───────────────────────────────────────────────────
    fig, axes = plt.subplots(1, 3, figsize=(14, 5), sharey=True)
    fig.suptitle("URLLC RTT Cumulative Distribution", fontsize=14, fontweight="bold")
    for ax, level in zip(axes, LEVELS):
        for orch in ["rule_based","agentic"]:
            d = np.sort(mstat[(mstat["orchestrator_type"]==orch)&(mstat["load_level"]==level)]["urllc_rtt_ms"].values)
            cdf = np.arange(1, len(d)+1) / len(d)
            ax.plot(d, cdf, color=COLORS[orch], linewidth=2,
                    label=orch.replace("_"," ").title())
        ax.axvline(SLA_MS, color="red", linestyle="--", linewidth=1.5)
        ax.set_xlim(0, min(100, np.percentile(mstat["urllc_rtt_ms"],98)))
        ax.set_title(f"{level.capitalize()} Load"); ax.grid(alpha=0.3)
        ax.set_xlabel("RTT (ms)"); ax.set_ylabel("CDF" if ax==axes[0] else "")
    axes[0].legend()
    plt.tight_layout()
    plt.savefig(OUT_DIR/"fig3_rtt_cdf.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Saved: fig3_rtt_cdf.png")

    # ── Fig 4: eMBB throughput ───────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(8, 5))
    for i, orch in enumerate(["rule_based","agentic"]):
        embb = []
        for level in LEVELS:
            d = mstat[(mstat["orchestrator_type"]==orch)&(mstat["load_level"]==level)]["embb_throughput_mbps"].mean()
            embb.append(d)
        ax.bar(x + (i-0.5)*w, embb, w, label=orch.replace("_"," ").title(),
               color=COLORS[orch], alpha=0.85)
    ax.set_xticks(x); ax.set_xticklabels([l.capitalize() for l in LEVELS])
    ax.set_xlabel("Load Level"); ax.set_ylabel("Mean eMBB Throughput (Mbps)")
    ax.set_title("eMBB Mean Throughput by Load Level", fontweight="bold")
    ax.legend(); ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT_DIR/"fig4_embb_throughput.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Saved: fig4_embb_throughput.png")

    # ── Fig 5: Throttle/Restore counts ──────────────────────────────────
    fig, ax = plt.subplots(figsize=(8,5))
    orch_labels = ["Rule-Based","Agentic"]
    thr_means = [rb_thr, ag_thr]
    res_means = [rb_res, ag_res]
    xi = np.arange(2)
    ax.bar(xi-0.2, thr_means, 0.35, label="Throttles", color="#F44336", alpha=0.8)
    ax.bar(xi+0.2, res_means, 0.35, label="Restores",  color="#4CAF50", alpha=0.8)
    ax.set_xticks(xi); ax.set_xticklabels(orch_labels)
    ax.set_ylabel("Mean count per run"); ax.set_title("Mean Throttle/Restore Events per Run", fontweight="bold")
    ax.legend(); ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT_DIR/"fig5_throttle_restore.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Saved: fig5_throttle_restore.png")

except ImportError as e:
    print(f"  matplotlib not available: {e}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("  SUMMARY")
print("="*70)
print(f"\n  rule_based RTT: {rb.mean():.2f} ± {rb.std():.2f} ms")
print(f"  agentic    RTT: {ag.mean():.2f} ± {ag.std():.2f} ms")
print(f"  Diff: {ag.mean()-rb.mean():+.2f} ms  Cohen's d={cohens_d:.3f}")
print(f"  Mann-Whitney p={mwu_p:.4e}  Welch-t p={t_p:.4e}")
print(f"\n  SLA violation (>15ms): RB={rb_viol:.1f}%  AG={ag_viol:.1f}%")
print(f"\n  Output dir: {OUT_DIR}")
print("="*70)
