"""
Reporting: executive portfolio summary + comparison against legacy SOA risk labels.
"""
from pathlib import Path

import pandas as pd


def format_inr(val: float) -> str:
    if abs(val) >= 1e7:
        return f"INR {val / 1e7:,.2f} Cr"
    if abs(val) >= 1e5:
        return f"INR {val / 1e5:,.2f} L"
    return f"INR {val:,.2f}"


def print_portfolio_summary(df: pd.DataFrame) -> None:
    total = len(df)
    total_dues = df["total_dues"].sum()
    unworked = int(df["never_worked"].sum())
    unworked_pct = (unworked / total * 100) if total else 0.0

    print("\n" + "=" * 70)
    print("COLLECTIONS RISK PROFILING — PORTFOLIO SUMMARY")
    print("=" * 70)
    print(f"Total loans scored             : {total:,}")
    print(f"Total outstanding dues exposure: {format_inr(total_dues)}")
    print(f"Loans with no collection MIS   : {unworked:,} ({unworked_pct:.1f}%)")
    print(f"Loans with collection history  : {total - unworked:,} ({100 - unworked_pct:.1f}%)")

    print("\n" + "-" * 70)
    print("RISK TIER BREAKDOWN")
    print("-" * 70)
    tier_order = [t for t in ["High", "Medium", "Low"] if t in df["risk_tier"].unique()]
    summary = df.groupby("risk_tier", observed=False).agg(
        Loan_Count=("loan_number", "count"),
        Total_Dues=("total_dues", "sum"),
        Avg_DPD=("dpd", "mean"),
        Avg_Score=("risk_score", "mean"),
    ).reindex(tier_order).fillna(0)
    summary["Loan_Share_%"] = summary["Loan_Count"] / total * 100 if total else 0
    summary["Dues_Share_%"] = summary["Total_Dues"] / total_dues * 100 if total_dues else 0
    summary["Total_Dues_INR"] = summary["Total_Dues"].apply(format_inr)
    cols = ["Loan_Count", "Loan_Share_%", "Total_Dues_INR", "Dues_Share_%", "Avg_DPD", "Avg_Score"]
    print(summary[cols].to_string())

    if "customer_type" in df.columns:
        print("\n" + "-" * 70)
        print("CUSTOMER TYPE BREAKDOWN (4-Class Banking Benchmark)")
        print("-" * 70)
        order_cust = ["Never Bounce", "Ever Bounce", "Matured", "3 MOB"]
        counts_cust = df["customer_type"].value_counts().reindex(order_cust).fillna(0).astype(int)
        other_cust = df["customer_type"].loc[~df["customer_type"].isin(order_cust)].value_counts()
        if not other_cust.empty:
            counts_cust = pd.concat([counts_cust, other_cust])
        print(pd.DataFrame({"Loan_Count": counts_cust, "Loan_Share_%": (counts_cust / total * 100).round(2) if total else 0}).to_string())

    if "bounce_type" in df.columns:
        print("\n" + "-" * 70)
        print("BOUNCE TYPE BREAKDOWN (8-Class Granular Specification)")
        print("-" * 70)
        order = ["Never Bounced", "Always Bounced", "3 MOB", "4 MOB", "5 MOB", "6 MOB", "7+ MOB", "Ever Bounced"]
        counts = df["bounce_type"].value_counts().reindex(order).fillna(0).astype(int)
        other = df["bounce_type"].loc[~df["bounce_type"].isin(order)].value_counts()
        if not other.empty:
            counts = pd.concat([counts, other])
        print(pd.DataFrame({"Loan_Count": counts, "Loan_Share_%": (counts / total * 100).round(2) if total else 0}).to_string())
    print("=" * 70 + "\n")


def evaluate_against_soa(soa_input, scored_input) -> None:
    """Compare model-assigned risk tiers against the original SOA 'Risk Type' column, if present."""
    if isinstance(soa_input, pd.DataFrame):
        soa = soa_input.copy()
    else:
        soa = pd.read_csv(soa_input, low_memory=False)

    if isinstance(scored_input, pd.DataFrame):
        scored = scored_input.copy()
    else:
        scored = pd.read_csv(scored_input, low_memory=False)

    soa.columns = [c.strip() for c in soa.columns]
    scored.columns = [c.strip() for c in scored.columns]

    loan_col_soa = next((c for c in soa.columns if c.lower().replace(" ", "_") == "loan_number"), "loan_number")
    soa["loan_number"] = soa[loan_col_soa].astype(str).str.strip()

    loan_col_scored = next((c for c in scored.columns if c.lower().replace(" ", "_") == "loan_number"), "loan_number")
    scored["loan_number"] = scored[loan_col_scored].astype(str).str.strip()

    risk_col = next((c for c in soa.columns if c.lower().replace(" ", "_") == "risk_type"), None)
    cust_col = next((c for c in soa.columns if c.lower().replace(" ", "_") == "customer_type"), None)
    zone_col = next((c for c in soa.columns if c.lower().replace(" ", "_") == "zone"), None)
    bkt_col = next((c for c in soa.columns if c.lower().replace(" ", "_") == "bucket_group"), None)

    meta_cols = [c for c in [risk_col, cust_col, zone_col, bkt_col] if c and c in soa.columns and c != "loan_number"]
    overlap = [c for c in meta_cols if c in scored.columns and c != "loan_number"]
    scored_clean = scored.drop(columns=overlap) if overlap else scored
    df = scored_clean.merge(soa[["loan_number"] + meta_cols], on="loan_number", how="left")

    has_risk_type = risk_col is not None
    df["soa_risk_type"] = df[risk_col].fillna("Unassigned / NaN") if has_risk_type else "Unknown"

    total_dues_cr = df["total_dues"].sum() / 1e7 if ("total_dues" in df.columns and df["total_dues"].sum()) else 1.0

    print("=" * 75)
    print("COMPARISON: SOA 'RISK TYPE' VS CALIBRATED RISK MODEL")
    print("=" * 75)

    soa_summary = df.groupby("soa_risk_type").agg(
        Accounts=("loan_number", "count"), Total_Dues_Cr=("total_dues", lambda x: x.sum() / 1e7), Avg_DPD=("dpd", "mean")
    ).reset_index()
    soa_summary["Acct_Share_%"] = (soa_summary["Accounts"] / len(df) * 100).round(2)
    soa_summary["Dues_Share_%"] = (soa_summary["Total_Dues_Cr"] / total_dues_cr * 100).round(2)
    soa_summary["Total_Dues_Cr"] = soa_summary["Total_Dues_Cr"].round(2)
    soa_summary["Avg_DPD"] = soa_summary["Avg_DPD"].round(1)
    print("\n--- 1. SOA MASTER RISK TYPE SUMMARY ---")
    print(soa_summary[["soa_risk_type", "Accounts", "Acct_Share_%", "Total_Dues_Cr", "Dues_Share_%", "Avg_DPD"]].to_string(index=False))

    tier_order = [t for t in ["High", "Medium", "Low"] if t in df["risk_tier"].unique()]
    model_summary = df.groupby("risk_tier").agg(
        Accounts=("loan_number", "count"), Total_Dues_Cr=("total_dues", lambda x: x.sum() / 1e7), Avg_DPD=("dpd", "mean")
    ).reindex(tier_order).reset_index()
    model_summary["Acct_Share_%"] = (model_summary["Accounts"] / len(df) * 100).round(2)
    model_summary["Dues_Share_%"] = (model_summary["Total_Dues_Cr"] / total_dues_cr * 100).round(2)
    model_summary["Total_Dues_Cr"] = model_summary["Total_Dues_Cr"].round(2)
    model_summary["Avg_DPD"] = model_summary["Avg_DPD"].round(1)
    print("\n--- 2. CALIBRATED MODEL RISK TIER SUMMARY ---")
    print(model_summary.to_string(index=False))

    ct = pd.crosstab(df["soa_risk_type"], df["risk_tier"], margins=True, margins_name="Total")
    cols_order = [c for c in ["High", "Medium", "Low", "Total"] if c in ct.columns]
    print("\n--- 3. MIGRATION MATRIX (account counts) ---")
    print(ct[cols_order])

    print("\n--- 4. ACCURACY METRICS ---")
    if not has_risk_type:
        print("[*] SOA file has no 'Risk Type' column — accuracy metrics skipped.")
    else:
        valid = df[df[risk_col].notna()].copy()
        match_count = int((valid["risk_tier"] == valid[risk_col]).sum())
        acc_valid = (valid["risk_tier"] == valid[risk_col]).mean() if len(valid) else 0.0
        acc_total = (df["risk_tier"] == df[risk_col].fillna("Low")).mean()
        print(f"[*] Exact match count        : {match_count:,} / {len(valid):,}")
        print(f"[*] Accuracy on valid tiers   : {acc_valid * 100:.2f}%")
        print(f"[*] Accuracy on full dataset  : {acc_total * 100:.2f}%")

    if cust_col and cust_col in df.columns:
        print("\n" + "=" * 75)
        print("CUSTOMER TYPE & BOUNCE TYPE EVALUATION")
        print("=" * 75)
        if "customer_type" in df.columns:
            print("\n--- 1. BENCHMARK: SOA 'CUSTOMER TYPE' VS MODEL 'customer_type' ---")
            ct_cust = pd.crosstab(df[cust_col].fillna("Unassigned / NaN"), df["customer_type"], margins=True, margins_name="Total")
            print(ct_cust)
            valid_cust = df[df[cust_col].notna()].copy()
            cust_match = int((valid_cust[cust_col] == valid_cust["customer_type"]).sum())
            cust_acc = (valid_cust[cust_col] == valid_cust["customer_type"]).mean() if len(valid_cust) else 0.0
            print(f"\n[*] Exact match count          : {cust_match:,} / {len(valid_cust):,}")
            print(f"[*] Accuracy on Customer Type   : {cust_acc * 100:.2f}%")

        if "bounce_type" in df.columns:
            print("\n--- 2. GRANULAR BOUNCE TYPE MATRIX (Customer Type vs bounce_type) ---")
            ct_bounce = pd.crosstab(df[cust_col].fillna("Unassigned / NaN"), df["bounce_type"], margins=True, margins_name="Total")
            print(ct_bounce)
    print("=" * 75 + "\n")
