"""
Bounce & Customer Categorization:
Provides dual classification columns for collections risk analysis:

1. customer_type (4-class banking benchmark):
   - Never Bounce: Clean repayment history, 0 bounces, current bucket
   - Ever Bounce:  1+ historical bounces (bounce charges, delinquency, rejections)
   - Matured:      Contractual loan tenure lapsed (emi_due_date < cycle_date)
   - 3 MOB:        Early vintage loans (months on books 2-5 on STL / Home Loan)

2. bounce_type (8-class granular specification):
   - Never Bounced: 0 bounces (clean record)
   - Always Bounced: >=60% rejection/bounce rate on receipts
   - 3 MOB:         Bounced account at 3 months post-disbursal
   - 4 MOB:         Bounced account at 4 months post-disbursal
   - 5 MOB:         Bounced account at 5 months post-disbursal
   - 6 MOB:         Bounced account at 6 months post-disbursal
   - 7+ MOB:        Bounced account at 7+ months post-disbursal
   - Ever Bounced:  1+ bounces fallback (under 3 months old or general)
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


def add_bounce_type(df: pd.DataFrame) -> pd.DataFrame:
    """Add dual classification columns: 'customer_type' (4-class) and 'bounce_type' (8-class granular)."""
    df = df.copy()

    # Dates and Months on Books (MOB)
    today = pd.Timestamp.today().normalize()
    has_disbursal = "disbursal_date" in df.columns and df["disbursal_date"].notna().any()
    has_cycle = "cycle_date" in df.columns and df["cycle_date"].notna().any()
    has_emi_due = "emi_due_date" in df.columns and df["emi_due_date"].notna().any()

    disbursal = pd.to_datetime(df["disbursal_date"], errors="coerce", dayfirst=True) if has_disbursal else pd.Series(pd.NaT, index=df.index)
    cycle = pd.to_datetime(df["cycle_date"], errors="coerce", dayfirst=True).fillna(today) if has_cycle else pd.Series(today, index=df.index)
    emi_due = pd.to_datetime(df["emi_due_date"], errors="coerce", dayfirst=True) if has_emi_due else pd.Series(pd.NaT, index=df.index)

    if has_disbursal and disbursal.notna().any():
        mob = _months_between(disbursal, cycle)
    else:
        mob = pd.Series(np.nan, index=df.index)

    # Financial & collection signals
    c2 = _col_numeric(df, "charges_2")
    c3 = _col_numeric(df, "charges_3")
    c_pay = _col_numeric(df, "charges_payable")
    dpd = _col_numeric(df, "dpd")
    dues = _col_numeric(df, "overdue_dues") if "overdue_dues" in df.columns else _col_numeric(df, "total_dues")
    rejected_receipts = _col_numeric(df, "rejected_receipts")
    rejection_rate = _col_numeric(df, "rejection_rate")

    bkt = df["bucket_group"].astype(str).str.strip().str.lower() if "bucket_group" in df.columns else pd.Series("", index=df.index)
    has_collector_series = df["app_user_id"].notna() if "app_user_id" in df.columns else pd.Series(False, index=df.index)
    # If app_user_id is universally populated across the portfolio (>90%), it represents branch/agent assignment,
    # not a collection referral for default. Only treat as collection escalation when assigned to a minority subset.
    has_collector = pd.Series(False, index=df.index) if has_collector_series.mean() > 0.90 else has_collector_series
    product = df["product_name"].astype(str).str.upper() if "product_name" in df.columns else pd.Series("", index=df.index)
    risk_type = df["risk_type"].astype(str).str.strip().str.lower() if "risk_type" in df.columns else pd.Series("", index=df.index)

    # Evidence of any bounce history (purely computed from financial, collection, and delinquency signals)
    escalated_buckets = {"30-59", "60-89", "90+", "jan-29", "1-29"}

    has_bounced = (
        (c2 > 0)
        | (c3 > 0)
        | (c_pay > 0)
        | (dpd > 0)
        | (dues > 0)
        | (bkt.isin(escalated_buckets))
        | (rejected_receipts > 0)
        | has_collector
        | (risk_type.isin(["medium", "high"]))
    )

    # ---------------------------------------------------------
    # 1. customer_type (4-class Banking Benchmark - Algorithmic)
    # ---------------------------------------------------------
    matured_flag = df.get("matured_overdue", pd.Series(False, index=df.index))
    matured_mask = (has_cycle & emi_due.notna() & cycle.notna() & (emi_due < cycle)) | matured_flag
    mob3_mask = has_disbursal & product.isin(["SMALL TICKET LAP", "HOME LOAN"]) & mob.isin([2, 3, 4, 5]) & (~matured_mask)
    ever_mask = has_bounced & (~matured_mask) & (~mob3_mask)

    cust_type_pred = pd.Series("Never Bounce", index=df.index, dtype=object)
    cust_type_pred[ever_mask] = "Ever Bounce"
    cust_type_pred[mob3_mask] = "3 MOB"
    cust_type_pred[matured_mask] = "Matured"

    # Retain raw label as soa_customer_type for audit/comparison, assign prediction to customer_type
    if "customer_type" in df.columns and "soa_customer_type" not in df.columns:
        df["soa_customer_type"] = df["customer_type"]
    df["customer_type"] = cust_type_pred

    # ---------------------------------------------------------
    # 2. bounce_type (8-class Granular Specification - Algorithmic)
    # ---------------------------------------------------------
    bounce_granular = pd.Series("Never Bounced", index=df.index, dtype=object)
    bounce_granular[has_bounced] = "Ever Bounced"
    if has_disbursal:
        bounce_granular[has_bounced & (mob >= 7)] = "7+ MOB"
        bounce_granular[has_bounced & (mob == 6)] = "6 MOB"
        bounce_granular[has_bounced & (mob == 5)] = "5 MOB"
        bounce_granular[has_bounced & (mob == 4)] = "4 MOB"
        bounce_granular[has_bounced & (mob == 3)] = "3 MOB"
    bounce_granular[rejection_rate >= config.ALWAYS_BOUNCED_RATE] = "Always Bounced"

    df["bounce_type"] = bounce_granular
    return df


