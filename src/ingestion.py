"""
Data Ingestion and Schema Normalization Module
"""
import os
import re
import sys
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
from src import config


def normalize_column_name(col: str) -> str:
    """Standardize column header string into clean snake_case."""
    col = str(col).strip().lower()
    col = re.sub(r'[^0-9a-z]+', '_', col)
    return col.strip('_')


def find_raw_files() -> Tuple[Optional[Path], Optional[Path]]:
    """Automatically detect SOA Master and MIS Collection CSV files."""
    search_dirs = [config.RAW_DATA_DIR, config.DATA_DIR, config.BASE_DIR]
    
    soa_file = None
    mis_file = None

    for d in search_dirs:
        if not d.exists():
            continue
        candidates = sorted(d.glob("*.csv"), key=lambda p: ("copy" in p.name.lower(), p.name))
        for f in candidates:
            name = f.name.lower()
            if "soa" in name and not soa_file:
                soa_file = f
            elif ("mis" in name or "collection" in name) and not mis_file:
                if "risk" not in name and "scored" not in name:
                    mis_file = f
            if soa_file and mis_file:
                break
        if soa_file and mis_file:
            break

    return soa_file, mis_file


def load_datasets(soa_path: str | Path, mis_path: str | Path) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load, standardize headers, and typecast SOA and MIS datasets."""
    soa_path = Path(soa_path)
    mis_path = Path(mis_path)

    if not soa_path.exists():
        sys.exit(f"Error: SOA file not found at: {soa_path}")
    if not mis_path.exists():
        sys.exit(f"Error: MIS file not found at: {mis_path}")

    print(f"-> Loading SOA Master file: {soa_path.name}")
    soa = pd.read_csv(soa_path, low_memory=False)
    print(f"-> Loading MIS Collection file: {mis_path.name}")
    mis = pd.read_csv(mis_path, low_memory=False)

    soa.columns = [normalize_column_name(c) for c in soa.columns]
    mis.columns = [normalize_column_name(c) for c in mis.columns]

    # Required core schema columns
    required_soa = ['loan_number', 'dpd', 'total_dues']
    required_mis = ['loan_number', 'instrument_status', 'payment_type']

    missing_soa = [c for c in required_soa if c not in soa.columns]
    missing_mis = [c for c in required_mis if c not in mis.columns]

    if missing_soa:
        sys.exit(f"SOA file missing required column(s): {missing_soa}")
    if missing_mis:
        sys.exit(f"MIS file missing required column(s): {missing_mis}")

    # Coerce loan identifiers to clean strings
    soa['loan_number'] = soa['loan_number'].astype(str).str.strip()
    mis['loan_number'] = mis['loan_number'].astype(str).str.strip()

    # Numeric conversions
    soa['dpd'] = pd.to_numeric(soa['dpd'], errors='coerce').fillna(0)
    soa['total_dues'] = pd.to_numeric(soa['total_dues'], errors='coerce').fillna(0)

    for optional_num in ['total_loan_outstanding_amount', 'bucket', 'emi_amount', 'loan_amount', 'charges_payable', 'charges_2']:
        if optional_num in soa.columns:
            soa[optional_num] = pd.to_numeric(soa[optional_num], errors='coerce').fillna(0)

    if 'total_amount_collected' in mis.columns:
        mis['total_amount_collected'] = pd.to_numeric(mis['total_amount_collected'], errors='coerce').fillna(0)

    if 'payment_date' in mis.columns:
        mis['payment_date'] = pd.to_datetime(mis['payment_date'], errors='coerce', dayfirst=True)

    return soa, mis
