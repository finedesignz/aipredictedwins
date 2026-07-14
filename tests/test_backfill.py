# tests/test_backfill.py
"""Stale-trade backfill — Phase 14 validation suite (Wave 0, PNL-05).

Pins the one-shot idempotent backfill contract BEFORE any implementation.
Zero network / zero Postgres: fakes copied+extended from
``tests/test_order_resolution.py`` (``FakeLogger`` / ``FakeAlpacaClient`` /
``_order`` / ``_pending_row``). ``FakeAlpacaClient`` gains a scripted
``get_closed_orders`` + ``get_positions`` (live-symbol set).

The not-yet-built surfaces are imported *inside* each test (lazy) so collection
always succeeds: the Wave-0 smoke passes today while the resolver/driver/db/
client cases fail RED on the missing impl, not on a malformed test.

Surfaces under contract (built by Plans 02/03):
  src.order_resolution.classify_order(order) -> (db_status|None, pnl|None)
  src.backfill.resolve_stale_row(row, entry_order, live_symbols, close_order)
      -> ("resolved"|"unchanged"|"unresolvable", write_kwargs|None)
  src.backfill.backfill(apply=False) -> list[(bot_id, counts)]
  src.db.get_stale_alpaca_candidates(bot_id, older_than_minutes=30)
  src.db.count_unresolvable_alpaca_rows(bot_id)
  AlpacaClient.get_closed_orders(symbol, after=None)
"""
import datetime
import os

import pytest

from src.pnl import realized_pnl
from src.fee_gate import TAKER_FEE


_TERMINAL = {"closed", "stopped", "target_hit", "canceled", "expired", "rejected"}


# ---------------------------------------------------------------------------
# In-memory doubles (copied+extended from tests/test_order_resolution.py)
# ---------------------------------------------------------------------------

class FakeLogger:
    """In-memory stand-in for TradeLogger's alpaca_trades surface."""

    def __init__(self, bot_id="A", seed_rows=None):
        self.bot_id = bot_id
        self.rows: dict[int, dict] = {}
        self.update_calls: list[tuple] = []
        self._next = 1
        for r in (seed_rows or []):
            row = dict(r)
            self.rows[row["id"]] = row
            self._next = max(self._next, row["id"] + 1)

    def update_alpaca_trade(self, trade_id, status, exit_price=None, pnl=None, fees=None):
        self.update_calls.append((trade_id, status, exit_price, pnl, fees))
        row = self.rows.setdefault(trade_id, {"id": trade_id})
        row["status"] = status
        if exit_price is not None:
            row["exit_price"] = exit_price
        if pnl is not None:
            row["pnl"] = pnl
        if fees is not None:
            row["fees"] = fees
        if status in _TERMINAL:
            row["closed_at"] = "2026-07-09T00:00:00+00:00"


def _order(order_id="ord-1", status="OrderStatus.FILLED", filled_qty=1.0,
           filled_avg_price=80000.0, symbol="BTC/USD", qty=1.0, side="buy",
           order_type="market", filled_at="2026-07-01T12:00:00+00:00"):
    """A _parse_order-shaped dict."""
    return {
        "order_id": order_id,
        "status": status,
        "filled_qty": filled_qty,
        "filled_avg_price": filled_avg_price,
        "symbol": symbol,
        "qty": qty,
        "side": side,
        "order_type": order_type,
        "filled_at": filled_at,
    }


def _stale_row(rid=1, order_id="ord-1", symbol="BTC/USD", side="buy", qty=1.0,
               entry_price=80000.0, filled_qty=1.0, filled_avg_price=80000.0,
               order_type="market", status="open",
               timestamp="2026-07-01T12:00:00+00:00"):
    return {
        "id": rid, "order_id": order_id, "symbol": symbol, "side": side,
        "qty": qty, "entry_price": entry_price, "filled_qty": filled_qty,
        "filled_avg_price": filled_avg_price, "order_type": order_type,
        "status": status, "timestamp": timestamp,
    }


class FakeAlpacaClient:
    """Scripts get_order / get_positions / get_closed_orders; no network."""

    def __init__(self, orders=None, positions=None, closed=None):
        # orders: {order_id: order_dict}; positions: [{"symbol": ...}];
        # closed: {symbol: [order_dict, ...]}
        self._orders = orders or {}
        self._positions = positions or []
        self._closed = closed or {}
        self.get_order_calls: list[str] = []
        self.get_closed_calls: list[tuple] = []

    def get_order(self, order_id):
        self.get_order_calls.append(order_id)
        return dict(self._orders[order_id])

    def get_positions(self):
        return [dict(p) for p in self._positions]

    def get_closed_orders(self, symbol, after=None):
        self.get_closed_calls.append((symbol, after))
        return [dict(o) for o in self._closed.get(symbol, [])]


# ===========================================================================
# Wave-0 smoke — confirm alpaca-py A1-A3 assumptions (must PASS today)
# ===========================================================================

def test_alpaca_closed_query_assumptions():
    # A1: QueryOrderStatus.CLOSED imports and is a real member.
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest

    assert QueryOrderStatus.CLOSED is not None

    # A2: GetOrdersRequest builds with status+symbols+limit+direction (+after tolerated).
    req = GetOrdersRequest(
        status=QueryOrderStatus.CLOSED,
        symbols=["BTC/USD"],
        limit=500,
        direction="desc",
    )
    assert req.status == QueryOrderStatus.CLOSED
    assert req.limit == 500

    # A3: crypto symbol keeps the slash — NOT stripped (matches alpaca_trades.symbol).
    assert req.symbols == ["BTC/USD"]
    assert "/" in req.symbols[0]

    # after= bound is accepted (used to shrink the window past entry.filled_at).
    req2 = GetOrdersRequest(
        status=QueryOrderStatus.CLOSED, symbols=["BTC/USD"], limit=500,
        direction="desc",
        after=datetime.datetime(2026, 7, 1, tzinfo=datetime.timezone.utc),
    )
    assert req2.after is not None


# ===========================================================================
# Pure resolve_stale_row cases (RED until Plan 03)
# ===========================================================================

def test_backfill_entry_canceled():
    """Case 1: entry canceled/rejected/expired, 0 fill → terminal non-position, pnl=0."""
    from src.backfill import resolve_stale_row

    for st, norm in [("OrderStatus.CANCELED", "canceled"),
                     ("OrderStatus.REJECTED", "rejected"),
                     ("OrderStatus.EXPIRED", "expired")]:
        entry = _order(status=st, filled_qty=0.0, filled_avg_price=0.0)
        row = _stale_row(status="submitted")
        outcome, kw = resolve_stale_row(row, entry, live_symbols=set(), close_order=None)
        assert outcome == "resolved"
        assert kw["status"] == norm
        assert kw["pnl"] == 0
        # terminal non-position never carries an exit price / fees
        assert kw.get("exit_price") is None
        assert kw.get("fees") is None


def test_backfill_filled_closed():
    """Case 2: filled + position gone + close found → closed, realized P&L + fees."""
    from src.backfill import resolve_stale_row

    entry = _order(status="OrderStatus.FILLED", filled_qty=1.0, filled_avg_price=80000.0)
    row = _stale_row(filled_qty=1.0, filled_avg_price=80000.0, side="buy")
    close = _order(order_id="close-1", side="sell", filled_qty=1.0,
                   filled_avg_price=85000.0, filled_at="2026-07-01T13:00:00+00:00")

    outcome, kw = resolve_stale_row(row, entry, live_symbols=set(), close_order=close)

    assert outcome == "resolved"
    assert kw["status"] == "closed"
    assert kw["exit_price"] == 85000.0
    assert kw["pnl"] == realized_pnl("buy", 80000.0, 85000.0, 1.0, TAKER_FEE)
    assert kw["fees"] == (80000.0 * 1.0 + 85000.0 * 1.0) * TAKER_FEE


def test_backfill_still_open_unchanged():
    """Case 3: filled + symbol still in live positions → unchanged (genuinely held).

    W0-1 CORRECTION (Phase 20). This case USED to feed ``live_symbols={"BTC/USD"}`` —
    a SLASHED set that Alpaca NEVER emits. ``get_positions()`` returns ``pos.symbol``
    RAW (src/alpaca_client.py:140-157), which is SLASHLESS for crypto — the codebase's
    own comment at :384-385 says so. The test therefore passed by MIRRORING the defect:
    it certified the one input shape under which the broken compare happens to work.
    The fixture is now the shape Alpaca really returns.
    """
    from src.backfill import resolve_stale_row

    entry = _order(status="OrderStatus.FILLED", filled_qty=1.0)
    row = _stale_row(symbol="BTC/USD")
    outcome, kw = resolve_stale_row(row, entry, live_symbols={"BTCUSD"}, close_order=None)
    assert outcome == "unchanged"
    assert kw is None


def test_backfill_close_not_found():
    """Case 5: filled + position gone + no close → unresolvable, untouched."""
    from src.backfill import resolve_stale_row

    entry = _order(status="OrderStatus.FILLED", filled_qty=1.0)
    row = _stale_row()
    outcome, kw = resolve_stale_row(row, entry, live_symbols=set(), close_order=None)
    assert outcome == "unresolvable"
    assert kw is None


def test_backfill_pnl_long():
    """Case 8: long realized_pnl reuse (entry_fill/exit_fill/filled_qty/TAKER_FEE)."""
    from src.backfill import resolve_stale_row

    entry = _order(status="OrderStatus.FILLED", filled_qty=2.0, filled_avg_price=100.0)
    row = _stale_row(side="buy", filled_qty=2.0, filled_avg_price=100.0)
    close = _order(order_id="c", side="sell", filled_qty=2.0, filled_avg_price=120.0,
                   filled_at="2026-07-01T13:00:00+00:00")
    outcome, kw = resolve_stale_row(row, entry, live_symbols=set(), close_order=close)
    assert outcome == "resolved"
    assert kw["pnl"] == realized_pnl("buy", 100.0, 120.0, 2.0, TAKER_FEE)
    assert kw["pnl"] > 0
    assert kw["fees"] == (100.0 * 2.0 + 120.0 * 2.0) * TAKER_FEE


def test_backfill_pnl_short():
    """Case 9: short side realized_pnl sign correct (exit < entry → profit)."""
    from src.backfill import resolve_stale_row

    entry = _order(status="OrderStatus.FILLED", filled_qty=1.0, filled_avg_price=80000.0,
                   side="sell")
    row = _stale_row(side="sell", filled_qty=1.0, filled_avg_price=80000.0)
    close = _order(order_id="c", side="buy", filled_qty=1.0, filled_avg_price=75000.0,
                   filled_at="2026-07-01T13:00:00+00:00")
    outcome, kw = resolve_stale_row(row, entry, live_symbols=set(), close_order=close)
    assert outcome == "resolved"
    assert kw["pnl"] == realized_pnl("sell", 80000.0, 75000.0, 1.0, TAKER_FEE)
    assert kw["pnl"] > 0  # short profit when exit < entry


def test_backfill_filled_avg_fallback_entry_price():
    """entry_fill falls back to row entry_price when filled_avg_price is 0/NULL."""
    from src.backfill import resolve_stale_row

    entry = _order(status="OrderStatus.FILLED", filled_qty=1.0, filled_avg_price=80000.0)
    row = _stale_row(filled_avg_price=0.0, entry_price=80000.0, filled_qty=1.0)
    close = _order(order_id="c", side="sell", filled_qty=1.0, filled_avg_price=85000.0,
                   filled_at="2026-07-01T13:00:00+00:00")
    outcome, kw = resolve_stale_row(row, entry, live_symbols=set(), close_order=close)
    assert outcome == "resolved"
    assert kw["pnl"] == realized_pnl("buy", 80000.0, 85000.0, 1.0, TAKER_FEE)


# ===========================================================================
# Driver backfill() cases (RED until Plan 03)
# ===========================================================================

def _wire(monkeypatch, bots, clients, candidates, residue=None):
    """Patch src.backfill's collaborators. Returns the FakeLogger map."""
    from src import backfill

    loggers: dict[str, FakeLogger] = {b: FakeLogger(bot_id=b) for b in bots}
    residue = residue or {b: 0 for b in bots}

    monkeypatch.setattr(backfill.reconciliation, "_enabled_bot_ids", lambda: list(bots))
    monkeypatch.setattr(backfill.reconciliation, "_client_for_bot",
                        lambda bot_id: clients[bot_id])
    monkeypatch.setattr(backfill.db, "get_stale_alpaca_candidates",
                        lambda bot_id, minutes: list(candidates.get(bot_id, [])))
    monkeypatch.setattr(backfill.db, "count_unresolvable_alpaca_rows",
                        lambda bot_id: residue.get(bot_id, 0))
    monkeypatch.setattr(backfill, "TradeLogger", lambda bot_id: loggers[bot_id])
    return loggers


def test_backfill_no_order_id_residue(monkeypatch):
    """Case 4: NULL-order_id rows excluded from candidates, counted as residue."""
    from src import backfill

    client = FakeAlpacaClient()
    _wire(monkeypatch, ["A"], {"A": client}, {"A": []}, residue={"A": 3})
    results = backfill.backfill(apply=False)
    counts = dict(results)["A"]
    assert counts["residue"] == 3
    assert counts["resolved"] == 0


def test_backfill_dry_run_no_write(monkeypatch):
    """Case 7: apply=False computes counts but never writes."""
    from src import backfill

    entry = _order(order_id="ord-1", status="OrderStatus.FILLED", filled_qty=1.0)
    close = _order(order_id="close-1", side="sell", filled_qty=1.0,
                   filled_avg_price=85000.0, filled_at="2026-07-01T13:00:00+00:00")
    client = FakeAlpacaClient(orders={"ord-1": entry}, positions=[],
                              closed={"BTC/USD": [close]})
    loggers = _wire(monkeypatch, ["A"], {"A": client},
                    {"A": [_stale_row(rid=1, order_id="ord-1")]})

    results = backfill.backfill(apply=False)
    counts = dict(results)["A"]
    assert counts["resolved"] == 1
    assert loggers["A"].update_calls == []  # nothing written in dry-run


def test_backfill_apply_writes(monkeypatch):
    """apply=True persists the resolved close via update_alpaca_trade."""
    from src import backfill

    entry = _order(order_id="ord-1", status="OrderStatus.FILLED", filled_qty=1.0,
                   filled_avg_price=80000.0)
    close = _order(order_id="close-1", side="sell", filled_qty=1.0,
                   filled_avg_price=85000.0, filled_at="2026-07-01T13:00:00+00:00")
    client = FakeAlpacaClient(orders={"ord-1": entry}, positions=[],
                              closed={"BTC/USD": [close]})
    loggers = _wire(monkeypatch, ["A"], {"A": client},
                    {"A": [_stale_row(rid=1, order_id="ord-1")]})

    backfill.backfill(apply=True)
    calls = loggers["A"].update_calls
    assert len(calls) == 1
    trade_id, status, exit_price, pnl, fees = calls[0]
    assert trade_id == 1
    assert status == "closed"
    assert exit_price == 85000.0
    assert pnl == realized_pnl("buy", 80000.0, 85000.0, 1.0, TAKER_FEE)


def test_backfill_idempotent(monkeypatch):
    """Case 6: 2nd pass sees an empty candidate set → no writes."""
    from src import backfill

    client = FakeAlpacaClient()
    loggers = _wire(monkeypatch, ["A"], {"A": client}, {"A": []})
    backfill.backfill(apply=True)
    backfill.backfill(apply=True)
    assert loggers["A"].update_calls == []


def test_backfill_guard_window(monkeypatch):
    """Case 10: guard window (BACKFILL_GUARD_MINUTES) forwarded to the candidate query."""
    from src import backfill

    monkeypatch.setenv("BACKFILL_GUARD_MINUTES", "45")
    seen = {}
    monkeypatch.setattr(backfill.reconciliation, "_enabled_bot_ids", lambda: ["A"])
    monkeypatch.setattr(backfill.reconciliation, "_client_for_bot",
                        lambda bot_id: FakeAlpacaClient())
    monkeypatch.setattr(backfill.db, "count_unresolvable_alpaca_rows", lambda bot_id: 0)
    monkeypatch.setattr(backfill, "TradeLogger", lambda bot_id: FakeLogger(bot_id))

    def _cand(bot_id, minutes):
        seen["minutes"] = minutes
        return []
    monkeypatch.setattr(backfill.db, "get_stale_alpaca_candidates", _cand)

    backfill.backfill(apply=False)
    assert seen["minutes"] == 45


def test_backfill_counts(monkeypatch):
    """Case 11: resolved/unchanged/unresolvable + residue reported per bot + overall."""
    from src import backfill

    resolved_entry = _order(order_id="ord-r", status="OrderStatus.FILLED", filled_qty=1.0)
    open_entry = _order(order_id="ord-o", status="OrderStatus.FILLED", filled_qty=1.0,
                        symbol="ETH/USD")
    unres_entry = _order(order_id="ord-u", status="OrderStatus.FILLED", filled_qty=1.0,
                         symbol="SOL/USD")
    close = _order(order_id="close-1", side="sell", filled_qty=1.0,
                   filled_avg_price=85000.0, filled_at="2026-07-01T13:00:00+00:00")
    client = FakeAlpacaClient(
        orders={"ord-r": resolved_entry, "ord-o": open_entry, "ord-u": unres_entry},
        # W3 (Phase 20): SLASHLESS — the shape get_positions() really returns.
        positions=[{"symbol": "ETHUSD"}],    # ord-o still held → unchanged
        closed={"BTC/USD": [close]},         # ord-r closes; SOL has no close → unresolvable
    )
    cands = [
        _stale_row(rid=1, order_id="ord-r", symbol="BTC/USD"),
        _stale_row(rid=2, order_id="ord-o", symbol="ETH/USD"),
        _stale_row(rid=3, order_id="ord-u", symbol="SOL/USD"),
    ]
    _wire(monkeypatch, ["A"], {"A": client}, {"A": cands}, residue={"A": 2})

    results = backfill.backfill(apply=False)
    counts = dict(results)["A"]
    assert counts["resolved"] == 1
    assert counts["unchanged"] == 1
    assert counts["unresolvable"] == 1
    assert counts["residue"] == 2


def test_backfill_ambiguous_close(monkeypatch):
    """Case 12: earliest opposite fill after entry chosen; qty mismatch → unresolvable."""
    from src import backfill

    entry = _order(order_id="ord-1", status="OrderStatus.FILLED", filled_qty=1.0,
                   filled_avg_price=80000.0, filled_at="2026-07-01T12:00:00+00:00")
    # A pre-entry close (ignored) + two post-entry closes; earliest post = 13:00 @ 85000.
    pre = _order(order_id="pre", side="sell", filled_qty=1.0, filled_avg_price=70000.0,
                 filled_at="2026-07-01T10:00:00+00:00")
    early = _order(order_id="early", side="sell", filled_qty=1.0, filled_avg_price=85000.0,
                   filled_at="2026-07-01T13:00:00+00:00")
    late = _order(order_id="late", side="sell", filled_qty=1.0, filled_avg_price=90000.0,
                  filled_at="2026-07-01T14:00:00+00:00")
    client = FakeAlpacaClient(orders={"ord-1": entry}, positions=[],
                              closed={"BTC/USD": [late, early, pre]})
    loggers = _wire(monkeypatch, ["A"], {"A": client},
                    {"A": [_stale_row(rid=1, order_id="ord-1", filled_qty=1.0)]})
    backfill.backfill(apply=True)
    # earliest-after-entry (13:00 @ 85000) selected, not 14:00 nor the pre-entry fill.
    assert loggers["A"].update_calls[0][2] == 85000.0

    # qty mismatch → no valid single close → unresolvable, nothing written.
    partial = _order(order_id="partial", side="sell", filled_qty=0.4,
                     filled_avg_price=85000.0, filled_at="2026-07-01T13:00:00+00:00")
    client2 = FakeAlpacaClient(orders={"ord-1": entry}, positions=[],
                               closed={"BTC/USD": [partial]})
    loggers2 = _wire(monkeypatch, ["A"], {"A": client2},
                     {"A": [_stale_row(rid=1, order_id="ord-1", filled_qty=1.0)]})
    results = backfill.backfill(apply=True)
    assert dict(results)["A"]["unresolvable"] == 1
    assert loggers2["A"].update_calls == []


def test_backfill_per_bot_keys(monkeypatch):
    """Case 13: each bot uses its OWN account client (no shared/bare keys)."""
    from src import backfill

    # W3 (Phase 20): SLASHLESS positions — the shape get_positions() really returns.
    client_a = FakeAlpacaClient(orders={"ord-a": _order(order_id="ord-a")},
                                positions=[{"symbol": "BTCUSD"}])
    client_b = FakeAlpacaClient(orders={"ord-b": _order(order_id="ord-b", symbol="ETH/USD")},
                                positions=[{"symbol": "ETHUSD"}])
    clients = {"A": client_a, "B": client_b}
    asked: list[str] = []

    monkeypatch.setattr(backfill.reconciliation, "_enabled_bot_ids", lambda: ["A", "B"])

    def _client_for_bot(bot_id):
        asked.append(bot_id)
        return clients[bot_id]
    monkeypatch.setattr(backfill.reconciliation, "_client_for_bot", _client_for_bot)
    monkeypatch.setattr(backfill.db, "get_stale_alpaca_candidates",
                        lambda bot_id, minutes: (
                            [_stale_row(rid=1, order_id="ord-a", symbol="BTC/USD")]
                            if bot_id == "A"
                            else [_stale_row(rid=1, order_id="ord-b", symbol="ETH/USD")]))
    monkeypatch.setattr(backfill.db, "count_unresolvable_alpaca_rows", lambda bot_id: 0)
    monkeypatch.setattr(backfill, "TradeLogger", lambda bot_id: FakeLogger(bot_id))

    backfill.backfill(apply=False)

    assert asked == ["A", "B"]
    # Bot A's client only ever queried A's order; B's only B's — no cross-account bleed.
    assert client_a.get_order_calls == ["ord-a"]
    assert client_b.get_order_calls == ["ord-b"]


# ===========================================================================
# DATABASE_URL-gated real-SQL guard (Case 14)
# ===========================================================================

@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs Postgres")
def test_stale_candidates_sql():
    """Case 14: real SQL returns only stale open/submitted + order_id rows; NULL
    order_id excluded from candidates but counted by count_unresolvable_alpaca_rows."""
    from src import db

    bot_id = "TESTBACKFILL"
    old = (datetime.datetime.now(datetime.timezone.utc)
           - datetime.timedelta(hours=2)).isoformat()
    with db.connection() as conn:
        conn.execute("DELETE FROM alpaca_trades WHERE bot_id = %s", (bot_id,))
        conn.execute(
            "INSERT INTO alpaca_trades (bot_id, order_id, symbol, side, qty, "
            "entry_price, status, timestamp) VALUES "
            "(%s,%s,%s,%s,%s,%s,%s,%s)",
            (bot_id, "ord-old", "BTC/USD", "buy", 1.0, 80000.0, "submitted", old),
        )
        conn.execute(
            "INSERT INTO alpaca_trades (bot_id, order_id, symbol, side, qty, "
            "entry_price, status, timestamp) VALUES "
            "(%s,%s,%s,%s,%s,%s,%s,%s)",
            (bot_id, None, "ETH/USD", "buy", 1.0, 4000.0, "open", old),
        )
        conn.commit()

    cands = db.get_stale_alpaca_candidates(bot_id, older_than_minutes=30)
    order_ids = {c["order_id"] for c in cands}
    assert "ord-old" in order_ids
    assert None not in order_ids
    assert db.count_unresolvable_alpaca_rows(bot_id) >= 1

    with db.connection() as conn:
        conn.execute("DELETE FROM alpaca_trades WHERE bot_id = %s", (bot_id,))
        conn.commit()


# ===========================================================================
# PHASE 20 — G3: THE BACKFILL SLASH BUG AND THE `None` DOOR (cases 1-8)
#
# src/backfill.py is a LOADED GUN. `:148` builds live_symbols from Alpaca's RAW
# `pos.symbol`, which is SLASH-LESS for crypto (src/alpaca_client.py:140-157; the
# codebase says so itself at :384-385). `:72` and `:155` then compare a SLASHED
# `row["symbol"]` against it. `"BTC/USD" in {"BTCUSD"}` is False for EVERY held
# position, ALWAYS — so the `unchanged` arm is UNREACHABLE in production, and a
# genuinely-held, live, open position resolves as CLOSED with a FABRICATED P&L.
#
# The second landmine: `:148`'s `or []` coerces a FAILED get_positions() (None) into
# an empty set. `None` means THE ALPACA CALL FAILED — not "nothing is held". Coerced,
# an Alpaca outage makes the ENTIRE BOOK look vanished. The live monitor guards this
# at src/alpaca_orchestrator.py:133-134; the backfill does not. Same class as Phase
# 18's B1.
#
# Every case here is PURE — fakes only. No DB, no network, no Alpaca.
# ===========================================================================

import pathlib  # noqa: E402

from src.universe import normalize  # noqa: E402

_BACKFILL_SRC = (
    pathlib.Path(__file__).resolve().parents[1] / "src" / "backfill.py"
).read_text(encoding="utf-8")


class FakeAlpacaClientPositionsFail(FakeAlpacaClient):
    """get_positions() returns None — THE ALPACA CALL FAILED.

    NOT "nothing is held". `or []` at src/backfill.py:148 erases that distinction.
    """

    def get_positions(self):
        return None


def test_held_position_real_alpaca_shape_is_unchanged():
    """Case 1 — THE ONE THAT MATTERS. A genuinely HELD position, in Alpaca's REAL
    slashless shape, with a close order available.

    RED on main: returns ('resolved', {'status': 'closed', 'exit_price': 80.0,
    'pnl': -20.45, 'fees': 0.45}) — a LIVE position closed with a FABRICATED LOSS.
    """
    from src.backfill import resolve_stale_row

    entry = _order(status="OrderStatus.FILLED", filled_qty=1.0)
    row = _stale_row(symbol="BTC/USD", side="buy", filled_qty=1.0,
                     filled_avg_price=100.0, entry_price=100.0)
    close = _order(order_id="close-1", side="sell", filled_qty=1.0,
                   filled_avg_price=80.0, filled_at="2026-07-01T13:00:00+00:00")

    outcome, kw = resolve_stale_row(
        row, entry, live_symbols={normalize("BTC/USD")}, close_order=close)

    assert outcome == "unchanged"
    # A HELD position NEVER carries a pnl. If kw is not None the backfill just
    # invented a P&L for a position that is still open at Alpaca.
    assert kw is None


def test_held_position_no_close_order_is_unchanged_not_unresolvable():
    """Case 2 — held, no close order available → `unchanged`, NOT `unresolvable`.

    NOT COSMETIC: `unresolvable` writes pnl = NULL, which drops the row out of
    get_open_alpaca_positions (src/db.py:160) and thereby KILLS its stop-loss,
    take-profit and exit advisor WHILE THE POSITION IS STILL LIVE AT ALPACA.

    RED on main: returns ('unresolvable', None).
    """
    from src.backfill import resolve_stale_row

    entry = _order(status="OrderStatus.FILLED", filled_qty=1.0)
    row = _stale_row(symbol="BTC/USD")

    outcome, kw = resolve_stale_row(
        row, entry, live_symbols={normalize("BTC/USD")}, close_order=None)

    assert outcome == "unchanged"
    assert kw is None


def test_symbol_shape_matrix():
    """Case 3 — all four slash combinations resolve to `unchanged`. BOTH sides normalized.

    RED on main: 2 of the 4 fail (the two where the row and the live set disagree
    on the slash).
    """
    from src.backfill import resolve_stale_row

    entry = _order(status="OrderStatus.FILLED", filled_qty=1.0)
    close = _order(order_id="c", side="sell", filled_qty=1.0, filled_avg_price=80.0,
                   filled_at="2026-07-01T13:00:00+00:00")

    for row_symbol in ("BTC/USD", "BTCUSD"):
        for live_symbol in ("BTC/USD", "BTCUSD"):
            row = _stale_row(symbol=row_symbol)
            outcome, kw = resolve_stale_row(
                row, entry, live_symbols={live_symbol}, close_order=close)
            assert outcome == "unchanged", (
                f"row={row_symbol!r} live={{{live_symbol!r}}} -> {outcome!r}; "
                f"normalize collapses both to {normalize(row_symbol)!r}"
            )
            assert kw is None

    # ONE normalizer, not two. A second one is a second thing to drift — and drift
    # between the monitor and the backfill is exactly how this bug was born.
    assert 'replace("/"' not in _BACKFILL_SRC, \
        "src/backfill.py hand-rolled a local normalizer instead of src.universe.normalize"


def test_genuinely_vanished_position_still_resolves():
    """Case 4 — POSITIVE CONTROL. The fix must not make the backfill inert.

    The position is genuinely GONE from Alpaca (a different symbol is held), so the
    close order really is the close. Passes today; must keep passing.
    """
    from src.backfill import resolve_stale_row

    entry = _order(status="OrderStatus.FILLED", filled_qty=1.0, filled_avg_price=80000.0)
    row = _stale_row(symbol="BTC/USD", side="buy", filled_qty=1.0,
                     filled_avg_price=80000.0)
    close = _order(order_id="c", side="sell", filled_qty=1.0, filled_avg_price=85000.0,
                   filled_at="2026-07-01T13:00:00+00:00")

    outcome, kw = resolve_stale_row(
        row, entry, live_symbols={"ETHUSD"}, close_order=close)

    assert outcome == "resolved"
    assert kw["status"] == "closed"
    assert kw["exit_price"] == 85000.0
    assert kw["pnl"] == realized_pnl("buy", 80000.0, 85000.0, 1.0, TAKER_FEE)
    assert kw["fees"] == (80000.0 * 1.0 + 85000.0 * 1.0) * TAKER_FEE


def test_driver_issues_no_close_hunt_for_a_held_symbol(monkeypatch):
    """Case 5 — the DRIVER's second compare (backfill.py:155).

    Fixing only :72 leaves the driver hunting closes for every held symbol. This case
    is what forces BOTH sites to be normalized.

    RED on main: :155's raw compare misses, a close hunt IS issued, and the row resolves.
    """
    from src import backfill

    entry = _order(order_id="ord-1", status="OrderStatus.FILLED", filled_qty=1.0)
    close = _order(order_id="close-1", side="sell", filled_qty=1.0,
                   filled_avg_price=85000.0, filled_at="2026-07-01T13:00:00+00:00")
    client = FakeAlpacaClient(
        orders={"ord-1": entry},
        positions=[{"symbol": "BTCUSD"}],     # HELD, in Alpaca's real shape
        closed={"BTC/USD": [close]},
    )
    _wire(monkeypatch, ["A"], {"A": client},
          {"A": [_stale_row(rid=1, order_id="ord-1", symbol="BTC/USD")]})

    results = backfill.backfill(apply=False)
    counts = dict(results)["A"]

    assert client.get_closed_calls == [], \
        "a close hunt was issued for a symbol that is STILL HELD at Alpaca"
    assert counts["unchanged"] == 1
    assert counts["resolved"] == 0


def test_get_positions_none_aborts_the_bot(monkeypatch):
    """Case 6 — THE SECOND LANDMINE. get_positions() -> None means THE CALL FAILED.

    `or []` at src/backfill.py:148 turns an Alpaca OUTAGE into "every position
    vanished" and would terminate the entire live book.

    The `counts["error"] = "positions_unavailable"` marker is LOAD-BEARING, not
    decoration: that counts dict IS the RECOVERY CEILING a human reads before
    authorizing A WRITE TO PRODUCTION TRADE DATA. Without it, an outage produces
    {"resolved": 0, ...} — BYTE-IDENTICAL to a clean bot with nothing to repair. An
    operator would read "0 recoverable" as "nothing to fix" when it actually means
    "ALPACA NEVER ANSWERED."

    RED on main: resolves the row against an empty set.
    """
    from src import backfill

    entry = _order(order_id="ord-1", status="OrderStatus.FILLED", filled_qty=1.0)
    close = _order(order_id="close-1", side="sell", filled_qty=1.0,
                   filled_avg_price=85000.0, filled_at="2026-07-01T13:00:00+00:00")
    client = FakeAlpacaClientPositionsFail(
        orders={"ord-1": entry}, closed={"BTC/USD": [close]})
    loggers = _wire(monkeypatch, ["A"], {"A": client},
                    {"A": [_stale_row(rid=1, order_id="ord-1", symbol="BTC/USD")]})

    # apply=True on purpose: even ARMED, an outage must write NOTHING.
    results = backfill.backfill(apply=True)
    counts = dict(results)["A"]

    assert counts["resolved"] == 0
    assert counts["unresolvable"] == 0
    assert loggers["A"].update_calls == []
    assert client.get_closed_calls == []
    assert counts.get("error") == "positions_unavailable", (
        "an Alpaca outage is indistinguishable from 'nothing to recover' — the recovery "
        "ceiling a human authorizes a prod write against would be a lie"
    )


def test_resolve_stale_row_treats_None_live_symbols_as_the_SAFE_arm():
    """Case 6b — live_symbols=None is the SAFE arm: leave the row alone, do not raise.

    Once the fix lands, a defensive `{normalize(s) for s in live_symbols}` would
    TypeError on None. None means the positions call FAILED, so the only safe answer
    is "leave the row alone" — never "resolve it against nothing".
    """
    from src.backfill import resolve_stale_row

    entry = _order(status="OrderStatus.FILLED", filled_qty=1.0)
    row = _stale_row(symbol="BTC/USD")
    close = _order(order_id="c", side="sell", filled_qty=1.0, filled_avg_price=80.0,
                   filled_at="2026-07-01T13:00:00+00:00")

    outcome, kw = resolve_stale_row(row, entry, live_symbols=None, close_order=close)

    assert outcome == "unchanged"
    assert kw is None


def test_dry_run_writes_nothing(monkeypatch):
    """Case 7 — FENCE. Dry-run is the DEFAULT and it writes NOTHING.

    Plus a SOURCE assertion: the only mutation site is guarded by `and apply`.
    """
    from src import backfill

    entry = _order(order_id="ord-1", status="OrderStatus.FILLED", filled_qty=1.0)
    close = _order(order_id="close-1", side="sell", filled_qty=1.0,
                   filled_avg_price=85000.0, filled_at="2026-07-01T13:00:00+00:00")
    client = FakeAlpacaClient(orders={"ord-1": entry}, positions=[],
                              closed={"BTC/USD": [close]})
    loggers = _wire(monkeypatch, ["A"], {"A": client},
                    {"A": [_stale_row(rid=1, order_id="ord-1")]})

    backfill.backfill(apply=False)
    assert loggers["A"].update_calls == []

    # POSITIVE CONTROL: the mutation call really is in this file.
    call = "logger.update_alpaca_trade("
    assert call in _BACKFILL_SRC
    assert _BACKFILL_SRC.count(call) == 1, \
        "more than one mutation site appeared in the backfill"

    guard = 'if outcome == "resolved" and apply:'
    assert guard in _BACKFILL_SRC, "the dry-run write gate moved"
    assert _BACKFILL_SRC.index(guard) < _BACKFILL_SRC.index(call), \
        "the mutation is no longer behind the `and apply` gate"


def test_dry_run_reports_the_recovery_ceiling(monkeypatch):
    """Case 8 — the dry-run counts dict IS the recovery ceiling. Assert its SHAPE.

    Never a live number: RESEARCH R1 refuted every projected magnitude in this phase.
    """
    from src import backfill

    entry = _order(order_id="ord-1", status="OrderStatus.FILLED", filled_qty=1.0)
    close = _order(order_id="close-1", side="sell", filled_qty=1.0,
                   filled_avg_price=85000.0, filled_at="2026-07-01T13:00:00+00:00")
    client = FakeAlpacaClient(orders={"ord-1": entry}, positions=[],
                              closed={"BTC/USD": [close]})
    _wire(monkeypatch, ["A"], {"A": client},
          {"A": [_stale_row(rid=1, order_id="ord-1")]}, residue={"A": 2})

    counts = dict(backfill.backfill(apply=False))["A"]

    for key in ("resolved", "unchanged", "unresolvable", "residue"):
        assert key in counts, f"the recovery-ceiling counts dict lost {key!r}"
        assert isinstance(counts[key], int)
