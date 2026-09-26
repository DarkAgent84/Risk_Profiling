"""
Data ingestion: auto-discover input files, load them, and normalize schema.
"""
import re
import sys
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

import config


def normalize_column_name(col: str) -> str:
    """'Total Dues (INR)' -> 'total_dues_inr'"""
    col = str(col).strip().lower()
    col = re.sub(r"[^0-9a-z]+", "_", col)
    return col.strip("_")


def find_raw_files() -> Tuple[Optional[Path], Optional[Path]]:
    """Look for an SOA master file and an MIS collections file in data/raw (or project root)."""
    search_dirs = [config.RAW_DATA_DIR, config.BASE_DIR]
    soa_file, mis_file = None, None

    for d in search_dirs:
        if not d.exists():
            continue
        candidates = sorted(d.glob("*.csv"), key=lambda p: ("copy" in p.name.lower(), p.name))
        for f in candidates:
            name = f.name.lower()
            if "soa" in name and not soa_file:
                soa_file = f
            elif ("mis" in name or "collection" in name) and "risk" not in name and "scored" not in name and not mis_file:
                mis_file = f
        if soa_file and mis_file:
            break

    return soa_file, mis_file


def prepare_soa(soa: pd.DataFrame) -> pd.DataFrame:
    """Standardize headers and typecast an SOA dataframe, regardless of where it came from (CSV or DB)."""
    soa = soa.copy()
    soa.columns = [normalize_column_name(c) for c in soa.columns]

    # customer_type is intentionally excluded from this pipeline — it is not
    # used as a scoring input and should not appear in output either.
    if "customer_type" in soa.columns:
        soa = soa.drop(columns=["customer_type"])

    missing = [c for c in ["loan_number", "dpd", "total_dues"] if c not in soa.columns]
    if missing:
        sys.exit(f"SOA data missing required column(s): {missing}")

    soa["loan_number"] = soa["loan_number"].astype(str).str.strip()
    soa["dpd"] = pd.to_numeric(soa["dpd"], errors="coerce").fillna(0)
    soa["total_dues"] = pd.to_numeric(soa["total_dues"], errors="coerce").fillna(0)

    for col in ["total_loan_outstanding_amount", "bucket", "emi_amount", "loan_amount", "charges_payable", "charges_2"]:
        if col in soa.columns:
            soa[col] = pd.to_numeric(soa[col], errors="coerce").fillna(0)

    return soa


def prepare_mis(mis: pd.DataFrame) -> pd.DataFrame:
    """Standardize headers and typecast an MIS dataframe, regardless of where it came from (CSV or DB)."""
    mis = mis.copy()
    mis.columns = [normalize_column_name(c) for c in mis.columns]

    missing = [c for c in ["loan_number", "instrument_status", "payment_type"] if c not in mis.columns]
    if missing:
        sys.exit(f"MIS data missing required column(s): {missing}")

    mis["loan_number"] = mis["loan_number"].astype(str).str.strip()
    if "total_amount_collected" in mis.columns:
        mis["total_amount_collected"] = pd.to_numeric(mis["total_amount_collected"], errors="coerce").fillna(0)
    if "payment_date" in mis.columns:
        mis["payment_date"] = pd.to_datetime(mis["payment_date"], errors="coerce", dayfirst=True)

    return mis


def load_datasets(soa_path: str | Path, mis_path: str | Path) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load the two required CSVs from disk, then standardize + typecast them."""
    soa_path, mis_path = Path(soa_path), Path(mis_path)

    if not soa_path.exists():
        sys.exit(f"Error: SOA file not found at: {soa_path}")
    if not mis_path.exists():
        sys.exit(f"Error: MIS file not found at: {mis_path}")

    print(f"-> Loading SOA master file: {soa_path.name}")
    soa = pd.read_csv(soa_path, low_memory=False)
    print(f"-> Loading MIS collection file: {mis_path.name}")
    mis = pd.read_csv(mis_path, low_memory=False)

    return prepare_soa(soa), prepare_mis(mis)
