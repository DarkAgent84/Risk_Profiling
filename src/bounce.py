"""
Bounce_Type: Categorizes every loan into the granular 8-category Bounce Type specification.

It is a descriptive label only — it does not change risk_score or risk_tier.

Categories:
-----------
  Never Bounced   0 bounces (clean repayment track record)
  Ever Bounced    1+ bounces (general / loans under 3 months old or missing vintage)
  Always Bounced  bounce rate >= config.ALWAYS_BOUNCED_RATE (60%+ of receipts)
  3 MOB           Disburse date + 3 month bounce
  4 MOB           Disburse date + 4 month bounce
  5 MOB           Disburse date + 5 month bounce
  6 MOB           Disburse date + 6 month bounce
  7+ MOB          Disburse date + 7+ month bounce

Priority Order:
---------------
  1. Never Bounced (0 bounces)
  2. Always Bounced (>=60% bounce rate)
  3. MOB Buckets (3 MOB, 4 MOB, 5 MOB, 6 MOB, 7+ MOB)
  4. Ever Bounced (bounced, fallback)
"""
import numpy as np
import pandas as pd

import config


def _months_between(start: pd.Series, end: pd.Series) -> pd.Series:
    """Whole calendar months from start to end (a month counts once the day-of-month is reached)."""
    months = (end.dt.year - start.dt.year) * 12 + (end.dt.month - start.dt.month)
    months = months - (end.dt.day < start.dt.day).astype(int)
    return months.clip(lower=0)


def _col_numeric(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(0)
    return pd.Series(0.0, index=df.index, dtype=float)


def _mob_bucket(m) -> str:
    """Map months-on-books integer to granular MOB bucket."""
    if pd.isna(m) or m < 3:
        return "Ever Bounced"
    if m == 3:
        return "3 MOB"
    if m == 4:
        return "4 MOB"
    if m == 5:
        return "5 MOB"
    if m == 6:
        return "6 MOB"
    return "7+ MOB"


def add_bounce_type(df: pd.DataFrame) -> pd.DataFrame:
    """Add the granular 8-category 'bounce_type' column to the dataframe."""
    df = df.copy()

    # Dates and Months on Books (MOB)
    today = pd.Timestamp.today().normalize()
    disbursal = pd.to_datetime(df.get("disbursal_date"), errors="coerce", dayfirst=True)
    cycle = pd.to_datetime(df.get("cycle_date"), errors="coerce", dayfirst=True).fillna(today)

    if disbursal.notna().any():
        mob = _months_between(disbursal, cycle)
    else:
        mob = pd.Series(np.nan, index=df.index)

    # Financial & collection bounce indicators
    c2 = _col_numeric(df, "charges_2")
    c3 = _col_numeric(df, "charges_3")
    c_pay = _col_numeric(df, "charges_payable")
    dpd = _col_numeric(df, "dpd")
    dues = _col_numeric(df, "total_dues")
    rejected_receipts = _col_numeric(df, "rejected_receipts")
    rejection_rate = _col_numeric(df, "rejection_rate")

    bkt = df["bucket_group"].astype(str).str.strip().str.lower() if "bucket_group" in df.columns else pd.Series("", index=df.index)
    has_collector = df["app_user_id"].notna() if "app_user_id" in df.columns else pd.Series(False, index=df.index)
    risk_type = df["risk_type"].astype(str).str.strip().str.lower() if "risk_type" in df.columns else pd.Series("", index=df.index)
    cust_type = df["customer_type"].astype(str).str.strip().str.lower() if "customer_type" in df.columns else pd.Series("", index=df.index)

    escalated_buckets = {"30-59", "60-89", "90+", "jan-29", "1-29"}

    # Bounced loan detection (combining MIS rejected receipts + SOA bounce indicators)
    has_bounced = (
        (rejected_receipts > 0)
        | (c2 > 0)
        | (c3 > 0)
        | (c_pay > 0)
        | (dpd > 0)
        | (dues > 0)
        | (bkt.isin(escalated_buckets))
        | has_collector
        | (risk_type.isin(["medium", "high"]))
        | (cust_type == "ever bounce")
    )

    # 1. Base: loans with 0 bounces get "Never Bounced"
    bounce_type = pd.Series("Never Bounced", index=df.index, dtype=object)

    # 2. Bounced loans: map to MOB bucket (3 MOB ... 7+ MOB, or Ever Bounced if <3 MOB)
    bounced_idx = df.index[has_bounced]
    bounce_type.loc[bounced_idx] = mob.loc[bounced_idx].map(_mob_bucket)

    # 3. Always Bounced: bounce/rejection rate >= 60% of receipts
    always_bounced_rate = getattr(config, "ALWAYS_BOUNCED_RATE", 0.60)
    always_bounced_mask = has_bounced & (rejection_rate >= always_bounced_rate) & (rejected_receipts > 0)
    bounce_type.loc[always_bounced_mask] = "Always Bounced"

    df["bounce_type"] = bounce_type
    return df
