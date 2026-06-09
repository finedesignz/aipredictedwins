"""Shared pytest fixtures for the Phase-4 ATR-exit tests.

No network, no DB — everything is in-memory MagicMocks and deterministic
bar generators. The bar dicts use the same "high"/"low"/"close" keys that
both ``technical_signals._atr`` and ``PositionMonitor`` consume.
"""

from unittest.mock import MagicMock

import pytest

from src.technical_signals import _atr


def fake_bars(highs, lows, closes):
    """Build a list[dict] of OHLC bars from parallel high/low/close lists."""
    return [
        {"high": h, "low": l, "close": c, "open": c, "volume": 1000.0}
        for h, l, c in zip(highs, lows, closes)
    ]


def make_bars_for_atr(atr_target, n=20, period=14):
    """Deterministic bars whose Wilder ATR equals ``atr_target`` exactly.

    Each bar has a constant true range of ``atr_target``: flat closes at a
    fixed base, every bar high = base + atr_target/2, low = base - atr_target/2.
    With flat closes the true range of every bar is high-low = atr_target, so
    the simple-mean seed and every Wilder step equal atr_target. Verified
    against ``_atr`` below.
    """
    base = 100.0
    closes = [base] * n
    highs = [base + atr_target / 2 for _ in range(n)]
    lows = [base - atr_target / 2 for _ in range(n)]
    return fake_bars(highs, lows, closes)


@pytest.fixture
def atr_bars():
    """Fixture wrapper so tests get the deterministic generator without a
    cross-module import (tests/ is not a package)."""
    return make_bars_for_atr


@pytest.fixture
def mock_alpaca():
    m = MagicMock(name="alpaca")
    m.get_positions.return_value = []
    m.get_latest_price.return_value = 100.0
    m.get_bars.return_value = []
    m.close_position.return_value = {}
    return m


@pytest.fixture
def mock_logger():
    m = MagicMock(name="logger")
    m.get_open_alpaca_positions.return_value = []
    m.update_alpaca_trade.return_value = None
    return m


@pytest.fixture
def mock_advisor():
    """ExitAdvisor stand-in — used to assert should_exit() is never called."""
    return MagicMock(name="exit_advisor")


# --- Phase 7 learning: in-memory fake TradeMemory (no DB) ------------------

class FakeTradeMemory:
    """Stand-in for src.trade_memory.TradeMemory used by the learning-wiring
    tests. Returns canned advice/thresholds so the candidate loops in
    bot_thread / alpaca_orchestrator can be driven without Postgres.

    Constructor takes the canned dicts; record_trade_context just appends the
    payload to ``self.recorded`` so tests can assert signal_type alignment.
    """

    def __init__(self, advice=None, thresholds=None):
        self._advice = advice or {
            "should_trade": True,
            "confidence_adjustment": 1.0,
            "win_rate_for_pattern": None,
            "sample_size": 0,
            "reasoning": "fake-default",
            "similar_trades": [],
            "lessons": [],
        }
        self._thresholds = thresholds or {
            "bullish_threshold": 0.53,
            "bearish_threshold": 0.47,
            "min_position_pct": 0.02,
            "max_position_pct": 0.05,
            "signal_scores": {},
            "overall_win_rate": 0.5,
            "total_closed_trades": 0,
        }
        self.recorded = []
        self.advice_calls = []

    def get_advice(self, symbol, signal_type, sentiment, price_change):
        self.advice_calls.append({
            "symbol": symbol, "signal_type": signal_type,
            "sentiment": sentiment, "price_change": price_change,
        })
        return dict(self._advice)

    def get_dynamic_thresholds(self):
        return dict(self._thresholds)

    def record_trade_context(self, trade_data):
        self.recorded.append(trade_data)
        return len(self.recorded)


@pytest.fixture
def fake_memory():
    return FakeTradeMemory


# --- sanity: the generator really produces the documented ATR -------------

def test_make_bars_for_atr_matches_atr():
    bars = make_bars_for_atr(2.5, n=20, period=14)
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    closes = [b["close"] for b in bars]
    assert abs(_atr(highs, lows, closes, 14) - 2.5) < 1e-9
