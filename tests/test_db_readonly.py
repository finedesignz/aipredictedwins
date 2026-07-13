"""Phase 18 — AIPW_DB_READONLY (VALIDATION cases 23-25).

`get_pool()` bootstraps the schema — CREATE TABLE + INSERT INTO bots — against
whatever DATABASE_URL names. An analysis script that merely IMPORTS src.db can
therefore run DDL against prod. AIPW_DB_READONLY=1 must (a) skip the bootstrap and
(b) make every pooled connection read-only SERVER-side.

Cases 24/25's live half is TEST_DATABASE_URL-gated (never DATABASE_URL) and skips
visibly. `src.db._pool` is reset on entry AND exit — a leaked pool makes these
assertions pass for the wrong reason.
"""
import os
from urllib.parse import urlparse

import pytest

_TEST_DB = os.environ.get("TEST_DATABASE_URL")
_needs_db = pytest.mark.skipif(
    not _TEST_DB, reason="TEST_DATABASE_URL not set — skipping live read-only probe")


@pytest.fixture
def clean_pool():
    from src import db
    db._pool = None
    yield db
    db._pool = None


def test_readonly_skips_bootstrap(monkeypatch, clean_pool):
    """case 23 — BOTH directions. Asserting only the skip would pass if the
    bootstrap had simply been deleted."""
    db = clean_pool
    calls: list[int] = []

    monkeypatch.setattr(db, "_bootstrap_schema", lambda: calls.append(1))
    monkeypatch.setattr(db, "_create_pool", lambda: object())

    monkeypatch.setenv("AIPW_DB_READONLY", "1")
    db._pool = None
    db.get_pool()
    assert calls == [], "AIPW_DB_READONLY=1 must NOT bootstrap the schema"

    monkeypatch.delenv("AIPW_DB_READONLY", raising=False)
    db._pool = None
    db.get_pool()
    assert calls == [1], "with the flag unset the bootstrap MUST still run"


@_needs_db
def test_readonly_is_enforced_server_side(monkeypatch, clean_pool):
    """case 24 — Postgres refuses the write, not a client-side convention."""
    import psycopg

    db = clean_pool
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("AIPW_DB_READONLY", "1")
    db._pool = None

    want = urlparse(_TEST_DB)
    with db.connection() as conn:
        info = conn.info
        # PROD GUARD — assert we are on the TEST database BEFORE probing.
        assert info.dbname == want.path.lstrip("/")
        assert (info.host or "") in (want.hostname or "", "")

        assert conn.execute("SELECT 1 AS x").fetchone()["x"] == 1
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("CREATE TABLE _aipw_probe (x int)")


@_needs_db
def test_default_unset_is_byte_identical(monkeypatch, clean_pool):
    """case 25 — unset == today's behavior: writes allowed, bootstrap ran."""
    db = clean_pool
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.delenv("AIPW_DB_READONLY", raising=False)
    db._pool = None

    with db.connection() as conn:
        ro = conn.execute("SHOW default_transaction_read_only").fetchone()
        assert list(ro.values())[0] == "off"
        # the bootstrap ran -> the bots table exists
        assert conn.execute(
            "SELECT to_regclass('public.bots') AS t").fetchone()["t"] is not None
