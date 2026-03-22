from __future__ import annotations

from deal_platform.db.connection import DatabaseConnection

DDL = """
CREATE TABLE IF NOT EXISTS context_index (
    context_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS compliance_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context_id TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence TEXT,
    as_of TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (context_id) REFERENCES context_index(context_id)
);
CREATE INDEX IF NOT EXISTS idx_compliance_ctx ON compliance_status(context_id);

CREATE TABLE IF NOT EXISTS discrepancies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    expected_value TEXT,
    actual_value TEXT,
    severity TEXT NOT NULL DEFAULT 'medium',
    resolved BOOLEAN NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (context_id) REFERENCES context_index(context_id)
);
CREATE INDEX IF NOT EXISTS idx_discrepancy_ctx ON discrepancies(context_id);

CREATE TABLE IF NOT EXISTS extracted_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    value TEXT,
    source TEXT,
    extracted_at TEXT NOT NULL,
    FOREIGN KEY (context_id) REFERENCES context_index(context_id)
);
CREATE INDEX IF NOT EXISTS idx_terms_ctx ON extracted_terms(context_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_terms_ctx_field ON extracted_terms(context_id, field_name);
"""


def initialize_db(db: DatabaseConnection) -> None:
    """Create all tables if they don't exist."""
    conn = db.get_connection()
    try:
        conn.executescript(DDL)
        conn.commit()
    finally:
        conn.close()
