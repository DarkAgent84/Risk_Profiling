"""
Bounce_Type: ONE column that categorizes every loan by its bounce history.

It is a descriptive label only — it does not change risk_score or risk_tier.

Categories
----------
  Never Bounced   0 bounces
  Ever Bounced    1+ bounces
  Always Bounced  bounce rate >= config.ALWAYS_BOUNCED_RATE (60% of receipts)
  3 MOB ... 6 MOB, 7+ MOB
                  bounced loan whose months on books (MOB) fall in that bucket.
                  MOB = whole months from disbursal_date to the report date
                  (cycle_date; today's date if the SOA has none).

A bounce = an MIS receipt whose instrument status matches
config.REJECTED_STATUS_KEYWORDS (already counted in features.py).

One column means one label per loan, and a loan can qualify for several
(e.g. bounced + 60%+ + 5 months old), so labels are assigned in a fixed
priority order — see PRIORITY below. The first that applies wins.
"""
import pandas as pd

import config


def _months_between(start: pd.Series, end: pd.Series) -> pd.Series:
    """Whole calendar months from start to end (a month counts once the day-of-month is reached)."""
    months = (end.dt.year - start.dt.year) * 12 + (end.dt.month - start.dt.month)
    months = months - (end.dt.day < start.dt.day).astype(int)
    return months.clip(lower=0)


def _mob_label(m) -> str | None:
    if pd.isna(m) or m < config.MOB_MIN:
        return None
    if m >= config.MOB_TOP:
        return f"{config.MOB_TOP}+ MOB"
    return f"{int(m)} MOB"


def _mob_labels(df: pd.DataFrame) -> pd.Series:
    """MOB bucket per loan (None if under MOB_MIN months or disbursal date is missing)."""
    if "disbursal_date" not in df.columns:
        print("[WARN] No 'Disbursal Date' column in SOA — MOB categories skipped.")
        return pd.Series(None, index=df.index, dtype=object)

    today = pd.Timestamp.today().normalize()
    if "cycle_date" in df.columns:
        ref = df["cycle_date"].fillna(today)
    else:
        ref = pd.Series(today, index=df.index)
    return _months_between(df["disbursal_date"], ref).map(_mob_label)


def add_bounce_type(df: pd.DataFrame) -> pd.DataFrame:
    """Add the single 'bounce_type' column."""
    df = df.copy()
    bounces = df["rejected_receipts"].fillna(0)
    rate = df["rejection_rate"].fillna(0.0)
    mob_label = _mob_labels(df)

    # PRIORITY (highest last — each line overwrites the ones above it):
    #   1. Never Bounced   4. Ever Bounced
    #   2. Always Bounced  3. N MOB
    bounce_type = pd.Series("Ever Bounced", index=df.index, dtype=object)   # 4. any other bounced loan
    has_mob = mob_label.notna()
    bounce_type[has_mob] = mob_label[has_mob]                                # 3. N MOB / 7+ MOB
    bounce_type[rate >= config.ALWAYS_BOUNCED_RATE] = "Always Bounced"       # 2.
    bounce_type[bounces == 0] = "Never Bounced"                              # 1.

    df["bounce_type"] = bounce_type
    return df
