#!/usr/bin/env python3
import pandas as pd
import numpy as np
import argparse
import os

def load_df(path):
    df = pd.read_csv(path)
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.sort_values(["slice", "ts"]).reset_index(drop=True)
    return df

def safe_clean(df):
    print("[clean] initial rows:", len(df))

    # -------------------------
    # 1. Remove rows with tun_exists == 0
    # -------------------------
    if "tun_exists" in df.columns:
        df = df[df["tun_exists"] == 1].copy()
        print("[clean] after tun filter:", len(df))

    # -------------------------
    # 2. Remove negative or nan throughput
    # -------------------------
    df["rx_rate_bps"] = pd.to_numeric(df["rx_rate_bps"], errors="coerce")
    df = df[df["rx_rate_bps"].notna()]
    df = df[df["rx_rate_bps"] >= 0]
    print("[clean] after removing invalid rx_rate:", len(df))

    # -------------------------
    # 3. Remove isolated 0-drops (1-frame artifacts)
    # -------------------------
    df["prev"] = df.groupby("slice")["rx_rate_bps"].shift(1)
    df["next"] = df.groupby("slice")["rx_rate_bps"].shift(-1)

    artifact_mask = (
        (df["rx_rate_bps"] < 500) &
        (df["prev"] > 3000) &
        (df["next"] > 3000)
    )

    print("[clean] isolated artifacts removed:", artifact_mask.sum())

    df = df[~artifact_mask].copy()

    df.drop(columns=["prev", "next"], inplace=True, errors="ignore")

    # -------------------------
    # 4. Remove insane spikes (> 5 × median of slice)
    # -------------------------
    med = df.groupby("slice")["rx_rate_bps"].transform("median")
    spike_mask = df["rx_rate_bps"] > (5 * med)

    print("[clean] spike rows removed:", spike_mask.sum())

    df = df[~spike_mask].copy()

    # -------------------------
    # 5. Remove timestamp duplicates
    # -------------------------
    df = df.drop_duplicates(subset=["slice", "ts"])

    # -------------------------
    # 6. Final sorting
    # -------------------------
    df = df.sort_values(["slice", "ts"]).reset_index(drop=True)

    print("[clean] final rows:", len(df))
    return df


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    df = load_df(args.input)
    cleaned = safe_clean(df)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    cleaned.to_csv(args.out, index=False)
    print("[clean] saved cleaned file:", args.out)


if __name__ == "__main__":
    main()

