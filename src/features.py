"""
Behavioral features: aggregate per-transaction MIS receipts into per-loan stats.
"""
import pandas as pd

import config


def build_behavior_features(mis: pd.DataFrame) -> pd.DataFrame:
    """One row per loan_number: total receipts, rejection rate, partial-payment rate, etc."""
    mis = mis.copy()

    status = mis["instrument_status"].astype(str).str.strip().str.lower()
    ptype = mis["payment_type"].astype(str).str.strip().str.lower()

    pattern = "|".join(config.REJECTED_STATUS_KEYWORDS)
    mis["is_rejected"] = status.str.contains(pattern, regex=True).astype(int)
    mis["is_partial"] = (ptype == config.PARTIAL_PAYMENT_KEYWORD).astype(int)

    agg = {"is_rejected": ["count", "sum", "mean"], "is_partial": "mean"}
    if "total_amount_collected" in mis.columns:
        agg["total_amount_collected"] = "sum"
    if "payment_date" in mis.columns:
        agg["payment_date"] = "max"

    grouped = mis.groupby("loan_number").agg(agg)
    grouped.columns = ["_".join(c).strip("_") if isinstance(c, tuple) else c for c in grouped.columns]

    grouped = grouped.rename(columns={
        "is_rejected_count": "total_receipts",
        "is_rejected_sum": "rejected_receipts",
        "is_rejected_mean": "rejection_rate",
        "is_partial_mean": "partial_payment_rate",
        "total_amount_collected_sum": "total_collected",
        "payment_date_max": "last_payment_date",
    })
    return grouped.reset_index()
