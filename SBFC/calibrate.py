"""
Calibration: tune scoring parameters to maximise agreement with the legacy SOA
'Risk Type' label. Run from inside FEDBANK/ or SBFC/:

    python calibrate.py                       # auto-discover files, search, report
    python calibrate.py --apply               # also write calibrated_params.json
    python calibrate.py --iters 3000 --seed 7

Method: random search + coordinate refinement over bucket base scores, weights,
cutoffs and the NPA floor. Objective = macro-F1 over High/Medium/Low (not raw
accuracy, so a rare High class isn't ignored), with a small dues-weighted
accuracy term. Fit on 70% of loans, report on a held-out 30%.

Caveat: this measures agreement with the legacy label, not true default risk.
If the legacy label is itself rule-based on bucket/DPD, a high score is
expected; if it's judgement-based, expect a ceiling below 100%.
"""
import argparse
import copy
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import numpy as np
import pandas as pd

import config
from src.features import build_behavior_features
from src.ingest import find_raw_files, load_datasets, normalize_column_name
from src.scoring import DEFAULTS, PARAMS_FILE, apply_score, build_frame

TIERS = ["High", "Medium", "Low"]


def macro_f1(y_true: pd.Series, y_pred: pd.Series) -> float:
    f1s = []
    for t in TIERS:
        tp = ((y_true == t) & (y_pred == t)).sum()
        fp = ((y_true != t) & (y_pred == t)).sum()
        fn = ((y_true == t) & (y_pred != t)).sum()
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * p * r / (p + r) if p + r else 0.0)
    return float(np.mean(f1s))


def objective(df, params, y, w):
    pred = apply_score(df, params)["risk_tier"]
    acc_w = float(((pred == y) * w).sum() / w.sum())
    return 0.85 * macro_f1(y, pred) + 0.15 * acc_w


def propose(rng, base, npa_high=True):
    p = copy.deepcopy(base)
    bb = p["bucket_base"]
    keys = ["0", "1-29", "30-59", "60-89", "90+"]
    vals = np.sort(np.clip([bb[k] + rng.normal(0, 0.06) for k in keys], 0.0, 1.0))
    p["bucket_base"] = {k: float(round(v, 3)) for k, v in zip(keys, vals)}  # keep monotonic
    for k, s in [("w_dpd", 0.04), ("w_dues", 0.04), ("w_beh", 0.04), ("bucket0_overdue_score", 0.06)]:
        p[k] = float(np.clip(p[k] + rng.normal(0, s), 0.0, 0.4 if k != "bucket0_overdue_score" else 0.9))
    p["w_ev"] = float(np.clip(p["w_ev"] + rng.normal(0, 0.06), 0.0, 0.9))
    for k in ["e_coll", "e_c3", "e_c2", "e_cp"]:
        p[k] = float(np.clip(p[k] + rng.normal(0, 0.06), 0.01, 1.0))
    p["npa_floor"] = float(np.clip(p["npa_floor"] + rng.normal(0, 0.05), 0.3, 1.0))
    hi = float(np.clip(p["high_cut"] + rng.normal(0, 0.05), 0.3, 0.95))
    me = float(np.clip(p["med_cut"] + rng.normal(0, 0.05), 0.05, hi - 0.05))
    p["high_cut"], p["med_cut"] = round(hi, 3), round(me, 3)
    if npa_high:  # policy guard: NPA (DPD>=threshold / matured) must always land in High
        p["npa_floor"] = float(max(p["npa_floor"], p["high_cut"] + 0.001))
    return p


def load_labels(soa_path):
    soa = pd.read_csv(soa_path, low_memory=False)
    soa.columns = [normalize_column_name(c) for c in soa.columns]
    if "risk_type" not in soa.columns:
        sys.exit("SOA file has no 'Risk Type' column — nothing to calibrate against.")
    soa["loan_number"] = soa["loan_number"].astype(str).str.strip()
    soa = soa.drop_duplicates("loan_number")
    soa["risk_type"] = soa["risk_type"].astype(str).str.strip().str.title()
    return soa.loc[soa["risk_type"].isin(TIERS), ["loan_number", "risk_type"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--soa"), ap.add_argument("--mis")
    ap.add_argument("--iters", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--allow-npa-downgrade", action="store_true",
                    help="let calibration place NPA loans below High (matches legacy labels, weakens policy)")
    a = ap.parse_args()

    soa_path, mis_path = a.soa, a.mis
    if not soa_path or not mis_path:
        d_soa, d_mis = find_raw_files(None)
        soa_path, mis_path = soa_path or d_soa, mis_path or d_mis
    if not soa_path or not mis_path:
        sys.exit("Could not find SOA/MIS files; pass --soa and --mis.")

    labels = load_labels(soa_path)
    soa, mis = load_datasets(soa_path, mis_path)
    df = build_frame(soa, build_behavior_features(mis))
    df = df.drop(columns=["risk_type"], errors="ignore").merge(labels, on="loan_number", how="inner")
    print(f"Labelled loans: {len(df):,}\nLabel mix:\n{df['risk_type'].value_counts(normalize=True).round(3)}\n")

    rng = np.random.default_rng(a.seed)
    idx = rng.permutation(len(df))
    cut = int(len(df) * 0.7)
    train, test = df.iloc[idx[:cut]].reset_index(drop=True), df.iloc[idx[cut:]].reset_index(drop=True)
    w_tr = np.maximum(train["total_dues"].values, 1.0)
    w_te = np.maximum(test["total_dues"].values, 1.0)

    base = copy.deepcopy(DEFAULTS)
    best, best_s = base, objective(train, base, train["risk_type"], w_tr)
    start_s = best_s
    for i in range(a.iters):
        cand = propose(rng, best, not a.allow_npa_downgrade)
        s = objective(train, cand, train["risk_type"], w_tr)
        if s > best_s:
            best, best_s = cand, s
    print(f"Train objective: {start_s:.4f} -> {best_s:.4f}")

    for name, params in [("defaults", DEFAULTS), ("calibrated", best)]:
        pred = apply_score(test, params)["risk_tier"]
        acc = (pred == test["risk_type"]).mean()
        print(f"\n[{name}] held-out accuracy {acc*100:.2f}% | macro-F1 {macro_f1(test['risk_type'], pred):.4f}")
        print(pd.crosstab(test["risk_type"], pred, margins=True))

    print("\nBest parameters:\n" + json.dumps(best, indent=2))
    if a.apply:
        PARAMS_FILE.write_text(json.dumps(best, indent=2))
        print(f"\n[OK] Wrote {PARAMS_FILE}")
    else:
        print("\n(Re-run with --apply to save these as calibrated_params.json)")


if __name__ == "__main__":
    main()
