"""
PostgreSQL Database-Driven Risk Profiling Pipeline
==================================================
1. Ingests 3 files into PostgreSQL (pgAdmin) tables:
   - raw_soa_master
   - raw_mis_collections
   - previous_loan_risk_tiers
2. Executes risk scoring directly from PostgreSQL data.
3. Saves scored dataset to PostgreSQL table 'scored_loan_risk_profiles' and 'risk_migration_summary'.

Usage:
    python db_pipeline.py
    python db_pipeline.py --upload-only
"""
import argparse
import sys
from pathlib import Path
import pandas as pd
from sqlalchemy import text

from src import config
from src.db import (
    ensure_database_exists,
    upload_all_raw_files,
    fetch_table,
    save_scored_results_to_db,
    get_engine,
    DB_CONFIG
)
from src.ingestion import find_raw_files, normalize_column_name
from src.behavior import extract_behavioral_features
from src.scoring import compute_risk_profile
from src.evaluation import print_portfolio_summary, format_currency_inr


def run_database_pipeline(
    soa_csv: Optional[str | Path] = None,
    mis_csv: Optional[str | Path] = None,
    prev_tier_csv: Optional[str | Path] = None,
    upload_data: bool = True
):
    """Run end-to-end database pipeline."""
    # Ensure database exists
    ensure_database_exists()

    # Locate files
    if not soa_csv or not mis_csv:
        def_soa, def_mis = find_raw_files()
        soa_csv = soa_csv or def_soa
        mis_csv = mis_csv or def_mis

    if not prev_tier_csv:
        candidate_prev = config.RAW_DATA_DIR / "previous_risk_tiers.csv"
        if candidate_prev.exists():
            prev_tier_csv = candidate_prev
        else:
            prev_tier_csv = config.BASE_DIR / "data" / "raw" / "previous_risk_tiers.csv"

    # Step 1: Upload 3 files to PostgreSQL if requested
    if upload_data:
        if not soa_csv or not mis_csv or not Path(prev_tier_csv).exists():
            print("Error: Missing input CSV files for database upload.")
            sys.exit(1)
        upload_all_raw_files(soa_csv, mis_csv, prev_tier_csv)

    # Step 2: Read raw data directly from PostgreSQL tables
    print("=" * 65)
    print("   EXECUTING RISK SCORING FROM POSTGRESQL TABLES (pgAdmin)  ")
    print("=" * 65)
    soa = fetch_table("raw_soa_master")
    mis = fetch_table("raw_mis_collections")
    prev_tiers = fetch_table("previous_loan_risk_tiers")

    # Standardize column headers from DB
    soa.columns = [normalize_column_name(c) for c in soa.columns]
    mis.columns = [normalize_column_name(c) for c in mis.columns]
    prev_tiers.columns = [normalize_column_name(c) for c in prev_tiers.columns]

    # Typecast
    soa['loan_number'] = soa['loan_number'].astype(str).str.strip()
    mis['loan_number'] = mis['loan_number'].astype(str).str.strip()
    prev_tiers['loan_number'] = prev_tiers['loan_number'].astype(str).str.strip()

    soa['dpd'] = pd.to_numeric(soa['dpd'], errors='coerce').fillna(0)
    soa['total_dues'] = pd.to_numeric(soa['total_dues'], errors='coerce').fillna(0)

    for optional_num in ['total_loan_outstanding_amount', 'bucket', 'emi_amount', 'loan_amount', 'charges_payable', 'charges_2']:
        if optional_num in soa.columns:
            soa[optional_num] = pd.to_numeric(soa[optional_num], errors='coerce').fillna(0)

    if 'total_amount_collected' in mis.columns:
        mis['total_amount_collected'] = pd.to_numeric(mis['total_amount_collected'], errors='coerce').fillna(0)

    # Step 3: Compute Behavioral Aggregation & Risk Scoring
    behavior = extract_behavioral_features(mis)
    scored = compute_risk_profile(soa, behavior)

    # Join previous benchmark risk tiers from 3rd table
    if 'previous_risk_tier' in prev_tiers.columns:
        scored = scored.merge(prev_tiers[['loan_number', 'previous_risk_tier']], on='loan_number', how='left')

    # Step 4: Display Summary
    print_portfolio_summary(scored)

    # Step 5: Save results back to PostgreSQL
    print("-> Saving calculated risk profile to PostgreSQL table 'scored_loan_risk_profiles'...")
    output_cols = [
        'loan_number', 'dpd', 'bucket', 'total_dues',
        'total_loan_outstanding_amount', 'product_name', 'zone',
        'risk_type', 'previous_risk_tier', 'customer_type', 'npa_tag',
        'never_worked', 'total_receipts', 'rejected_receipts',
        'rejection_rate', 'partial_payment_rate', 'total_collected',
        'last_payment_date', 'risk_score', 'risk_tier'
    ]
    selected_cols = [c for c in output_cols if c in scored.columns]
    save_scored_results_to_db(scored[selected_cols], "scored_loan_risk_profiles")

    # Step 6: Create Migration Summary Table in DB
    if 'previous_risk_tier' in scored.columns or 'risk_type' in scored.columns:
        orig_col = 'previous_risk_tier' if 'previous_risk_tier' in scored.columns else 'risk_type'
        migration_ct = pd.crosstab(
            scored[orig_col].fillna('Unassigned / NaN'),
            scored['risk_tier'],
            margins=True,
            margins_name='Total'
        ).reset_index()
        migration_ct.columns = [str(c).replace(' ', '_').lower() for c in migration_ct.columns]
        save_scored_results_to_db(migration_ct, "risk_migration_summary")

    # Step 7: Export copy to CSV for local file access
    config.PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    csv_out = config.PROCESSED_DATA_DIR / "risk_scored_loans.csv"
    scored[selected_cols].to_csv(csv_out, index=False)
    print(f"[OK] Exported local copy to: {csv_out}")

    print("\n" + "=" * 65)
    print("   POSTGRESQL DATABASE PIPELINE COMPLETED SUCCESSFULLY!    ")
    print(f"   Database Name : {DB_CONFIG['dbname']}")
    print("   Tables in pgAdmin:")
    print("     1. raw_soa_master              (Source 1: SOA Master)")
    print("     2. raw_mis_collections         (Source 2: MIS Collection)")
    print("     3. previous_loan_risk_tiers    (Source 3: Previous Risk Tiers)")
    print("     4. scored_loan_risk_profiles   (Final Model Risk Scores & Tiers)")
    print("     5. risk_migration_summary      (Comparison Matrix)")
    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="PostgreSQL Collections Risk Pipeline")
    parser.add_argument('--soa', type=str, default=None, help='Path to SOA Master CSV')
    parser.add_argument('--mis', type=str, default=None, help='Path to MIS Collection CSV')
    parser.add_argument('--prev-tiers', type=str, default=None, help='Path to Previous Risk Tiers CSV')
    parser.add_argument('--upload-only', action='store_true', help='Only upload 3 CSVs to DB without scoring')
    parser.add_argument('--no-upload', action='store_true', help='Skip upload and score directly from existing DB tables')
    args = parser.parse_args()

    if args.upload_only:
        def_soa, def_mis = find_raw_files()
        soa_csv = args.soa or def_soa
        mis_csv = args.mis or def_mis
        prev_csv = args.prev_tiers or (config.RAW_DATA_DIR / "previous_risk_tiers.csv")
        upload_all_raw_files(soa_csv, mis_csv, prev_csv)
    else:
        run_database_pipeline(
            soa_csv=args.soa,
            mis_csv=args.mis,
            prev_tier_csv=args.prev_tiers,
            upload_data=not args.no_upload
        )


if __name__ == '__main__':
    main()
