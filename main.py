"""
Collections Risk Engine - Main Pipeline Execution Entrypoint
============================================================
Usage:
    # 1. Automatic run (auto-discovers input CSV files in ./data/raw):
    python main.py

    # 2. Custom file paths:
    python main.py --soa data/raw/my_soa.csv --mis data/raw/my_mis.csv --out data/processed/my_scored.csv
"""
import argparse
import sys
from pathlib import Path

from src import config
from src.ingestion import find_raw_files, load_datasets
from src.behavior import extract_behavioral_features
from src.scoring import compute_risk_profile
from src.evaluation import print_portfolio_summary


def run_pipeline(soa_path: str | Path, mis_path: str | Path, output_path: str | Path = config.DEFAULT_OUTPUT_FILE):
    """Execute end-to-end data ingestion, feature extraction, scoring, and export."""
    soa, mis = load_datasets(soa_path, mis_path)
    behavior = extract_behavioral_features(mis)
    scored = compute_risk_profile(soa, behavior)

    print_portfolio_summary(scored)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    output_cols = [
        'loan_number', 'dpd', 'bucket', 'total_dues',
        'total_loan_outstanding_amount', 'product_name', 'zone',
        'risk_type', 'customer_type', 'npa_tag',
        'never_worked', 'total_receipts', 'rejected_receipts',
        'rejection_rate', 'partial_payment_rate', 'total_collected',
        'last_payment_date', 'risk_score', 'risk_tier'
    ]
    selected_cols = [c for c in output_cols if c in scored.columns]
    
    # Save output to target path (and mirror to root if in data/processed)
    scored[selected_cols].to_csv(out, index=False)
    print(f"[OK] Scored dataset saved to: {out}")
    
    root_mirror = config.BASE_DIR / "risk_scored_loans.csv"
    if out.resolve() != root_mirror.resolve():
        try:
            scored[selected_cols].to_csv(root_mirror, index=False)
            print(f"[OK] Scored dataset mirrored to: {root_mirror}")
        except Exception:
            pass
    print()

    return scored


def main():
    parser = argparse.ArgumentParser(
        description="Collections Risk Profiling Pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('--soa', type=str, default=None, help='Path to SOA Master export CSV')
    parser.add_argument('--mis', type=str, default=None, help='Path to Dynamic Collection MIS CSV')
    parser.add_argument('--out', type=str, default=str(config.DEFAULT_OUTPUT_FILE), help='Path for output scored CSV')

    args = parser.parse_args()

    soa_path = args.soa
    mis_path = args.mis

    if not soa_path or not mis_path:
        default_soa, default_mis = find_raw_files()
        soa_path = soa_path or default_soa
        mis_path = mis_path or default_mis

    if not soa_path or not mis_path:
        print("Error: Could not automatically detect SOA and/or MIS CSV files in data/raw or root.")
        print("Usage: python main.py --soa <path_to_soa> --mis <path_to_mis>")
        sys.exit(1)

    print("==================================================")
    print("      COLLECTIONS RISK PROFILING PIPELINE         ")
    print("==================================================")
    print(f"SOA Master File : {soa_path}")
    print(f"MIS Report File : {mis_path}")
    print(f"Output Path     : {args.out}")
    print("==================================================")

    run_pipeline(soa_path, mis_path, output_path=args.out)


if __name__ == '__main__':
    main()
