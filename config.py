"""
Collections Risk Profiling — Configuration
===========================================
Every value below is actually read by src/scoring.py. If you change a
number here, model output changes. There is no hidden/duplicate logic
elsewhere — this file is the single source of truth for tuning.
"""
import os
from pathlib import Path

# --- Paths ---
BASE_DIR = Path(__file__).resolve().parent
RAW_DATA_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DATA_DIR = BASE_DIR / "data" / "processed"
DEFAULT_OUTPUT_FILE = PROCESSED_DATA_DIR / "risk_scored_loans.csv"

# --- Delinquency / Exposure normalization ---
DPD_CAP_CEILING = 180            # DPD values are clipped to this before normalizing to 0-1

# --- NPA safety floor ---
# Any loan at or beyond this many days-past-due is floored at NPA_FLOOR_SCORE,
# regardless of what business-rule branch it fell into below.
NPA_DPD_THRESHOLD = 90
NPA_FLOOR_SCORE = 0.75

# --- Behavioral friction blend (used for "ever bounce" accounts in Bucket 0+) ---
BEHAVIOR_REJECTION_WEIGHT = 0.60   # share of behavior score from payment bounce/rejection rate
BEHAVIOR_PARTIAL_WEIGHT = 0.40     # share of behavior score from partial-payment incidence rate
UNWORKED_OVERDUE_PENALTY = 0.50    # score applied when a loan is overdue but has no collection attempts on record

# --- Risk tier cutoffs ---
# The final numeric score (after the NPA floor is applied) is mapped to a
# tier using these cutoffs. This mapping is now the ONLY place tier labels
# are decided — scoring.py never hardcodes a label next to a score.
TIER_HIGH_CUTOFF = 0.66          # score >= this -> High
TIER_MEDIUM_CUTOFF = 0.33        # score >= this (and < High) -> Medium; below -> Low

# --- MIS keyword flags ---
REJECTED_STATUS_KEYWORDS = ["reject", "bounce", "disapprov", "fail"]
PARTIAL_PAYMENT_KEYWORD = "part payment"

# --- Bucket labels Excel commonly mangles into a date (e.g. "1-29" -> "Jan-29") ---
EARLY_BUCKET_ALIASES = {"jan-29", "1-29"}

# --- Database (optional; only needed if you use `python main.py sync-db` / `evaluate --from-db`) ---
DB_CONFIG = {
    "host": os.environ.get("RISK_DB_HOST", "localhost"),
    "port": int(os.environ.get("RISK_DB_PORT", "5432")),
    "user": os.environ.get("RISK_DB_USER", "postgres"),
    "password": os.environ.get("RISK_DB_PASSWORD", ""),   # set RISK_DB_PASSWORD env var — no default credential
    "dbname": os.environ.get("RISK_DB_NAME", "collections_risk_profiling"),
}
