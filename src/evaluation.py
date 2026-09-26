"""
Portfolio Reporting and Model Evaluation Diagnostics
"""
from pathlib import Path
import pandas as pd
from src import config


def format_currency_inr(val: float) -> str:
    """Format numeric values into readable INR Crores / Lakhs."""
    if abs(val) >= 1e7:
        return f"INR {val / 1e7:,.2f} Cr"
    elif abs(val) >= 1e5:
        return f"INR {val / 1e5:,.2f} L"
    return f"INR {val:,.2f}"


def print_portfolio_summary(df: pd.DataFrame) -> None:
    """Print executive portfolio summary to terminal."""
    total_loans = len(df)
    total_dues_all = df['total_dues'].sum()
    unworked_count = df['never_worked'].sum()
    unworked_pct = (unworked_count / total_loans) * 100

    print("\n" + "=" * 70)
    print("COLLECTIONS RISK PROFILING - EXECUTIVE PORTFOLIO SUMMARY")
    print("=" * 70)
    print(f"Total Portfolio Loans Scored   : {total_loans:,}")
    print(f"Total Outstanding Dues Exposure: {format_currency_inr(total_dues_all)}")
    print(f"Loans with No Collection MIS   : {unworked_count:,} ({unworked_pct:.1f}%)")
    print(f"Loans with Collection History  : {total_loans - unworked_count:,} ({100 - unworked_pct:.1f}%)")

    print("\n" + "-" * 70)
    print("RISK TIER BREAKDOWN")
    print("-" * 70)
    tier_order = [t for t in ['High', 'Medium', 'Low', '3 MOB'] if t in df['risk_tier'].unique()]
    tier_summary = df.groupby('risk_tier', observed=False).agg(
        Loan_Count=('loan_number', 'count'),
        Total_Dues=('total_dues', 'sum'),
        Avg_DPD=('dpd', 'mean'),
        Avg_Score=('risk_score', 'mean'),
    ).reindex(tier_order).fillna(0)

    tier_summary['Loan_Share_%'] = (tier_summary['Loan_Count'] / total_loans) * 100
    tier_summary['Dues_Share_%'] = (tier_summary['Total_Dues'] / total_dues_all) * 100
    tier_summary['Total_Dues_INR'] = tier_summary['Total_Dues'].apply(format_currency_inr)

    disp_cols = ['Loan_Count', 'Loan_Share_%', 'Total_Dues_INR', 'Dues_Share_%', 'Avg_DPD', 'Avg_Score']
    print(tier_summary[disp_cols].to_string())
    print("=" * 70 + "\n")


def compare_with_original_soa(soa_path: str | Path, scored_path: str | Path) -> None:
    """Compare model-assigned risk tiers against original SOA Risk Type classification."""
    soa = pd.read_csv(soa_path, low_memory=False)
    soa.columns = [c.strip() for c in soa.columns]
    
    soa_loan_col = next((c for c in soa.columns if c.lower().replace(' ', '_') == 'loan_number'), 'Loan number')
    soa['loan_number'] = soa[soa_loan_col].astype(str).str.strip()

    scored = pd.read_csv(scored_path, low_memory=False)
    scored['loan_number'] = scored['loan_number'].astype(str).str.strip()

    meta_cols = [c for c in ['Risk Type', 'Customer Type', 'Bucket Group', 'Zone'] if c in soa.columns]
    df = scored.merge(soa[['loan_number'] + meta_cols], on='loan_number', how='left')
    df['soa_risk_type'] = df['Risk Type'].fillna('Unassigned / NaN') if 'Risk Type' in df.columns else 'Unknown'

    total_dues_cr = df['total_dues'].sum() / 1e7

    print("=" * 75)
    print("COMPARISON: SOA MASTER 'RISK TYPE' VS CALIBRATED RISK MODEL")
    print("=" * 75)

    # 1. SOA Summary
    soa_summary = df.groupby('soa_risk_type').agg(
        Accounts=('loan_number', 'count'),
        Total_Dues_Cr=('total_dues', lambda x: x.sum() / 1e7),
        Avg_DPD=('dpd', 'mean')
    ).reset_index()
    soa_summary['Acct_Share_%'] = (soa_summary['Accounts'] / len(df) * 100).round(2)
    soa_summary['Dues_Share_%'] = (soa_summary['Total_Dues_Cr'] / total_dues_cr * 100).round(2)
    soa_summary['Total_Dues_Cr'] = soa_summary['Total_Dues_Cr'].round(2)
    soa_summary['Avg_DPD'] = soa_summary['Avg_DPD'].round(1)

    print("\n--- 1. SOA MASTER RISK TYPE SUMMARY ---")
    print(soa_summary[['soa_risk_type', 'Accounts', 'Acct_Share_%', 'Total_Dues_Cr', 'Dues_Share_%', 'Avg_DPD']].to_string(index=False))

    # 2. Model Summary
    tier_order = [t for t in ['High', 'Medium', 'Low', '3 MOB'] if t in df['risk_tier'].unique()]
    model_summary = df.groupby('risk_tier').agg(
        Accounts=('loan_number', 'count'),
        Total_Dues_Cr=('total_dues', lambda x: x.sum() / 1e7),
        Avg_DPD=('dpd', 'mean')
    ).reindex(tier_order).reset_index()
    model_summary['Acct_Share_%'] = (model_summary['Accounts'] / len(df) * 100).round(2)
    model_summary['Dues_Share_%'] = (model_summary['Total_Dues_Cr'] / total_dues_cr * 100).round(2)
    model_summary['Total_Dues_Cr'] = model_summary['Total_Dues_Cr'].round(2)
    model_summary['Avg_DPD'] = model_summary['Avg_DPD'].round(1)

    print("\n--- 2. CALIBRATED MODEL RISK TIER SUMMARY ---")
    print(model_summary.to_string(index=False))

    # 3. Migration Matrix
    ct_counts = pd.crosstab(df['soa_risk_type'], df['risk_tier'], margins=True, margins_name='Total')
    cols_order = [c for c in ['High', 'Medium', 'Low', '3 MOB', 'Total'] if c in ct_counts.columns]
    print("\n--- 3. MIGRATION MATRIX (Account Counts) ---")
    print(ct_counts[cols_order])

    # 4. Accuracy metrics
    valid = df[df['Risk Type'].notna()].copy()
    match_count = (valid['risk_tier'] == valid['Risk Type']).sum()
    acc_valid = (valid['risk_tier'] == valid['Risk Type']).mean()
    acc_total = (df['risk_tier'] == df['Risk Type'].fillna('Low')).mean()

    print("\n--- 4. ACCURACY METRICS ---")
    print(f"[*] Exact Match Count        : {match_count:,} / {len(valid):,}")
    print(f"[*] Accuracy on Valid Tiers  : {acc_valid * 100:.2f}%")
    print(f"[*] Accuracy on Full Dataset : {acc_total * 100:.2f}%")
    print("=" * 75 + "\n")
