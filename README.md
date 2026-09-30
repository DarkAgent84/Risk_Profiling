# Collections Risk Profiling Engine

A calibrated, multi-factor risk scoring engine for loan collections. Rebuilt
for a flat, predictable structure — one CLI, one config file, four small
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

That's it — no bridge files, no duplicate config, no dead code paths.

## Quick start

```bash
pip install -r requirements.txt

# Drop your SOA master CSV and MIS collection CSV into data/raw/, then:
python main.py score

# Compare model tiers against the SOA's legacy "Risk Type" column:
python main.py evaluate
```

Custom paths:

```bash
python main.py score --soa data/raw/soa.csv --mis data/raw/mis.csv --out my_scored.csv
python main.py evaluate --soa data/raw/soa.csv --scored data/processed/my_scored.csv
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
python main.py sync-db --soa data/raw/Customer_Data.csv --mis data/raw/Collection_Data.csv
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

`customer_type` is not used anywhere in this pipeline — it's excluded on
ingestion (`src/ingest.py`), never referenced in scoring, and never appears
in output. All loans go through the same rule:

1. **Raw score (0–1)** — one uniform bucket/DPD escalation rule applies to
   every loan (see `src/scoring.py`):
   - Bucket in `30-59` / `60-89` / `90+` (or an Excel-mangled early-bucket
     alias), or any positive DPD → escalated: at least 0.70, scaled up
     further by DPD severity, dues exposure, and behavioral friction.
   - Bucket `0` (current) but still carrying dues, charges, or receipt
     activity → 0.70.
   - Otherwise (current, nothing owed, no activity) → 0.05.
2. **NPA floor** — any loan at or beyond `config.NPA_DPD_THRESHOLD` days
   past due is floored at `config.NPA_FLOOR_SCORE`, applied uniformly to
   every loan (there's no early-vintage exemption any more, since that
   concept depended on `customer_type == "3 MOB"`).
3. **Tier** — the *final* score (after the floor) is mapped to
   High / Medium / Low using `config.TIER_HIGH_CUTOFF` /
   `config.TIER_MEDIUM_CUTOFF`. This is the only place a tier label is
   decided — changing a cutoff in `config.py` immediately changes output,
   with no hardcoded label anywhere else to keep in sync.

## matured_overdue (src/matured.py) — feeds the NPA floor

Reverse-engineered from the original `Customer Type = "Matured"` tag, but
computed from loan-tenure math (not a behavioral/outcome proxy, so it's safe
to use as a scoring input — unlike `customer_type` itself, which was found
to be leakage): `Emi due date < Cycle Date` (tenure has contractually
lapsed) **and** the loan is still carrying DPD or dues.

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

## Bounce_Type (Granular 8-Category Specification)

A descriptive classification column computed in `src/bounce.py` that categorizes every loan by its bounce incidence and vintage progression:

| Category | Definition | Qualification Rule |
|---|---|---|
| `Never Bounced` | 0 no. of Bounces | Clean record: no rejected receipts, zero bounce charges, Bucket 0 |
| `Ever Bounced` | 1+ no. of Bounces | Bounced account with unassigned MOB or under 3 months on book |
| `Always Bounced` | 60%+ Bounces | Bounced account with rejection rate $\ge$ 60% of MIS receipts |
| `3 MOB` | Disburse date + 3 month bounce | Bounced account with 3 months on books |
| `4 MOB` | Disburse date + 4 month bounce | Bounced account with 4 months on books |
| `5 MOB` | Disburse date + 5 month bounce | Bounced account with 5 months on books |
| `6 MOB` | Disburse date + 6 month bounce | Bounced account with 6 months on books |
| `7+ MOB` | Disburse date + 7+ month bounce | Bounced account with 7 or more months on books |

- **Evaluation**: Running `python main.py evaluate` compares granular `bounce_type` against the legacy 4-class `Customer Type` with full cross-tabulation and mapped alignment.

