# tests/test_order_resolution.py
"""Order-state resolution engine — Phase 11 validation suite (Wave 0).

Proves PNL-01 (every submitted order reaches a recorded terminal state — no
silent drops) and PNL-04 (DB-driven, idempotent, crash-safe resolution so the
forward resolution rate is ~100%).

No live Alpaca network and no Postgres: an in-memory ``FakeLogger`` stands in
for the ``alpaca_trades`` table (same public surface as ``TradeLogger`` —
``log_alpaca_trade`` / ``update_alpaca_trade`` / ``get_open_alpaca_positions`` /
``get_pending_alpaca_orders``) and a ``FakeAlpacaClient`` scripts
``get_order`` / ``cancel_order`` / ``place_market_order`` / ``place_limit_order``
with ``_parse_order``-shaped dicts (and can raise on demand).
"""
import datetime

import pytest

from src.bot_config import BotConfig
from src.bot_thread import BotThread


# Alpaca order statuses that terminalize the row (used to stamp closed_at).
_TERMINAL = {"closed", "stopped", "target_hit", "canceled", "expired", "rejected"}


# ---------------------------------------------------------------------------
# In-memory doubles
# ---------------------------------------------------------------------------

class FakeLogger:
    """In-memory stand-in for TradeLogger's alpaca_trades surface."""

    def __init__(self, seed_rows=None):
        self.bot_id = "A"
        self.rows: dict[int, dict] = {}
        self._next = 1
        for r in (seed_rows or []):
            row = dict(r)
            self.rows[row["id"]] = row
            self._next = max(self._next, row["id"] + 1)

    def log_alpaca_trade(self, trade_data: dict) -> int:
        tid = self._next
        self._next += 1
        row = dict(trade_data)
        row["id"] = tid
        row.setdefault("status", "submitted")
        if row["status"] in _TERMINAL:
            row.setdefault("closed_at", "2026-07-09T00:00:00+00:00")
        self.rows[tid] = row
        return tid

    def update_alpaca_trade(self, trade_id, status, exit_price=None, pnl=None):
        row = self.rows[trade_id]
        row["status"] = status
        if exit_price is not None:
            row["exit_price"] = exit_price
        if pnl is not None:
            row["pnl"] = pnl
        if status in _TERMINAL:
            row["closed_at"] = "2026-07-09T00:00:00+00:00"

    def get_open_alpaca_positions(self):
        return [dict(r) for r in self.rows.values() if r.get("status") == "open"]

    def get_pending_alpaca_orders(self):
        return [dict(r) for r in self.rows.values() if r.get("status") == "submitted"]


def _order(order_id="ord-1", status="OrderStatus.ACCEPTED", filled_qty=0.0,
           filled_avg_price=0.0, symbol="BTC/USD", qty=1.0, side="buy",
           order_type="market"):
    """A _parse_order-shaped dict (status rendered like str(OrderStatus.X))."""
    return {
        "order_id": order_id,
        "status": status,
        "filled_qty": filled_qty,
        "filled_avg_price": filled_avg_price,
        "symbol": symbol,
        "qty": qty,
        "side": side,
        "order_type": order_type,
    }


class FakeAlpacaClient:
    """Scripts order lifecycle calls; never touches the network."""

    def __init__(self, get_order_result=None, get_order_sequence=None,
                 get_order_error=False, place_result=None, place_error=False):
        self._get_order_result = get_order_result
        self._get_order_sequence = list(get_order_sequence) if get_order_sequence else None
        self._get_order_error = get_order_error
        self._place_result = place_result
        self._place_error = place_error
        self.canceled: list[str] = []
        self.get_order_calls: list[str] = []
        self.placed: list[dict] = []

    def get_order(self, order_id):
        self.get_order_calls.append(order_id)
        if self._get_order_error:
            raise RuntimeError("get_order boom")
        if self._get_order_sequence:
            return dict(self._get_order_sequence.pop(0))
        return dict(self._get_order_result)

    def cancel_order(self, order_id):
        self.canceled.append(order_id)
        return True

    def place_market_order(self, symbol, qty, side):
        if self._place_error:
            raise RuntimeError("submit boom")
        self.placed.append({"symbol": symbol, "qty": qty, "side": side, "type": "market"})
        return dict(self._place_result or _order(
            order_id="ord-new", symbol=symbol, qty=qty, side=side, order_type="market"))

    def place_limit_order(self, symbol, qty, side, limit_price):
        if self._place_error:
            raise RuntimeError("submit boom")
        self.placed.append({"symbol": symbol, "qty": qty, "side": side, "type": "limit"})
        return dict(self._place_result or _order(
            order_id="ord-new", symbol=symbol, qty=qty, side=side, order_type="limit"))


def _bot():
    return BotThread(BotConfig(bot_id="A", label="A",
                               alpaca_api_key="k", alpaca_secret_key="s"))


def _pending_row(rid=1, order_id="ord-1", symbol="BTC/USD", order_type="market",
                 timestamp=None):
    if timestamp is None:
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {
        "id": rid, "order_id": order_id, "symbol": symbol, "qty": 1.0,
        "side": "buy", "order_type": order_type, "timestamp": timestamp,
        "status": "submitted",
    }


# ---------------------------------------------------------------------------
# 1. Submit persists a 'submitted' row (VALIDATION case 1, PNL-01 happy path)
# ---------------------------------------------------------------------------

def test_submit_persists_submitted_row():
    bot = _bot()
    alpaca = FakeAlpacaClient(place_result=_order(
        order_id="ord-42", status="OrderStatus.ACCEPTED", symbol="BTC/USD"))
    logger = FakeLogger()

    trade_id, order = bot._submit_order(
        alpaca, logger, symbol="BTC/USD", qty=1.0, side="buy",
        order_type="market",
        trade_data={"symbol": "BTC/USD", "asset_class": "crypto", "side": "buy",
                    "qty": 1.0, "entry_price": 80000.0, "mirofish_prob": 0.6},
    )

    row = logger.rows[trade_id]
    assert row["status"] == "submitted"
    assert row["order_id"] == "ord-42"
    assert row["order_type"] == "market"
    assert order["order_id"] == "ord-42"


# ---------------------------------------------------------------------------
# 2. Filled → open (PNL-01 / PNL-04)
# ---------------------------------------------------------------------------

def test_filled_becomes_open():
    bot = _bot()
    logger = FakeLogger([_pending_row(order_id="ord-9")])
    alpaca = FakeAlpacaClient(get_order_result=_order(
        order_id="ord-9", status="OrderStatus.FILLED",
        filled_qty=1.0, filled_avg_price=80000.0))

    bot._resolve_pending_orders(alpaca, logger)

    row = logger.rows[1]
    assert row["status"] == "open"


# ---------------------------------------------------------------------------
# 3. Canceled (0 fill) → terminal canceled, pnl=0, not open/closed (PNL-01)
# ---------------------------------------------------------------------------

def test_canceled_terminalizes():
    bot = _bot()
    logger = FakeLogger([_pending_row()])
    alpaca = FakeAlpacaClient(get_order_result=_order(status="OrderStatus.CANCELED"))

    bot._resolve_pending_orders(alpaca, logger)

    row = logger.rows[1]
    assert row["status"] == "canceled"
    assert row["pnl"] == 0
    assert row["status"] not in ("open", "closed")
    assert row.get("closed_at")


# ---------------------------------------------------------------------------
# 4. Rejected → terminal rejected, pnl=0 (PNL-01)
# ---------------------------------------------------------------------------

def test_rejected_terminalizes():
    bot = _bot()
    logger = FakeLogger([_pending_row()])
    alpaca = FakeAlpacaClient(get_order_result=_order(status="OrderStatus.REJECTED"))

    bot._resolve_pending_orders(alpaca, logger)

    row = logger.rows[1]
    assert row["status"] == "rejected"
    assert row["pnl"] == 0


# ---------------------------------------------------------------------------
# 5. Expired → terminal expired, pnl=0 (PNL-01)
# ---------------------------------------------------------------------------

def test_expired_terminalizes():
    bot = _bot()
    logger = FakeLogger([_pending_row()])
    alpaca = FakeAlpacaClient(get_order_result=_order(status="OrderStatus.EXPIRED"))

    bot._resolve_pending_orders(alpaca, logger)

    row = logger.rows[1]
    assert row["status"] == "expired"
    assert row["pnl"] == 0


# ---------------------------------------------------------------------------
# 6. Submit exception → a terminal 'rejected' row is written (PNL-01)
# ---------------------------------------------------------------------------

def test_submit_exception_records_rejected():
    bot = _bot()
    alpaca = FakeAlpacaClient(place_error=True)
    logger = FakeLogger()

    trade_id, order = bot._submit_order(
        alpaca, logger, symbol="BTC/USD", qty=1.0, side="buy",
        order_type="market",
        trade_data={"symbol": "BTC/USD", "asset_class": "crypto", "side": "buy",
                    "qty": 1.0, "entry_price": 80000.0, "mirofish_prob": 0.6},
    )

    assert order is None
    # exactly one row, terminal rejected, pnl=0, never dropped
    assert len(logger.rows) == 1
    row = next(iter(logger.rows.values()))
    assert row["status"] == "rejected"
    assert row["pnl"] == 0


# ---------------------------------------------------------------------------
# 7. Partial fill then canceled (filled_qty>0) → kept as open (PNL-04)
# ---------------------------------------------------------------------------

def test_partial_fill_kept():
    bot = _bot()
    logger = FakeLogger([_pending_row()])
    alpaca = FakeAlpacaClient(get_order_result=_order(
        status="OrderStatus.CANCELED", filled_qty=0.4, filled_avg_price=80000.0))

    bot._resolve_pending_orders(alpaca, logger)

    row = logger.rows[1]
    assert row["status"] == "open"


# ---------------------------------------------------------------------------
# 8. Resting limit past timeout → cancel_order called + row terminalized (PNL-04)
# ---------------------------------------------------------------------------

def test_limit_timeout_cancels(monkeypatch):
    monkeypatch.setenv("LIMIT_ORDER_TIMEOUT_S", "1")
    bot = _bot()
    old_ts = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=1)).isoformat()
    logger = FakeLogger([_pending_row(order_id="ord-lim", order_type="limit",
                                      timestamp=old_ts)])
    # first poll: still resting; after cancel, fresh status = canceled
    alpaca = FakeAlpacaClient(get_order_sequence=[
        _order(order_id="ord-lim", status="OrderStatus.ACCEPTED"),
        _order(order_id="ord-lim", status="OrderStatus.CANCELED"),
    ])

    bot._resolve_pending_orders(alpaca, logger)

    assert "ord-lim" in alpaca.canceled
    row = logger.rows[1]
    assert row["status"] == "canceled"
    assert row["pnl"] == 0


# ---------------------------------------------------------------------------
# 9. Idempotent — re-poll an already-terminal row is a no-op (PNL-04)
# ---------------------------------------------------------------------------

def test_resolver_idempotent():
    bot = _bot()
    terminal = _pending_row()
    terminal["status"] = "canceled"
    terminal["pnl"] = 0
    terminal["closed_at"] = "2026-07-09T00:00:00+00:00"
    logger = FakeLogger([terminal])
    alpaca = FakeAlpacaClient(get_order_result=_order(status="OrderStatus.FILLED",
                                                      filled_qty=1.0))

    bot._resolve_pending_orders(alpaca, logger)

    # terminal row never re-fetched, never mutated
    assert alpaca.get_order_calls == []
    assert logger.rows[1]["status"] == "canceled"


# ---------------------------------------------------------------------------
# 10. Restart re-poll — pending 'submitted' rows re-resolved from DB (PNL-04)
# ---------------------------------------------------------------------------

def test_restart_repolls_pending():
    bot = _bot()
    logger = FakeLogger([
        _pending_row(rid=1, order_id="ord-a"),
        _pending_row(rid=2, order_id="ord-b", symbol="ETH/USD"),
    ])
    alpaca = FakeAlpacaClient(get_order_sequence=[
        _order(order_id="ord-a", status="OrderStatus.FILLED", filled_qty=1.0),
        _order(order_id="ord-b", status="OrderStatus.CANCELED"),
    ])

    bot._resolve_pending_orders(alpaca, logger)

    assert logger.rows[1]["status"] == "open"
    assert logger.rows[2]["status"] == "canceled"
    assert logger.get_pending_alpaca_orders() == []
