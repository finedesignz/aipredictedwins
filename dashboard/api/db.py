"""
SQLite connection helper for the dashboard API.

Read-only connection to the trades database. The bot container writes to
this database; the dashboard only reads. Uses WAL mode for concurrent
read access without blocking the writer.

If the database file does not exist yet (e.g. no volume mounted), yields
an in-memory connection with the correct empty schema so all routes return
zero rows instead of 500 errors.
"""

import os
import sqlite3
from contextlib import contextmanager
from typing import Generator

# DATA_DIR is set by supervisord.conf to /app/data in production
_DATA_DIR = os.environ.get("DATA_DIR", "data")
DB_PATH = os.environ.get("DB_PATH", os.path.join(_DATA_DIR, "trades.db"))
# Bot B database — mounted at /app/data-b in production (empty string = not configured)
DB_PATH_B = os.environ.get("DB_PATH_B", "")

_EMPTY_SCHEMA = """
CREATE TABLE IF NOT EXISTS alpaca_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    entry_price REAL NOT NULL,
    mirofish_prob REAL NOT NULL,
    market_sentiment TEXT,
    target_price REAL,
    stop_loss REAL,
    status TEXT DEFAULT 'open',
    exit_price REAL,
    pnl REAL,
    closed_at TEXT,
    simulation_id TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS validations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    kalshi_ticker TEXT NOT NULL,
    event_title TEXT NOT NULL,
    mirofish_prob REAL NOT NULL,
    kalshi_price REAL NOT NULL,
    gap REAL NOT NULL,
    proposed_side TEXT NOT NULL,
    decision TEXT NOT NULL,
    confidence REAL,
    adjusted_probability REAL,
    size_multiplier REAL DEFAULT 1.0,
    sentiment_report TEXT,
    news_report TEXT,
    contrarian_report TEXT,
    risk_assessment TEXT,
    veto_reason TEXT,
    trade_id INTEGER
);
"""


def _make_empty_db() -> sqlite3.Connection:
    """Create an in-memory DB with the correct empty schema as a fallback."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_EMPTY_SCHEMA)
    return conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Yield a SQLite connection with Row factory.

    Opens the live database read-only when it exists. Falls back to an
    in-memory empty DB when the file is not yet present (e.g. volume not
    mounted), so all routes return zero rows instead of 500 errors.
    """
    if os.path.exists(DB_PATH):
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA query_only=ON")
    else:
        conn = _make_empty_db()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_db_b() -> Generator[sqlite3.Connection, None, None]:
    """Yield a connection to Bot B's database (or empty fallback)."""
    if DB_PATH_B and os.path.exists(DB_PATH_B):
        conn = sqlite3.connect(f"file:{DB_PATH_B}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA query_only=ON")
    else:
        conn = _make_empty_db()
    try:
        yield conn
    finally:
        conn.close()


def query_both(sql: str, params: tuple = ()) -> list[dict]:
    """Run a query against both bots' databases and return combined rows.

    Each row dict gets an injected ``bot`` key: "Agent A" or "Agent B".
    """
    results = []
    for bot_name, db_ctx in [("Agent A", get_db), ("Agent B", get_db_b)]:
        with db_ctx() as conn:
            rows = conn.execute(sql, params).fetchall()
            for row in rows_to_list(rows):
                row["bot"] = bot_name
                results.append(row)
    return results


def row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row)


def rows_to_list(rows: list[sqlite3.Row]) -> list[dict]:
    """Convert a list of sqlite3.Row objects to a list of dicts."""
    return [dict(r) for r in rows]
