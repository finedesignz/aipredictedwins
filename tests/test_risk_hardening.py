# tests/test_risk_hardening.py
"""Tests for the risk/selectivity hardening pass.

Covers: bear_fraction shared helper, RSI-ceiling long filter, broad-bear long
pause, and the realistic Kelly reward/risk ratio.
"""
from src.technical_signals import Signal, bear_fraction
from src.alpaca_orchestrator import _kelly_technical
from src.bot_config import BotConfig


def _sig(symbol: str, *, ema_bullish: bool = True, rsi: float = 50.0,
         confluence: int = 4, trend_4h: str = "neutral") -> Signal:
    """Minimal Signal for filter/helper tests."""
    return Signal(
        symbol=symbol,
        ema_bullish=ema_bullish,
        adx_value=30.0,
        adx_trending=True,
        plus_di=25.0,
        minus_di=10.0,
        rsi_value=rsi,
        rsi_signal="neutral",
        volume_spike=True,
        vwap_bullish=True,
        confluence_score=confluence,
        details={},
        trend_4h=trend_4h,
    )


# -- bear_fraction shared helper -------------------------------------------

def test_bear_fraction_empty_is_zero():
    assert bear_fraction([]) == 0.0


def test_bear_fraction_counts_non_bullish():
    sigs = [
        _sig("A", ema_bullish=False),
        _sig("B", ema_bullish=False),
        _sig("C", ema_bullish=True),
        _sig("D", ema_bullish=True),
    ]
    assert bear_fraction(sigs) == 0.5


def test_bear_fraction_triggers_pause_threshold():
    # 3/4 bearish = 0.75 >= default 0.60 threshold
    sigs = [_sig(s, ema_bullish=False) for s in ("A", "B", "C")] + [_sig("D")]
    assert bear_fraction(sigs) >= 0.60


# -- RSI ceiling long filter (mirrors bot_thread long predicate) -----------

def _long_filter(signals, cfg):
    return [
        s for s in signals
        if s.confluence_score >= cfg.min_confluence
        and s.rsi_value < cfg.rsi_ceiling
        and s.trend_4h != "bearish"
    ]


def test_overbought_long_is_filtered_out():
    cfg = BotConfig(bot_id="A", label="A", alpaca_api_key="k", alpaca_secret_key="s")
    assert cfg.rsi_ceiling == 65.0
    healthy = _sig("BTC/USD", rsi=55.0)
    overbought = _sig("ETH/USD", rsi=72.0)  # above 65 ceiling
    kept = _long_filter([healthy, overbought], cfg)
    symbols = {s.symbol for s in kept}
    assert "BTC/USD" in symbols
    assert "ETH/USD" not in symbols


# -- Kelly realistic reward/risk -------------------------------------------

def test_kelly_uses_conservative_reward_risk():
    """b = 0.08/0.08 = 1.0 (was 1.6). For conf=4 (p=0.60), kelly_pct = (1*.6-.4)/1 = 0.20."""
    res = _kelly_technical(
        confluence=4, current_price=100.0, bankroll=100_000.0,
        kelly_fraction=1.0, max_position_pct=1.0,
    )
    assert abs(res["kelly_pct"] - 0.20) < 1e-9
