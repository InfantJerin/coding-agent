from __future__ import annotations

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path("./data/deal_platform.db")


class DatabaseConnection:
    """Thread-safe SQLite connection factory with WAL mode."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path

    def get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn
