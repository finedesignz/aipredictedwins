"""
Postgres connection pool for the dashboard API.

All routes use get_db() as a context manager to get a connection.
query_filtered() handles the bot=A|B|both parameter pattern used across routes.
"""

import os
from contextlib import contextmanager
from typing import Generator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=os.environ["DATABASE_URL"],
            min_size=2,
            max_size=10,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _pool


@contextmanager
def get_db() -> Generator[psycopg.Connection, None, None]:
    """Yield a psycopg3 connection from the pool."""
    with _get_pool().connection() as conn:
        yield conn


def query_filtered(sql: str, params: tuple, bot: str) -> list[dict]:
    """Run a query with optional bot_id filter.

    bot='both' returns all rows unfiltered.
    bot='A' or bot='B' wraps the query to add a bot_id filter.
    """
    if bot in ("A", "B"):
        wrapped = f"SELECT * FROM ({sql}) _q WHERE bot_id = %s"
        final_params = params + (bot,)
    else:
        wrapped = sql
        final_params = params
    with get_db() as conn:
        return conn.execute(wrapped, final_params).fetchall()


def rows_to_list(rows) -> list[dict]:
    """Compatibility shim — psycopg3 dict_row already returns dicts."""
    return list(rows)


# ---------------------------------------------------------------------------
# Backward-compatibility stubs for routes that have not yet been migrated
# from the SQLite implementation.  These will raise at call-time (not import-
# time) so the API starts up cleanly; once the routes are migrated the stubs
# can be removed.
# ---------------------------------------------------------------------------

# DB_PATH is no longer meaningful with Postgres; expose an empty string so
# routes that import it for os.path.exists() checks degrade gracefully.
DB_PATH: str = ""

# Bot-B is now a different schema concept (bot_id column).  Routes that call
# get_db_b() should be migrated to use query_filtered(..., bot="B") instead.
@contextmanager
def get_db_b():
    """Deprecated stub — raises at call time.  Migrate callers to query_filtered."""
    raise NotImplementedError(
        "get_db_b() is removed in the Postgres layer. "
        "Use query_filtered(sql, params, bot='B') instead."
    )
    yield  # make this a generator so the contextmanager decorator is happy


def query_both(sql: str, params: tuple = ()) -> list[dict]:
    """Deprecated stub — raises at call time.  Migrate callers to query_filtered."""
    raise NotImplementedError(
        "query_both() is removed in the Postgres layer. "
        "Use query_filtered(sql, params, bot='both') instead."
    )


def row_to_dict(row) -> dict:
    """Compatibility shim — psycopg3 dict_row rows are already dicts."""
    if isinstance(row, dict):
        return row
    return dict(row)
