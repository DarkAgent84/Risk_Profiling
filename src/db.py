"""
Optional PostgreSQL integration. Only needed for `python main.py sync-db` /
`python main.py evaluate --from-db`. Requires `pip install psycopg2-binary sqlalchemy`
and a RISK_DB_PASSWORD environment variable (no default credential is baked in).
"""
import io
import re
from pathlib import Path
from typing import Optional

import pandas as pd

import config

try:
    import psycopg2
    from sqlalchemy import create_engine, text, types as satypes
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "Database features require extra packages. Install with:\n"
        "  pip install psycopg2-binary sqlalchemy"
    ) from e


def _require_password() -> None:
    """Fail early with a clear message if no DB password has been provided."""
    if not config.DB_CONFIG["password"]:
        raise SystemExit(
            "Error: no database password set.\n"
            "In PowerShell run:  $env:RISK_DB_PASSWORD = \"your_postgres_password\"\n"
            "(it only lasts for the current PowerShell window), then re-run the command."
        )


def _get_db_url(dbname: Optional[str] = None) -> str:
    _require_password()
    c = config.DB_CONFIG
    db = dbname or c["dbname"]
    return f"postgresql+psycopg2://{c['user']}:{c['password']}@{c['host']}:{c['port']}/{db}"


def get_engine(dbname: Optional[str] = None):
    return create_engine(_get_db_url(dbname))


def _get_raw_connection(dbname: Optional[str] = None):
    _require_password()
    c = config.DB_CONFIG
    return psycopg2.connect(host=c["host"], port=c["port"], user=c["user"], password=c["password"], dbname=dbname or c["dbname"])


def ensure_database_exists() -> None:
    dbname = config.DB_CONFIG["dbname"]
    conn = _get_raw_connection("postgres")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (dbname,))
    if not cur.fetchone():
        print(f"Creating database '{dbname}'...")
        cur.execute(f'CREATE DATABASE "{dbname}";')
    cur.close()
    conn.close()


def infer_column_type(col_name: str, series: pd.Series):
    """
    Intelligently infer PostgreSQL/SQLAlchemy column type from column name and series data.
    Ensures empty columns don't erroneously become double precision, dates are proper DATE/TIMESTAMP,
    identifiers remain TEXT, and numbers are correctly sized NUMERIC/BIGINT.
    """
    clean_name = col_name.lower().strip()

    # 1. Geographic Coordinates
    if any(p == clean_name or clean_name.endswith(f"_{p}") for p in ["latitude", "longitude", "lat", "lon"]):
        return satypes.Numeric(10, 7)

    # 2. Rates / Scores / Percentages
    if any(p in clean_name for p in ["rate", "score", "percentage", "pct", "waiver"]):
        return satypes.Numeric(8, 4)

    # 3. Dates & Datetimes
    date_patterns = ["date", "time", "due_date", "submit_date", "disbursal", "cycle"]
    if any(p in clean_name for p in date_patterns):
        non_null = series.dropna().astype(str).str.strip()
        non_null = non_null[~non_null.isin(["", "nan", "None", "NULL", "NaT"])]
        if len(non_null) > 0:
            sample = non_null.iloc[0]
            if ":" in sample or " " in sample:
                return satypes.DateTime()
        return satypes.Date()

    # 4. Boolean flags
    if any(p in clean_name for p in ["is_", "has_", "flag", "never_worked", "matured_overdue", "active_or_inactive"]):
        return satypes.Boolean()

    # 5. Identifier / text / categorical columns (PRIORITIZE text for IDs, relations, codes, addresses)
    text_patterns = [
        "name", "address", "relation", "email", "mobile", "phone", "pan", "image",
        "url", "map", "status", "mode", "type", "zone", "branch", "group", "product",
        "tier", "action", "remark", "comment", "user_id", "app_user", "code", "ifsc",
        "receipt_number", "receipt_no", "loan_number", "account_number", "bank_a_c",
        "instrument_number", "transaction_id", "pincode", "priority", "area", "bucket",
        "description", "notes", "tag"
    ]
    if any(p in clean_name for p in text_patterns) or clean_name == "id" or clean_name.endswith("_id") or "_id_" in clean_name:
        return satypes.Text()

    # 6. Serial numbers / integer counters
    if clean_name in ["sr_no", "serial_no", "row_num"]:
        return satypes.BigInteger()

    # 7. Amounts, charges, dues, balances, counts
    amount_patterns = [
        "due", "dues", "amount", "charge", "charges", "balance", "penal", "bcc",
        "collected", "dpd", "count", "receipts", "total"
    ]
    if any(p in clean_name for p in amount_patterns):
        return satypes.Numeric(15, 2)

    # Fallback inspecting series content
    non_null = series.dropna()
    if len(non_null) == 0:
        return satypes.Text()

    if pd.api.types.is_bool_dtype(series):
        return satypes.Boolean()
    if pd.api.types.is_integer_dtype(series):
        return satypes.BigInteger()
    if pd.api.types.is_float_dtype(series):
        return satypes.Numeric(15, 2)
    if pd.api.types.is_datetime64_any_dtype(series):
        return satypes.DateTime()

    return satypes.Text()


def prepare_dataframe_for_db(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Clean column names and cast/format values according to inferred types for PostgreSQL COPY."""
    df_clean = df.copy()
    df_clean.columns = [re.sub(r"[^a-zA-Z0-9_]+", "_", str(c).strip().lower()).strip("_") or "col" for c in df_clean.columns]

    dtypes = {}
    for col in df_clean.columns:
        sql_type = infer_column_type(col, df_clean[col])
        dtypes[col] = sql_type

        # Format values cleanly for COPY
        if isinstance(sql_type, (satypes.Date, satypes.DateTime)):
            df_clean[col] = pd.to_datetime(df_clean[col], errors="coerce", dayfirst=True)
            if isinstance(sql_type, satypes.Date):
                df_clean[col] = df_clean[col].dt.strftime("%Y-%m-%d").replace("NaT", None)
            else:
                df_clean[col] = df_clean[col].dt.strftime("%Y-%m-%d %H:%M:%S").replace("NaT", None)
        elif isinstance(sql_type, satypes.Numeric):
            df_clean[col] = pd.to_numeric(df_clean[col], errors="coerce")
        elif isinstance(sql_type, satypes.BigInteger):
            df_clean[col] = pd.to_numeric(df_clean[col], errors="coerce").astype("Int64")
        elif isinstance(sql_type, satypes.Boolean):
            df_clean[col] = df_clean[col].map({
                1: True, 0: False, "1": True, "0": False,
                True: True, False: False, "True": True, "False": False, "true": True, "false": False
            })
        elif isinstance(sql_type, satypes.Text):
            df_clean[col] = df_clean[col].astype(str).str.strip()
            df_clean[col] = df_clean[col].replace({"nan": None, "None": None, "NULL": None, "NA": None, "": None})

    return df_clean, dtypes


def upload_dataframe(df: pd.DataFrame, table_name: str) -> None:
    """Fast bulk load via COPY, automatically detecting accurate schema datatypes."""
    engine = get_engine()
    df_clean, dtypes = prepare_dataframe_for_db(df)
    df_clean.head(0).to_sql(table_name, engine, if_exists="replace", index=False, dtype=dtypes)

    conn = _get_raw_connection()
    conn.autocommit = True
    cur = conn.cursor()
    buf = io.StringIO()
    df_clean.to_csv(buf, index=False, header=False, sep="\t", na_rep="\\N")
    buf.seek(0)
    cur.copy_expert(f'COPY "{table_name}" FROM STDIN WITH (FORMAT csv, DELIMITER E\'\\t\', NULL \'\\N\');', buf)
    cur.close()
    conn.close()
    print(f"[OK] Uploaded {len(df_clean):,} rows to '{table_name}' with verified column datatypes")


def fetch_table(table_name: str) -> pd.DataFrame:
    return pd.read_sql(f'SELECT * FROM "{table_name}"', get_engine())


def drop_column(table_name: str, column: str) -> None:
    """Drop a column from an existing PostgreSQL table (no-op if it's already gone)."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(f'ALTER TABLE "{table_name}" DROP COLUMN IF EXISTS "{column}";'))
    print(f"[OK] Dropped column '{column}' from '{table_name}' (if it existed).")


def upload_raw_files(soa_path, mis_path) -> None:
    """Upload the two raw CSVs into PostgreSQL as raw_soa_master / raw_mis_collections."""
    ensure_database_exists()
    soa = pd.read_csv(soa_path, low_memory=False)
    upload_dataframe(soa, "raw_soa_master")
    upload_dataframe(pd.read_csv(mis_path, low_memory=False), "raw_mis_collections")


def fetch_raw_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pull raw_soa_master and raw_mis_collections back out of PostgreSQL."""
    print("-> Fetching raw_soa_master from PostgreSQL...")
    soa = fetch_table("raw_soa_master")
    print("-> Fetching raw_mis_collections from PostgreSQL...")
    mis = fetch_table("raw_mis_collections")
    return soa, mis


def save_scored_results(df: pd.DataFrame, table_name: str = "scored_loan_risk_profiles") -> None:
    """Write the final scored dataframe back to PostgreSQL, replacing the table."""
    upload_dataframe(df, table_name)
