"""
matured_overdue: structural risk flag (tenure lapsed AND still genuinely overdue).

v2 change: "still owing" now uses overdue_dues (arrears) instead of gross
total_dues. Fedbank-style feeds bill gross dues including the current EMI, so
the v1 check (total_dues > 0) flagged almost every lapsed loan, even clean ones.
"""
import pandas as pd


def add_matured_overdue(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["matured_overdue"] = False
    if "emi_due_date" not in df.columns or "cycle_date" not in df.columns:
        return df

    cycle = pd.to_datetime(df["cycle_date"], errors="coerce", dayfirst=True)
    emi = pd.to_datetime(df["emi_due_date"], errors="coerce", dayfirst=True)
    if not cycle.notna().any() or not emi.notna().any():
        return df

    dpd = pd.to_numeric(df.get("dpd", 0), errors="coerce").fillna(0)
    dues_col = "overdue_dues" if "overdue_dues" in df.columns else "total_dues"
    dues = pd.to_numeric(df.get(dues_col, 0), errors="coerce").fillna(0)

    tenure_lapsed = emi.notna() & cycle.notna() & (emi < cycle)
    df["matured_overdue"] = tenure_lapsed & ((dpd > 0) | (dues > 0))
    return df
