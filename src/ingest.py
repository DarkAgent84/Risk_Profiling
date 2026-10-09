"""
Data ingestion: auto-discover input files, load them, and normalize schema.
"""
import re
import sys
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd

import config


def normalize_column_name(col: str) -> str:
    """'Total Dues (INR)' -> 'total_dues_inr'"""
    col = str(col).strip().lower()
    col = re.sub(r"[^0-9a-z]+", "_", col)
    return col.strip("_")


def find_raw_files(client: Optional[str] = None) -> Tuple[Optional[Path], Optional[Path]]:
    """Look for an SOA master file and an MIS collections file in data/raw (or project root).

    Supports optional client specification: 'client2' (default when Client2 files are present)
    or 'client1', as well as generic auto-discovery.
    """
    search_dirs = [config.RAW_DATA_DIR, config.BASE_DIR]

    if client:
        c_lower = client.lower().strip()
        for d in search_dirs:
            if not d.exists():
                continue
            # Look for files matching the client name
            c_soa = list(d.glob(f"*{c_lower}*customer*.csv")) + list(d.glob(f"*{c_lower}*soa*.csv"))
            c_mis = list(d.glob(f"*{c_lower}*collection*.csv")) + list(d.glob(f"*{c_lower}*mis*.csv"))
            # Also check client subdirectories (e.g. data/raw/Client1/)
            for sub in d.glob("*"):
                if sub.is_dir() and c_lower in sub.name.lower():
                    c_soa += list(sub.glob("*customer*.csv")) + list(sub.glob("*soa*.csv"))
                    c_mis += list(sub.glob("*collection*.csv")) + list(sub.glob("*mis*.csv"))
            soa = c_soa[0] if c_soa else None
            mis = c_mis[0] if c_mis else None
            if soa and mis:
                return soa, mis

    soa_file, mis_file = None, None

    # Priority 1: Check data/raw for Client 2 files directly
    for d in search_dirs:
        if not d.exists():
            continue
        # Sort so client2 files are picked first when present in data/raw
        candidates = sorted(
            d.glob("*.csv"),
            key=lambda p: (
                0 if "client2" in p.name.lower() else (1 if "client" in p.name.lower() else 2),
                "copy" in p.name.lower(),
                p.name,
            ),
        )
        for f in candidates:
            name = f.name.lower()
            if ("soa" in name or "customer" in name) and not soa_file:
                soa_file = f
            elif ("mis" in name or "collection" in name) and "risk" not in name and "scored" not in name and not mis_file:
                mis_file = f
        if soa_file and mis_file:
            break

    # Priority 2: Check subdirectories (e.g. data/raw/Client1/)
    if not soa_file or not mis_file:
        for d in search_dirs:
            if not d.exists():
                continue
            for sub in d.glob("*"):
                if sub.is_dir() and not sub.name.startswith("."):
                    candidates = sorted(sub.glob("*.csv"), key=lambda p: ("copy" in p.name.lower(), p.name))
                    for f in candidates:
                        name = f.name.lower()
                        if ("soa" in name or "customer" in name) and not soa_file:
                            soa_file = f
                        elif ("mis" in name or "collection" in name) and "risk" not in name and "scored" not in name and not mis_file:
                            mis_file = f
                    if soa_file and mis_file:
                        break

    return soa_file, mis_file


def _drop_blank_loan_numbers(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """Drop rows with a missing/blank loan_number before it gets cast to the literal string 'nan'.

    Without this, blank loan numbers on both sides of a join collapse into a
    single fake match (every blank == every other blank), which silently
    corrupts the behavior-feature join and the risk summary.
    """
    blank_mask = df["loan_number"].isna() | (df["loan_number"].astype(str).str.strip() == "")
    n_blank = int(blank_mask.sum())
    if n_blank:
        print(f"-> Dropping {n_blank:,} {source_name} row(s) with a blank loan number")
        df = df[~blank_mask].copy()
    return df


def prepare_soa(soa: pd.DataFrame) -> pd.DataFrame:
    """Standardize headers and typecast an SOA dataframe, regardless of where it came from (CSV or DB)."""
    soa = soa.copy()
    soa.columns = [normalize_column_name(c) for c in soa.columns]

    if "loan_number" not in soa.columns:
        sys.exit("SOA data missing required column: 'loan_number'")

    soa = _drop_blank_loan_numbers(soa, "SOA")
    soa["loan_number"] = soa["loan_number"].astype(str).str.strip()

    # customer_type is retained for audit/evaluation, but never used as an input to risk scoring.
    if "customer_type" in soa.columns:
        soa["customer_type"] = soa["customer_type"].astype(str).str.strip()
        soa["customer_type"] = soa["customer_type"].replace({"nan": None, "None": None, "": None})

    # Total dues handling (primary: total_dues, fallback: emi_pemi_dues)
    if "total_dues" in soa.columns:
        soa["total_dues"] = pd.to_numeric(soa["total_dues"], errors="coerce").fillna(0)
    elif "emi_pemi_dues" in soa.columns:
        soa["total_dues"] = pd.to_numeric(soa["emi_pemi_dues"], errors="coerce").fillna(0)
    else:
        soa["total_dues"] = 0.0

    # Retain raw unclipped dues if negative (advance balance indicator), but floor total_dues at 0 for exposure
    if (soa["total_dues"] < 0).any():
        soa["total_dues_net"] = soa["total_dues"]
        soa["total_dues"] = np.maximum(0.0, soa["total_dues"])

    # Standardize bucket label format (remove internal multi-spaces e.g. '3  Above' -> '3+')
    if "bucket" in soa.columns:
        soa["bucket"] = soa["bucket"].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
        soa["bucket"] = soa["bucket"].replace({
            "nan": "0", "None": "0", "": "0",
            "3 Above": "3+", "3 & Above": "3+", "3  Above": "3+"
        })

    # DPD and Bucket Group handling (in Client 2, DPD may not be present, but Bucket is)
    if "dpd" not in soa.columns:
        if "bucket" in soa.columns:
            print("-> Note: 'dpd' column not in SOA. Deriving 'dpd' and 'bucket_group' from 'bucket'...")
            def _bucket_to_dpd(b):
                b_str = str(b).strip().lower()
                if b_str in ["0", "0.0"]:
                    return 0.0
                elif b_str in ["1", "1.0"]:
                    return 15.0
                elif b_str in ["2", "2.0"]:
                    return 45.0
                elif b_str in ["3", "3.0"]:
                    return 75.0
                elif "above" in b_str or "+" in b_str:
                    return 90.0
                try:
                    num = float(b_str)
                    if num == 0: return 0.0
                    elif num == 1: return 15.0
                    elif num == 2: return 45.0
                    elif num == 3: return 75.0
                    elif num >= 4: return 90.0
                except ValueError:
                    pass
                return 0.0

            soa["dpd"] = soa["bucket"].apply(_bucket_to_dpd)
        else:
            soa["dpd"] = 0.0
    else:
        soa["dpd"] = pd.to_numeric(soa["dpd"], errors="coerce").fillna(0)

    # Bucket group standardization (used for risk scoring escalation)
    if "bucket_group" not in soa.columns:
        if "bucket" in soa.columns:
            def _bucket_to_group(b):
                b_str = str(b).strip().lower()
                if b_str in ["0", "0.0"]:
                    return "0"
                elif b_str in ["1", "1.0"]:
                    return "1-29"
                elif b_str in ["2", "2.0"]:
                    return "30-59"
                elif b_str in ["3", "3.0"]:
                    return "60-89"
                elif "above" in b_str or "+" in b_str:
                    return "90+"
                try:
                    num = float(b_str)
                    if num == 0: return "0"
                    elif num == 1: return "1-29"
                    elif num == 2: return "30-59"
                    elif num == 3: return "60-89"
                    elif num >= 4: return "90+"
                except ValueError:
                    pass
                return "0"

            soa["bucket_group"] = soa["bucket"].apply(_bucket_to_group)
        else:
            soa["bucket_group"] = soa["dpd"].apply(
                lambda d: "0" if d <= 0 else ("1-29" if d < 30 else ("30-59" if d < 60 else ("60-89" if d < 90 else "90+")))
            )

    # Preserve bucket as string
    if "bucket" in soa.columns:
        soa["bucket"] = soa["bucket"].astype(str).str.strip().replace({"nan": "0", "None": "0", "": "0"})

    # Numeric amount fields
    numeric_amount_cols = [
        "total_loan_outstanding_amount", "emi_amount", "loan_amount",
        "loan_principle_balance_amount", "charges_payable", "charges_2",
        "charges_3", "settlement_amount", "emi_pemi_dues"
    ]
    for col in numeric_amount_cols:
        if col in soa.columns:
            soa[col] = pd.to_numeric(soa[col], errors="coerce").fillna(0)

    # Overdue dues calculation:
    # Some lending systems (e.g. Client 2) bill gross cumulative dues including the current cycle's EMI
    # rather than only delinquent/overdue arrears.
    # For clean loans (Bucket 0 / 0 DPD) where total_dues matches current installment, overdue_dues = max(0, total_dues - emi).
    emi_val = pd.to_numeric(soa.get("emi_amount", 0), errors="coerce").fillna(0)
    bkt_str = soa.get("bucket", "").astype(str).str.strip().str.lower()
    dpd_val = soa.get("dpd", pd.Series(0, index=soa.index))
    bkt_is_zero = bkt_str.isin(["0", "0.0"]) | (dpd_val <= 0)
    dues_matches_emi = bkt_is_zero & (soa["total_dues"] > 0) & (soa["total_dues"] <= emi_val * 1.05)
    if dues_matches_emi.any():
        soa["overdue_dues"] = np.where(dues_matches_emi, np.maximum(0.0, soa["total_dues"] - emi_val), soa["total_dues"])
    else:
        soa["overdue_dues"] = np.maximum(0.0, soa["total_dues"])
    soa["overdue_dues"] = np.maximum(0.0, soa["overdue_dues"])

    # Dates used for months-on-books (MOB) and the matured-overdue check
    for col in ["disbursal_date", "cycle_date", "emi_due_date"]:
        if col in soa.columns:
            soa[col] = pd.to_datetime(soa[col], errors="coerce", dayfirst=True)

    return soa


def prepare_mis(mis: pd.DataFrame) -> pd.DataFrame:
    """Standardize headers and typecast an MIS dataframe, regardless of where it came from (CSV or DB)."""
    mis = mis.copy()
    mis.columns = [normalize_column_name(c) for c in mis.columns]

    if "loan_number" not in mis.columns:
        sys.exit("MIS data missing required column: 'loan_number'")

    mis = _drop_blank_loan_numbers(mis, "MIS")
    mis["loan_number"] = mis["loan_number"].astype(str).str.strip()

    # Clean text status fields (strip whitespace and handle empty values)
    if "instrument_status" not in mis.columns:
        mis["instrument_status"] = ""
    else:
        mis["instrument_status"] = mis["instrument_status"].astype(str).str.strip().replace({"nan": "", "None": ""})

    if "payment_type" not in mis.columns:
        mis["payment_type"] = ""
    else:
        mis["payment_type"] = mis["payment_type"].astype(str).str.strip().replace({"nan": "", "None": ""})

    if "receipt_status" not in mis.columns:
        mis["receipt_status"] = ""
    else:
        mis["receipt_status"] = mis["receipt_status"].astype(str).str.strip().replace({"nan": "", "None": ""})

    # Numeric collections and charges
    amount_cols = [
        "total_amount_collected", "total_dues", "charges_payable", "penal",
        "bcc", "emi_pemi_dues", "total_emi_due", "cash_handling_charges",
        "legal_charges", "foreclosure_charges", "charge_7", "charge_8",
        "charge_9", "charge_10"
    ]
    for col in amount_cols:
        if col in mis.columns:
            mis[col] = pd.to_numeric(mis[col], errors="coerce").fillna(0)

    # Dates
    for col in ["payment_date", "submit_date", "business_date", "instrument_date"]:
        if col in mis.columns:
            mis[col] = pd.to_datetime(mis[col], errors="coerce", dayfirst=True)

    # Rejection Count
    if "rejection_count" in mis.columns:
        mis["rejection_count"] = pd.to_numeric(mis["rejection_count"], errors="coerce").fillna(0)

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
