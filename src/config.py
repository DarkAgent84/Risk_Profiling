"""
Configuration, Model Weights, and Project Paths
"""
from pathlib import Path

# --- Model Weights ---
WEIGHT_SEVERITY = 0.45          # Delinquency severity weight (DPD)
WEIGHT_EXPOSURE = 0.20          # Monetary exposure weight (Total Dues)
WEIGHT_BEHAVIOR = 0.35          # Behavioral collection friction weight

# Behavioral component weights
BEHAVIOR_REJECTION_WEIGHT = 0.60   # Share for payment bounce/rejection rate
BEHAVIOR_PARTIAL_WEIGHT = 0.40     # Share for partial payment incidence rate

# --- Risk Thresholds ---
DPD_CAP_CEILING = 180           # DPD capping ceiling for normalization
NPA_DPD_THRESHOLD = 90          # 90+ DPD threshold for severe default / NPA
NPA_FLOOR_SCORE = 0.75          # Minimum risk score enforced for 90+ DPD accounts
UNWORKED_OVERDUE_PENALTY = 0.50 # Penalty score for overdue loans with no collection attempts

# --- Risk Tier Cutoffs ---
TIER_HIGH_CUTOFF = 0.66         # >= 0.66: High
TIER_MEDIUM_CUTOFF = 0.33       # 0.33 - 0.66: Medium, < 0.33: Low

# --- MIS Keyword Flags ---
REJECTED_STATUS_KEYWORDS = ['reject', 'bounce', 'disapprov', 'fail']
PARTIAL_PAYMENT_KEYWORD = 'part payment'

# --- Directory Paths ---
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
DEFAULT_OUTPUT_FILE = PROCESSED_DATA_DIR / "risk_scored_loans.csv"
