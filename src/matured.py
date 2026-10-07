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
        df["matured_overdue"] = False
        return df

    cycle_series = pd.to_datetime(df["cycle_date"], errors="coerce", dayfirst=True)
    emi_series = pd.to_datetime(df["emi_due_date"], errors="coerce", dayfirst=True)

    if not cycle_series.notna().any() or not emi_series.notna().any():
        df["matured_overdue"] = False
        return df

    dpd = pd.to_numeric(df.get("dpd", 0), errors="coerce").fillna(0)
    dues = pd.to_numeric(df.get("total_dues", 0), errors="coerce").fillna(0)

    tenure_lapsed = emi_series.notna() & cycle_series.notna() & (emi_series < cycle_series)
    still_owing = (dpd > 0) | (dues > 0)

    df["matured_overdue"] = tenure_lapsed & still_owing
    return df
