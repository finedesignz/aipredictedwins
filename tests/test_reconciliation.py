# tests/test_reconciliation.py
"""Phase 13 reconciliation contract — Wave 0 (RED), PNL-03 cases 1-10.

Trade-log realized P&L vs Alpaca-derived realized P&L per bot, with a dollar
tolerance breach flag. Pure math cases pass plain floats; the three-state sum
and driver cases use zero-network in-memory doubles (mirroring
tests/test_close_pnl.py) plus a DATABASE_URL-gated integration guard.

RED until Plan 02 (reconcile_bot + db accessors) and Plan 03 (driver + alert +
entrypoint) land. The pure cases lock the derivation; case 6 locks the
three-state realized-P&L set so a 'closed'-only regression cannot pass.
"""
import os
from contextlib import contextmanager

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Pure reconcile_bot math cases (1-5, 10)
#   alpaca_realized_pnl = (equity - starting_equity) - unrealized_pnl
#   delta               = trade_log_pnl - alpaca_realized_pnl
#   within_tolerance    = abs(delta) <= tolerance   (inclusive)
# ─────────────────────────────────────────────────────────────────────────────

_KEYS = {"trade_log_pnl", "alpaca_realized_pnl", "delta", "within_tolerance", "tolerance"}


def test_reconcile_within_tolerance():
    from src.reconciliation import reconcile_bot

    # alpaca_realized = (100500 - 100000) - 0 = 500 ; delta = 490 - 500 = -10
    r = reconcile_bot(trade_log_pnl=490.0, equity=100500.0,
                      starting_equity=100000.0, unrealized_pnl=0.0, tolerance=25.0)
    assert r["alpaca_realized_pnl"] == pytest.approx(500.0, abs=1e-9)
    assert r["delta"] == pytest.approx(-10.0, abs=1e-9)
    assert r["within_tolerance"] is True


def test_reconcile_over_tolerance():
    from src.reconciliation import reconcile_bot

    # alpaca_realized = 500 ; delta = 560 - 500 = 60 > 25 -> breach
    r = reconcile_bot(trade_log_pnl=560.0, equity=100500.0,
                      starting_equity=100000.0, unrealized_pnl=0.0, tolerance=25.0)
    assert r["delta"] == pytest.approx(60.0, abs=1e-9)
    assert r["within_tolerance"] is False


def test_reconcile_boundary():
    from src.reconciliation import reconcile_bot

    # alpaca_realized = 500 ; delta = 525 - 500 = 25 == tolerance -> inclusive True
    r = reconcile_bot(trade_log_pnl=525.0, equity=100500.0,
                      starting_equity=100000.0, unrealized_pnl=0.0, tolerance=25.0)
    assert r["delta"] == pytest.approx(25.0, abs=1e-9)
    assert r["within_tolerance"] is True


def test_reconcile_negative_delta():
    from src.reconciliation import reconcile_bot

    # alpaca_realized = 500 ; delta = 450 - 500 = -50 ; abs 50 > 25 -> breach via abs()
    r = reconcile_bot(trade_log_pnl=450.0, equity=100500.0,
                      starting_equity=100000.0, unrealized_pnl=0.0, tolerance=25.0)
    assert r["delta"] == pytest.approx(-50.0, abs=1e-9)
    assert r["within_tolerance"] is False


def test_reconcile_alpaca_derivation():
    from src.reconciliation import reconcile_bot

    # Long, positive unrealized: (101000 - 100000) - 300 = 700
    long = reconcile_bot(trade_log_pnl=700.0, equity=101000.0,
                         starting_equity=100000.0, unrealized_pnl=300.0, tolerance=25.0)
    assert long["alpaca_realized_pnl"] == pytest.approx(700.0, abs=1e-9)
    assert long["within_tolerance"] is True

    # Short / losing open, negative unrealized: (100800 - 100000) - (-200) = 1000
    short = reconcile_bot(trade_log_pnl=1000.0, equity=100800.0,
                          starting_equity=100000.0, unrealized_pnl=-200.0, tolerance=25.0)
    assert short["alpaca_realized_pnl"] == pytest.approx(1000.0, abs=1e-9)
    assert short["within_tolerance"] is True


def test_reconcile_guards():
    from src.reconciliation import reconcile_bot

    # Zero unrealized / empty-positions path -> realized == equity - starting_equity
    r = reconcile_bot(trade_log_pnl=0.0, equity=100000.0,
                      starting_equity=100000.0, unrealized_pnl=0.0, tolerance=25.0)
    assert r["alpaca_realized_pnl"] == pytest.approx(0.0, abs=1e-9)
    assert r["delta"] == pytest.approx(0.0, abs=1e-9)
    assert r["within_tolerance"] is True
    # Result shape: exactly the 5 documented keys
    assert set(r.keys()) == _KEYS
    assert r["trade_log_pnl"] == pytest.approx(0.0, abs=1e-9)
    assert r["tolerance"] == pytest.approx(25.0, abs=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# Case 6 — three-state realized-P&L sum (closed + stopped + target_hit)
# ─────────────────────────────────────────────────────────────────────────────

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Mimics psycopg dict_row semantics for the get_realized_pnl SELECT.

    Applies the SAME three-state status filter Postgres would, over an
    in-memory row set, so the Python summation + NULL guard are exercised
    with zero network. The real WHERE clause is guarded separately by the
    DATABASE_URL-gated integration test below.
    """

    _THREE_STATE = ("closed", "stopped", "target_hit")

    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):
        bot_id = params[0]
        matched = [
            {"pnl": r["pnl"]}
            for r in self._rows
            if r["bot_id"] == bot_id and r["status"] in self._THREE_STATE
        ]
        return _FakeResult(matched)


def _fake_connection_factory(rows):
    @contextmanager
    def _conn():
        yield _FakeConn(rows)

    return _conn


def test_realized_pnl_three_states(monkeypatch):
    from src import db

    rows = [
        {"bot_id": "A", "status": "closed", "pnl": 100.0},
        {"bot_id": "A", "status": "stopped", "pnl": 50.0},
        {"bot_id": "A", "status": "target_hit", "pnl": 25.0},
        {"bot_id": "A", "status": "canceled", "pnl": None},
        {"bot_id": "A", "status": "rejected", "pnl": None},
        {"bot_id": "A", "status": "expired", "pnl": None},
    ]
    monkeypatch.setattr(db, "connection", _fake_connection_factory(rows))
    # Only closed+stopped+target_hit contribute: 100 + 50 + 25 = 175
    assert db.get_realized_pnl("A") == pytest.approx(175.0, abs=1e-9)

    # Removing the three non-position terminals does NOT change the sum.
    monkeypatch.setattr(db, "connection", _fake_connection_factory(rows[:3]))
    assert db.get_realized_pnl("A") == pytest.approx(175.0, abs=1e-9)


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping Postgres three-state integration guard",
)
def test_realized_pnl_three_states_db():
    """Real-SQL guard: a regression to 'closed'-only is caught when a DB is present."""
    from src import db

    bot = "A"
    inserted: list[int] = []
    try:
        baseline = db.get_realized_pnl(bot)
        seed = [
            ("closed", 100.0),
            ("stopped", 50.0),
            ("target_hit", 25.0),
            ("canceled", None),
            ("rejected", None),
            ("expired", None),
        ]
        for status, pnl in seed:
            tid = db.log_alpaca_trade(bot, {
                "symbol": "BTC/USD", "asset_class": "crypto", "side": "buy",
                "qty": 1.0, "entry_price": 100.0, "mirofish_prob": 0.5,
            })
            inserted.append(tid)
            db.update_alpaca_trade(bot, tid, status, pnl=pnl)

        after = db.get_realized_pnl(bot)
        # Only closed+stopped+target_hit summed: 100 + 50 + 25 = 175
        assert after - baseline == pytest.approx(175.0, abs=1e-9)
    finally:
        if inserted:
            with db.connection() as conn:
                conn.execute(
                    "DELETE FROM alpaca_trades WHERE id = ANY(%s)", (inserted,)
                )


# ─────────────────────────────────────────────────────────────────────────────
# Driver cases (7-9) — persist + alert + multi-bot isolation
# ─────────────────────────────────────────────────────────────────────────────

class _FakeAlpaca:
    """Per-bot Alpaca double returning fixed equity + open-position unrealized."""

    def __init__(self, equity, positions):
        self._equity = equity
        self._positions = positions

    def get_account(self):
        return {"equity": self._equity}

    def get_positions(self):
        return [{"unrealized_pnl": u} for u in self._positions]


@pytest.fixture
def driver_env(monkeypatch):
    """Wire the src.reconciliation driver against fakes: db reads, persist capture,
    and a send_alert call-counter. Returns handles the tests assert against."""
    from src import reconciliation, notifier
    from src import db

    recorded: list[tuple[str, dict]] = []
    alerts: list[tuple] = []

    # Per-bot db inputs
    realized = {"A": 500.0, "B": 500.0}
    starting = {"A": 100000.0, "B": 100000.0}

    monkeypatch.setattr(db, "get_realized_pnl", lambda bot_id: realized[bot_id])
    monkeypatch.setattr(db, "get_starting_equity", lambda bot_id: starting[bot_id])
    monkeypatch.setattr(
        db, "record_reconciliation",
        lambda bot_id, result: recorded.append((bot_id, result)),
    )
    monkeypatch.setattr(
        notifier, "send_alert",
        lambda subject, body: alerts.append((subject, body)) or True,
    )
    monkeypatch.setenv("RECONCILIATION_TOLERANCE_USD", "25.0")

    return {
        "reconciliation": reconciliation,
        "recorded": recorded,
        "alerts": alerts,
        "realized": realized,
        "starting": starting,
    }


def test_persist_reconciliation(driver_env, caplog):
    reconciliation = driver_env["reconciliation"]
    recorded = driver_env["recorded"]

    # equity 100600, unrealized 0 -> alpaca_realized 600 ; trade_log 500 -> delta -100 breach
    alpaca = _FakeAlpaca(equity=100600.0, positions=[])
    with caplog.at_level("WARNING"):
        result = reconciliation.reconcile_bot_live("A", alpaca)

    assert result["within_tolerance"] is False
    assert len(recorded) == 1
    bot_id, rec = recorded[0]
    assert bot_id == "A"
    assert rec["delta"] == pytest.approx(-100.0, abs=1e-9)
    assert rec["within_tolerance"] is False
    assert rec["tolerance"] == pytest.approx(25.0, abs=1e-9)


def test_breach_alerts(driver_env, caplog):
    reconciliation = driver_env["reconciliation"]
    alerts = driver_env["alerts"]

    # Breach -> WARNING + exactly one alert
    breaching = _FakeAlpaca(equity=100600.0, positions=[])
    with caplog.at_level("INFO"):
        reconciliation.reconcile_bot_live("A", breaching)
    assert len(alerts) == 1
    assert any(r.levelname == "WARNING" for r in caplog.records)

    # Within tolerance -> INFO, no additional alert
    alerts.clear()
    caplog.clear()
    clean = _FakeAlpaca(equity=100500.0, positions=[])  # realized 500 == trade_log 500
    with caplog.at_level("INFO"):
        reconciliation.reconcile_bot_live("A", clean)
    assert alerts == []
    assert any(r.levelname == "INFO" for r in caplog.records)


def test_multi_bot_independent(driver_env, monkeypatch):
    reconciliation = driver_env["reconciliation"]
    recorded = driver_env["recorded"]
    alerts = driver_env["alerts"]

    # Bot A clean (realized 500, equity 100500 -> alpaca 500), Bot B breaching
    # (realized 500, equity 100600 -> alpaca 600 -> delta -100).
    clients = {
        "A": _FakeAlpaca(equity=100500.0, positions=[]),
        "B": _FakeAlpaca(equity=100600.0, positions=[]),
    }

    def fake_enabled_bots():
        return ["A", "B"]

    def fake_client_for(bot_id):
        return clients[bot_id]

    # The driver enumerates enabled bots and builds one client per bot; patch
    # both seams so no real DB/Alpaca is touched.
    monkeypatch.setattr(reconciliation, "_enabled_bot_ids", fake_enabled_bots, raising=False)
    monkeypatch.setattr(reconciliation, "_client_for_bot", fake_client_for, raising=False)

    results = reconciliation.reconcile()

    by_bot = {bot_id: res for bot_id, res in results}
    assert by_bot["A"]["within_tolerance"] is True
    assert by_bot["B"]["within_tolerance"] is False
    assert by_bot["B"]["delta"] == pytest.approx(-100.0, abs=1e-9)

    # Two independent rows recorded; only the breaching bot alerted.
    assert {b for b, _ in recorded} == {"A", "B"}
    assert len(alerts) == 1
