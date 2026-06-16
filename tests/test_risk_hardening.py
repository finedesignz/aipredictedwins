# tests/test_risk_hardening.py
"""Tests for the risk/selectivity hardening pass.

Covers: bear_fraction shared helper, RSI-ceiling long filter, broad-bear long
pause, and the realistic Kelly reward/risk ratio.
"""
from src.technical_signals import Signal, bear_fraction
from src.alpaca_orchestrator import _kelly_technical, BEAR_MARKET_PAUSE_THRESHOLD
from src.bot_config import BotConfig
from src.bot_thread import select_long_candidates, select_short_candidates


def _sig(symbol: str, *, ema_bullish: bool = True, rsi: float = 50.0,
         confluence: int = 4, trend_4h: str = "neutral",
         short_score: int = 0) -> Signal:
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
        short_score=short_score,
    )


def _cfg() -> BotConfig:
    return BotConfig(bot_id="A", label="A", alpaca_api_key="k", alpaca_secret_key="s")


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


# -- RSI ceiling long filter (REAL bot_thread predicate) -------------------

def test_overbought_long_is_filtered_out():
    """Drives the real bot_thread.select_long_candidates predicate
    (bot_thread.py: ``s.rsi_value < cfg.rsi_ceiling``)."""
    cfg = _cfg()
    assert cfg.rsi_ceiling == 65.0
    healthy = _sig("BTC/USD", rsi=55.0)
    overbought = _sig("ETH/USD", rsi=72.0)  # above 65 ceiling
    kept = select_long_candidates(
        [healthy, overbought], cfg, open_symbols=set(), recent_loss_symbols=set()
    )
    symbols = {s.symbol for s in kept}
    assert "BTC/USD" in symbols
    assert "ETH/USD" not in symbols


# -- Broad-bear pause: real bot_thread long/short wiring -------------------

def _long_set_for(signals, cfg):
    """Mirror bot_thread._run_one_cycle long gating: broad-bear pause
    suppresses ALL longs, otherwise the real per-signal predicate runs."""
    market_is_broadly_bearish = bear_fraction(signals) >= BEAR_MARKET_PAUSE_THRESHOLD
    return [] if market_is_broadly_bearish else select_long_candidates(
        signals, cfg, open_symbols=set(), recent_loss_symbols=set()
    )


def test_broad_bear_pause_suppresses_longs_not_shorts():
    cfg = _cfg()
    # 3/4 bearish EMA = 0.75 >= 0.60 threshold. Each carries a tradeable
    # long (bullish confluence) AND a short (short_score) signal.
    # Use Alpaca-tradeable symbols (ETH/LINK/DOT etc. are untradeable & excluded).
    sigs = [
        _sig(s, ema_bullish=False, trend_4h="neutral", short_score=4)
        for s in ("BTC/USD", "SOL/USD", "XRP/USD")
    ] + [_sig("ADA/USD", ema_bullish=True, short_score=4)]
    assert bear_fraction(sigs) >= BEAR_MARKET_PAUSE_THRESHOLD

    longs = _long_set_for(sigs, cfg)
    shorts = select_short_candidates(
        sigs, cfg, open_symbols=set(), recent_loss_symbols=set()
    )
    assert longs == []                 # longs paused
    assert len(shorts) > 0             # shorts unaffected


def test_non_bearish_market_lets_longs_through():
    cfg = _cfg()
    # 1/3 bearish = 0.33 < 0.60 — no pause, healthy longs pass.
    # (cycle caps entries via MAX_ENTRIES_PER_CYCLE, so keep candidates <= cap)
    sigs = [
        _sig("BTC/USD", ema_bullish=True, rsi=55.0),
        _sig("SOL/USD", ema_bullish=True, rsi=50.0),
        _sig("XRP/USD", ema_bullish=False, rsi=52.0, confluence=1),
    ]
    assert bear_fraction(sigs) < BEAR_MARKET_PAUSE_THRESHOLD
    longs = _long_set_for(sigs, cfg)
    assert {s.symbol for s in longs} == {"BTC/USD", "SOL/USD"}


# -- Kelly realistic reward/risk -------------------------------------------

def test_kelly_uses_conservative_reward_risk():
    """b = 0.08/0.08 = 1.0 (was 1.6). For conf=4 (p=0.60), kelly_pct = (1*.6-.4)/1 = 0.20."""
    res = _kelly_technical(
        confluence=4, current_price=100.0, bankroll=100_000.0,
        kelly_fraction=1.0, max_position_pct=1.0,
    )
    assert abs(res["kelly_pct"] - 0.20) < 1e-9
