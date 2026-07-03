#!/usr/bin/env python3
import os, argparse, random, math, glob
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import matplotlib.pyplot as plt
import seaborn as sns

# ============================================================
# CONFIG
# ============================================================
SEED = 42
DEFAULT_FREQ = "250ms"
DEFAULT_CONG = {
    "n_windows_per_slice": 3,
    "min_duration_s": 5,
    "max_duration_s": 30,
    "scale_factor": 2.5,
    "add_loss_prob": 0.15
}

def set_seed(seed=SEED):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

def ensure_dir(d):
    os.makedirs(d, exist_ok=True)

# ============================================================
# PREPROCESS (FIXED)
# ============================================================

def preprocess(raw_df, freq, inject_cong, cong_params, outdir):
    df = raw_df.copy()
    df["ts"] = pd.to_datetime(df["ts"])
    slices = sorted(df["slice"].unique())
    out_frames = []
    delta = pd.to_timedelta(freq).total_seconds()

    for sl in slices:
        g = df[df["slice"] == sl].sort_values("ts").set_index("ts")

        # Force numeric types
        for c in ["rx_bytes","tx_bytes","rx_pkts","tx_pkts","tcp_rtt_ms","probe_loss","tun_exists"]:
            g[c] = pd.to_numeric(g.get(c), errors="coerce")

        # Resample to strict grid
        g = g.resample(freq).first()

        # Fill counters and stats
        for c in ["rx_bytes","tx_bytes","rx_pkts","tx_pkts","tun_exists"]:
            g[c] = g[c].ffill().bfill().fillna(0)

        g["probe_loss"] = g["probe_loss"].fillna(0)
        g["latency_ms"] = g["tcp_rtt_ms"].astype(float)

        # Rate calc
        g["rx_rate_bps"] = g["rx_bytes"].diff().fillna(0) * 8 / delta
        g["tx_rate_bps"] = g["tx_bytes"].diff().fillna(0) * 8 / delta
        g["rx_rate_bps"] = g["rx_rate_bps"].clip(lower=0).fillna(0)
        g["tx_rate_bps"] = g["tx_rate_bps"].clip(lower=0).fillna(0)

        g["jitter_ms"] = g["latency_ms"].diff().abs().fillna(0)

        # Rolling features
        win5 = max(1, int(round(5 / delta)))
        win30 = max(1, int(round(30 / delta)))

        g["rx_rate_ma_5s"] = g["rx_rate_bps"].rolling(win5).mean().fillna(0)
        g["rx_rate_ma_30s"] = g["rx_rate_bps"].rolling(win30).mean().fillna(0)
        g["loss_5s"] = g["probe_loss"].rolling(win5).mean().fillna(0)

        g["slice"] = sl
        out_frames.append(g.reset_index())

    df_all = pd.concat(out_frames).sort_values(["ts","slice"]).reset_index(drop=True)

    # Inject Congestion
    if inject_cong:
        params = DEFAULT_CONG.copy()
        if cong_params:
            params.update(eval(cong_params))
        df_all = inject_cong_safe(df_all, freq, params)

    # FIX: Drop overlapping columns if they exist (prevents ValueError)
    for col in ["total_rx_rate_bps", "slice_share"]:
        if col in df_all.columns:
            df_all.drop(columns=[col], inplace=True)

    # Recalculate totals/shares globally
    total = df_all.groupby("ts")["rx_rate_bps"].sum().rename("total_rx_rate_bps")
    df_all = df_all.set_index("ts").join(total).reset_index()
    df_all["total_rx_rate_bps"] = df_all["total_rx_rate_bps"].fillna(0)
    df_all["slice_share"] = df_all["rx_rate_bps"] / (df_all["total_rx_rate_bps"] + 1e-9)

    # Clean NaNs
    for c in ["rx_rate_bps","tx_rate_bps","latency_ms","jitter_ms","rx_rate_ma_5s",
              "rx_rate_ma_30s","loss_5s","slice_share","total_rx_rate_bps"]:
        df_all[c] = df_all[c].fillna(0)

    ensure_dir(outdir)
    return df_all


# ============================================================
# CONGESTION (Helper)
# ============================================================

def inject_cong_safe(df, freq, params):
    df = df.copy()
    ts_list = sorted(df["ts"].unique())
    n = len(ts_list)
    delta = pd.to_timedelta(freq).total_seconds()
    rng = np.random.RandomState(SEED)

    for sl in df["slice"].unique():
        # Inject N windows of chaos per slice
        for _ in range(params["n_windows_per_slice"]):
            dur_s = rng.randint(params["min_duration_s"], params["max_duration_s"]+1)
            dur_n = max(1, int(round(dur_s / delta)))

            start = rng.randint(0, max(1, n - dur_n))
            s_ts = ts_list[start]
            e_ts = ts_list[min(n-1, start + dur_n)]

            mask = (df["slice"] == sl) & (df["ts"] >= s_ts) & (df["ts"] <= e_ts)

            if mask.sum() == 0: continue

            # Scale up traffic (congestion)
            df.loc[mask,"rx_rate_bps"] *= params["scale_factor"]
            # Add latency noise
            df.loc[mask,"latency_ms"] = df.loc[mask,"latency_ms"].fillna(1) + rng.uniform(5,50,mask.sum())
            
            # Random packet loss
            flips = rng.rand(mask.sum()) < params["add_loss_prob"]
            df.loc[mask,"probe_loss"] = np.where(flips, 1, df.loc[mask,"probe_loss"])

    # Recalculate rolling stats after modification
    df = df.sort_values(["slice","ts"])
    delta = pd.to_timedelta(freq).total_seconds()
    w5 = max(1,int(round(5/delta)))
    w30 = max(1,int(round(30/delta)))

    for sl in df["slice"].unique():
        idx = df["slice"] == sl
        df.loc[idx,"rx_rate_ma_5s"] = df.loc[idx,"rx_rate_bps"].rolling(w5,min_periods=1).mean().values
        df.loc[idx,"rx_rate_ma_30s"] = df.loc[idx,"rx_rate_bps"].rolling(w30,min_periods=1).mean().values
        df.loc[idx,"loss_5s"] = df.loc[idx,"probe_loss"].rolling(w5,min_periods=1).mean().values

    return df


# ============================================================
# DATASET
# ============================================================

class SliceDataset(Dataset):
    def __init__(self, df, feat_cols, target_col, seq_len, horizon):
        self.samples = []
        # Group by slice to create valid time sequences
        for sl, g in df.groupby("slice"):
            g = g.sort_values("ts").reset_index(drop=True)
            X = g[feat_cols].values.astype(np.float32)
            y = g[target_col].values.astype(np.float32)

            if len(g) < seq_len + horizon:
                continue

            # Sliding window
            for i in range(len(g) - seq_len - horizon + 1):
                self.samples.append(
                    (X[i:i+seq_len], y[i+seq_len:i+seq_len+horizon], sl)
                )

    def __len__(self): return len(self.samples)
    def __getitem__(self, idx):
        x,y,sl = self.samples[idx]
        return torch.tensor(x), torch.tensor(y), sl


# ============================================================
# MODEL (TCN)
# ============================================================

class Chomp1d(nn.Module):
    def __init__(self,ch): super().__init__(); self.c=ch
    def forward(self,x): return x[:,:,:-self.c]

class TempBlock(nn.Module):
    def __init__(self,in_ch,out_ch,kernel,dilation,drop):
        super().__init__()
        pad = (kernel-1)*dilation
        self.net = nn.Sequential(
            nn.Conv1d(in_ch,out_ch,kernel,padding=pad,dilation=dilation),
            Chomp1d(pad),
            nn.ReLU(),
            nn.Dropout(drop),
            nn.Conv1d(out_ch,out_ch,kernel,padding=pad,dilation=dilation),
            Chomp1d(pad),
            nn.ReLU(),
            nn.Dropout(drop)
        )
        self.down = nn.Conv1d(in_ch,out_ch,1) if in_ch!=out_ch else None

    def forward(self,x):
        out = self.net(x)
        res = x if self.down is None else self.down(x)
        return torch.relu(out + res)

class TCN(nn.Module):
    def __init__(self, input_size, output_size, channels, kernel, drop):
        super().__init__()
        layers=[]
        for i,ch in enumerate(channels):
            dil = 2**i
            in_ch = input_size if i==0 else channels[i-1]
            layers.append(TempBlock(in_ch,ch,kernel,dil,drop))
        self.tcn = nn.Sequential(*layers)
        self.fc = nn.Linear(channels[-1], output_size)

    def forward(self,x):
        x = x.permute(0,2,1) # [B, T, C] -> [B, C, T]
        y = self.tcn(x)
        return self.fc(y[:,:,-1])


# ============================================================
# TRAIN LOGIC
# ============================================================

def train_slice(df_tr, df_val, df_te, feat_cols, args, sl):
    ds_tr = SliceDataset(df_tr, feat_cols, "target", args.seq_len, args.horizon)
    ds_val = SliceDataset(df_val, feat_cols, "target", args.seq_len, args.horizon)
    ds_te = SliceDataset(df_te, feat_cols, "target", args.seq_len, args.horizon)

    if len(ds_tr)==0:
        print(f"[skip] slice {sl} has no training data")
        return None, None

    tr = DataLoader(ds_tr,batch_size=args.batch,shuffle=True)
    va = DataLoader(ds_val,batch_size=args.batch,shuffle=False)
    te = DataLoader(ds_te,batch_size=args.batch,shuffle=False)

    channels=[int(x) for x in args.num_channels.split(",")]

    model = TCN(
        input_size=len(feat_cols),
        output_size=args.horizon,
        channels=channels,
        kernel=args.kernel,
        drop=args.dropout
    ).to(args.device)

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr)
    loss_fn = nn.SmoothL1Loss()

    best=float("inf")
    best_path = os.path.join(args.outdir, f"best_{sl}.pt")
    
    no_improve=0

    for ep in range(1,args.epochs+1):
        model.train()
        losses=[]
        for X,Y,_ in tr:
            X,Y = X.to(args.device), Y.to(args.device)
            pred = model(X)
            if pred.dim()==1: pred = pred.view(-1, args.horizon)
            if Y.dim()==1: Y = Y.view(-1, args.horizon)
            loss = loss_fn(pred,Y)
            opt.zero_grad(); loss.backward(); opt.step()
            losses.append(loss.item())

        # val
        model.eval()
        vloss=[]
        with torch.no_grad():
            for X,Y,_ in va:
                X,Y = X.to(args.device), Y.to(args.device)
                pred = model(X)
                if pred.dim()==1: pred = pred.view(-1,args.horizon)
                if Y.dim()==1: Y = Y.view(-1,args.horizon)
                vloss.append(loss_fn(pred,Y).item())

        v = np.mean(vloss) if vloss else 0
        t_loss = np.mean(losses) if losses else 0
        
        if ep % 5 == 0 or ep == 1:
            print(f"[{sl} ep{ep}] train={t_loss:.4f} val={v:.4f}")

        if v < best:
            best = v
            torch.save(model.state_dict(), best_path)
            no_improve=0
        else:
            no_improve+=1

        if no_improve >= 10:
            print(f"[{sl}] Early stopping at ep {ep}")
            break

    # TEST
    model.load_state_dict(torch.load(best_path,map_location=args.device))
    model.eval()

    preds=[]
    with torch.no_grad():
        for X,Y,slc in te:
            pr = model(X.to(args.device)).cpu().numpy()
            tr = Y.numpy()
            for a,b in zip(pr,tr):
                preds.append((float(a[0]), float(b[0])))

    if not preds:
        return 0.0, 0.0

    pred_arr = np.array([p[0] for p in preds])
    true_arr = np.array([p[1] for p in preds])

    if args.target_log1p:
        pred_arr = np.expm1(pred_arr)
        true_arr = np.expm1(true_arr)

    mae = mean_absolute_error(true_arr,pred_arr)
    rmse = math.sqrt(mean_squared_error(true_arr,pred_arr))

    pd.DataFrame({"pred":pred_arr,"true":true_arr}).to_csv(
        os.path.join(args.outdir,f"preds_{sl}.csv"), index=False
    )

    print(f"[eval] slice={sl} MAE={mae:.2f} RMSE={rmse:.2f}")
    return mae, rmse

# ============================================================
# VISUALIZATION
# ============================================================

def visualize_results(outdir):
    print("\n" + "="*30)
    print(" Generating Visualizations")
    print("="*30)
    
    pred_files = glob.glob(os.path.join(outdir, "preds_*.csv"))
    if not pred_files:
        print("No prediction files found to visualize.")
        return

    # Use Seaborn/Matplotlib for plotting
    sns.set_theme(style="whitegrid")

    for p_file in pred_files:
        slice_name = os.path.basename(p_file).replace("preds_", "").replace(".csv", "")
        print(f"Plotting {slice_name}...")
        
        df = pd.read_csv(p_file)
        if len(df) < 5: continue
        
        r2 = r2_score(df['true'], df['pred'])
        mae = mean_absolute_error(df['true'], df['pred'])
        
        fig = plt.figure(figsize=(16, 8))
        gs = fig.add_gridspec(2, 2)

        # 1. Forecast Plot
        ax1 = fig.add_subplot(gs[0, :])
        n_view = min(400, len(df))
        ax1.plot(df['true'][:n_view], label='Actual', color='black', alpha=0.6)
        ax1.plot(df['pred'][:n_view], label='Predicted', color='dodgerblue', alpha=0.9)
        ax1.set_title(f"Forecast: {slice_name} (Sample)", fontsize=13)
        ax1.set_ylabel("Throughput (bps)")
        ax1.legend()

        # 2. Scatter
        ax2 = fig.add_subplot(gs[1, 0])
        sns.scatterplot(x=df['true'], y=df['pred'], ax=ax2, alpha=0.3, color='purple', s=20)
        min_v = min(df['true'].min(), df['pred'].min())
        max_v = max(df['true'].max(), df['pred'].max())
        ax2.plot([min_v, max_v], [min_v, max_v], 'r--', label='Ideal')
        ax2.set_title(f"Correlation (R2={r2:.2f})")
        ax2.set_xlabel("True")
        ax2.set_ylabel("Predicted")

        # 3. Residuals
        ax3 = fig.add_subplot(gs[1, 1])
        sns.histplot(df['true'] - df['pred'], kde=True, ax=ax3, color='orange', bins=30)
        ax3.axvline(0, color='red', linestyle='--')
        ax3.set_title(f"Error Dist (MAE={mae:.0f})")

        plt.tight_layout()
        save_path = os.path.join(outdir, f"vis_{slice_name}.png")
        plt.savefig(save_path)
        plt.close()
        print(f" -> Saved {save_path}")

# ============================================================
# MAIN
# ============================================================

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--outdir", required=True)
    p.add_argument("--freq", default="250ms")
    p.add_argument("--seq-len", type=int, default=64)
    p.add_argument("--horizon", type=int, default=1)
    p.add_argument("--batch", type=int, default=64)
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--kernel", type=int, default=3)
    p.add_argument("--dropout", type=float, default=0.1)
    p.add_argument("--num-channels", default="32,64,96")
    p.add_argument("--inject-congestion", action="store_true")
    p.add_argument("--cong-params", default=None)
    p.add_argument("--target-log1p", action="store_true")
    p.add_argument("--per-slice", action="store_true")
    p.add_argument("--per-slice-scale", action="store_true")
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = p.parse_args()

    set_seed()
    ensure_dir(args.outdir)

    print("[LOAD]", args.input)
    raw = pd.read_csv(args.input)
    print(f"Rows: {len(raw)}, Slices: {raw.slice.unique()}")

    processed = preprocess(raw, args.freq, args.inject_congestion, args.cong_params, args.outdir)

    feat_cols = [
        "rx_rate_bps","tx_rate_bps","latency_ms","jitter_ms",
        "rx_rate_ma_5s","rx_rate_ma_30s","loss_5s","slice_share"
    ]
    target="rx_rate_bps"

    if args.target_log1p:
        processed["target"]=np.log1p(processed[target])
    else:
        processed["target"]=processed[target]

    # Chronological Split
    ts_sorted = sorted(processed.ts.unique())
    n = len(ts_sorted)
    tr = set(ts_sorted[:int(0.7*n)])
    va = set(ts_sorted[int(0.7*n):int(0.85*n)])
    te = set(ts_sorted[int(0.85*n):])

    df_tr = processed[processed.ts.isin(tr)].copy()
    df_va = processed[processed.ts.isin(va)].copy()
    df_te = processed[processed.ts.isin(te)].copy()

    # Scaling & Training
    if args.per_slice:
        results=[]
        for sl in processed.slice.unique():
            print("\n" + "="*30)
            print(f" Training slice: {sl}")
            print("="*30)

            dtr = df_tr[df_tr.slice==sl].copy()
            dva = df_va[df_va.slice==sl].copy()
            dte = df_te[df_te.slice==sl].copy()

            if len(dtr) == 0:
                print(f"Skipping {sl}, not enough data.")
                continue

            if args.per_slice_scale:
                sc=StandardScaler()
                dtr[feat_cols]=sc.fit_transform(dtr[feat_cols])
                dva[feat_cols]=sc.transform(dva[feat_cols])
                dte[feat_cols]=sc.transform(dte[feat_cols])
            else:
                sc = StandardScaler()
                sc.fit(dtr[feat_cols])
                dtr[feat_cols]=sc.transform(dtr[feat_cols])
                dva[feat_cols]=sc.transform(dva[feat_cols])
                dte[feat_cols]=sc.transform(dte[feat_cols])

            mae,rmse = train_slice(dtr,dva,dte,feat_cols,args,sl)
            results.append({"slice":sl,"mae":mae,"rmse":rmse})

        pd.DataFrame(results).to_csv(os.path.join(args.outdir,"metrics_per_slice.csv"),index=False)
        print("\n[DONE] all per-slice models saved.")
        print(pd.DataFrame(results))
    
    # CALL VISUALIZATION FUNCTION
    visualize_results(args.outdir)

if __name__ == "__main__":
    main()
