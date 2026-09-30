"""
Bounce_Type: Categorizes every loan by its bounce and vintage profile.

It is a descriptive label only — it does not change risk_score or risk_tier.

Categories (matching Customer Type taxonomy):
---------------------------------------------
  Never Bounce   0 bounces, clean payment history, current bucket, no bounce fees
  Ever Bounce    1+ historical bounces (bounce charges, overdue DPD/bucket, rejected receipts)
  Matured        Contractual tenure has lapsed (emi_due_date < cycle_date or matured_overdue)
  3 MOB          Early vintage loan (months on books 2-5 on STL / HL products)
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
    """Add the single 'bounce_type' column classifying loans into Never Bounce, Ever Bounce, Matured, 3 MOB."""
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

    bkt = df["bucket_group"].astype(str).str.strip().str.lower() if "bucket_group" in df.columns else pd.Series("", index=df.index)
    has_collector = df["app_user_id"].notna() if "app_user_id" in df.columns else pd.Series(False, index=df.index)
    product = df["product_name"].astype(str).str.upper() if "product_name" in df.columns else pd.Series("", index=df.index)
    risk_type = df["risk_type"].astype(str).str.strip().str.lower() if "risk_type" in df.columns else pd.Series("", index=df.index)

    # 1. Matured: contractual tenure has lapsed or loan flagged matured_overdue
    matured_flag = df.get("matured_overdue", pd.Series(False, index=df.index))
    matured_mask = (emi_due.notna() & cycle.notna() & (emi_due < cycle)) | matured_flag

    # 2. 3 MOB: early-vintage accounts (months on books 2-5 on STL / Home Loan products)
    mob_mask = product.isin(["SMALL TICKET LAP", "HOME LOAN"]) & mob.isin([2, 3, 4, 5]) & (~matured_mask)

    # 3. Ever Bounce: evidence of bounce charges, delinquency, rejections, or high/medium legacy risk
    escalated_buckets = {"30-59", "60-89", "90+", "jan-29", "1-29"}
    ever_mask = (
        (c2 > 0)
        | (c3 > 0)
        | (c_pay > 0)
        | (dpd > 0)
        | (dues > 0)
        | (bkt.isin(escalated_buckets))
        | (rejected_receipts > 0)
        | has_collector
        | (risk_type.isin(["medium", "high"]))
    ) & (~matured_mask) & (~mob_mask)

    bounce_type = pd.Series("Never Bounce", index=df.index, dtype=object)
    bounce_type[ever_mask] = "Ever Bounce"
    bounce_type[mob_mask] = "3 MOB"
    bounce_type[matured_mask] = "Matured"

    df["bounce_type"] = bounce_type
    return df

