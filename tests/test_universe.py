# tests/test_universe.py
"""Phase 15 — Universe hard-gate (UNIV-01) + config-driven quarantine (UNIV-02).

Wave 0 RED suite: the 19 VALIDATION cases as executable specs.

Zero network, zero DB (except case 16, which is DATABASE_URL-gated). Fakes follow
the tests/test_order_resolution.py convention. ``FakeAlpacaClient.get_positions``
returns the REAL row shape from src/alpaca_client.py:140-157 — slashless ``symbol``,
SIGNED float ``qty`` (negative for a short), plus ``side`` — so the copytrade
reduce-vs-add branch is drivable.

Load-bearing invariants:
  * case 17 — ``entry_allowed`` never appears in src/alpaca_client.py (exits ungated)
  * case 18 — a copytrade order that REDUCES a held position still submits
  * case 19 — a copytrade BUY that ADDS to a held off-universe long is BLOCKED
"""
import logging
import os
from pathlib import Path

import pytest

from src.bot_config import BotConfig
from src.bot_thread import BotThread, select_long_candidates, select_short_candidates
from src.universe import entry_allowed, normalize


DEFAULT_CRYPTO = [
    "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD",
    "ADA/USD", "AVAX/USD", "DOT/USD", "LINK/USD",
]

_REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeLogger:
    """In-memory stand-in for TradeLogger's alpaca_trades surface."""

    def __init__(self):
        self.bot_id = "A"
        self.rows: list[dict] = []
        self.updates: list[tuple] = []
        self._next = 1

    def log_alpaca_trade(self, trade_data: dict) -> int:
        tid = self._next
        self._next += 1
        row = dict(trade_data)
        row["id"] = tid
        row.setdefault("status", "submitted")
        self.rows.append(row)
        return tid

    def update_alpaca_trade(self, trade_id, status, exit_price=None, pnl=None, fees=None):
        self.updates.append((trade_id, status, exit_price, pnl, fees))

    def get_open_alpaca_positions(self):
        return []

    def get_pending_alpaca_orders(self):
        return []


class FakeAlpacaClient:
    """Records orders/closes; scripts get_positions() with the real row shape."""

    def __init__(self, positions=None, price=100.0):
        self._positions = list(positions or [])
        self._price = price
        self.orders: list[dict] = []
        self.closed: list[str] = []
        self.positions_error = False

    # -- entry surface --
    def place_market_order(self, symbol, qty, side):
        self.orders.append({"symbol": symbol, "qty": qty, "side": side, "type": "market"})
        return {"order_id": "ord-new", "status": "OrderStatus.ACCEPTED",
                "symbol": symbol, "qty": qty, "side": side,
                "filled_qty": 0.0, "filled_avg_price": 0.0, "order_type": "market"}

    def place_limit_order(self, symbol, qty, side, limit_price):
        self.orders.append({"symbol": symbol, "qty": qty, "side": side, "type": "limit"})
        return {"order_id": "ord-new", "status": "OrderStatus.ACCEPTED",
                "symbol": symbol, "qty": qty, "side": side,
                "filled_qty": 0.0, "filled_avg_price": 0.0, "order_type": "limit"}

    # -- exit surface (must never be gated) --
    def close_position(self, symbol):
        self.closed.append(symbol)
        return True

    # -- state --
    def get_positions(self):
        if self.positions_error:
            raise RuntimeError("positions boom")
        return [dict(p) for p in self._positions]

    def get_latest_price(self, symbol):
        return self._price


def _position(symbol="TRUMPUSD", qty=5.0):
    """Row shaped exactly like src/alpaca_client.py:140-157 (SIGNED qty, no slash)."""
    return {
        "symbol": symbol,
        "qty": qty,
        "side": "long" if qty >= 0 else "short",
        "current_price": 100.0,
        "avg_entry_price": 90.0,
        "unrealized_pnl": 10.0,
    }


class FakeSignal:
    def __init__(self, symbol, confluence_score=5, short_score=5, rsi_value=40.0,
                 trend_4h="bullish"):
        self.symbol = symbol
        self.confluence_score = confluence_score
        self.short_score = short_score
        self.rsi_value = rsi_value
        self.trend_4h = trend_4h


def _cfg(**kw) -> BotConfig:
    base = dict(bot_id="A", label="A", alpaca_api_key="k", alpaca_secret_key="s")
    base.update(kw)
    return BotConfig(**base)


def _bot(**kw) -> BotThread:
    return BotThread(_cfg(**kw))


def _trade_data(symbol, side="buy"):
    return {"symbol": symbol, "asset_class": "crypto", "side": side,
            "qty": 1.0, "entry_price": 100.0, "mirofish_prob": 0.6}


# ===========================================================================
# 1-5, 12, 15 — pure module + BotConfig
# ===========================================================================

def test_allowed_symbol_passes():
    assert entry_allowed("ETH/USD", ["BTC/USD", "ETH/USD"], []) == (True, None)


def test_off_universe_blocked():
    allowed, reason = entry_allowed("TRUMP/USD", DEFAULT_CRYPTO, [])
    assert allowed is False
    assert reason == "off_universe"


def test_quarantined_blocked():
    allowed, reason = entry_allowed("BTC/USD", DEFAULT_CRYPTO, ["BTC/USD"])
    assert allowed is False
    assert reason == "quarantined"
    # Quarantine PRECEDES the allowlist check: a symbol that is BOTH off-universe
    # and quarantined reports "quarantined".
    assert entry_allowed("TRUMP/USD", DEFAULT_CRYPTO, ["TRUMP/USD"]) == (False, "quarantined")


def test_normalize_formats():
    assert normalize("BTC/USD") == normalize("BTCUSD") == normalize("btc/usd") == "BTCUSD"
    assert normalize("SPY") == "SPY"
    assert normalize("") == ""
    assert normalize(None) == ""
    assert normalize(normalize("btc/usd")) == "BTCUSD"  # idempotent
    assert normalize(" eth/usd ") == "ETHUSD"


def test_empty_quarantine_noop():
    assert entry_allowed("BTC/USD", DEFAULT_CRYPTO, []) == (True, None)
    assert entry_allowed("BTC/USD", DEFAULT_CRYPTO, [""]) == (True, None)


def test_empty_allowlist_allows():
    # Decision 4 safety net — an empty allowlist means "no allowlist restriction".
    assert entry_allowed("TRUMP/USD", [], []) == (True, None)
    # ...but quarantine still applies.
    assert entry_allowed("TRUMP/USD", [], ["TRUMP/USD"]) == (False, "quarantined")


def test_trend_symbol_allowed():
    cfg = _cfg(asset_class="stock")
    assert "BITX" not in cfg.symbols
    allow = list(cfg.symbols) + [cfg.trend_symbol]
    assert entry_allowed("BITX", allow, cfg.quarantined) == (True, None)
    # Against the bare stock_universe (no BITX) it is off-universe.
    assert entry_allowed("BITX", cfg.symbols, []) == (False, "off_universe")


def test_bot_config_quarantined():
    row = {"bot_id": "A", "label": "A", "quarantined_symbols": "BTC/USD, FIL/USD"}
    assert BotConfig.from_row(row).quarantined == ["BTC/USD", "FIL/USD"]
    # Missing key (pre-migration DB) fails safe.
    assert BotConfig.from_row({"bot_id": "A", "label": "A"}).quarantined == []
    assert BotConfig.from_row({"bot_id": "A", "label": "A",
                               "quarantined_symbols": None}).quarantined == []
    assert BotConfig.from_row({"bot_id": "A", "label": "A",
                               "quarantined_symbols": ""}).quarantined == []


def test_bot_config_all_symbols():
    cfg = _cfg()  # asset_class="crypto"
    allsyms = cfg.all_symbols
    assert "BTC/USD" in allsyms          # crypto universe
    assert "NVDA" in allsyms             # stock universe — union spans BOTH
    assert "TRUMP/USD" not in allsyms    # in neither → the leak still closes
    assert len(allsyms) == len(set(allsyms))  # deduped


# ===========================================================================
# 6-10 — _submit_order + selectors
# ===========================================================================

def test_submit_order_blocks_off_universe():
    bot, alpaca, logger = _bot(), FakeAlpacaClient(), FakeLogger()
    trade_id, order = bot._submit_order(
        alpaca, logger, symbol="TRUMP/USD", qty=1.0, side="buy",
        order_type="market", trade_data=_trade_data("TRUMP/USD"))

    assert (trade_id, order) == (None, None)
    assert alpaca.orders == []
    assert len(logger.rows) == 1
    assert logger.rows[0]["status"] == "rejected"
    assert logger.rows[0]["pnl"] == 0


def test_submit_order_blocks_short_entry():
    bot, alpaca, logger = _bot(), FakeAlpacaClient(), FakeLogger()
    trade_id, order = bot._submit_order(
        alpaca, logger, symbol="TRUMP/USD", qty=1.0, side="sell",
        order_type="market", trade_data=_trade_data("TRUMP/USD", side="sell"))

    assert (trade_id, order) == (None, None)
    assert alpaca.orders == []
    assert len(logger.rows) == 1
    assert logger.rows[0]["status"] == "rejected"


def test_submit_order_blocks_quarantined():
    bot = _bot(quarantined_symbols="BTC/USD")
    alpaca, logger = FakeAlpacaClient(), FakeLogger()
    trade_id, order = bot._submit_order(
        alpaca, logger, symbol="BTC/USD", qty=1.0, side="buy",
        order_type="market", trade_data=_trade_data("BTC/USD"))

    assert (trade_id, order) == (None, None)
    assert alpaca.orders == []
    assert len(logger.rows) == 1
    assert logger.rows[0]["status"] == "rejected"


def test_submit_order_logs_rejection(caplog):
    bot, alpaca, logger = _bot(), FakeAlpacaClient(), FakeLogger()
    with caplog.at_level(logging.WARNING):
        bot._submit_order(alpaca, logger, symbol="TRUMP/USD", qty=1.0, side="buy",
                          order_type="market", trade_data=_trade_data("TRUMP/USD"))

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "expected a WARNING for the blocked entry"
    blob = " ".join(warnings)
    assert "TRUMP/USD" in blob
    assert "off_universe" in blob
    assert "A" in blob  # bot_id


def test_submit_order_allows_universe_symbol():
    bot, alpaca, logger = _bot(), FakeAlpacaClient(), FakeLogger()
    trade_id, order = bot._submit_order(
        alpaca, logger, symbol="ETH/USD", qty=1.0, side="buy",
        order_type="market", trade_data=_trade_data("ETH/USD"))

    assert trade_id is not None and order is not None
    assert len(alpaca.orders) == 1
    assert len(logger.rows) == 1
    assert logger.rows[0]["status"] == "submitted"


def test_select_long_universe_filter():
    cfg = _cfg(quarantined_symbols="BTC/USD", min_confluence=3)
    signals = [
        FakeSignal("SOL/USD"),
        FakeSignal("TRUMP/USD"),
        FakeSignal("BTC/USD"),
    ]
    picked = {s.symbol for s in select_long_candidates(signals, cfg, set(), set())}
    assert picked == {"SOL/USD"}


def test_select_short_universe_filter():
    cfg = _cfg(quarantined_symbols="BTC/USD", min_short_confluence=3)
    signals = [
        FakeSignal("SOL/USD", trend_4h="bearish"),
        FakeSignal("TRUMP/USD", trend_4h="bearish"),
        FakeSignal("BTC/USD", trend_4h="bearish"),
    ]
    picked = {s.symbol for s in select_short_candidates(signals, cfg, set(), set())}
    assert picked == {"SOL/USD"}


# ===========================================================================
# 11 — exits are never gated
# ===========================================================================

def test_exit_not_gated():
    """A quarantined, off-universe symbol with an open position still closes."""
    alpaca = FakeAlpacaClient(positions=[_position("TRUMPUSD", 5.0)])

    # The PositionMonitor close path.
    alpaca.close_position("BTC/USD")
    assert alpaca.closed == ["BTC/USD"]

    # A direct exit sell is not blocked either.
    alpaca.place_market_order(symbol="TRUMP/USD", qty=5.0, side="sell")
    assert alpaca.orders[-1]["side"] == "sell"


# ===========================================================================
# 12/14 — bot_c entry
# ===========================================================================

def test_bot_c_entry_blocked(monkeypatch):
    """_process_ticker driven DIRECTLY with an off-universe ticker never orders."""
    from src.bot_c import strategy as bc

    monkeypatch.setattr(bc, "_parse_rating", lambda text: "Buy")
    alpaca, logger = FakeAlpacaClient(), FakeLogger()

    class _Graph:
        def propagate(self, symbol, today):
            return None, "FINAL TRANSACTION PROPOSAL: **BUY**"

    bc._process_ticker(
        symbol="TRUMP", today="2026-07-12", graph=_Graph(), cfg=_cfg(),
        alpaca=alpaca, logger=logger, bankroll=100_000.0, equity=100_000.0,
        open_by_symbol={}, recent_loss_symbols=set(), bot_id="C",
        cycle_exposure_tracker=lambda d: None,
    )

    assert alpaca.orders == []


# ===========================================================================
# 13, 18, 19 — copytrade
# ===========================================================================

def _copytrader(**kw):
    from src.copytrade_thread import CopyTraderThread
    return CopyTraderThread(_cfg(**kw), pool=None)


def _signal(symbol, side="buy", market="crypto", entry_price=100.0, quantity=100.0):
    return {"id": 1, "symbol": symbol, "market": market, "side": side,
            "entry_price": entry_price, "quantity": quantity,
            "agent_id": 7, "agent_name": "leader", "signal_type": "open",
            "executed_at": "2026-07-12T00:00:00Z"}


def test_copytrade_entry_blocked():
    """An off-universe OPEN (not held) is blocked; a cross-asset-class mirror passes."""
    ct = _copytrader()
    alpaca = FakeAlpacaClient(positions=[])  # nothing held

    res = ct._execute_signal(_signal("TRUMP"), alpaca, 100_000.0)
    assert alpaca.orders == []
    assert res["action"] == "blocked"
    assert "off_universe" in str(res["error_detail"])

    # all_symbols = crypto ∪ stock → a legitimately-mirrored stock still passes.
    alpaca2 = FakeAlpacaClient(positions=[])
    res2 = ct._execute_signal(_signal("NVDA", market="us-stock"), alpaca2, 100_000.0)
    assert res2["action"] == "executed"
    assert len(alpaca2.orders) == 1


def test_copytrade_sell_held_symbol_not_gated():
    """Case 18 — a SELL that REDUCES a held off-universe LONG still submits."""
    ct = _copytrader()
    alpaca = FakeAlpacaClient(positions=[_position("TRUMPUSD", 5.0)])

    res = ct._execute_signal(_signal("TRUMP", side="sell"), alpaca, 100_000.0)
    assert res["action"] == "executed"
    assert len(alpaca.orders) == 1
    assert alpaca.orders[0]["side"] == "sell"


def test_copytrade_buy_held_symbol_blocked():
    """Case 19 — a BUY that ADDS to a held off-universe LONG is BLOCKED."""
    ct = _copytrader()
    alpaca = FakeAlpacaClient(positions=[_position("TRUMPUSD", 5.0)])

    res = ct._execute_signal(_signal("TRUMP", side="buy"), alpaca, 100_000.0)
    assert alpaca.orders == []
    assert res["action"] == "blocked"

    # Mirror image: a BUY on a symbol held SHORT is a REDUCE → submits.
    alpaca2 = FakeAlpacaClient(positions=[_position("TRUMPUSD", -5.0)])
    res2 = ct._execute_signal(_signal("TRUMP", side="buy"), alpaca2, 100_000.0)
    assert res2["action"] == "executed"
    assert len(alpaca2.orders) == 1

    # A SELL on a NOT-held off-universe symbol is a short-to-OPEN → gated.
    alpaca3 = FakeAlpacaClient(positions=[])
    res3 = ct._execute_signal(_signal("TRUMP", side="sell"), alpaca3, 100_000.0)
    assert alpaca3.orders == []
    assert res3["action"] == "blocked"

    # Fail CLOSED: get_positions() raising must not produce an ungated submit.
    alpaca4 = FakeAlpacaClient(positions=[_position("TRUMPUSD", 5.0)])
    alpaca4.positions_error = True
    res4 = ct._execute_signal(_signal("TRUMP", side="buy"), alpaca4, 100_000.0)
    assert alpaca4.orders == []
    assert res4["action"] == "blocked"


# ===========================================================================
# 16 — real-SQL guard (DATABASE_URL-gated)
# ===========================================================================

@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs Postgres")
def test_quarantine_column_sql():
    import psycopg
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        row = conn.execute(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'bots' AND column_name = 'quarantined_symbols'"
        ).fetchone()
    assert row is not None, "bots.quarantined_symbols is missing (migration 018 not applied)"
    # Postgres renders TEXT DEFAULT '' as "''::text" — do NOT assert equality with "".
    assert str(row[0]).startswith("''")


# ===========================================================================
# 17 — STATIC guard: the gate never lands in the exit layer
# ===========================================================================

def test_gate_absent_from_alpaca_client():
    text = (_REPO_ROOT / "src" / "alpaca_client.py").read_text(encoding="utf-8")
    assert "entry_allowed" not in text, (
        "The universe gate must NEVER appear in src/alpaca_client.py — "
        "three exit paths call place_market_order directly and would be stranded."
    )
