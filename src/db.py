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
    from sqlalchemy import create_engine, text
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


def upload_dataframe(df: pd.DataFrame, table_name: str) -> None:
    """Fast bulk load via COPY, replacing the table."""
    engine = get_engine()
    df_clean = df.copy()
    df_clean.columns = [re.sub(r"[^a-zA-Z0-9_]+", "_", str(c).strip().lower()).strip("_") or "col" for c in df_clean.columns]
    df_clean.head(0).to_sql(table_name, engine, if_exists="replace", index=False)

    conn = _get_raw_connection()
    conn.autocommit = True
    cur = conn.cursor()
    buf = io.StringIO()
    df_clean.to_csv(buf, index=False, header=False, sep="\t", na_rep="\\N")
    buf.seek(0)
    cur.copy_expert(f'COPY "{table_name}" FROM STDIN WITH (FORMAT csv, DELIMITER E\'\\t\', NULL \'\\N\');', buf)
    cur.close()
    conn.close()
    print(f"[OK] Uploaded {len(df_clean):,} rows to '{table_name}'")


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
