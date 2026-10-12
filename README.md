# Collections Risk Profiling Platform

Multi-factor collections risk scoring engines for **Fedbank** and **SBFC**.

## Repository Structure

```
Risk_Profiling/
├── run_all.py              # Unified CLI runner for both portfolios
├── requirements.txt        # Shared dependencies
├── README.md               # Main repository documentation
│
├── FEDBANK/                # Fedbank (Federal Bank / Fedfina) Portfolio
│   ├── main.py             # CLI entrypoint: score / evaluate / sync-db / db-score
│   ├── config.py           # Fedbank scoring parameters & cutoffs
│   ├── data/
│   │   ├── raw/            # Fedbank_Customer.csv & Fedbank_Collection.csv (+ DDL/dumps)
│   │   └── processed/      # Fedbank_Risk_Scored.csv
│   └── src/                # Ingestion, behavioral features, scoring, reporting, db
│
└── SBFC/                   # SBFC Finance Portfolio
    ├── main.py             # CLI entrypoint: score / evaluate / sync-db / db-score
    ├── config.py           # SBFC scoring parameters & cutoffs
    ├── data/
    │   ├── raw/            # SBFC_Customer.csv & SBFC_Collection.csv
    │   └── processed/      # SBFC_Risk_Scored.csv
    └── src/                # Ingestion, behavioral features, scoring, reporting, db
```

---

## Quick Start

### 1. Installation
```bash
pip install -r requirements.txt
```

### 2. Run Both Portfolios (Unified Runner)
```bash
# Run risk scoring across both banks:
python run_all.py

# Run scoring and benchmark evaluations:
python run_all.py --eval

# Run scoring directly from and back to PostgreSQL:
python run_all.py --db

# Run for a specific bank only:
python run_all.py --bank fedbank
python run_all.py --bank sbfc
```

---

## Running Per Bank

### Fedbank
```bash
cd FEDBANK
python main.py score               # File-based scoring
python main.py evaluate            # Evaluate against SOA Risk Type benchmark
python main.py db-score            # Score directly via PostgreSQL
python main.py sync-db             # Sync CSVs to PostgreSQL tables
```

### SBFC
```bash
cd SBFC
python main.py score               # File-based scoring
python main.py evaluate            # Generate tier & dues distributions
python main.py db-score            # Score directly via PostgreSQL
python main.py sync-db             # Sync CSVs to PostgreSQL tables
```
