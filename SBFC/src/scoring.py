"""
Risk scoring engine (v2) — identical for FEDBANK and SBFC.

What changed vs v1 (accuracy fixes):
  * Severity is monotonic: current < 1-29 < 30-59 < 60-89 < 90+. In v1 a current
    loan with any small charge scored 0.70 (High) while a 1-29 DPD loan was Medium.
  * Bucket and DPD are combined (max), so loans with DPD>0 but a missing/odd
    bucket label are no longer treated as current.
  * Duplicate loan numbers in the SOA are dropped (v1 double-counted dues).
  * Fully vectorised (no row-wise apply) so it can be tuned by calibrate.py.
  * Every number lives in DEFAULTS and can be overridden by
    <bank>/calibrated_params.json (written by calibrate.py) — no code edits needed.
"""
import json

import config
import numpy as np
import pandas as pd

from src.bounce import add_bounce_type
from src.matured import add_matured_overdue

PARAMS_FILE = config.BASE_DIR / "calibrated_params.json"

DEFAULTS = {
    # base score per delinquency bucket (must be non-decreasing)
    "bucket_base": {"0": 0.05, "1-29": 0.30, "30-59": 0.50, "60-89": 0.65, "90+": 0.80},
    "w_dpd": 0.10,    # extra score for DPD severity (0-1 normalised)
    "w_dues": 0.08,   # extra score for overdue-dues exposure (log-normalised)
    "w_beh": 0.07,    # extra score for rejection / partial-payment friction
    "bucket0_overdue_score": 0.30,  # current bucket but carrying overdue dues/charges
    # Bounce-history evidence (collector assignment + bounce/penal charges).
    # Strong separator of the legacy High/Low labels; tuned by calibrate.py.
    "w_ev": 0.30,
    "e_coll": 0.40, "e_c3": 0.25, "e_c2": 0.20, "e_cp": 0.15,
    "npa_dpd": config.NPA_DPD_THRESHOLD,
    "npa_floor": config.NPA_FLOOR_SCORE,
    "high_cut": config.TIER_HIGH_CUTOFF,
    "med_cut": config.TIER_MEDIUM_CUTOFF,
    "dpd_cap": config.DPD_CAP_CEILING,
}


def load_params(overrides: dict | None = None) -> dict:
    """DEFAULTS < calibrated_params.json < explicit overrides."""
    params = json.loads(json.dumps(DEFAULTS))  # deep copy
    if PARAMS_FILE.exists():
        params.update(json.loads(PARAMS_FILE.read_text()))
    if overrides:
        params.update(overrides)
    return params


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return pd.Series(0.0, index=df.index)


def tier_from_score(score: pd.Series, high_cut: float, med_cut: float) -> pd.Series:
    return pd.Series(
        np.select([score >= high_cut, score >= med_cut], ["High", "Medium"], default="Low"),
        index=score.index,
    )


def build_frame(soa: pd.DataFrame, behavior: pd.DataFrame) -> pd.DataFrame:
    """Merge SOA + behaviour features and add parameter-independent columns."""
    n_dup = int(soa["loan_number"].duplicated().sum())
    if n_dup:
        print(f"-> Dropping {n_dup:,} duplicate SOA loan_number row(s) (keeping first)")
        soa = soa.drop_duplicates("loan_number", keep="first")

    overlap = [c for c in behavior.columns if c in soa.columns and c != "loan_number"]
    df = (soa.drop(columns=overlap) if overlap else soa).merge(behavior, on="loan_number", how="left")

    df["never_worked"] = df["total_receipts"].isna()
    df["total_receipts"] = df["total_receipts"].fillna(0).astype(int)
    df["rejected_receipts"] = df["rejected_receipts"].fillna(0).astype(int)
    df["rejection_rate"] = df["rejection_rate"].fillna(0.0).round(4)
    df["partial_payment_rate"] = df["partial_payment_rate"].fillna(0.0).round(4)
    if "total_collected" in df.columns:
        df["total_collected"] = df["total_collected"].fillna(0.0)

    return add_matured_overdue(df)


def apply_score(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    """Compute risk_score / risk_tier from a frame made by build_frame()."""
    p = load_params(params)
    df = df.copy()
    bb = {k.lower(): float(v) for k, v in p["bucket_base"].items()}

    dpd = _num(df, "dpd")
    dues_col = "overdue_dues" if "overdue_dues" in df.columns else "total_dues"
    dues = _num(df, dues_col).clip(lower=0)

    # --- severity from bucket label AND dpd; take the worse of the two
    if "bucket_group" in df.columns:
        grp = df["bucket_group"].astype(str).str.strip().str.lower().replace({"jan-29": "1-29"})
        base_bucket = grp.map(bb).fillna(bb["0"])
    else:
        base_bucket = pd.Series(bb["0"], index=df.index)
    base_dpd = np.select(
        [dpd <= 0, dpd < 30, dpd < 60, dpd < 90],
        [bb["0"], bb["1-29"], bb["30-59"], bb["60-89"]],
        default=bb["90+"],
    )
    base = np.maximum(base_bucket.values, base_dpd)
    delinquent = base > bb["0"]

    # --- normalised drivers
    dpd_norm = np.clip(dpd / float(p["dpd_cap"]), 0.0, 1.0)
    max_dues = dues.max()
    dues_norm = np.log1p(dues) / (np.log1p(max_dues) if max_dues > 0 else 1.0)

    worked_beh = (
        config.BEHAVIOR_REJECTION_WEIGHT * df["rejection_rate"]
        + config.BEHAVIOR_PARTIAL_WEIGHT * df["partial_payment_rate"]
    )
    beh = np.where(df["never_worked"], np.where(dpd > 0, config.UNWORKED_OVERDUE_PENALTY, 0.0), worked_beh)

    has_charge = (_num(df, "charges_payable") > 0) | (_num(df, "charges_2") > 0)
    overdue_flag = (dues > 0) | has_charge

    # bounce-history evidence in [0, 1]; collector flag ignored if assigned to >90% of loans
    coll = df["app_user_id"].notna() if "app_user_id" in df.columns else pd.Series(False, index=df.index)
    coll = coll.values if coll.mean() <= 0.90 else np.zeros(len(df), dtype=bool)
    ev_raw = (p["e_coll"] * coll + p["e_c3"] * (_num(df, "charges_3") > 0)
              + p["e_c2"] * (_num(df, "charges_2") > 0) + p["e_cp"] * (_num(df, "charges_payable") > 0))
    ev = np.clip(ev_raw / max(p["e_coll"] + p["e_c3"] + p["e_c2"] + p["e_cp"], 1e-9), 0.0, 1.0)

    score = np.where(
        delinquent,
        base + p["w_dpd"] * dpd_norm + p["w_dues"] * dues_norm + p["w_beh"] * beh,
        np.where(overdue_flag, p["bucket0_overdue_score"] + p["w_dues"] * dues_norm, base),
    ) + p["w_ev"] * ev
    score = np.clip(score, 0.0, 1.0)

    # --- NPA floor: DPD >= threshold OR matured_overdue
    matured = df["matured_overdue"] if "matured_overdue" in df.columns else False
    npa_hit = (dpd >= p["npa_dpd"]) | matured
    score = np.where(npa_hit, np.maximum(score, p["npa_floor"]), score)

    df["dpd_norm"], df["dues_norm"], df["behavior_score"] = dpd_norm, dues_norm, beh
    df["risk_score"] = np.round(score, 3)
    df["risk_tier"] = tier_from_score(df["risk_score"], p["high_cut"], p["med_cut"])
    return df


def score_portfolio(soa: pd.DataFrame, behavior: pd.DataFrame, dpd_cap: float | None = None,
                    params: dict | None = None, with_labels: bool = True) -> pd.DataFrame:
    """Full pipeline entry point (signature kept compatible with v1)."""
    overrides = dict(params or {})
    if dpd_cap is not None:
        overrides.setdefault("dpd_cap", dpd_cap)
    df = apply_score(build_frame(soa, behavior), overrides)
    return add_bounce_type(df) if with_labels else df
