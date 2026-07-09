# tests/test_close_pnl.py
"""PositionMonitor close-path storage — Phase 12 Wave 0 (RED), PNL-02 cases 6-10.

Drives ``PositionMonitor._check_all_positions`` with zero-network in-memory doubles
(FakeLogger + FakeAlpacaClient, mirroring tests/test_order_resolution.py) and proves
that a triggered close stores the REAL exit fill (not the live quote), the net
realized P&L, and the fees total — with logged fallbacks for missing fills.

RED against the current un-wired monitor, which stores exit_price=current_price,
pnl=trade_pnl (quote-based) and passes no fees.
"""
import datetime

import pytest

from src.alpaca_orchestrator import PositionMonitor
from src.fee_gate import TAKER_FEE

_TERMINAL = {"closed", "stopped", "target_hit", "canceled", "expired", "rejected"}

SYMBOL = "BTC/USD"
ENTRY_FILL = 100.0
EXIT_FILL = 82.0        # real close fill (distinct from the live quote)
CURRENT_PRICE = 80.0    # live quote — must NOT be used for pnl/exit_price
QTY = 2.0


# ---------------------------------------------------------------------------
# In-memory doubles (fees kwarg added vs the Phase 11 copy)
# ---------------------------------------------------------------------------

class FakeLogger:
    def __init__(self, seed_rows=None):
        self.bot_id = "A"
        self.rows: dict[int, dict] = {}
        self._next = 1
        for r in (seed_rows or []):
            row = dict(r)
            self.rows[row["id"]] = row
            self._next = max(self._next, row["id"] + 1)

    def update_alpaca_trade(self, trade_id, status, exit_price=None, pnl=None, fees=None):
        row = self.rows[trade_id]
        row["status"] = status
        if exit_price is not None:
            row["exit_price"] = exit_price
        if pnl is not None:
            row["pnl"] = pnl
        if fees is not None:
            row["fees"] = fees
        if status in _TERMINAL:
            row["closed_at"] = "2026-07-09T00:00:00+00:00"

    def get_open_alpaca_positions(self):
        return [dict(r) for r in self.rows.values() if r.get("status") == "open"]


class FakeAlpacaClient:
    def __init__(self, close_result, current_price=CURRENT_PRICE):
        self._close_result = close_result
        self._current_price = current_price
        self.closed: list[str] = []

    def get_positions(self):
        # Return the symbol (Alpaca-style, no slash) so reconciliation keeps it.
        return [{"symbol": SYMBOL.replace("/", "")}]

    def get_latest_price(self, symbol):
        return self._current_price

    def get_bars(self, symbol, timeframe=None, limit=None):
        return []  # ATR 0 -> exit is driven by the hard_stop pnl_pct

    def close_position(self, symbol):
        self.closed.append(symbol)
        return dict(self._close_result)


def _open_row(entry_fill=ENTRY_FILL, entry_price=ENTRY_FILL, qty=QTY):
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "id": 1, "symbol": SYMBOL, "asset_class": "crypto", "side": "buy",
        "qty": qty, "entry_price": entry_price, "filled_avg_price": entry_fill,
        "status": "open", "order_id": "ord-1", "timestamp": ts,
    }


def _close_dict(filled_avg_price=EXIT_FILL):
    return {
        "order_id": "ord-close", "status": "OrderStatus.FILLED",
        "filled_qty": QTY, "filled_avg_price": filled_avg_price,
        "symbol": SYMBOL, "qty": QTY, "side": "sell", "order_type": "market",
    }


def _run(logger, alpaca):
    monitor = PositionMonitor(alpaca, logger)
    monitor._check_all_positions()
    return monitor


# ---------------------------------------------------------------------------
# Case 6 — exit_price is the real fill, not the quote
# ---------------------------------------------------------------------------

def test_close_stores_exit_fill():
    logger = FakeLogger([_open_row()])
    monitor = _run(logger, FakeAlpacaClient(_close_dict()))
    row = logger.rows[1]
    assert row["status"] == "closed"
    assert row["exit_price"] == pytest.approx(EXIT_FILL, abs=1e-9)
    assert row["exit_price"] != pytest.approx(CURRENT_PRICE, abs=1e-9)


# ---------------------------------------------------------------------------
# Case 7 — stored pnl is the net realized figure, not the quote-based trade_pnl
# ---------------------------------------------------------------------------

def test_close_stores_net_pnl():
    logger = FakeLogger([_open_row()])
    _run(logger, FakeAlpacaClient(_close_dict()))
    row = logger.rows[1]
    gross = (EXIT_FILL - ENTRY_FILL) * QTY
    fees = (ENTRY_FILL * QTY + EXIT_FILL * QTY) * TAKER_FEE
    expected = gross - fees
    assert row["pnl"] == pytest.approx(expected, abs=1e-9)
    # NOT the quote-based figure (current_price 80 -> gross -40)
    quote_pnl = (CURRENT_PRICE - ENTRY_FILL) * QTY
    assert row["pnl"] != pytest.approx(quote_pnl, abs=1e-9)


# ---------------------------------------------------------------------------
# Case 8 — fees persisted on the row
# ---------------------------------------------------------------------------

def test_close_persists_fees():
    logger = FakeLogger([_open_row()])
    _run(logger, FakeAlpacaClient(_close_dict()))
    row = logger.rows[1]
    expected_fees = (ENTRY_FILL * QTY + EXIT_FILL * QTY) * TAKER_FEE
    assert row["fees"] == pytest.approx(expected_fees, abs=1e-9)


# ---------------------------------------------------------------------------
# Case 9 — legacy row (entry fill None/0) falls back to entry_price, logged
# ---------------------------------------------------------------------------

def test_close_legacy_entry_fallback(caplog):
    row_seed = _open_row(entry_fill=0.0, entry_price=ENTRY_FILL)
    logger = FakeLogger([row_seed])
    with caplog.at_level("WARNING"):
        _run(logger, FakeAlpacaClient(_close_dict()))
    row = logger.rows[1]
    # entry_fill falls back to entry_price -> same realized figure as case 7
    gross = (EXIT_FILL - ENTRY_FILL) * QTY
    fees = (ENTRY_FILL * QTY + EXIT_FILL * QTY) * TAKER_FEE
    assert row["pnl"] == pytest.approx(gross - fees, abs=1e-9)
    assert any("entry" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# Case 10 — missing exit fill (close dict filled_avg_price 0) -> current_price, logged
# ---------------------------------------------------------------------------

def test_close_exit_fallback(caplog):
    logger = FakeLogger([_open_row()])
    with caplog.at_level("WARNING"):
        _run(logger, FakeAlpacaClient(_close_dict(filled_avg_price=0.0)))
    row = logger.rows[1]
    # exit_fill falls back to current_price
    assert row["exit_price"] == pytest.approx(CURRENT_PRICE, abs=1e-9)
    gross = (CURRENT_PRICE - ENTRY_FILL) * QTY
    fees = (ENTRY_FILL * QTY + CURRENT_PRICE * QTY) * TAKER_FEE
    assert row["pnl"] == pytest.approx(gross - fees, abs=1e-9)
    assert any("exit" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# total_pnl accumulates the realized figure
# ---------------------------------------------------------------------------

def test_total_pnl_uses_realized():
    logger = FakeLogger([_open_row()])
    monitor = _run(logger, FakeAlpacaClient(_close_dict()))
    gross = (EXIT_FILL - ENTRY_FILL) * QTY
    fees = (ENTRY_FILL * QTY + EXIT_FILL * QTY) * TAKER_FEE
    assert monitor.total_pnl == pytest.approx(gross - fees, abs=1e-9)
    assert monitor.get_stats()["total_pnl"] == pytest.approx(gross - fees, abs=1e-9)
