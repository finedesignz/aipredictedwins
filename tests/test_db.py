"""
Smoke tests for src/db.py.

The Postgres smoke tests are skipped unless DATABASE_URL is set. The Phase-18
win-rate-denominator tests (cases 9-12) are PURE: they drive get_alpaca_accuracy
through a fake connection that honours the SQL it is handed, so the fix is proven
without a database.
"""
import os
import pytest

_needs_pg = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping Postgres smoke tests",
)


@_needs_pg
def test_log_and_query_alpaca_trade():
    from src import db

    trade_id = db.log_alpaca_trade("A", {
        "symbol": "BTC/USD",
        "asset_class": "crypto",
        "side": "buy",
        "qty": 0.001,
        "entry_price": 80000.0,
        "mirofish_prob": 0.65,
    })
    assert isinstance(trade_id, int)
    assert trade_id > 0

    positions = db.get_open_alpaca_positions("A")
    assert any(p["id"] == trade_id for p in positions)

    db.update_alpaca_trade("A", trade_id, "closed", exit_price=82000.0, pnl=200.0)

    stats = db.get_alpaca_accuracy("A")
    assert stats["resolved"] >= 1
    assert stats["wins"] >= 1


@_needs_pg
def test_log_validation():
    from src import db

    val_id = db.log_validation("B", {
        "kalshi_ticker": "TEST-TICK",
        "event_title": "Test Event",
        "mirofish_prob": 0.7,
        "kalshi_price": 0.5,
        "gap": 0.2,
        "proposed_side": "yes",
        "decision": "VETO",
        "veto_reason": "too risky",
    })
    assert isinstance(val_id, int)

    vetos = db.get_veto_history("B", last_n=10)
    assert any(v["id"] == val_id for v in vetos)


# ===========================================================================
# Phase 18 — the win-rate denominator (VALIDATION cases 9-12)
#
# The bug: `resolved = len(rows)` counts rows whose pnl is NULL, and
# `losses = resolved - wins` then books every one of them as a LOSS.
# The fix: `AND pnl IS NOT NULL` in the WHERE clause.
#
# These tests are PURE. The fake connection below applies the pnl filter ONLY
# when the SQL it is handed actually asks for it, so a test that passes proves
# the SQL changed — it cannot pass vacuously.
# ===========================================================================

_TERMINAL = ("closed", "stopped", "target_hit")


def _t(pnl, status="closed", asset_class="crypto", symbol="BTC/USD"):
    return {"status": status, "pnl": pnl, "symbol": symbol, "asset_class": asset_class}


# 2 wins, 3 real losses, 1 genuine 0.0 close, 4 NULLs.
def _fixture_rows():
    return [
        _t(100.0), _t(50.0),
        _t(-10.0), _t(-20.0), _t(-30.0),
        _t(0.0),
        _t(None), _t(None), _t(None), _t(None),
    ]


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Honours the SQL: filters NULL pnl only if the query says `pnl IS NOT NULL`."""

    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        if "COUNT(*)" in sql:
            return _FakeResult([{"n": len(self.rows)}])
        rows = [r for r in self.rows if r["status"] in _TERMINAL]
        if "pnl IS NOT NULL" in sql:
            rows = [r for r in rows if r["pnl"] is not None]
        return _FakeResult(rows)


@pytest.fixture
def accuracy(monkeypatch):
    """get_alpaca_accuracy driven against an in-memory row set."""
    import contextlib
    from src import db

    def _run(rows):
        @contextlib.contextmanager
        def _conn():
            yield _FakeConn(rows)

        monkeypatch.setattr(db, "connection", _conn)
        return db.get_alpaca_accuracy("A")

    return _run


def test_null_pnl_excluded_from_denominator(accuracy):
    stats = accuracy(_fixture_rows())
    assert stats["resolved"] == 6          # NOT 10
    assert stats["wins"] == 2
    assert stats["losses"] == 4            # 3 real losses + the ONE genuine 0.0
    assert stats["win_rate"] == pytest.approx(2 / 6)


def test_old_arithmetic_gives_a_different_answer(accuracy):
    rows = _fixture_rows()
    stats = accuracy(rows)

    terminal = [r for r in rows if r["status"] in _TERMINAL]
    resolved_old = len(terminal)
    wins_old = sum(1 for r in terminal if (r["pnl"] or 0) > 0)
    losses_old = resolved_old - wins_old
    win_rate_old = wins_old / resolved_old

    assert stats["win_rate"] != win_rate_old
    assert stats["losses"] < losses_old


def test_sums_unaffected(accuracy):
    rows = _fixture_rows()
    stats = accuracy(rows)
    real = sum(r["pnl"] for r in rows if r["pnl"] is not None)
    assert stats["total_pnl"] == pytest.approx(real)

    stats2 = accuracy(rows + [_t(None), _t(None)])
    assert stats2["total_pnl"] == pytest.approx(real)


def test_accuracy_dict_shape_unchanged(accuracy):
    stats = accuracy(_fixture_rows())
    for key in ("total_trades", "resolved", "wins", "losses", "win_rate",
                "total_pnl", "avg_pnl", "crypto_pnl", "stock_pnl"):
        assert key in stats
