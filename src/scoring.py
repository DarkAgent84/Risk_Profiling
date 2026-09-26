"""
Calibrated Multi-Factor Risk Scoring and Tiering Engine
"""
import numpy as np
import pandas as pd
from src import config


def compute_risk_profile(soa: pd.DataFrame, behavior: pd.DataFrame, dpd_cap: float = config.DPD_CAP_CEILING) -> pd.DataFrame:
    """Merge datasets and compute calibrated multi-factor risk scores and tiers."""
    overlap_cols = [c for c in behavior.columns if c in soa.columns and c != 'loan_number']
    soa_clean = soa.drop(columns=overlap_cols) if overlap_cols else soa

    df = soa_clean.merge(behavior, on='loan_number', how='left')

    df['never_worked'] = df['total_receipts'].isna()
    df['total_receipts'] = df['total_receipts'].fillna(0).astype(int)
    df['rejected_receipts'] = df['rejected_receipts'].fillna(0).astype(int)
    df['rejection_rate'] = df['rejection_rate'].fillna(0.0).round(4)
    df['partial_payment_rate'] = df['partial_payment_rate'].fillna(0.0).round(4)
    if 'total_collected' in df.columns:
        df['total_collected'] = df['total_collected'].fillna(0.0)

    # 1. Delinquency Severity Normalization
    df['dpd_norm'] = np.clip(df['dpd'] / float(dpd_cap), 0.0, 1.0)

    # 2. Monetary Exposure Normalization (Log1p scale)
    max_dues = df['total_dues'].max()
    max_log_dues = np.log1p(max_dues) if max_dues > 0 else 1.0
    df['dues_norm'] = np.log1p(np.maximum(0, df['total_dues'])) / max_log_dues

    # 3. Behavioral Friction Score
    worked_behavior_score = (
        config.BEHAVIOR_REJECTION_WEIGHT * df['rejection_rate'] +
        config.BEHAVIOR_PARTIAL_WEIGHT * df['partial_payment_rate']
    )
    df['behavior_score'] = np.where(
        df['never_worked'],
        np.where(df['dpd'] > 0, config.UNWORKED_OVERDUE_PENALTY, 0.0),
        worked_behavior_score
    )

    # 4. Calibrated Domain-Aware Risk Tier Scoring
    def calculate_loan_risk(row):
        cust = str(row.get('customer_type', '')).strip().lower()
        bkt = str(row.get('bucket_group', '')).strip().lower()
        dpd = float(row.get('dpd', 0) or 0)
        dues = float(row.get('total_dues', 0) or 0)
        beh_score = float(row.get('behavior_score', 0) or 0)
        dpd_norm = float(row.get('dpd_norm', 0) or 0)
        dues_norm = float(row.get('dues_norm', 0) or 0)

        # 1. Early Vintage: 3 MOB
        if cust == '3 mob':
            return 0.10, '3 MOB'

        charges = float(row.get('charges_payable', 0) or 0)
        charges2 = float(row.get('charges_2', 0) or 0)
        receipts = float(row.get('total_receipts', 0) or 0)

        # 2. Never Bounce accounts (clean repayment history)
        if cust == 'never bounce':
            if bkt in ['jan-29', '1-29']:
                return 0.40, 'Medium'
            if bkt == '0':
                if (dues > 500 or charges > 500) and (receipts > 0 or dues > 2000):
                    return 0.40, 'Medium'
                return 0.05, 'Low'
            return 0.05, 'Low'

        # 3. Ever Bounce accounts (historically bounced)
        if cust == 'ever bounce':
            if bkt in ['jan-29', '1-29', '30-59', '60-89', '90+'] or dpd > 0:
                score = max(0.70, 0.40 + 0.30 * dpd_norm + 0.15 * dues_norm + 0.15 * beh_score)
                return round(min(score, 1.0), 3), 'High'
            # In Bucket 0 (DPD == 0)
            if dues > 0 or charges > 0 or receipts > 0 or charges2 > 0:
                return 0.70, 'High'
            return 0.45, 'Medium'

        # 4. Matured accounts (completed tenure)
        if cust == 'matured':
            if bkt in ['30-59', '60-89', 'jan-29', '1-29'] and (dues > 0 or charges > 0):
                return 0.75, 'High'
            elif bkt == '0' and (dues > 5000 or charges > 5000):
                return 0.40, 'Medium'
            return 0.05, 'Low'

        # 5. Fallback for unassigned / DND
        return 0.05, 'Low'

    scores_and_tiers = df.apply(calculate_loan_risk, axis=1)
    df['risk_score'] = [s[0] for s in scores_and_tiers]
    df['risk_tier'] = [s[1] for s in scores_and_tiers]

    return df
