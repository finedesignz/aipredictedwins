"""
SQLite connection helper for the dashboard API.

Read-only connection to the trades database. The bot container writes to
this database; the dashboard only reads. Uses WAL mode for concurrent
read access without blocking the writer.
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Generator

# DATA_DIR is set by supervisord.conf to /app/data in production
_DATA_DIR = os.environ.get("DATA_DIR", "data")
DB_PATH = os.environ.get("DB_PATH", os.path.join(_DATA_DIR, "trades.db"))


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Yield a read-only SQLite connection with Row factory.

    Opens in WAL mode with query_only pragma to prevent accidental writes.
    The connection is closed automatically when the context exits.
    """
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA query_only=ON")
    try:
        yield conn
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row)


def rows_to_list(rows: list[sqlite3.Row]) -> list[dict]:
    """Convert a list of sqlite3.Row objects to a list of dicts."""
    return [dict(r) for r in rows]
