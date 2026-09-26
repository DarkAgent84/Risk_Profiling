# Collections Risk Profiling Engine

A production-grade, modular collections risk profiling and portfolio segmentation engine for credit risk management.

---

## 📁 Restructured Project Layout

```text
Risk Profiling/
│
├── data/
│   ├── raw/                  # Place raw input CSV files here (SOA Master, MIS Report)
│   └── processed/            # Output directory for risk_scored_loans.csv
│
├── src/                      # Core modular python package
│   ├── __init__.py
│   ├── config.py             # Hyperparameters, model weights, and thresholds
│   ├── ingestion.py          # Data loading, file auto-detection & schema standardization
│   ├── behavior.py           # Feature engineering from collection transactions (MIS)
│   ├── scoring.py            # Multi-factor calibrated risk scoring & tiering engine
│   └── evaluation.py         # Summary statistics, migration diagnostics & accuracy metrics
│
├── main.py                   # Primary pipeline entry point (1-command execution)
├── evaluate.py               # Comparative analytics against legacy SOA categories
├── requirements.txt          # Python dependencies
├── .gitignore                # Git configuration
└── README.md                 # Project documentation
```

---

## 🚀 Quick Start

### 1. Install Requirements
```bash
pip install -r requirements.txt
```

### 2. Run the Risk Engine
Automatically discovers data files in `data/raw/` and generates the scored dataset:
```bash
python main.py
```
*Outputs are saved to `data/processed/risk_scored_loans.csv` (and mirrored to `risk_scored_loans.csv`).*

### 3. Evaluate Model Accuracy vs SOA Baseline
```bash
python evaluate.py
```

---

## ⚙️ Custom Arguments

To specify custom file paths:
```bash
python main.py --soa data/raw/custom_soa.csv --mis data/raw/custom_mis.csv --out data/processed/custom_scored.csv
```

---

## 🧠 Risk Scoring & Tiering Methodology

The engine scores borrower risk based on:
1. **Customer Lifecycle & Bounce Profile (`customer_type`)**:
   - `Never Bounce`: Clean repayment track record $\rightarrow$ Baseline **`Low`** risk.
   - `Ever Bounce`: Prior bounce history $\rightarrow$ Baseline **`Medium`** to **`High`** when active dues or delinquent bucket progression occurs.
   - `3 MOB`: Early-vintage portfolio onboarding book.
   - `Matured`: Completed tenure loans.
2. **Delinquency Severity (DPD)**: Capped normalized delinquency.
3. **Monetary Exposure**: Log-transformed outstanding overdue dues.
4. **Behavioral Collection Touchpoints**: Bounce/rejection rates and partial payment tendencies.
