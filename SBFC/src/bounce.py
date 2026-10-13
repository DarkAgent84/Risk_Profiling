"""
Bounce & customer categorisation (v2).

v2 change: the SOA's own 'risk_type' is no longer an input to has_bounced. In v1
it fed the predicted customer_type/bounce_type and then those were evaluated
against the SOA labels, which is circular and inflated agreement.
"""
import config
import numpy as np
import pandas as pd


def _months_between(start: pd.Series, end: pd.Series) -> pd.Series:
    months = (end.dt.year - start.dt.year) * 12 + (end.dt.month - start.dt.month)
    months = months - (end.dt.day < start.dt.day).astype(int)
    return months.clip(lower=0)


def _col_numeric(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(0)
    return pd.Series(0.0, index=df.index, dtype=float)


def add_bounce_type(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    today = pd.Timestamp.today().normalize()
    has_disbursal = "disbursal_date" in df.columns and df["disbursal_date"].notna().any()
    has_cycle = "cycle_date" in df.columns and df["cycle_date"].notna().any()
    has_emi_due = "emi_due_date" in df.columns and df["emi_due_date"].notna().any()

    disbursal = pd.to_datetime(df["disbursal_date"], errors="coerce", dayfirst=True) if has_disbursal else pd.Series(pd.NaT, index=df.index)
    cycle = pd.to_datetime(df["cycle_date"], errors="coerce", dayfirst=True).fillna(today) if has_cycle else pd.Series(today, index=df.index)
    emi_due = pd.to_datetime(df["emi_due_date"], errors="coerce", dayfirst=True) if has_emi_due else pd.Series(pd.NaT, index=df.index)

    mob = _months_between(disbursal, cycle) if has_disbursal else pd.Series(np.nan, index=df.index)

    c2, c3, c_pay = _col_numeric(df, "charges_2"), _col_numeric(df, "charges_3"), _col_numeric(df, "charges_payable")
    dpd = _col_numeric(df, "dpd")
    dues = _col_numeric(df, "overdue_dues") if "overdue_dues" in df.columns else _col_numeric(df, "total_dues")
    rejected_receipts = _col_numeric(df, "rejected_receipts")
    rejection_rate = _col_numeric(df, "rejection_rate")

    bkt = df["bucket_group"].astype(str).str.strip().str.lower() if "bucket_group" in df.columns else pd.Series("", index=df.index)
    has_collector_series = df["app_user_id"].notna() if "app_user_id" in df.columns else pd.Series(False, index=df.index)
    has_collector = pd.Series(False, index=df.index) if has_collector_series.mean() > 0.90 else has_collector_series
    product = df["product_name"].astype(str).str.upper() if "product_name" in df.columns else pd.Series("", index=df.index)

    escalated_buckets = {"30-59", "60-89", "90+", "jan-29", "1-29"}
    has_bounced = (
        (c2 > 0) | (c3 > 0) | (c_pay > 0) | (dpd > 0) | (dues > 0)
        | bkt.isin(escalated_buckets) | (rejected_receipts > 0) | has_collector
    )

    matured_flag = df["matured_overdue"] if "matured_overdue" in df.columns else pd.Series(False, index=df.index)
    matured_mask = (has_cycle & emi_due.notna() & cycle.notna() & (emi_due < cycle)) | matured_flag
    mob3_mask = has_disbursal & product.isin(["SMALL TICKET LAP", "HOME LOAN"]) & mob.isin([2, 3, 4, 5]) & (~matured_mask)
    ever_mask = has_bounced & (~matured_mask) & (~mob3_mask)

    cust = pd.Series("Never Bounce", index=df.index, dtype=object)
    cust[ever_mask] = "Ever Bounce"
    cust[mob3_mask] = "3 MOB"
    cust[matured_mask] = "Matured"
    if "customer_type" in df.columns and "soa_customer_type" not in df.columns:
        df["soa_customer_type"] = df["customer_type"]
    df["customer_type"] = cust

    b = pd.Series("Never Bounced", index=df.index, dtype=object)
    b[has_bounced] = "Ever Bounced"
    if has_disbursal:
        b[has_bounced & (mob >= config.MOB_TOP)] = "7+ MOB"
        for m in range(config.MOB_MIN, config.MOB_TOP):
            b[has_bounced & (mob == m)] = f"{m} MOB"
    # Require at least 2 receipts so one bounced receipt doesn't mean "always"
    b[(rejection_rate >= config.ALWAYS_BOUNCED_RATE) & (_col_numeric(df, "total_receipts") >= 2)] = "Always Bounced"
    df["bounce_type"] = b
    return df
