"""Phase 10 / VERIFY-01 — REAL-loop learning veto/scale integration tests.

Closes the Phase-7 mirror-helper gap: tests/test_learning_wiring.py asserts the
veto/scale contract against ``_advice_consume`` (a re-implementation), NOT the
production entry loop. A regression that dropped the real
``if not advice["should_trade"]`` veto or the ``adj = advice.get(...)`` scale in
``BotThread._run_cycle`` would NOT be caught by those tests.

These tests drive the ACTUAL ``BotThread._run_cycle`` with injected stubs
(fake alpaca, stub logger, seeded FakeTradeMemory, monkeypatched src.bot_thread._db
and src.bot_thread.scan_assets — no network, no DB) and assert on
``place_market_order`` call-count (veto) and the captured ``qty`` kwarg (scale),
covering BOTH enforce and shadow modes.
"""

import pytest

import src.bot_thread as bt
from src.bot_thread import BotThread
from src.bot_config import BotConfig
from src.technical_signals import Signal


# Dynamic thresholds with NO position floor — isolates the confidence-scale
# ratio from the min_position_pct floor (which only applies under enforce and
# would otherwise mask the adj=0.5 vs adj=1.0 qty ratio).
_NO_FLOOR = {
    "bullish_threshold": 0.53, "bearish_threshold": 0.47,
    "min_position_pct": 0.0, "max_position_pct": 0.05,
    "signal_scores": {}, "overall_win_rate": 0.5, "total_closed_trades": 0,
}


# --- helpers ---------------------------------------------------------------

def _make_signal(symbol="BTC/USD", confluence=4):
    """A LONG candidate that survives the _run_cycle filters."""
    return Signal(
        symbol=symbol,
        ema_bullish=True,
        adx_value=30.0,
        adx_trending=True,
        plus_di=25.0,
        minus_di=10.0,
        rsi_value=55.0,           # < rsi_ceiling
        rsi_signal="neutral",
        volume_spike=True,
        vwap_bullish=True,
        confluence_score=confluence,
        details={},
        market_regime="trending",
        short_score=0,
        trend_4h="bullish",        # != "bearish"
        atr_value=50.0,
    )


class _FakeAlpaca:
    """Minimal alpaca stub for _run_cycle: account/price/bars + order capture."""

    def __init__(self):
        self.orders = []

    def get_account(self):
        return {"buying_power": 100_000.0, "equity": 100_000.0}

    def get_latest_price(self, symbol):
        return 100.0

    def get_bars(self, symbol, timeframe="1Hour", limit=24):
        # 24 flat-ish hourly bars so change_pct/volume compute cleanly.
        return [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
                 "volume": 1000.0} for _ in range(limit)]

    def place_market_order(self, symbol, qty, side):
        self.orders.append({"symbol": symbol, "qty": qty, "side": side})
        return {"order_id": "X", "status": "accepted"}


class _StubLogger:
    def get_open_alpaca_positions(self):
        return []

    def log_alpaca_trade(self, trade_data):
        return 1


def _make_bot():
    cfg = BotConfig(
        bot_id="TEST",
        label="test",
        alpaca_api_key="k",
        alpaca_secret_key="s",
        kelly_fraction=0.05,   # keeps adjusted_pct below the 0.05 cap so the
                               # confidence-scale ratio is observable pre-cap
        min_confluence=4,
        rsi_ceiling=65.0,
        skip_risk_gate=True,          # bypass LLM panel — straight to sizing
        max_position_pct=0.05,
        short_enabled=False,
        crypto_universe="BTC/USD",
    )
    return BotThread(cfg)


@pytest.fixture
def realloop(monkeypatch, fake_memory):
    """Wire the shared stubs for a _run_cycle invocation. Returns a runner."""
    # No DB.
    monkeypatch.setattr(bt._db, "get_recent_loss_symbols", lambda bot_id, hours=24: set())
    monkeypatch.setattr(bt._db, "persist_scan_signals", lambda bot_id, signals: None)
    # Deterministic single LONG candidate (learning wiring is downstream of scan).
    monkeypatch.setattr(bt, "scan_assets",
                        lambda *a, **k: [_make_signal()])
    monkeypatch.setenv("BOT_PROFILE", "daytrade")

    bot = _make_bot()
    alpaca = _FakeAlpaca()
    logger = _StubLogger()

    def run(memory):
        bot._run_cycle(
            bot.config, alpaca, logger, risk_gate=None,
            starting_bankroll=100_000.0, cycle_count=1,
            memory=memory, learning_loop=None, universe=["BTC/USD"],
        )
        return alpaca

    return run, fake_memory


# --- VETO -------------------------------------------------------------------

def test_realloop_veto_enforce(realloop):
    """should_trade=False + enforce (closed_count>=30, LEARNING_ENFORCE unset)
    → the REAL loop vetoes: place_market_order NOT called."""
    run, fake_memory = realloop
    mem = fake_memory(advice={
        "should_trade": False, "confidence_adjustment": 0.0,
        "win_rate_for_pattern": 0.1, "sample_size": 4, "reasoning": "losing",
    }, closed_count=999)
    alpaca = run(mem)
    assert alpaca.orders == []


def test_realloop_veto_shadow(realloop, monkeypatch):
    """Same losing advice but LEARNING_ENFORCE=0 → shadow: order IS still placed."""
    run, fake_memory = realloop
    monkeypatch.setenv("LEARNING_ENFORCE", "0")
    mem = fake_memory(advice={
        "should_trade": False, "confidence_adjustment": 0.0,
        "win_rate_for_pattern": 0.1, "sample_size": 4, "reasoning": "losing",
    }, closed_count=999)
    alpaca = run(mem)
    assert len(alpaca.orders) == 1


# --- SCALE ------------------------------------------------------------------

def test_realloop_scale_enforce(realloop, fake_memory):
    """confidence_adjustment=0.5 + enforce → real loop scales qty to ~half of the
    adj=1.0 baseline (compared pre-cap so max_position_pct doesn't mask the ratio)."""
    run, _ = realloop
    base_mem = fake_memory(advice={
        "should_trade": True, "confidence_adjustment": 1.0,
        "win_rate_for_pattern": 0.6, "sample_size": 5, "reasoning": "ok",
    }, thresholds=_NO_FLOOR, closed_count=999)
    base_alpaca = run(base_mem)
    assert len(base_alpaca.orders) == 1
    base_qty = base_alpaca.orders[0]["qty"]

    # Fresh loop for the scaled run.
    run2, fake_memory2 = realloop
    # realloop fixture is function-scoped per param; build a new memory + rerun.
    scaled_mem = fake_memory2(advice={
        "should_trade": True, "confidence_adjustment": 0.5,
        "win_rate_for_pattern": 0.45, "sample_size": 5, "reasoning": "weak",
    }, thresholds=_NO_FLOOR, closed_count=999)
    scaled_alpaca = run2(scaled_mem)
    assert len(scaled_alpaca.orders) == 2  # same alpaca instance across run() calls
    scaled_qty = scaled_alpaca.orders[1]["qty"]

    # base 0.05-cap value vs scaled 0.025 — both below cap so ratio is exact.
    assert abs(scaled_qty - base_qty * 0.5) < 1e-9


def test_realloop_scale_shadow(realloop, fake_memory, monkeypatch):
    """confidence_adjustment=0.5 but LEARNING_ENFORCE=0 → adj stays 1.0 (unscaled)."""
    run, _ = realloop
    base_mem = fake_memory(advice={
        "should_trade": True, "confidence_adjustment": 1.0,
        "win_rate_for_pattern": 0.6, "sample_size": 5, "reasoning": "ok",
    }, thresholds=_NO_FLOOR, closed_count=999)
    base_alpaca = run(base_mem)
    base_qty = base_alpaca.orders[0]["qty"]

    monkeypatch.setenv("LEARNING_ENFORCE", "0")
    shadow_mem = fake_memory(advice={
        "should_trade": True, "confidence_adjustment": 0.5,
        "win_rate_for_pattern": 0.45, "sample_size": 5, "reasoning": "weak",
    }, thresholds=_NO_FLOOR, closed_count=999)
    shadow_alpaca = run(shadow_mem)
    shadow_qty = shadow_alpaca.orders[1]["qty"]
    # Shadow ignores the adjustment -> identical qty to the adj=1.0 baseline.
    assert abs(shadow_qty - base_qty) < 1e-9
