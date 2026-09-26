"""
Risk scoring engine.

Design:
  1. Every loan gets a raw 0-1 risk score from ONE uniform bucket/DPD
     escalation rule — there is no per-customer-type branching. The same
     rule that used to apply only to "Ever Bounce" accounts now applies to
     every loan, since customer_type is no longer used as an input anywhere
     in this pipeline (removed from scoring, ingestion, and output).
  2. An NPA safety floor is applied: any loan at/beyond NPA_DPD_THRESHOLD
     days-past-due is floored at NPA_FLOOR_SCORE, no matter what the raw
     rule produced. There's no early-vintage exemption any more — that
     concept came from customer_type == "3 MOB", which no longer exists as
     a signal, so every loan is judged purely on bucket/DPD/dues/behavior.
  3. The tier label (High / Medium / Low) is derived from the FINAL score
     using config.TIER_HIGH_CUTOFF / TIER_MEDIUM_CUTOFF. Tier labels are
     never hardcoded next to a score value — this is the one place tiers
     are decided, so config changes actually change output.
"""
import numpy as np
import pandas as pd

import config

ESCALATED_BUCKETS = {"30-59", "60-89", "90+"} | config.EARLY_BUCKET_ALIASES


def _raw_score(row: pd.Series) -> float:
    """Uniform bucket/DPD escalation rule, applied the same way to every loan."""
    bkt = str(row.get("bucket_group", "")).strip().lower()
    dpd = float(row.get("dpd", 0) or 0)
    dues = float(row.get("total_dues", 0) or 0)
    charges = float(row.get("charges_payable", 0) or 0)
    charges2 = float(row.get("charges_2", 0) or 0)
    receipts = float(row.get("total_receipts", 0) or 0)
    beh_score = float(row.get("behavior_score", 0) or 0)
    dpd_norm = float(row.get("dpd_norm", 0) or 0)
    dues_norm = float(row.get("dues_norm", 0) or 0)

    # 1. Delinquent bucket, or any positive DPD: escalate.
    if bkt in ESCALATED_BUCKETS or dpd > 0:
        score = max(0.70, 0.40 + 0.30 * dpd_norm + 0.15 * dues_norm + 0.15 * beh_score)
        return min(score, 1.0)

    # 2. Bucket 0 (current) but still carrying dues/charges/receipt activity.
    if dues > 0 or charges > 0 or receipts > 0 or charges2 > 0:
        return 0.70

    # 3. Clean: bucket 0, nothing owed, no activity.
    return 0.05


def _tier_from_score(score: float) -> str:
    if score >= config.TIER_HIGH_CUTOFF:
        return "High"
    if score >= config.TIER_MEDIUM_CUTOFF:
        return "Medium"
    return "Low"


def score_portfolio(soa: pd.DataFrame, behavior: pd.DataFrame, dpd_cap: float = config.DPD_CAP_CEILING) -> pd.DataFrame:
    """Merge SOA + behavior features and compute calibrated risk scores and tiers."""
    overlap_cols = [c for c in behavior.columns if c in soa.columns and c != "loan_number"]
    soa_clean = soa.drop(columns=overlap_cols) if overlap_cols else soa
    df = soa_clean.merge(behavior, on="loan_number", how="left")

    df["never_worked"] = df["total_receipts"].isna()
    df["total_receipts"] = df["total_receipts"].fillna(0).astype(int)
    df["rejected_receipts"] = df["rejected_receipts"].fillna(0).astype(int)
    df["rejection_rate"] = df["rejection_rate"].fillna(0.0).round(4)
    df["partial_payment_rate"] = df["partial_payment_rate"].fillna(0.0).round(4)
    if "total_collected" in df.columns:
        df["total_collected"] = df["total_collected"].fillna(0.0)

    # Normalization
    df["dpd_norm"] = np.clip(df["dpd"] / float(dpd_cap), 0.0, 1.0)
    max_dues = df["total_dues"].max()
    max_log_dues = np.log1p(max_dues) if max_dues > 0 else 1.0
    df["dues_norm"] = np.log1p(np.maximum(0, df["total_dues"])) / max_log_dues

    # Behavioral friction
    worked_behavior = (
        config.BEHAVIOR_REJECTION_WEIGHT * df["rejection_rate"]
        + config.BEHAVIOR_PARTIAL_WEIGHT * df["partial_payment_rate"]
    )
    df["behavior_score"] = np.where(
        df["never_worked"],
        np.where(df["dpd"] > 0, config.UNWORKED_OVERDUE_PENALTY, 0.0),
        worked_behavior,
    )

    # Raw bucket/DPD escalation score — same rule for every loan
    df["risk_score"] = df.apply(_raw_score, axis=1)

    # NPA floor: enforced here, applies to every loan uniformly
    npa_hit = df["dpd"] >= config.NPA_DPD_THRESHOLD
    df["risk_score"] = np.where(npa_hit, np.maximum(df["risk_score"], config.NPA_FLOOR_SCORE), df["risk_score"])
    df["risk_score"] = df["risk_score"].round(3)

    # Tier derived from final score, using config cutoffs
    df["risk_tier"] = df["risk_score"].apply(_tier_from_score)

    return df
