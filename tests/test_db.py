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
    """Honours the SQL: applies each pnl clause ONLY if the query actually asks for it.

    Phase 19 adds `pnl <> 0` to the vocabulary. Post-Phase-19 `get_alpaca_accuracy`
    selects the terminal rows UNFILTERED (so the unresolved ones can be COUNTED) and
    partitions in Python — but the clause handling stays here so a regression to a
    SQL-side filter is still honoured rather than silently ignored.
    """

    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        if "COUNT(*)" in sql:
            return _FakeResult([{"n": len(self.rows)}])
        rows = [r for r in self.rows if r["status"] in _TERMINAL]
        if "pnl IS NOT NULL" in sql:
            rows = [r for r in rows if r["pnl"] is not None]
        if "pnl <> 0" in sql:
            # SQL semantics: `NULL <> 0` is NULL, so a NULL row fails this clause too.
            rows = [r for r in rows if r["pnl"] is not None and r["pnl"] != 0]
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
    # PHASE 19 CHANGED THIS: RESOLVED is now `pnl IS NOT NULL AND pnl <> 0`, so the
    # genuine 0.0 left the denominator too (it was `resolved == 6 / losses == 4`).
    assert stats["resolved"] == 5          # NOT 10, and no longer 6
    assert stats["wins"] == 2
    assert stats["losses"] == 3            # 3 real losses — the 0.0 is UNRESOLVED, not a loss
    assert stats["win_rate"] == pytest.approx(2 / 5)


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


# ===========================================================================
# Phase 19 (RUN-02) — the RESOLVED predicate. VALIDATION cases 13, 14.
#
# RESOLVED := `pnl IS NOT NULL AND pnl <> 0`.
#
# 0.0 is NOT NULL, so Phase 18's `AND pnl IS NOT NULL` passes the 395 historical
# sentinel rows straight through, and `(r["pnl"] or 0) > 0 -> False` then books every
# one of them as a LOSS — roughly 60% of the closed-row population is a fabricated loss.
# db.py:228's own comment ADMITS it: "A genuine 0.00 close is still counted."
#
# src/symbol_stats.py's `zero_pnl` bucket is the REFERENCE IMPLEMENTATION. The dashboard
# is being brought into line with it, not the reverse.
#
# PURE — driven by the same _FakeConn fixture. These do NOT skip.
# ===========================================================================

def _resolved_fixture():
    """1 win (+10), 1 real loss (-5), 1 sentinel (0.0), 1 NULL."""
    return [_t(10.0), _t(-5.0), _t(0.0), _t(None)]


def test_zero_pnl_is_not_a_loss(accuracy):
    stats = accuracy(_resolved_fixture())
    assert stats["wins"] == 1
    assert stats["losses"] == 1            # NOT 2 — the 0.0 is not a loss
    assert stats["resolved"] == 2          # NOT 3 — the sentinel left the DENOMINATOR too
    assert stats["win_rate"] == pytest.approx(0.5)
    assert stats["unresolved"] == 2        # the sentinel AND the NULL, reported BESIDE them


def test_accuracy_dict_gains_unresolved_additively(accuracy):
    """Research N6: consumers index by key (trade_logger.py:52-53 ->
    alpaca_orchestrator.py:650,:1327; scripts/symbol_report.py:271). The nine existing
    keys keep their names; `unresolved` is purely additive."""
    stats = accuracy(_resolved_fixture())
    for key in ("total_trades", "resolved", "wins", "losses", "win_rate",
                "total_pnl", "avg_pnl", "crypto_pnl", "stock_pnl", "unresolved"):
        assert key in stats, key
    assert stats["total_pnl"] == pytest.approx(5.0)   # resolved rows only: +10 - 5
