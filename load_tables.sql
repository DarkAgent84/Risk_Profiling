-- =====================================================================
-- Collections Risk Profiling: Create tables and load raw CSVs
--
-- Recommended approach: use the Python CLI which handles schema
-- type inference, header variations, and bulk upload automatically:
--
--   python main.py sync-db                          # Auto-discovers Client 2 CSVs
--   python main.py sync-db --client client1         # For Client 1
--
-- Alternatively, to run via psql directly:
--   psql -U postgres -h localhost -f load_tables.sql
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Create the database (skip if it already exists) and connect to it
-- ---------------------------------------------------------------------
SELECT 'CREATE DATABASE collections_risk_profiling'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'collections_risk_profiling')\gexec

\c collections_risk_profiling

SET datestyle = 'ISO, DMY';

-- ---------------------------------------------------------------------
-- 2. Client 2 Schema Definitions
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS raw_soa_master CASCADE;
CREATE TABLE raw_soa_master (
    emi_pemi_dues                  NUMERIC(15, 2),
    settlement_amount              NUMERIC(15, 2),
    emi_due_date                   DATE,
    charges_payable                NUMERIC(15, 2),
    emi_amount                     NUMERIC(15, 2),
    total_dues                     NUMERIC(15, 2),
    loan_principle_balance_amount  NUMERIC(15, 2),
    total_loan_outstanding_amount  NUMERIC(15, 2),
    bucket                         TEXT,
    app_user_s_full_name           TEXT,
    active_or_inactive_1_or_0      TEXT,
    branch_id                      TEXT,
    app_user_id                    TEXT,
    loan_number                    TEXT,
    current_address_of_the_customer TEXT,
    co_applicant_1_full_name       TEXT,
    pincode                        TEXT,
    co_applicant_2_relation        TEXT,
    co_applicant_2_address         TEXT,
    co_applicant_2_email           TEXT,
    co_applicant_2_mobile_number   TEXT,
    co_applicant_2_full_name       TEXT,
    co_applicant_1_relation        TEXT,
    co_applicant_1_address         TEXT,
    co_applicant_1_email           TEXT,
    priority                       TEXT,
    product_name                   TEXT
);

DROP TABLE IF EXISTS raw_mis_collections CASCADE;
CREATE TABLE raw_mis_collections (
    sr_no                          BIGINT,
    submit_date                    TIMESTAMP,
    payment_date                   TIMESTAMP,
    business_date                  DATE,
    loan_number                    TEXT,
    loan_branch                    TEXT,
    user_id                        TEXT,
    user_name                      TEXT,
    receipt_number                 TEXT,
    client_receipt_number          TEXT,
    client_receipt_image           TEXT,
    customer_name                  TEXT,
    primary_mobile_no              TEXT,
    alternate_mobile_number        TEXT,
    collection_done_mobile         TEXT,
    area                           TEXT,
    bucket                         TEXT,
    total_dues                     NUMERIC(15, 2),
    charges_payable                NUMERIC(15, 2),
    instrument_collected_by_id     TEXT,
    instrument_collected_by_name   TEXT,
    instrument_mode                TEXT,
    instrument_status              TEXT,
    transaction_id                 TEXT,
    instrument_date                DATE,
    payment_type                   TEXT,
    settlement_waiver_percentage   NUMERIC(8, 4),
    total_amount_collected         NUMERIC(15, 2),
    emi_pemi_dues                  NUMERIC(15, 2),
    penal                          NUMERIC(15, 2),
    bcc                            NUMERIC(15, 2),
    total_emi_due                  NUMERIC(15, 2),
    cash_handling_charges          NUMERIC(15, 2),
    legal_charges                  NUMERIC(15, 2),
    foreclosure_charges            NUMERIC(15, 2),
    charge_7                       NUMERIC(15, 2),
    charge_8                       NUMERIC(15, 2),
    charge_9                       NUMERIC(15, 2),
    charge_10                      NUMERIC(15, 2),
    bank_name                      TEXT,
    branch_name                    TEXT,
    ifsc_code                      TEXT,
    instrument_number              TEXT,
    bank_a_c_number                TEXT,
    image_name                     TEXT,
    instrument_image               TEXT,
    app_receipt_no                 TEXT,
    latitude                       NUMERIC(10, 7),
    longitude                      NUMERIC(10, 7),
    receipt_status                 TEXT,
    payer_type                     TEXT,
    payer_name                     TEXT,
    payer_relation                 TEXT,
    action                         TEXT,
    group_name                     TEXT,
    pan_no                         TEXT,
    pan_image                      TEXT,
    view_on_map                    TEXT
);

DROP TABLE IF EXISTS scored_loan_risk_profiles CASCADE;
CREATE TABLE scored_loan_risk_profiles (
    loan_number                    TEXT,
    branch_id                      TEXT,
    pincode                        TEXT,
    dpd                            NUMERIC,
    bucket                         TEXT,
    total_dues                     NUMERIC(15, 2),
    overdue_dues                   NUMERIC(15, 2),
    emi_amount                     NUMERIC(15, 2),
    emi_due_date                   DATE,
    total_loan_outstanding_amount  NUMERIC(15, 2),
    loan_principle_balance_amount  NUMERIC(15, 2),
    product_name                   TEXT,
    priority                       TEXT,
    active_or_inactive_1_or_0      TEXT,
    never_worked                   BOOLEAN,
    total_receipts                 INTEGER,
    rejected_receipts              INTEGER,
    rejection_rate                 NUMERIC(6,4),
    partial_payment_rate           NUMERIC(6,4),
    total_collected                NUMERIC(15, 2),
    last_payment_date              DATE,
    customer_type                  TEXT,
    bounce_type                    TEXT,
    matured_overdue                BOOLEAN,
    risk_score                     NUMERIC(5,3),
    risk_tier                      TEXT
);

-- ---------------------------------------------------------------------
-- 3. Bulk load Client 2 CSVs
-- ---------------------------------------------------------------------
\copy raw_soa_master FROM 'D:\CREDILITY\Risk Profiling\data\raw\Client2_Customer_Data.csv' WITH (FORMAT csv, HEADER true, NULL '')
\copy raw_mis_collections FROM 'D:\CREDILITY\Risk Profiling\data\raw\Client2_Collection_Data.csv' WITH (FORMAT csv, HEADER true, NULL '')

-- ---------------------------------------------------------------------
-- 4. Cleanup and checks
-- ---------------------------------------------------------------------
DELETE FROM raw_soa_master      WHERE loan_number IS NULL OR btrim(loan_number) = '';
DELETE FROM raw_mis_collections WHERE loan_number IS NULL OR btrim(loan_number) = '';

CREATE INDEX IF NOT EXISTS idx_soa_loan ON raw_soa_master (loan_number);
CREATE INDEX IF NOT EXISTS idx_mis_loan ON raw_mis_collections (loan_number);

SELECT 'raw_soa_master'      AS table_name, COUNT(*) AS row_count FROM raw_soa_master
UNION ALL
SELECT 'raw_mis_collections', COUNT(*) FROM raw_mis_collections;
