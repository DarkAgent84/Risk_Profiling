"""
matured_overdue: a structural risk flag, independent of customer_type.

A loan is flagged if its EMI due date has already passed as of the report's
Cycle Date, and it's still carrying delinquency or dues. This is loan-tenure
math (Emi due date < Cycle Date), not a behavioral/outcome-derived proxy, so
it's safe to use as a scoring input — unlike the original customer_type,
which was found to be leakage (see README).

Source: reverse-engineered against the real "Matured" customer_type tag —
Emi due date < Cycle Date matched 96.6% of "Matured" loans (recall) at 96.0%
precision. Matured loans were 83% at 90+ DPD already, so this flag's main
value is catching the remaining ~17%: tenure has lapsed but DPD/bucket data
hasn't (yet) crossed the usual 90-day NPA threshold.
"""
import pandas as pd


def add_matured_overdue(df: pd.DataFrame) -> pd.DataFrame:
    """Add the boolean 'matured_overdue' column."""
    df = df.copy()

    if "emi_due_date" not in df.columns or "cycle_date" not in df.columns:
        print("[WARN] No 'Emi due date' / 'Cycle Date' column in SOA — matured_overdue skipped (defaulting to False).")
        df["matured_overdue"] = False
        return df

    dpd = pd.to_numeric(df.get("dpd", 0), errors="coerce").fillna(0)
    dues = pd.to_numeric(df.get("total_dues", 0), errors="coerce").fillna(0)

    tenure_lapsed = df["emi_due_date"].notna() & df["cycle_date"].notna() & (df["emi_due_date"] < df["cycle_date"])
    still_owing = (dpd > 0) | (dues > 0)

    df["matured_overdue"] = tenure_lapsed & still_owing
    return df
