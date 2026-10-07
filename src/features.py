"""
Behavioral features: aggregate per-transaction MIS receipts into per-loan stats.

Bounce ("is_rejected") logic (see config.py for sources) — a receipt counts
as a bounce if ANY of the following hold. If the money didn't land, it
counts against the customer regardless of whose fault it was:
  - current status is "Rejected by Operations" (or similar keyword match), or
  - Rejection Count > 0 — it was rejected at some point, even if later
    re-submitted and approved (status text alone misses this — see A25 in
    the dataset report), or
  - status is a cancelled/"Deleted" variant — the receipt was voided, so the
    payment never successfully completed either way.
"""
import pandas as pd

import config


def build_behavior_features(mis: pd.DataFrame) -> pd.DataFrame:
    """One row per loan_number: total receipts, rejection rate, partial-payment rate, etc."""
    mis = mis.copy()

    status = mis["instrument_status"].astype(str).str.strip().str.lower()
    ptype = mis["payment_type"].astype(str).str.strip().str.lower()

    status_rejected = status.str.contains("|".join(config.REJECTED_STATUS_KEYWORDS), regex=True)
    status_cancelled = status.str.contains(config.CANCELLED_STATUS_KEYWORD, regex=False)
    count_rejected = (mis["rejection_count"] > 0) if "rejection_count" in mis.columns else False
    mis["is_rejected"] = (status_rejected | status_cancelled | count_rejected).astype(int)

    # An installment is truly partial only if it paid less than the installment due.
    # When total_amount_collected equals or exceeds emi_pemi_dues, the borrower paid
    # the complete installment (even if the app labeled it 'Part payment' against total cumulative dues).
    is_part_type = (ptype == config.PARTIAL_PAYMENT_KEYWORD)
    if "total_amount_collected" in mis.columns and "emi_pemi_dues" in mis.columns:
        collected = pd.to_numeric(mis["total_amount_collected"], errors="coerce").fillna(0)
        pemi_due = pd.to_numeric(mis["emi_pemi_dues"], errors="coerce").fillna(0)
        paid_full = (pemi_due > 0) & (collected >= pemi_due * 0.95)
        mis["is_partial"] = (is_part_type & ~paid_full).astype(int)
    else:
        mis["is_partial"] = is_part_type.astype(int)

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
