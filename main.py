"""
Collections Risk Profiling — CLI
=================================
Usage:
    python main.py score                          # auto-discover files in data/raw, write scored CSV
    python main.py score --soa a.csv --mis b.csv --out out.csv
    python main.py evaluate                        # compare scored output against SOA 'Risk Type'
    python main.py evaluate --soa a.csv --scored out.csv
    python main.py sync-db                         # (optional) upload raw CSVs to PostgreSQL
"""
import argparse
import sys

import config
from src.ingest import find_raw_files, load_datasets
from src.features import build_behavior_features
from src.scoring import score_portfolio
from src.report import print_portfolio_summary, evaluate_against_soa

OUTPUT_COLUMNS = [
    "loan_number", "dpd", "bucket", "total_dues", "total_loan_outstanding_amount",
    "product_name", "zone", "soa_customer_type", "customer_type", "risk_type", "npa_tag",
    "never_worked", "total_receipts", "rejected_receipts", "rejection_rate",
    "partial_payment_rate", "total_collected", "last_payment_date",
    "disbursal_date", "bounce_type", "matured_overdue",
    "risk_score", "risk_tier",
]


def cmd_score(args) -> None:
    soa_path, mis_path = args.soa, args.mis
    if not soa_path or not mis_path:
        default_soa, default_mis = find_raw_files()
        soa_path = soa_path or default_soa
        mis_path = mis_path or default_mis
    if not soa_path or not mis_path:
        sys.exit("Error: could not find SOA and/or MIS CSV files in data/raw. "
                  "Pass them explicitly with --soa and --mis.")

    print("=" * 55)
    print("   COLLECTIONS RISK PROFILING — SCORING RUN")
    print("=" * 55)
    print(f"SOA file   : {soa_path}")
    print(f"MIS file   : {mis_path}")

    soa, mis = load_datasets(soa_path, mis_path)
    behavior = build_behavior_features(mis)
    scored = score_portfolio(soa, behavior)
    print_portfolio_summary(scored)

    from pathlib import Path
    out_path = Path(args.out) if ("/" in args.out or "\\" in args.out) else config.PROCESSED_DATA_DIR / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cols = [c for c in OUTPUT_COLUMNS if c in scored.columns]
    try:
        scored[cols].to_csv(out_path, index=False)
        print(f"[OK] Scored dataset saved to: {out_path}\n")
    except PermissionError:
        sys.exit(f"Error: could not write to {out_path} — it may be open in another program "
                  f"(e.g. Excel) or read-only. Close it and re-run, or pass a different --out path.")


def cmd_evaluate(args) -> None:
    soa_path = args.soa
    if not soa_path:
        soa_path, _ = find_raw_files()
    from pathlib import Path
    scored_path = Path(args.scored) if args.scored else config.DEFAULT_OUTPUT_FILE
    if not soa_path or not scored_path.exists():
        sys.exit(f"Error: missing input files for evaluation.\n"
                  f"SOA: {soa_path}\nScored: {scored_path}\n"
                  f"Run `python main.py score` first to generate the scored dataset.")

    evaluate_against_soa(soa_path, scored_path)


def cmd_sync_db(args) -> None:
    from src.db import upload_raw_files
    soa_path, mis_path = args.soa, args.mis
    if not soa_path or not mis_path:
        default_soa, default_mis = find_raw_files()
        soa_path = soa_path or default_soa
        mis_path = mis_path or default_mis
    if not soa_path or not mis_path:
        sys.exit("Error: could not find SOA and/or MIS CSV files to upload.")
    upload_raw_files(soa_path, mis_path)


def cmd_db_score(args) -> None:
    """Same pipeline as `score`, but reading input from PostgreSQL and writing results back to it."""
    from pathlib import Path
    from src.db import fetch_raw_tables, save_scored_results
    from src.ingest import prepare_soa, prepare_mis

    print("=" * 55)
    print("   COLLECTIONS RISK PROFILING — SCORING FROM POSTGRESQL")
    print("=" * 55)

    raw_soa, raw_mis = fetch_raw_tables()
    soa = prepare_soa(raw_soa)
    mis = prepare_mis(raw_mis)

    behavior = build_behavior_features(mis)
    scored = score_portfolio(soa, behavior)
    print_portfolio_summary(scored)

    cols = [c for c in OUTPUT_COLUMNS if c in scored.columns]

    print("-> Saving scored results to PostgreSQL table 'scored_loan_risk_profiles'...")
    save_scored_results(scored[cols], "scored_loan_risk_profiles")

    # Also mirror to CSV so `python main.py evaluate` keeps working without changes.
    # This is a convenience step only — the PostgreSQL write above already succeeded,
    # so a locked/read-only file here should not fail the whole run.
    out_path = Path(args.out) if ("/" in args.out or "\\" in args.out) else config.PROCESSED_DATA_DIR / args.out
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        scored[cols].to_csv(out_path, index=False)
        print(f"[OK] Scored dataset also mirrored to: {out_path}\n")
    except PermissionError:
        print(f"[WARN] Could not write CSV mirror to {out_path} — it may be open in another "
              f"program (e.g. Excel) or read-only. The PostgreSQL table was saved successfully; "
              f"close the file and re-run if you need the CSV mirror too.\n")


def cmd_db_drop_column(args) -> None:
    from src.db import drop_column
    drop_column(args.table, args.column)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collections Risk Profiling Engine")
    sub = parser.add_subparsers(dest="command", required=True)

    p_score = sub.add_parser("score", help="Run the risk scoring pipeline")
    p_score.add_argument("--soa", type=str, default=None, help="Path to SOA master CSV")
    p_score.add_argument("--mis", type=str, default=None, help="Path to MIS collection CSV")
    p_score.add_argument("--out", type=str, default="risk_scored_loans.csv",
                          help="Output filename (relative to data/processed) or a full path")
    p_score.set_defaults(func=cmd_score)

    p_eval = sub.add_parser("evaluate", help="Compare scored output against SOA 'Risk Type'")
    p_eval.add_argument("--soa", type=str, default=None, help="Path to raw SOA CSV")
    p_eval.add_argument("--scored", type=str, default=None, help="Path to scored loans CSV")
    p_eval.set_defaults(func=cmd_evaluate)

    p_db = sub.add_parser("sync-db", help="Upload raw SOA + MIS CSVs to PostgreSQL")
    p_db.add_argument("--soa", type=str, default=None)
    p_db.add_argument("--mis", type=str, default=None)
    p_db.set_defaults(func=cmd_sync_db)

    p_dbscore = sub.add_parser("db-score", help="Run scoring reading from PostgreSQL, writing results back to it")
    p_dbscore.add_argument("--out", type=str, default="risk_scored_loans.csv",
                            help="CSV mirror filename (relative to data/processed) or a full path")
    p_dbscore.set_defaults(func=cmd_db_score)

    p_dropcol = sub.add_parser("db-drop-column", help="Drop a column from an existing PostgreSQL table")
    p_dropcol.add_argument("--table", type=str, required=True, help="Table name, e.g. raw_soa_master")
    p_dropcol.add_argument("--column", type=str, required=True, help="Column name to drop, e.g. customer_type")
    p_dropcol.set_defaults(func=cmd_db_drop_column)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
