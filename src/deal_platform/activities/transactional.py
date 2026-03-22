from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from temporalio import activity

from deal_platform.db.connection import DatabaseConnection

_db = DatabaseConnection()

# Tables that agents can read/write, with their column definitions
_VALID_TABLES = {
    "context_index",
    "compliance_status",
    "discrepancies",
    "extracted_terms",
}


@activity.defn
async def db_read(
    context_id: str, table: str, filters: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Read rows from SQLite scoped to context_id."""
    if table not in _VALID_TABLES:
        raise ValueError(f"Invalid table: {table}")

    conn = _db.get_connection()
    try:
        where_clauses = ["context_id = ?"]
        params: list[Any] = [context_id]

        for col, val in (filters or {}).items():
            where_clauses.append(f"{col} = ?")
            params.append(val)

        query = f"SELECT * FROM {table} WHERE {' AND '.join(where_clauses)}"
        cursor = conn.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        conn.close()


@activity.defn
async def db_write(
    context_id: str, table: str, data: dict[str, Any]
) -> dict[str, Any]:
    """Insert or update a row in SQLite. All rows scoped to context_id."""
    if table not in _VALID_TABLES:
        raise ValueError(f"Invalid table: {table}")

    now = datetime.now(timezone.utc).isoformat()
    row = {"context_id": context_id, **data}

    # Add timestamp columns based on table
    if table == "context_index":
        row.setdefault("updated_at", now)
        row.setdefault("created_at", now)
    elif table == "compliance_status":
        row.setdefault("updated_at", now)
    elif table == "discrepancies":
        row.setdefault("created_at", now)
    elif table == "extracted_terms":
        row.setdefault("extracted_at", now)

    conn = _db.get_connection()
    try:
        columns = list(row.keys())
        placeholders = ", ".join("?" for _ in columns)
        col_str = ", ".join(columns)

        # UPSERT for tables with unique constraints
        if table == "extracted_terms":
            sql = (
                f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}) "
                f"ON CONFLICT(context_id, field_name) DO UPDATE SET "
                f"value=excluded.value, source=excluded.source, extracted_at=excluded.extracted_at"
            )
        elif table == "context_index":
            sql = (
                f"INSERT INTO {table} ({col_str}) VALUES ({placeholders}) "
                f"ON CONFLICT(context_id) DO UPDATE SET "
                f"name=excluded.name, status=excluded.status, updated_at=excluded.updated_at"
            )
        else:
            sql = f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})"

        cursor = conn.execute(sql, list(row.values()))
        conn.commit()
        return {"ok": True, "rowid": cursor.lastrowid}
    finally:
        conn.close()
