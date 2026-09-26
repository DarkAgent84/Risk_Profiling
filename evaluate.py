"""
Model Evaluation and Migration Diagnostics CLI
==============================================
Usage:
    python evaluate.py
"""
import argparse
import sys
from pathlib import Path

from src import config
from src.ingestion import find_raw_files
from src.evaluation import compare_with_original_soa


def main():
    parser = argparse.ArgumentParser(description="Evaluate Model Risk Tiers against Original SOA Risk Types")
    parser.add_argument('--soa', type=str, default=None, help='Path to raw SOA CSV')
    parser.add_argument('--scored', type=str, default=None, help='Path to scored loans CSV')
    args = parser.parse_args()

    soa_path = args.soa
    scored_path = args.scored

    if not soa_path:
        default_soa, _ = find_raw_files()
        soa_path = default_soa

    if not scored_path:
        candidate_paths = [
            config.PROCESSED_DATA_DIR / "risk_scored_loans.csv",
            config.BASE_DIR / "risk_scored_loans.csv"
        ]
        for p in candidate_paths:
            if p.exists():
                scored_path = p
                break

    if not soa_path or not scored_path:
        print("Error: Missing input files for evaluation.")
        print(f"SOA: {soa_path}, Scored: {scored_path}")
        print("Please run `python main.py` first to generate the scored dataset.")
        sys.exit(1)

    compare_with_original_soa(soa_path, scored_path)


if __name__ == '__main__':
    main()
