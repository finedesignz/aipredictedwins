"""
Tests for dashboard/api/db.py psycopg3 pool.
Skipped unless DATABASE_URL is set.
"""
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping Postgres tests",
)


def test_get_db_yields_connection():
    from db import get_db
    with get_db() as conn:
        row = conn.execute("SELECT 1 AS n").fetchone()
        assert row["n"] == 1


def test_query_filtered_both():
    from db import query_filtered
    rows = query_filtered("SELECT id FROM bots", (), "both")
    ids = {r["id"] for r in rows}
    assert "A" in ids and "B" in ids


def test_query_filtered_single_bot():
    from db import query_filtered
    rows = query_filtered("SELECT id FROM bots", (), "A")
    assert all(r["id"] == "A" for r in rows)
