"""
Borrower Collection Behavior Feature Engineering
"""
import pandas as pd
from src import config


def extract_behavioral_features(mis: pd.DataFrame) -> pd.DataFrame:
    """Aggregate transactional collection receipts into per-loan behavioral features."""
    mis = mis.copy()

    instrument_status_clean = mis['instrument_status'].astype(str).str.strip().str.lower()
    payment_type_clean = mis['payment_type'].astype(str).str.strip().str.lower()

    pattern = '|'.join(config.REJECTED_STATUS_KEYWORDS)
    mis['is_rejected'] = instrument_status_clean.str.contains(pattern, regex=True).astype(int)
    mis['is_partial'] = (payment_type_clean == config.PARTIAL_PAYMENT_KEYWORD).astype(int)

    agg_dict = {
        'is_rejected': ['count', 'sum', 'mean'],
        'is_partial': 'mean',
    }

    if 'total_amount_collected' in mis.columns:
        agg_dict['total_amount_collected'] = 'sum'
    if 'payment_date' in mis.columns:
        agg_dict['payment_date'] = 'max'

    grouped = mis.groupby('loan_number').agg(agg_dict)
    grouped.columns = ['_'.join(c).strip('_') if isinstance(c, tuple) else c for c in grouped.columns]

    rename_map = {
        'is_rejected_count': 'total_receipts',
        'is_rejected_sum': 'rejected_receipts',
        'is_rejected_mean': 'rejection_rate',
        'is_partial_mean': 'partial_payment_rate',
        'total_amount_collected_sum': 'total_collected',
        'payment_date_max': 'last_payment_date',
    }
    return grouped.rename(columns=rename_map).reset_index()
