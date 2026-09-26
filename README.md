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

## Removing customer_type from existing PostgreSQL data

If you already uploaded data before this change, drop the column from the
live table (this doesn't touch any other column or row):

```bash
python main.py db-drop-column --table raw_soa_master --column customer_type
```

Going forward, `python main.py sync-db` also strips `customer_type` from
the SOA file automatically before uploading, so it won't reappear on the
next sync even if your source CSV still has it.

All tunable numbers — DPD cap, behavioral-friction weights, NPA floor,
tier cutoffs — live in `config.py` and nowhere else.

## Fixes vs. the previous version

- `evaluate` no longer crashes when the SOA file has no `Risk Type` column
  (accuracy metrics are skipped with a message instead).
- Removed the unused `typing.Optional` import bug that broke the database
  pipeline on import.
- `config.py` weights, thresholds, and cutoffs are now actually read by the
  scoring logic — previously several (weights, tier cutoffs, NPA floor)
  were defined but silently ignored.
- No hardcoded DB password; credentials come from environment variables.
- Collapsed the bridge files (`run.py`, `compare.py`, `pipeline.py`, root
  `config.py`, `db_config.py`) into one entrypoint and one config file.
