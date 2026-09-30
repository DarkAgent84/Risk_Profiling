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
    disbursal = pd.to_datetime(df.get("disbursal_date"), errors="coerce", dayfirst=True)
    cycle = pd.to_datetime(df.get("cycle_date"), errors="coerce", dayfirst=True).fillna(today)
    emi_due = pd.to_datetime(df.get("emi_due_date"), errors="coerce", dayfirst=True)

    if disbursal.notna().any():
        mob = _months_between(disbursal, cycle)
    else:
        mob = pd.Series(np.nan, index=df.index)

    # Financial & collection signals
    c2 = _col_numeric(df, "charges_2")
    c3 = _col_numeric(df, "charges_3")
    c_pay = _col_numeric(df, "charges_payable")
    dpd = _col_numeric(df, "dpd")
    dues = _col_numeric(df, "total_dues")
    rejected_receipts = _col_numeric(df, "rejected_receipts")
    rejection_rate = _col_numeric(df, "rejection_rate")

    bkt = df["bucket_group"].astype(str).str.strip().str.lower() if "bucket_group" in df.columns else pd.Series("", index=df.index)
    has_collector = df["app_user_id"].notna() if "app_user_id" in df.columns else pd.Series(False, index=df.index)
    product = df["product_name"].astype(str).str.upper() if "product_name" in df.columns else pd.Series("", index=df.index)
    risk_type = df["risk_type"].astype(str).str.strip().str.lower() if "risk_type" in df.columns else pd.Series("", index=df.index)

    # Evidence of any bounce history
    escalated_buckets = {"30-59", "60-89", "90+", "jan-29", "1-29"}
    raw_cust_type = df["customer_type"].astype(str).str.strip().str.lower() if "customer_type" in df.columns else pd.Series("", index=df.index)

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
        | (raw_cust_type == "ever bounce")
    )

    # ---------------------------------------------------------
    # 1. customer_type (4-class Banking Benchmark)
    # ---------------------------------------------------------
    matured_flag = df.get("matured_overdue", pd.Series(False, index=df.index))
    matured_mask = (emi_due.notna() & cycle.notna() & (emi_due < cycle)) | matured_flag
    mob3_mask = product.isin(["SMALL TICKET LAP", "HOME LOAN"]) & mob.isin([2, 3, 4, 5]) & (~matured_mask)
    ever_mask = has_bounced & (~matured_mask) & (~mob3_mask)

    cust_type_pred = pd.Series("Never Bounce", index=df.index, dtype=object)
    cust_type_pred[ever_mask] = "Ever Bounce"
    cust_type_pred[mob3_mask] = "3 MOB"
    cust_type_pred[matured_mask] = "Matured"

    if "customer_type" in df.columns and df["customer_type"].notna().any():
        df["customer_type"] = df["customer_type"].fillna(cust_type_pred)
    else:
        df["customer_type"] = cust_type_pred

    # ---------------------------------------------------------
    # 2. bounce_type (8-class Granular Specification)
    # ---------------------------------------------------------
    bounce_granular = pd.Series("Never Bounced", index=df.index, dtype=object)
    bounce_granular[has_bounced] = "Ever Bounced"
    bounce_granular[has_bounced & (mob >= 7)] = "7+ MOB"
    bounce_granular[has_bounced & (mob == 6)] = "6 MOB"
    bounce_granular[has_bounced & (mob == 5)] = "5 MOB"
    bounce_granular[has_bounced & (mob == 4)] = "4 MOB"
    bounce_granular[has_bounced & (mob == 3)] = "3 MOB"
    bounce_granular[rejection_rate >= config.ALWAYS_BOUNCED_RATE] = "Always Bounced"

    df["bounce_type"] = bounce_granular
    return df


