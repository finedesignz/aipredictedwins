# tests/test_e2e_reconciliation.py
"""Phase 20 — G1: the END-TO-END CHAIN nothing tests (cases 31-36).

    submit -> fill -> external exit -> resolve_stale_row -> a RESOLVED row in the
    trade log -> get_realized_pnl -> reconcile_bot -> within_tolerance

**THIS TESTS THE JOINS, NOT THE LINKS.** Every link is ALREADY unit-tested and green:
order resolution (tests/test_order_resolution.py), the P&L math (tests/test_pnl.py),
the universe gate (tests/test_universe.py), reconcile_bot (tests/test_reconciliation.py).
VERIFY-01 is ~80% covered by phases 11-19 and this file does NOT pile on redundant unit
tests.

What NOTHING asserts is the CHAIN. **A sign error or a unit mismatch AT A JOIN survives
all 488 current cases.** That is the gap this file closes.

Every fixture's Alpaca equity is CONSTRUCTED FROM the same realized_pnl + TAKER_FEE the
chain itself computes, so a mismatch can only come from a JOIN — never from the fixture.

Zero DB, zero Alpaca, zero network, zero skips.
"""
from contextlib import contextmanager

import pytest

from src.db import is_resolved
from src.fee_gate import TAKER_FEE
from src.pnl import realized_pnl
from src.reconciliation import reconcile_bot

# The doubles are REUSED from the sibling module rather than forked into a third style.
# (pytest's prepend import mode puts tests/ on sys.path, so this resolves.)
from test_backfill import (  # noqa: E402
    FakeAlpacaClient,
    FakeLogger,
    _order,
    _stale_row,
    _wire,
)

_STARTING_EQUITY = 100_000.0
_TOLERANCE = 25.0
_TERMINAL = ("closed", "stopped", "target_hit")


# ── the trade log, read back the way src/db.py:299 reads it ──────────────────

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeLogConn:
    """get_realized_pnl's SELECT, honoured: the three position-closed terminals only,
    with NULL pnl coerced to 0.0 exactly as src/db.py:312 does."""

    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        return _FakeResult([
            {"pnl": r.get("pnl")} for r in self.rows if r.get("status") in _TERMINAL
        ])


def _log_conn(rows):
    @contextmanager
    def _conn():
        yield _FakeLogConn(rows)

    return _conn


def _realized_from_log(monkeypatch, rows, bot_id="A"):
    """Drive the REAL src.db.get_realized_pnl over an in-memory trade log."""
    from src import db

    monkeypatch.setattr(db, "connection", _log_conn(rows))
    return db.get_realized_pnl(bot_id)


def _resolve_into_log(logger, row, entry, live_symbols, close_order):
    """Run the REAL resolve_stale_row and apply its verdict to the fake trade log —
    the same write the driver performs at src/backfill.py:164-167."""
    from src.backfill import resolve_stale_row

    outcome, kw = resolve_stale_row(row, entry, live_symbols, close_order)
    if outcome == "resolved":
        payload = {k: v for k, v in kw.items() if v is not None}
        logger.update_alpaca_trade(row["id"], **payload)
    return outcome


# ── case 31 — the full chain, LONG ───────────────────────────────────────────

def test_full_chain_long(monkeypatch):
    """Case 31. Long BTC/USD filled @80_000, externally exited @85_000, qty 1.

    The trade log's realized P&L must agree TO THE CENT with the Alpaca-derived figure
    ((equity - starting_equity) - unrealized).
    """
    entry_fill, exit_fill, qty = 80_000.0, 85_000.0, 1.0
    expected = realized_pnl("buy", entry_fill, exit_fill, qty, TAKER_FEE)

    logger = FakeLogger(bot_id="A", seed_rows=[
        _stale_row(rid=1, symbol="BTC/USD", side="buy",
                   filled_qty=qty, filled_avg_price=entry_fill),
    ])
    entry = _order(status="OrderStatus.FILLED", filled_qty=qty, filled_avg_price=entry_fill)
    close = _order(order_id="c", side="sell", filled_qty=qty, filled_avg_price=exit_fill,
                   filled_at="2026-07-01T13:00:00+00:00")

    outcome = _resolve_into_log(
        logger, logger.rows[1], entry, live_symbols={"ETHUSD"}, close_order=close)
    assert outcome == "resolved"

    trade_log_pnl = _realized_from_log(monkeypatch, list(logger.rows.values()))

    # Alpaca's equity is BUILT FROM the same realized figure — a mismatch can only be a JOIN.
    r = reconcile_bot(trade_log_pnl=trade_log_pnl,
                      equity=_STARTING_EQUITY + expected,
                      starting_equity=_STARTING_EQUITY,
                      unrealized_pnl=0.0,
                      tolerance=_TOLERANCE)

    assert trade_log_pnl == pytest.approx(expected, abs=1e-9)
    assert r["delta"] == pytest.approx(0.0, abs=1e-9)
    assert r["within_tolerance"] is True


# ── case 32 — the full chain, SHORT ──────────────────────────────────────────

def test_full_chain_short(monkeypatch):
    """Case 32. Side 'sell', exit BELOW entry — a SHORT PROFIT.

    CATCHES A SIGN INVERSION THAT A LONG-ONLY CHAIN STRUCTURALLY CANNOT. Phase 17's
    EVIDENCE flags sign-inverted shorts on the fee-less rows; this is the seam that
    would have caught them.
    """
    entry_fill, exit_fill, qty = 80_000.0, 75_000.0, 1.0
    expected = realized_pnl("sell", entry_fill, exit_fill, qty, TAKER_FEE)
    assert expected > 0, "fixture error — a short exiting below entry is a PROFIT"

    logger = FakeLogger(bot_id="A", seed_rows=[
        _stale_row(rid=1, symbol="BTC/USD", side="sell",
                   filled_qty=qty, filled_avg_price=entry_fill),
    ])
    entry = _order(status="OrderStatus.FILLED", side="sell",
                   filled_qty=qty, filled_avg_price=entry_fill)
    close = _order(order_id="c", side="buy", filled_qty=qty, filled_avg_price=exit_fill,
                   filled_at="2026-07-01T13:00:00+00:00")

    _resolve_into_log(logger, logger.rows[1], entry,
                      live_symbols={"ETHUSD"}, close_order=close)

    trade_log_pnl = _realized_from_log(monkeypatch, list(logger.rows.values()))

    r = reconcile_bot(trade_log_pnl=trade_log_pnl,
                      equity=_STARTING_EQUITY + expected,
                      starting_equity=_STARTING_EQUITY,
                      unrealized_pnl=0.0,
                      tolerance=_TOLERANCE)

    assert trade_log_pnl == pytest.approx(expected, abs=1e-9)
    assert trade_log_pnl > 0
    assert r["within_tolerance"] is True


# ── case 33 — fees carry through the join with the RIGHT SIGN ────────────────

def test_fees_carry_through_the_join_with_the_right_sign(monkeypatch):
    """Case 33. VERIFY-01's "realized-P&L math WITH FEES" clause, asserted AT THE SEAM.

    NOT NUMERICALLY VACUOUS: the fixture is sized so gross-vs-net is $412.50 — more than
    16x the $25 tolerance. A chain that carried GROSS P&L through would BREACH.
    """
    entry_fill, exit_fill, qty = 80_000.0, 85_000.0, 1.0
    net = realized_pnl("buy", entry_fill, exit_fill, qty, TAKER_FEE)
    gross = (exit_fill - entry_fill) * qty
    fees = (entry_fill * qty + exit_fill * qty) * TAKER_FEE

    assert gross - net == pytest.approx(fees, abs=1e-9)
    assert fees > _TOLERANCE, "fixture is vacuous — size it so gross-vs-net exceeds $25"

    logger = FakeLogger(bot_id="A", seed_rows=[
        _stale_row(rid=1, symbol="BTC/USD", side="buy",
                   filled_qty=qty, filled_avg_price=entry_fill),
    ])
    entry = _order(status="OrderStatus.FILLED", filled_qty=qty, filled_avg_price=entry_fill)
    close = _order(order_id="c", side="sell", filled_qty=qty, filled_avg_price=exit_fill,
                   filled_at="2026-07-01T13:00:00+00:00")

    _resolve_into_log(logger, logger.rows[1], entry,
                      live_symbols={"ETHUSD"}, close_order=close)

    # Fees were RECORDED, not dropped — a NULL `fees` is the TELL that pnl is gross.
    assert logger.rows[1]["fees"] == pytest.approx(fees, abs=1e-9)

    trade_log_pnl = _realized_from_log(monkeypatch, list(logger.rows.values()))
    assert trade_log_pnl == pytest.approx(net, abs=1e-9)

    alpaca_equity = _STARTING_EQUITY + net
    ok = reconcile_bot(trade_log_pnl, alpaca_equity, _STARTING_EQUITY, 0.0, _TOLERANCE)
    assert ok["within_tolerance"] is True

    # And the counterfactual: a GROSS figure would BREACH the tolerance.
    breached = reconcile_bot(gross, alpaca_equity, _STARTING_EQUITY, 0.0, _TOLERANCE)
    assert breached["within_tolerance"] is False


# ── case 34 — G3's BUG, CAUGHT AT CHAIN LEVEL ───────────────────────────────

def test_slashed_and_slashless_shapes_survive_the_chain(monkeypatch):
    """Case 34. The trade log stores SLASHED symbols ("BTC/USD"); Alpaca's get_positions()
    returns SLASHLESS ones ("BTCUSD").

    Two rows: BTC/USD is STILL HELD at Alpaca; ETH/USD was genuinely exited. Only the
    ETH/USD realized P&L may reach the trade log. The held BTC/USD position's value lives
    in Alpaca's UNREALIZED, and the two sides must still reconcile.

    RED TODAY: the slash mismatch makes the HELD BTC/USD row resolve as `closed` with a
    FABRICATED P&L, which is then summed into the trade log — so the log over-reports
    realized by the fabrication and the reconciliation BREACHES. GREEN after Plan 20-03.
    """
    from src import backfill

    eth_entry, eth_exit, eth_qty = 4_000.0, 4_500.0, 2.0
    eth_realized = realized_pnl("buy", eth_entry, eth_exit, eth_qty, TAKER_FEE)
    btc_unrealized = 1_500.0          # the HELD position — unrealized, not realized

    entries = {
        "ord-btc": _order(order_id="ord-btc", status="OrderStatus.FILLED",
                          symbol="BTC/USD", filled_qty=1.0, filled_avg_price=80_000.0),
        "ord-eth": _order(order_id="ord-eth", status="OrderStatus.FILLED",
                          symbol="ETH/USD", filled_qty=eth_qty,
                          filled_avg_price=eth_entry),
    }
    eth_close = _order(order_id="c-eth", side="sell", filled_qty=eth_qty,
                       filled_avg_price=eth_exit, filled_at="2026-07-01T13:00:00+00:00")
    btc_close = _order(order_id="c-btc", side="sell", filled_qty=1.0,
                       filled_avg_price=70_000.0, filled_at="2026-07-01T13:00:00+00:00")

    client = FakeAlpacaClient(
        orders=entries,
        positions=[{"symbol": "BTCUSD"}],       # SLASHLESS — the real Alpaca shape. HELD.
        closed={"BTC/USD": [btc_close], "ETH/USD": [eth_close]},
    )
    candidates = [
        _stale_row(rid=1, order_id="ord-btc", symbol="BTC/USD", side="buy",
                   filled_qty=1.0, filled_avg_price=80_000.0),
        _stale_row(rid=2, order_id="ord-eth", symbol="ETH/USD", side="buy",
                   filled_qty=eth_qty, filled_avg_price=eth_entry),
    ]
    loggers = _wire(monkeypatch, ["A"], {"A": client}, {"A": candidates})

    backfill.backfill(apply=True)      # fakes only — no DB, no Alpaca, no prod

    log_rows = list(loggers["A"].rows.values())
    trade_log_pnl = _realized_from_log(monkeypatch, log_rows)

    # ONLY the genuinely-exited ETH trade contributed realized P&L.
    assert trade_log_pnl == pytest.approx(eth_realized, abs=1e-9), (
        "the trade log realized P&L for a position that is STILL OPEN AT ALPACA — "
        "the slash mismatch fabricated it"
    )

    r = reconcile_bot(
        trade_log_pnl=trade_log_pnl,
        equity=_STARTING_EQUITY + eth_realized + btc_unrealized,
        starting_equity=_STARTING_EQUITY,
        unrealized_pnl=btc_unrealized,
        tolerance=_TOLERANCE,
    )
    assert r["within_tolerance"] is True


# ── cases 35-36 — NULL and 0.0 are excluded from BOTH sides of the ratio ─────

def test_a_null_pnl_row_is_excluded_from_BOTH_numerator_and_denominator(monkeypatch):
    """Case 35. An `unresolvable` row (pnl = NULL) must move NEITHER get_realized_pnl NOR
    the win-rate denominator — and must NOT BE BOOKED AS A LOSS."""
    entry_fill, exit_fill, qty = 80_000.0, 85_000.0, 1.0
    won = realized_pnl("buy", entry_fill, exit_fill, qty, TAKER_FEE)

    logger = FakeLogger(bot_id="A", seed_rows=[
        _stale_row(rid=1, symbol="BTC/USD", side="buy",
                   filled_qty=qty, filled_avg_price=entry_fill),
        _stale_row(rid=2, symbol="SOL/USD", side="buy"),
    ])
    entry = _order(status="OrderStatus.FILLED", filled_qty=qty, filled_avg_price=entry_fill)
    close = _order(order_id="c", side="sell", filled_qty=qty, filled_avg_price=exit_fill,
                   filled_at="2026-07-01T13:00:00+00:00")

    _resolve_into_log(logger, logger.rows[1], entry, live_symbols={"ETHUSD"},
                      close_order=close)
    # The SOL row has no close order -> unresolvable -> it is left ALONE (pnl absent/NULL).
    out = _resolve_into_log(logger, logger.rows[2], entry, live_symbols={"ETHUSD"},
                            close_order=None)
    assert out == "unresolvable"

    rows = list(logger.rows.values())
    unresolved_row = logger.rows[2]
    unresolved_row["status"] = "closed"       # a terminal row carrying a NULL pnl
    unresolved_row["pnl"] = None

    trade_log_pnl = _realized_from_log(monkeypatch, rows)
    assert trade_log_pnl == pytest.approx(won, abs=1e-9), "the NULL row moved the numerator"

    terminal = [r for r in rows if r.get("status") in _TERMINAL]
    resolved = [r for r in terminal if is_resolved(r.get("pnl"))]
    assert len(resolved) == 1, "the NULL row entered the win-rate DENOMINATOR"
    losses = [r for r in resolved if r["pnl"] < 0]
    assert losses == [], "the NULL row was BOOKED AS A LOSS"


def test_a_zero_pnl_sentinel_row_is_likewise_excluded(monkeypatch):
    """Case 36. A `closed` row carrying pnl = 0.0 — the historical sentinel shape, 395 of
    which sit in prod. It becomes a loss NOWHERE, and lands in the `unresolved` bucket."""
    won = realized_pnl("buy", 80_000.0, 85_000.0, 1.0, TAKER_FEE)

    rows = [
        {"id": 1, "status": "closed", "pnl": won},
        {"id": 2, "status": "closed", "pnl": 0.0},      # THE SENTINEL
    ]

    trade_log_pnl = _realized_from_log(monkeypatch, rows)
    assert trade_log_pnl == pytest.approx(won, abs=1e-9), \
        "the 0.0 sentinel moved the realized total"

    resolved = [r for r in rows if is_resolved(r["pnl"])]
    unresolved = [r for r in rows if not is_resolved(r["pnl"])]

    assert len(resolved) == 1
    assert len(unresolved) == 1
    assert [r for r in resolved if r["pnl"] < 0] == [], \
        "the 0.0 sentinel was booked as a LOSS"
