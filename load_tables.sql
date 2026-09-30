-- =====================================================================
-- Collections Risk Profiling: create tables and load raw CSVs
-- Run with psql (NOT the pgAdmin Query Tool, because \copy is a psql command):
--
--   psql -U postgres -h localhost -f load_tables.sql
--
-- IMPORTANT: the column ORDER below must match the column order of your CSV
-- files. Edit the column lists if your files differ.
-- Update the two file paths in the \copy lines (Section 3) before running.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Create the database (skip if it already exists) and connect to it
-- ---------------------------------------------------------------------
SELECT 'CREATE DATABASE collections_risk_profiling'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'collections_risk_profiling')\gexec

\c collections_risk_profiling

-- Indian-style dates in the CSVs are day-first (e.g. 31/12/2025)
SET datestyle = 'ISO, DMY';

-- ---------------------------------------------------------------------
-- 2. Create tables (dropped and recreated on every run)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS raw_soa_master;
CREATE TABLE raw_soa_master (
    loan_number                    TEXT,
    dpd                            NUMERIC,
    bucket                         TEXT,      -- kept as text: values like '0', '1-29', '30-59'
    bucket_group                   TEXT,
    total_dues                     NUMERIC,
    total_loan_outstanding_amount  NUMERIC,
    emi_amount                     NUMERIC,
    loan_amount                    NUMERIC,
    charges_payable                NUMERIC,
    charges_2                      NUMERIC,
    disbursal_date                 DATE,
    cycle_date                     DATE,
    product_name                   TEXT,
    zone                           TEXT,
    risk_type                      TEXT,
    npa_tag                        TEXT,
    customer_type                  TEXT       -- dropped below; not used by the pipeline
);

DROP TABLE IF EXISTS raw_mis_collections;
CREATE TABLE raw_mis_collections (
    loan_number             TEXT,
    instrument_status       TEXT,
    payment_type            TEXT,
    total_amount_collected  NUMERIC,
    payment_date            DATE
);

DROP TABLE IF EXISTS scored_loan_risk_profiles;
CREATE TABLE scored_loan_risk_profiles (
    loan_number                    TEXT,
    dpd                            NUMERIC,
    bucket                         TEXT,
    total_dues                     NUMERIC,
    total_loan_outstanding_amount  NUMERIC,
    product_name                   TEXT,
    zone                           TEXT,
    risk_type                      TEXT,
    npa_tag                        TEXT,
    never_worked                   BOOLEAN,
    total_receipts                 INTEGER,
    rejected_receipts              INTEGER,
    rejection_rate                 NUMERIC(6,4),
    partial_payment_rate           NUMERIC(6,4),
    total_collected                NUMERIC,
    last_payment_date              DATE,
    disbursal_date                 DATE,
    bounce_type                    TEXT,
    risk_score                     NUMERIC(5,3),
    risk_tier                      TEXT
);

-- ---------------------------------------------------------------------
-- 3. Bulk load the CSVs (client-side; paths are relative to where you run psql)
--    Use forward slashes even on Windows, e.g. 'C:/data/raw/Customer_Data.csv'
-- ---------------------------------------------------------------------
\copy raw_soa_master FROM 'D:\CREDILITY\Risk Profiling\data\raw\Customer_Data.csv' WITH (FORMAT csv, HEADER true, NULL '')
\copy raw_mis_collections FROM 'D:\CREDILITY\Risk Profiling\data\raw\Collection_Data.csv' WITH (FORMAT csv, HEADER true, NULL '')

-- ---------------------------------------------------------------------
-- 4. Cleanup and checks
-- ---------------------------------------------------------------------
-- Pipeline policy: customer_type is never used.
ALTER TABLE raw_soa_master DROP COLUMN IF EXISTS customer_type;

-- Blank loan numbers would otherwise falsely match each other in a join
DELETE FROM raw_soa_master      WHERE loan_number IS NULL OR btrim(loan_number) = '';
DELETE FROM raw_mis_collections WHERE loan_number IS NULL OR btrim(loan_number) = '';

-- Helpful index for the per-loan join
CREATE INDEX IF NOT EXISTS idx_soa_loan ON raw_soa_master (loan_number);
CREATE INDEX IF NOT EXISTS idx_mis_loan ON raw_mis_collections (loan_number);

SELECT 'raw_soa_master'      AS table_name, COUNT(*) AS row_count FROM raw_soa_master
UNION ALL
SELECT 'raw_mis_collections', COUNT(*) FROM raw_mis_collections;
