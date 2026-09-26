"""
PostgreSQL Database Integration Module
======================================
Manages connections, table schemas, batch ingestion, and SQL exports for pgAdmin.
"""
import io
import re
from pathlib import Path
from typing import Optional, Tuple
import psycopg2
import pandas as pd
from sqlalchemy import create_engine, text
from src import config

# --- Database Credentials ---
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "postgres",
    "password": "root",
    "dbname": "Collection_Data_Risk_Profiling"
}


def get_db_url(dbname: Optional[str] = None) -> str:
    """Construct SQLAlchemy database URL."""
    db = dbname or DB_CONFIG["dbname"]
    user = DB_CONFIG["user"]
    pwd = DB_CONFIG["password"]
    host = DB_CONFIG["host"]
    port = DB_CONFIG["port"]
    return f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{db}"


def get_engine(dbname: Optional[str] = None):
    """Create SQLAlchemy engine."""
    return create_engine(get_db_url(dbname))


def get_raw_connection(dbname: Optional[str] = None):
    """Create direct psycopg2 connection."""
    return psycopg2.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        dbname=dbname or DB_CONFIG["dbname"]
    )


def ensure_database_exists():
    """Ensure the target PostgreSQL database exists, creating it if needed."""
    dbname = DB_CONFIG["dbname"]
    conn = get_raw_connection("postgres")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"SELECT 1 FROM pg_database WHERE datname = '{dbname}';")
    exists = cur.fetchone()
    if not exists:
        print(f"Creating database '{dbname}' in PostgreSQL...")
        cur.execute(f'CREATE DATABASE "{dbname}";')
        print(f"[OK] Database '{dbname}' created successfully.")
    else:
        print(f"[OK] Database '{dbname}' verified.")
    cur.close()
    conn.close()


def fast_copy_dataframe(df: pd.DataFrame, table_name: str, if_exists: str = 'replace'):
    """High-speed bulk ingestion using PostgreSQL COPY command."""
    engine = get_engine()
    
    # Normalize column names for valid PostgreSQL identifiers
    df_clean = df.copy()
    clean_cols = []
    for c in df_clean.columns:
        norm = re.sub(r'[^a-zA-Z0-9_]+', '_', str(c).strip().lower()).strip('_')
        clean_cols.append(norm or 'col')
    df_clean.columns = clean_cols

    # Create empty table schema via pandas
    if if_exists == 'replace':
        df_clean.head(0).to_sql(table_name, engine, if_exists='replace', index=False)
    
    # Fast in-memory COPY streaming
    raw_conn = get_raw_connection()
    raw_conn.autocommit = True
    cur = raw_conn.cursor()

    buffer = io.StringIO()
    df_clean.to_csv(buffer, index=False, header=False, sep='\t', na_rep='\\N')
    buffer.seek(0)

    cur.copy_expert(f'COPY "{table_name}" FROM STDIN WITH (FORMAT csv, DELIMITER E\'\\t\', NULL \'\\N\');', buffer)
    cur.close()
    raw_conn.close()
    print(f"[OK] Uploaded {len(df_clean):,} records to PostgreSQL table: '{table_name}'")


def upload_all_raw_files(
    soa_path: str | Path,
    mis_path: str | Path,
    prev_tier_path: str | Path
):
    """Upload all 3 source files into PostgreSQL database tables."""
    ensure_database_exists()

    print("\n" + "=" * 60)
    print("   UPLOADING 3 SOURCE FILES TO POSTGRESQL (pgAdmin)    ")
    print("=" * 60)

    # 1. SOA Master Export
    print(f"1. Ingesting SOA Master file: {Path(soa_path).name}")
    soa = pd.read_csv(soa_path, low_memory=False)
    fast_copy_dataframe(soa, "raw_soa_master", if_exists='replace')

    # 2. MIS Collection Done Report
    print(f"2. Ingesting MIS Collection file: {Path(mis_path).name}")
    mis = pd.read_csv(mis_path, low_memory=False)
    fast_copy_dataframe(mis, "raw_mis_collections", if_exists='replace')

    # 3. Previous Risk Tiers (Loan Number wise)
    print(f"3. Ingesting Previous Risk Tiers file: {Path(prev_tier_path).name}")
    prev = pd.read_csv(prev_tier_path, low_memory=False)
    fast_copy_dataframe(prev, "previous_loan_risk_tiers", if_exists='replace')

    print("=" * 60)
    print("[SUCCESS] All 3 files uploaded to PostgreSQL successfully!\n")


def fetch_table(table_name: str) -> pd.DataFrame:
    """Fetch table from database as DataFrame."""
    engine = get_engine()
    return pd.read_sql(f'SELECT * FROM "{table_name}"', engine)


def save_scored_results_to_db(df: pd.DataFrame, table_name: str = "scored_loan_risk_profiles"):
    """Save finalized risk scoring dataset to PostgreSQL table."""
    fast_copy_dataframe(df, table_name, if_exists='replace')
