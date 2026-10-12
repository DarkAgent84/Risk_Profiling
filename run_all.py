"""
Collections Risk Profiling — Dual Bank Pipeline Runner
======================================================
Runs risk scoring and evaluation across both Fedbank and SBFC portfolios.
Supports both file-based (CSV) and database-driven (PostgreSQL) workflows.

Usage:
    python run_all.py                 # File-based scoring for both banks
    python run_all.py --db            # PostgreSQL-based scoring for both banks
    python run_all.py --sync-db       # Upload raw CSVs to PostgreSQL for both
    python run_all.py --eval          # Scoring + Evaluation for both banks
    python run_all.py --db --eval     # PostgreSQL scoring + PostgreSQL evaluation
    python run_all.py --bank fedbank  # Fedbank only
    python run_all.py --bank sbfc     # SBFC only
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

def run_bank(bank_name: str, use_db: bool = False, do_eval: bool = False, do_sync: bool = False):
    bank_dir = ROOT_DIR / bank_name.upper()
    if not bank_dir.exists():
        print(f"[-] Error: Directory {bank_dir} not found.")
        return False
    
    print("\n" + "#" * 65)
    mode = "POSTGRESQL PIPELINE" if use_db else "CSV PIPELINE"
    print(f"   STARTING {mode} FOR {bank_name.upper()}")
    print("#" * 65 + "\n")

    # 1. Sync DB (optional)
    if do_sync:
        print(f"-> Syncing raw files into PostgreSQL for {bank_name.upper()}...")
        cmd_sync = [sys.executable, "main.py", "sync-db"]
        ret_sync = subprocess.run(cmd_sync, cwd=str(bank_dir))
        if ret_sync.returncode != 0:
            print(f"[-] sync-db failed for {bank_name.upper()}")
            return False

    # 2. Score
    score_cmd = "db-score" if use_db else "score"
    print(f"-> Executing '{score_cmd}' for {bank_name.upper()}...")
    cmd_score = [sys.executable, "main.py", score_cmd]
    ret_score = subprocess.run(cmd_score, cwd=str(bank_dir))
    if ret_score.returncode != 0:
        print(f"[-] Scoring failed for {bank_name.upper()} (exit code {ret_score.returncode})")
        return False
    
    # 3. Evaluate (optional)
    if do_eval:
        print("\n" + "-" * 65)
        print(f"   RUNNING EVALUATION FOR {bank_name.upper()}")
        print("-" * 65 + "\n")
        cmd_eval = [sys.executable, "main.py", "evaluate"]
        if use_db:
            cmd_eval.append("--from-db")
        subprocess.run(cmd_eval, cwd=str(bank_dir))
    
    return True

def main():
    parser = argparse.ArgumentParser(description="Run Collections Risk Profiling for Fedbank and/or SBFC")
    parser.add_argument("--bank", choices=["fedbank", "sbfc", "all"], default="all",
                        help="Which bank portfolio to run (default: all)")
    parser.add_argument("--db", action="store_true",
                        help="Run scoring directly from and back to PostgreSQL tables")
    parser.add_argument("--sync-db", action="store_true",
                        help="Upload raw CSV files into PostgreSQL before scoring")
    parser.add_argument("--eval", action="store_true",
                        help="Also run evaluation against benchmarks after scoring")
    args = parser.parse_args()

    banks = ["fedbank", "sbfc"] if args.bank == "all" else [args.bank]
    
    success = True
    for b in banks:
        if not run_bank(b, use_db=args.db, do_eval=args.eval, do_sync=args.sync_db):
            success = False
            
    print("\n" + "=" * 65)
    print("   ALL REQUESTED PIPELINES FINISHED")
    print("=" * 65 + "\n")
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
