"""Phase 18 — the sentinel writer never fabricates again (VALIDATION cases 1-8, 4b, 5b).

Unit under test: ``src.alpaca_orchestrator._resolve_external_exit(alpaca, row, live_symbols)``.

Zero network, zero DB. ``FakeAlpaca`` replicates the three-method surface of
``tests/test_backfill.py::FakeAlpacaClient`` (get_order / get_positions /
get_closed_orders) and additionally records EVERY call, so case 4b can assert that
a ``live_symbols=None`` (i.e. get_positions() FAILED) resolves to "no write" WITHOUT
touching Alpaca at all.
"""
import pathlib

import pytest

from src.alpaca_orchestrator import _resolve_external_exit
from src.fee_gate import TAKER_FEE
from src.pnl import realized_pnl

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "alpaca_orchestrator.py"


# ---------------------------------------------------------------------------
# Doubles (shape copied from tests/test_backfill.py:66-116)
# ---------------------------------------------------------------------------

def _order(order_id="ord-1", status="OrderStatus.FILLED", filled_qty=2.0,
           filled_avg_price=100.0, symbol="BTC/USD", qty=2.0, side="buy",
           order_type="market", filled_at="2026-07-01T12:00:00+00:00"):
    return {
        "order_id": order_id, "status": status, "filled_qty": filled_qty,
        "filled_avg_price": filled_avg_price, "symbol": symbol, "qty": qty,
        "side": side, "order_type": order_type, "filled_at": filled_at,
    }


def _row(rid=1, order_id="ord-1", symbol="BTC/USD", side="buy", qty=2.0,
         entry_price=100.0, filled_qty=2.0, filled_avg_price=100.0,
         status="open", timestamp="2026-07-01T12:00:00+00:00"):
    return {
        "id": rid, "bot_id": "A", "order_id": order_id, "symbol": symbol,
        "side": side, "qty": qty, "entry_price": entry_price,
        "filled_qty": filled_qty, "filled_avg_price": filled_avg_price,
        "order_type": "market", "status": status, "timestamp": timestamp,
        "fees": None,
    }


class FakeAlpaca:
    """get_order / get_positions / get_closed_orders. No network. Records calls."""

    def __init__(self, orders=None, positions=None, closed=None,
                 raise_on_get_order=False, raise_on_get_closed=False):
        self._orders = orders or {}
        self._positions = positions or []
        self._closed = closed or {}
        self._raise_get_order = raise_on_get_order
        self._raise_get_closed = raise_on_get_closed
        self.calls: list[tuple] = []

    def get_order(self, order_id):
        self.calls.append(("get_order", order_id))
        if self._raise_get_order:
            raise RuntimeError("alpaca 500")
        o = self._orders.get(order_id)
        return dict(o) if o else None

    def get_positions(self):
        self.calls.append(("get_positions",))
        return [dict(p) for p in self._positions]

    def get_closed_orders(self, symbol, after=None):
        self.calls.append(("get_closed_orders", symbol, after))
        if self._raise_get_closed:
            raise RuntimeError("alpaca 500")
        return [dict(o) for o in self._closed.get(symbol, [])]


def _reconcile_slice() -> str:
    """The monitor's reconcile block (the code that used to fabricate)."""
    text = _SRC.read_text(encoding="utf-8")
    start = text.index("def _check_all_positions")
    end = text.index("for trade in open_trades:", text.index("live_symbols is not None", start))
    return text[start:end]


# ---------------------------------------------------------------------------
# case 1 — the fabrication literals are GONE (static, with a positive control)
# ---------------------------------------------------------------------------

def test_fabrication_literals_are_gone():
    block = _reconcile_slice()
    # POSITIVE CONTROL — the slice we scanned is real and is the right one.
    assert block.strip(), "reconcile slice is empty — the static test would pass vacuously"
    assert "live_symbols" in block

    assert "pnl=0.0" not in block
    assert 'exit_price=trade.get("entry_price"' not in block


# ---------------------------------------------------------------------------
# case 2 — unresolvable -> NULL, never 0.0
# ---------------------------------------------------------------------------

def test_unresolvable_writes_null_never_zero():
    alpaca = FakeAlpaca(orders={"ord-1": _order()}, closed={"BTC/USD": []})
    kwargs = _resolve_external_exit(alpaca, _row(), live_symbols=set())

    assert kwargs == {"status": "closed", "exit_price": None, "pnl": None, "fees": None}
    assert kwargs["pnl"] is None          # identity — NOT `== 0`
    assert kwargs["exit_price"] is None


# ---------------------------------------------------------------------------
# case 3 — resolvable -> the REAL, fee-net P&L
# ---------------------------------------------------------------------------

def test_resolvable_recovers_the_real_fee_net_pnl():
    close = _order(order_id="ord-2", side="sell", filled_avg_price=110.0,
                   filled_qty=2.0, qty=2.0, filled_at="2026-07-02T12:00:00+00:00")
    alpaca = FakeAlpaca(orders={"ord-1": _order()}, closed={"BTC/USD": [close]})

    kwargs = _resolve_external_exit(alpaca, _row(), live_symbols=set())

    assert kwargs["status"] == "closed"
    assert kwargs["exit_price"] == 110.0
    expected = realized_pnl("buy", 100.0, 110.0, 2.0, TAKER_FEE)
    assert kwargs["pnl"] == pytest.approx(expected)
    assert kwargs["pnl"] != 0.0     # not fabricated
    assert kwargs["pnl"] != 20.0    # fees subtracted on BOTH legs


# ---------------------------------------------------------------------------
# case 4 — a HELD position is left alone (THE SLASH TRAP)
# ---------------------------------------------------------------------------

def test_held_position_is_left_alone_slash_trap():
    alpaca = FakeAlpaca(orders={"ord-1": _order()}, closed={"BTC/USD": []})
    # live_symbols is SLASH-STRIPPED, exactly as alpaca_orchestrator.py:159 builds it.
    kwargs = _resolve_external_exit(alpaca, _row(symbol="BTC/USD"),
                                    live_symbols={"BTCUSD"})
    assert kwargs == {}, "a HELD position must never be written (mass-close regression)"


# ---------------------------------------------------------------------------
# case 4b — THE THIRD DOOR: live_symbols is None (get_positions FAILED)
# ---------------------------------------------------------------------------

def test_none_live_symbols_is_no_op():
    alpaca = FakeAlpaca(orders={"ord-1": _order()}, closed={"BTC/USD": []})
    kwargs = _resolve_external_exit(alpaca, _row(), live_symbols=None)

    assert kwargs == {}
    assert alpaca.calls == [], "None means the fetch FAILED — no Alpaca call, no write"


# ---------------------------------------------------------------------------
# case 5 / 5b — a transient Alpaca error writes NOTHING
# ---------------------------------------------------------------------------

def test_transient_alpaca_error_writes_nothing():
    alpaca = FakeAlpaca(orders={"ord-1": _order()}, raise_on_get_closed=True)
    kwargs = _resolve_external_exit(alpaca, _row(), live_symbols=set())

    assert kwargs == {}
    assert kwargs != {"status": "closed", "exit_price": None, "pnl": None, "fees": None}


def test_each_alpaca_call_fails_closed():
    alpaca = FakeAlpaca(orders={"ord-1": _order()}, raise_on_get_order=True)
    assert _resolve_external_exit(alpaca, _row(), live_symbols=set()) == {}


# ---------------------------------------------------------------------------
# case 6 — a terminal 0-fill entry keeps its HONEST zero
# ---------------------------------------------------------------------------

def test_terminal_zero_fill_keeps_the_honest_zero():
    entry = _order(status="OrderStatus.CANCELED", filled_qty=0.0, filled_avg_price=0.0)
    alpaca = FakeAlpaca(orders={"ord-1": entry}, closed={"BTC/USD": []})

    kwargs = _resolve_external_exit(alpaca, _row(), live_symbols=set())

    assert kwargs["status"] == "canceled"
    assert kwargs["exit_price"] is None
    assert kwargs["pnl"] == 0


# ---------------------------------------------------------------------------
# case 7 — a partial/ambiguous close is unresolvable
# ---------------------------------------------------------------------------

def test_partial_close_is_unresolvable():
    half = _order(order_id="ord-2", side="sell", filled_avg_price=110.0,
                  filled_qty=1.0, qty=1.0, filled_at="2026-07-02T12:00:00+00:00")
    alpaca = FakeAlpaca(orders={"ord-1": _order()}, closed={"BTC/USD": [half]})

    kwargs = _resolve_external_exit(alpaca, _row(), live_symbols=set())

    assert kwargs["status"] == "closed"
    assert kwargs["pnl"] is None


# ---------------------------------------------------------------------------
# case 8 — a row with no order_id resolves to NULL
# ---------------------------------------------------------------------------

def test_missing_order_id_resolves_to_null():
    alpaca = FakeAlpaca()
    kwargs = _resolve_external_exit(alpaca, _row(order_id=None), live_symbols=set())

    assert kwargs["status"] == "closed"
    assert kwargs["pnl"] is None
    assert kwargs["exit_price"] is None
