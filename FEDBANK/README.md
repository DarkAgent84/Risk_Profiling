# Collections Risk Profiling Engine

A calibrated, multi-factor risk scoring engine for loan collections. Rebuilt
for a flat, predictable structure — one CLI, one config file, a handful of small
modules.

## Structure

```
risk_profiling/
├── main.py              # single CLI entrypoint: score / evaluate / sync-db
├── config.py             # all tunable numbers — the only file to edit for calibration
├── requirements.txt
├── .env.example           # optional DB credentials template
├── data/
│   ├── raw/               # put your SOA master + MIS collection CSVs here
│   └── processed/         # scored output lands here
└── src/
    ├── ingest.py          # file discovery, loading, schema normalization
    ├── features.py        # behavioral features from MIS receipts
    ├── scoring.py          # risk scoring + tiering rules
    ├── report.py           # portfolio summary + SOA comparison
    └── db.py               # optional PostgreSQL sync (only imported if used)
```

That's it — no bridge files and no duplicate config.

## Quick start

```bash
pip install -r requirements.txt

# Run risk scoring (automatically discovers Fedbank_Customer.csv and Fedbank_Collection.csv):
python main.py score

# Compare model tiers against the Fedbank SOA's legacy "Risk Type" column:
python main.py evaluate
```

Custom paths:

```bash
python main.py score --soa data/raw/Fedbank_Customer.csv --mis data/raw/Fedbank_Collection.csv --out Fedbank_Risk_Scored.csv
python main.py evaluate --soa data/raw/Fedbank_Customer.csv --scored data/processed/Fedbank_Risk_Scored.csv
```

## Optional: run the whole pipeline through PostgreSQL / pgAdmin

By default everything runs on CSV files. If you'd rather stage the data in
PostgreSQL (and browse/query it in pgAdmin), two extra subcommands cover the
whole DB-driven flow — same `src/scoring.py` rules either way, nothing about
the model changes.

**1. Install the extra dependencies and set credentials:**

```bash
pip install psycopg2-binary sqlalchemy
cp .env.example .env   # fill in RISK_DB_PASSWORD (and host/user/dbname if not local defaults)
export $(cat .env | xargs)     # PowerShell: run `Get-Content .env` and set each var with $env:NAME
```

No database credentials are hardcoded anywhere in the code — they're read
from environment variables. `RISK_DB_PASSWORD` has no default and must be
set explicitly; host/port/user/dbname fall back to local Postgres defaults
if unset.

**2. Upload your raw CSVs into PostgreSQL:**

```bash
python main.py sync-db                          # Auto-discovers Client 2 files
python main.py sync-db --client client1         # Or upload Client 1
```

This creates the database (if it doesn't exist yet) and two tables:
`raw_soa_master` and `raw_mis_collections`. Open pgAdmin and you'll see them
under your configured database — good for spot-checking the raw data or
running your own SQL before scoring.

**3. Score directly from PostgreSQL:**

```bash
python main.py db-score
```

This fetches `raw_soa_master` / `raw_mis_collections` back out of Postgres,
runs the exact same ingest → features → scoring pipeline as `score`, prints
the same portfolio summary, and then:
- writes the results to a new PostgreSQL table, `scored_loan_risk_profiles`
  (replaced on each run — visible in pgAdmin immediately), and
- mirrors a CSV copy to `data/processed/risk_scored_loans.csv` so
  `python main.py evaluate` keeps working exactly as before, no changes
  needed on that side.

`score`/`evaluate` never need `psycopg2` installed — the database module is
only imported when you actually run `sync-db` or `db-score`.

## How scoring works

`customer_type` is never used as an input feature in risk scoring to prevent
target leakage — all loans are evaluated under the same objective escalation
rules. An algorithmic 4-class `customer_type` is independently computed by the
engine and included in the output alongside `soa_customer_type` for audit and
evaluation. All loans go through the same rule:

1. **Raw score (0–1)** — one uniform rule for every loan (see `src/scoring.py`),
   monotonic in severity so a worse bucket never scores below a better one:
   - Severity base from the worse of the bucket label and DPD
     (`0` < `1-29` < `30-59` < `60-89` < `90+`), plus small terms for DPD
     severity, overdue-dues exposure and receipt behaviour (rejections /
     partial payments).
   - Current loans carrying overdue dues or charges get a modest
     `bucket0_overdue_score` (below any delinquent bucket), not a High score.
   - Bounce-history evidence (collector assigned when it is a minority
     assignment, and `charges_2` / `charges_3` / `charges_payable` > 0) adds
     `w_ev` × evidence. The collector flag is ignored when >90% of loans have one.
   - Duplicate SOA loan numbers are dropped (first kept).
2. **NPA floor** — DPD >= `NPA_DPD_THRESHOLD` or `matured_overdue` floors the
   score at `npa_floor`, which is kept above the High cutoff so NPA is always High.
3. **Tier** — the final score maps to High / Medium / Low via `high_cut` /
   `med_cut`.

All of these numbers live in `DEFAULTS` in `src/scoring.py` (seeded from
`config.py`) and are overridden by `calibrated_params.json` when present.

## Calibration (`calibrate.py`)

```
python calibrate.py                 # search parameters, print held-out report (70/30 split)
python calibrate.py --apply         # also write calibrated_params.json
python calibrate.py --allow-npa-downgrade   # let NPA loans fall below High (policy decision)
```

It maximises agreement (macro-F1 plus a dues-weighted accuracy term) with the
legacy SOA `Risk Type`. Needs a labelled SOA. SBFC has none, so it ships a
conservative hand-set parameter file; recalibrate if you get labels/outcomes.
Caveat: the legacy label tracks bounce history, not DPD, so higher agreement is
not the same as better default prediction.

## Tests

```
python tests/test_scoring.py        # or: pytest tests
```

## matured_overdue (src/matured.py) — feeds the NPA floor

Reverse-engineered from the original `Customer Type = "Matured"` tag, but
computed from loan-tenure math (not a behavioral/outcome proxy, so it's safe
to use as a scoring input — unlike `customer_type` itself, which was found
to be leakage): `Emi due date < Cycle Date` (tenure has contractually
lapsed) **and** the loan is still carrying DPD or overdue arrears
(`overdue_dues`, not gross `total_dues`).

It floors `risk_score` to `config.NPA_FLOOR_SCORE`, the same floor used for
DPD>=90 loans. Most matured-overdue loans already hit that floor via DPD
anyway; the value this adds is catching the minority whose DPD/bucket data
hasn't (yet) crossed the 90-day threshold despite the loan's term being over.
`matured_overdue` is included in the output CSV/table for audit visibility.

## Rejection / bounce detection (src/features.py)

A receipt counts as a **bounce** if the payment never successfully landed —
whoever's fault it was. Specifically, any of:
- current `Instrument Status` is "Rejected by Operations" (or similar — matches
  `config.REJECTED_STATUS_KEYWORDS`), including administrative/paperwork rejections
  (wrong deposit slip, amount mismatch, etc.) — these still count, by design;
- `Rejection Count` is greater than 0 — rejected at some point, even if later
  re-submitted and approved. Checking current status alone misses this entirely;
- status is a cancelled/`Deleted` variant — the receipt was voided, so the payment
  never completed either way.

All three stay in the `total_receipts` denominator (nothing is dropped).

This mirrors the source data's own documented behavior: see the "Dataset Understanding &
Analysis Report" supplied with this project, §5 and §15 (A25 rejection funnel).

## Dual Columns: Customer Type & Bounce Type

The pipeline produces two complementary categorization columns for every loan:

### 1. `customer_type` (4-Class Banking Benchmark)
Preserves and predicts the core banking repayment profile:
- **`Never Bounce`**: Clean record, 0 bounces, current bucket, no bounce fees.
- **`Ever Bounce`**: 1+ historical bounces (bounce charges, overdue DPD/bucket, rejected receipts).
- **`Matured`**: Contractual tenure lapsed (`emi_due_date < cycle_date` or `matured_overdue`).
- **`3 MOB`**: Early vintage accounts (months on books 2–5 on Small Ticket LAP / Home Loan products).

### 2. `bounce_type` (8-Class Granular Specification)
Categorizes loans into the specific 8-tier operational attribute:
- **`Never Bounced`**: 0 no. of bounces (clean).
- **`Always Bounced`**: Bounce / rejection rate $\ge 60\%$.
- **`3 MOB`**: Disbursed date + 3 months bounce.
- **`4 MOB`**: Disbursed date + 4 months bounce.
- **`5 MOB`**: Disbursed date + 5 months bounce.
- **`6 MOB`**: Disbursed date + 6 months bounce.
- **`7+ MOB`**: Disbursed date + 7+ months bounce.
- **`Ever Bounced`**: 1+ bounces fallback (loans under 3 months old or general).

Running `python main.py evaluate` prints the cross-tabulation and evaluation metrics for both columns.

## Adaptive Schema Ingestion & Multi-Client Support

The pipeline automatically adapts to varying portfolio formats (such as Client 1 and Client 2):

1. **Intelligent Datatype Inference for Database Sync (`sync-db`)**:
   - **Identifiers & Text**: Empty or sparse columns (`co_applicant_2_address`, `action`, etc.), phone numbers, and alphanumeric codes (`user_id`, `instrument_collected_by_id`) are preserved as SQL `TEXT` rather than defaulting to `DOUBLE PRECISION`.
   - **Dates & Timestamps**: Automatically parses ISO and day-first date strings, assigning `TIMESTAMP WITHOUT TIME ZONE` to receipt logs and `DATE` to daily loan markers.
   - **Coordinates & Financials**: `latitude`/`longitude` map to `NUMERIC(10, 7)`; financial amounts, dues, and charges map to `NUMERIC(15, 2)`.

2. **Dynamic Delinquency & Bucket Normalization**:
   - If an SOA file provides `Bucket` but lacks an explicit `DPD` column (as in Client 2), the engine dynamically maps buckets (`0`, `1`, `2`, `3`, `3  Above`) to standardized DPDs and bucket groups (`0`, `1-29`, `30-59`, `60-89`, `90+`) without truncating string labels.
   - Robust date validation ensures absent `cycle_date` or `disbursal_date` fields default safely without runtime exceptions or artificial tenure lapses.


