"""Smoke tests for the scoring engine. Run from the bank folder: python tests/test_scoring.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd

from src.scoring import DEFAULTS, apply_score, score_portfolio

BEH = pd.DataFrame({"loan_number": ["c"], "total_receipts": [3], "rejected_receipts": [1],
                    "rejection_rate": [0.33], "partial_payment_rate": [0.0]})


# Pin to built-in defaults so tests do not depend on calibrated_params.json
PARAMS = {**DEFAULTS, "w_ev": 0.0}


def _soa():
    return pd.DataFrame({
        "loan_number": ["a", "b", "c", "d", "e", "f", "f"],
        "bucket_group": ["0", "0", "1-29", "30-59", "60-89", "90+", "90+"],
        "dpd": [0, 0, 10, 40, 70, 120, 120],
        "total_dues": [0, 500, 2000, 5000, 9000, 20000, 20000],
        "overdue_dues": [0, 500, 2000, 5000, 9000, 20000, 20000],
        "charges_payable": [0] * 7,
    })


def test_severity_is_monotonic_and_deduped():
    r = score_portfolio(_soa(), BEH, params=PARAMS)
    assert r["loan_number"].is_unique
    s = r.set_index("loan_number")["risk_score"]
    assert s["a"] < s["b"] < s["c"] < s["d"] < s["e"] <= s["f"]


def test_current_loan_with_small_dues_is_not_high():
    r = score_portfolio(_soa(), BEH, params=PARAMS).set_index("loan_number")
    assert r.loc["b", "risk_tier"] != "High"


def test_npa_is_high_and_clean_is_low():
    r = score_portfolio(_soa(), BEH, params=PARAMS).set_index("loan_number")
    assert r.loc["f", "risk_tier"] == "High"
    assert r.loc["a", "risk_tier"] == "Low"


def test_tiers_follow_cutoffs():
    r = score_portfolio(_soa(), BEH, params=PARAMS)
    hi, me = DEFAULTS["high_cut"], DEFAULTS["med_cut"]
    for _, row in r.iterrows():
        exp = "High" if row.risk_score >= hi else "Medium" if row.risk_score >= me else "Low"
        assert row.risk_tier == exp


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
