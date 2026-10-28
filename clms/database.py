"""SQLite storage for the CLMS.

All money is stored as integer cents to avoid floating-point rounding.
Timestamps are stored as ISO-8601 text (``YYYY-MM-DD HH:MM``) and dates as
``YYYY-MM-DD``.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".clms" / "clms.db"

SCHEMA = """
PRAGMA foreign_keys = ON;

-- SRS 6.1.1 - one row holding the laboratory's own information.
CREATE TABLE IF NOT EXISTS lab_info (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    name           TEXT NOT NULL,
    website        TEXT NOT NULL DEFAULT '',
    address        TEXT NOT NULL DEFAULT '',
    owner          TEXT NOT NULL DEFAULT '',
    phone          TEXT NOT NULL DEFAULT '',
    working_hours  TEXT NOT NULL DEFAULT '',
    updated_at     TEXT,
    updated_by     TEXT
);

-- SRS 6.1.4 - patient accounts.
CREATE TABLE IF NOT EXISTS patients (
    patient_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name               TEXT NOT NULL,
    last_name                TEXT NOT NULL,
    date_of_birth            TEXT NOT NULL,
    gender                   TEXT NOT NULL DEFAULT '',
    address                  TEXT NOT NULL,
    phone                    TEXT NOT NULL,
    email                    TEXT NOT NULL DEFAULT '',
    insurance_provider       TEXT NOT NULL DEFAULT '',
    insurance_policy_number  TEXT NOT NULL DEFAULT '',
    insurance_coverage       TEXT NOT NULL DEFAULT '',
    created_at               TEXT NOT NULL,
    created_by               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    updated_by               TEXT NOT NULL
);

-- Ordering physicians (name, license/ID and contact details are required per test).
CREATE TABLE IF NOT EXISTS physicians (
    physician_id   TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    phone          TEXT NOT NULL DEFAULT '',
    email          TEXT NOT NULL DEFAULT '',
    practice       TEXT NOT NULL DEFAULT ''
);

-- Tests the laboratory offers, with prices for the POS.
CREATE TABLE IF NOT EXISTS test_catalog (
    test_code        TEXT PRIMARY KEY,
    test_name        TEXT NOT NULL,
    sample_type      TEXT NOT NULL,
    units            TEXT NOT NULL DEFAULT '',
    reference_range  TEXT NOT NULL DEFAULT '',
    price_cents      INTEGER NOT NULL CHECK (price_cents >= 0),
    active           INTEGER NOT NULL DEFAULT 1
);

-- SRS 6.3.1/6.3.2 + note of Oct 1st - every field a test must carry.
-- Patient and insurance values are copied at intake so the report stays
-- correct even if the patient record later changes or is deleted.
CREATE TABLE IF NOT EXISTS test_requests (
    report_id                  TEXT PRIMARY KEY,
    report_datetime            TEXT NOT NULL,
    source                     TEXT NOT NULL CHECK (source IN ('WALK_IN', 'PHONE')),
    entered_by                 TEXT NOT NULL,
    -- Patient information
    patient_id                 INTEGER REFERENCES patients(patient_id) ON DELETE SET NULL,
    patient_name               TEXT NOT NULL,
    patient_dob                TEXT NOT NULL,
    patient_gender             TEXT NOT NULL,
    -- Ordering physician information
    physician_id               TEXT NOT NULL REFERENCES physicians(physician_id),
    physician_name             TEXT NOT NULL,
    -- Test execution details
    test_code                  TEXT NOT NULL REFERENCES test_catalog(test_code),
    sample_type                TEXT NOT NULL,
    sample_id                  TEXT,
    collection_datetime        TEXT,
    collected_by               TEXT,
    performed_by               TEXT,
    machine_used               TEXT,
    -- Test results
    test_name                  TEXT NOT NULL,
    result_value               TEXT,
    result_units               TEXT NOT NULL DEFAULT '',
    reference_range            TEXT NOT NULL DEFAULT '',
    result_status              TEXT NOT NULL DEFAULT 'pending'
                               CHECK (result_status IN ('pending', 'completed', 'validated')),
    results_received_datetime  TEXT,
    validated_by               TEXT,
    -- Health insurance / billing
    insurance_provider         TEXT NOT NULL,
    insurance_policy_number    TEXT NOT NULL,
    notes                      TEXT NOT NULL DEFAULT ''
);

-- SRS 6.6 - purchases (one per POS transaction).
CREATE TABLE IF NOT EXISTS purchases (
    purchase_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id          INTEGER REFERENCES patients(patient_id) ON DELETE SET NULL,
    customer_name       TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'COMPLETED', 'VOID')),
    created_at          TEXT NOT NULL,
    created_by          TEXT NOT NULL,
    signature_obtained  INTEGER NOT NULL DEFAULT 0,
    signed_by           TEXT,
    signed_at           TEXT,
    completed_at        TEXT,
    total_cents         INTEGER NOT NULL DEFAULT 0,
    change_cents        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS purchase_items (
    item_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_id       INTEGER NOT NULL REFERENCES purchases(purchase_id) ON DELETE CASCADE,
    test_code         TEXT NOT NULL REFERENCES test_catalog(test_code),
    description       TEXT NOT NULL,
    unit_price_cents  INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    quantity          INTEGER NOT NULL CHECK (quantity > 0),
    report_id         TEXT REFERENCES test_requests(report_id) ON DELETE SET NULL
);

-- SRS 6.6.4 - several payments (cash/debit/credit) may settle one purchase.
CREATE TABLE IF NOT EXISTS payments (
    payment_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_id     INTEGER NOT NULL REFERENCES purchases(purchase_id) ON DELETE CASCADE,
    method          TEXT NOT NULL CHECK (method IN ('CASH', 'DEBIT', 'CREDIT')),
    amount_cents    INTEGER NOT NULL CHECK (amount_cents > 0),
    tendered_cents  INTEGER NOT NULL,
    card_last4      TEXT,
    reference       TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS receipts (
    receipt_no    TEXT PRIMARY KEY,
    purchase_id   INTEGER NOT NULL UNIQUE REFERENCES purchases(purchase_id),
    created_at    TEXT NOT NULL,
    body          TEXT NOT NULL
);
"""

DEFAULT_CATALOG = (
    # code,  name,                              sample,  units,       reference range,   price
    ("CBC", "Complete Blood Count",             "blood", "",          "See report",      3500),
    ("BMP", "Basic Metabolic Panel",            "blood", "",          "See report",      4200),
    ("LIPID", "Lipid Panel",                    "blood", "mg/dL",     "Total < 200",     4800),
    ("A1C", "Hemoglobin A1c",                   "blood", "%",         "4.0 - 5.6",       3900),
    ("TSH", "Thyroid Stimulating Hormone",      "blood", "mIU/L",     "0.4 - 4.0",       5200),
    ("B123", "T3 Uptake",                       "blood", "%",         "24 - 39",         4500),
    ("UA", "Urinalysis",                        "urine", "",          "See report",      2500),
    ("U123", "Urine Nitrite",                   "urine", "",          "Absent",          1800),
    ("BIOPSY", "Tissue Biopsy Histopathology",  "tissue", "",         "See report",     18000),
)


def now() -> str:
    """Current local time in the format used by every timestamp column."""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def connect(path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open (and if needed create) the CLMS database.

    Pass ``":memory:"`` for a throw-away database in tests.
    """
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _seed(conn)
    return conn


def _seed(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) FROM test_catalog").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO test_catalog (test_code, test_name, sample_type, units, reference_range, price_cents)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            DEFAULT_CATALOG,
        )
    if conn.execute("SELECT COUNT(*) FROM lab_info").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO lab_info (id, name) VALUES (1, 'Clinical Laboratory')"
        )
    conn.commit()
