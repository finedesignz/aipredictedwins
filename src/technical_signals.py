"""
Technical Signal Engine for crypto swing trading.

Computes proven quantitative indicators from OHLCV bar data and
produces a confluence score (0-4) for long trade decisions and a
short_score (0-4) for short trade decisions.

Indicators:
  1. EMA Crossover (9/21) — trend direction
  2. ADX (14-period) — trend strength
  3. RSI (14-period) — overbought/oversold
  4. VWAP — intraday value reference

Optional 4H trend filter: EMA9/21 on 4-hour bars sets trend_4h field.

No LLM calls. Pure math on price data.
"""

import logging
from dataclasses import dataclass

from src.strategy_profile import SWING

log = logging.getLogger(__name__)


@dataclass
class Signal:
    """Result of technical analysis for a single asset."""
    symbol: str
    ema_bullish: bool
    adx_value: float
    adx_trending: bool
    plus_di: float            # +DI from ADX calculation
    minus_di: float           # -DI from ADX calculation
    rsi_value: float
    rsi_signal: str          # "oversold", "overbought", or "neutral"
    volume_spike: bool
    vwap_bullish: bool
    confluence_score: int    # 0-4: how many long indicators are bullish
    details: dict            # raw indicator values for logging
    market_regime: str = "ranging"  # "trending", "ranging", or "mixed"
    short_score: int = 0     # 0-4: how many short indicators are bearish
    trend_4h: str = "unknown"  # "bullish", "bearish", "neutral", or "unknown"
    atr_value: float = 0.0   # Average True Range over profile.atr_period (Phase 4 consumes)


# ---------------------------------------------------------------------------
# Indicator calculations (no external TA library — pandas only)
# ---------------------------------------------------------------------------

def _ema(closes: list[float], period: int) -> list[float]:
    """Exponential moving average."""
    if len(closes) < period:
        return []
    multiplier = 2.0 / (period + 1)
    ema_vals = [sum(closes[:period]) / period]
    for price in closes[period:]:
        ema_vals.append((price - ema_vals[-1]) * multiplier + ema_vals[-1])
    return ema_vals


def _sma(values: list[float], period: int) -> list[float]:
    """Simple moving average."""
    if len(values) < period:
        return []
    return [
        sum(values[i:i + period]) / period
        for i in range(len(values) - period + 1)
    ]


def _rsi(closes: list[float], period: int = 14) -> float | None:
    """Relative Strength Index using Wilder's smoothing."""
    if len(closes) < period + 1:
        return None

    deltas = [closes[i + 1] - closes[i] for i in range(len(closes) - 1)]

    gains = [max(d, 0) for d in deltas[:period]]
    losses = [abs(min(d, 0)) for d in deltas[:period]]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for d in deltas[period:]:
        avg_gain = (avg_gain * (period - 1) + max(d, 0)) / period
        avg_loss = (avg_loss * (period - 1) + abs(min(d, 0))) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> tuple[float, float, float] | None:
    """Average Directional Index (ADX) using Wilder's smoothing.

    Returns (adx, plus_di, minus_di), or None if insufficient data.
    Requires at least (period * 2 + 1) bars.
    """
    n = len(closes)
    if n < period * 2 + 1 or len(highs) != n or len(lows) != n:
        return None

    # True Range, +DM, -DM
    tr_list = []
    plus_dm_list = []
    minus_dm_list = []

    for i in range(1, n):
        high_diff = highs[i] - highs[i - 1]
        low_diff = lows[i - 1] - lows[i]

        plus_dm = high_diff if high_diff > low_diff and high_diff > 0 else 0.0
        minus_dm = low_diff if low_diff > high_diff and low_diff > 0 else 0.0

        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

        tr_list.append(tr)
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)

    # Wilder's smoothing for first period
    atr = sum(tr_list[:period])
    plus_dm_smooth = sum(plus_dm_list[:period])
    minus_dm_smooth = sum(minus_dm_list[:period])

    dx_list = []

    for i in range(period, len(tr_list)):
        atr = atr - (atr / period) + tr_list[i]
        plus_dm_smooth = plus_dm_smooth - (plus_dm_smooth / period) + plus_dm_list[i]
        minus_dm_smooth = minus_dm_smooth - (minus_dm_smooth / period) + minus_dm_list[i]

        plus_di = (plus_dm_smooth / atr * 100) if atr > 0 else 0
        minus_di = (minus_dm_smooth / atr * 100) if atr > 0 else 0

        di_sum = plus_di + minus_di
        dx = (abs(plus_di - minus_di) / di_sum * 100) if di_sum > 0 else 0
        dx_list.append(dx)

    if len(dx_list) < period:
        return None

    # First ADX = SMA of first `period` DX values
    adx = sum(dx_list[:period]) / period

    # Smooth remaining
    for dx in dx_list[period:]:
        adx = (adx * (period - 1) + dx) / period

    final_plus_di = (plus_dm_smooth / atr * 100) if atr > 0 else 0.0
    final_minus_di = (minus_dm_smooth / atr * 100) if atr > 0 else 0.0
    return (adx, final_plus_di, final_minus_di)


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    """Average True Range (Wilder smoothing). Returns latest ATR, 0.0 on insufficient data.

    Reuses the true-range formula from ``_adx`` (max of high-low, |high-prev_close|,
    |low-prev_close|). First ATR = simple mean of the first ``period`` TRs, then Wilder
    smoothing for the rest. Needs only ``period + 1`` bars (looser than ``_adx``).
    """
    n = len(closes)
    if n < period + 1 or len(highs) != n or len(lows) != n:
        return 0.0
    tr_list = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        tr_list.append(tr)
    atr = sum(tr_list[:period]) / period
    for tr in tr_list[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _volume_spike(volumes: list[float], lookback: int = 20, threshold: float = 1.5) -> bool:
    """True if the latest volume bar exceeds threshold * average of prior bars."""
    if len(volumes) < lookback + 1:
        return False
    avg_vol = sum(volumes[-(lookback + 1):-1]) / lookback
    if avg_vol <= 0:
        return False
    return volumes[-1] > avg_vol * threshold


def bear_fraction(signals: list) -> float:
    """Fraction of scanned signals whose EMA is bearish (not bullish).

    Shared by both orchestrator paths (CLI + per-bot thread) to drive the
    broad-market long pause. Returns 0.0 for an empty list.
    """
    if not signals:
        return 0.0
    bear_count = sum(1 for s in signals if not s.ema_bullish)
    return bear_count / len(signals)


def _detect_regime(adx_value: float, plus_di: float, minus_di: float) -> str:
    """Classify market regime based on ADX strength and directional spread.

    Returns:
        "trending"  — ADX > 25 and +DI leads -DI by >= 8 points (strong uptrend)
        "ranging"   — ADX < 20 (weak/no trend, mean-reversion favoured)
        "mixed"     — ADX 20-25 (transition, use relaxed pullback logic)
    """
    di_spread = plus_di - minus_di
    if adx_value > 25 and di_spread >= 8:
        return "trending"
    elif adx_value < 20:
        return "ranging"
    else:
        return "mixed"


def _vwap_bullish(
    closes: list[float],
    volumes: list[float],
    vwaps: list[float],
    timestamps: list[str] | None = None,
    session_anchor: bool = False,
) -> bool:
    """True if the latest close is above the latest VWAP.

    When ``session_anchor`` and ``timestamps`` are provided (daytrade path), the
    VWAP is anchored to the current UTC day: only bars sharing the last bar's
    date (ISO ``timestamp[:10]``) contribute to the cumulative VWAP. This resets
    the anchor at each UTC-day boundary. Otherwise the existing swing behavior is
    used unchanged (per-bar ``vwap`` if present, else a rolling-20 fallback).
    """
    if session_anchor and timestamps:
        last_day = timestamps[-1][:10]
        idx = [i for i, t in enumerate(timestamps) if t and t[:10] == last_day]
        cum_vol = sum(volumes[i] for i in idx)
        if cum_vol <= 0:
            return False
        cum_pv = sum(closes[i] * volumes[i] for i in idx)
        return closes[-1] > cum_pv / cum_vol

    if vwaps and vwaps[-1] > 0:
        return closes[-1] > vwaps[-1]

    # Fallback: compute from close * volume
    n = min(20, len(closes), len(volumes))
    if n == 0:
        return False
    cum_pv = sum(closes[-n + i] * volumes[-n + i] for i in range(n))
    cum_vol = sum(volumes[-n:])
    if cum_vol <= 0:
        return False
    computed_vwap = cum_pv / cum_vol
    return closes[-1] > computed_vwap


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(symbol: str, bars: list[dict], bars_4h: list[dict] | None = None, profile=SWING) -> Signal | None:
    """Run all technical indicators on OHLCV bars and return a Signal.

    Parameters
    ----------
    symbol : str
        Asset symbol (e.g. "BTC/USD").
    bars : list[dict]
        OHLCV bars from AlpacaClient.get_bars(). Each bar must have
        keys: open, high, low, close, volume, vwap (optional).
        Should be at least 50 bars for reliable indicators.
    bars_4h : list[dict] or None
        Optional 4-hour bars used to compute a higher-timeframe trend filter.
        Requires at least 21 bars. If None or insufficient, trend_4h="unknown".

    Returns
    -------
    Signal or None if insufficient data or both long and short scores are 0.
    """
    if len(bars) < 30:
        log.warning("Insufficient bars for %s (%d < 30 needed)", symbol, len(bars))
        return None

    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    volumes = [b["volume"] for b in bars]
    vwaps = [b.get("vwap", 0) for b in bars]

    # --- EMA Crossover (profile-sourced periods) ---
    ema9 = _ema(closes, profile.ema_fast)
    ema21 = _ema(closes, profile.ema_slow)
    if ema9 and ema21:
        # Align: ema9 starts at index 8, ema21 at index 20
        # Latest values:
        ema9_latest = ema9[-1]
        ema21_latest = ema21[-1]
        ema_bullish = ema9_latest > ema21_latest
    else:
        ema_bullish = False
        ema9_latest = 0
        ema21_latest = 0

    # --- ADX (14-period) ---
    adx_result = _adx(highs, lows, closes, profile.adx_period)
    if adx_result is None:
        adx_value = 0.0
        plus_di = 0.0
        minus_di = 0.0
    else:
        adx_value, plus_di, minus_di = adx_result
    # ADX trending: must be strong (>20) AND directionally bullish (+DI > -DI)
    adx_trending = adx_value > 20 and plus_di > minus_di

    # --- Market Regime ---
    regime = _detect_regime(adx_value, plus_di, minus_di)

    # --- RSI (14-period) ---
    rsi_value = _rsi(closes, profile.rsi_period)
    if rsi_value is None:
        rsi_value = 50.0
    if rsi_value < 30:
        rsi_signal = "oversold"
    elif rsi_value > 70:
        rsi_signal = "overbought"
    else:
        rsi_signal = "neutral"

    # RSI ceiling: used to gate the long score only (not a hard block/return None)
    # Lowered default from 72 to 65 — QC showed avg losing RSI was 70.1
    import os as _os
    RSI_ENTRY_CEILING = float(_os.environ.get("RSI_ENTRY_CEILING", "65.0"))
    rsi_above_ceiling = rsi_value > RSI_ENTRY_CEILING
    if rsi_above_ceiling:
        log.debug(
            "RSI ceiling hit for %s: RSI=%.1f > %.0f (long RSI point suppressed; short scoring continues)",
            symbol, rsi_value, RSI_ENTRY_CEILING,
        )

    # --- ATR (computed for Phase 4 exits; not wired into scoring/exits here) ---
    atr_value = _atr(highs, lows, closes, profile.atr_period)

    # --- Volume Spike ---
    vol_spike = _volume_spike(volumes, lookback=20, threshold=1.5)

    # --- VWAP (session-anchored for daytrade; swing semantics unchanged) ---
    timestamps = [b.get("timestamp") for b in bars]
    vwap_bull = _vwap_bullish(
        closes, volumes, vwaps,
        timestamps=timestamps,
        session_anchor=(profile.name == "daytrade"),
    )

    # --- Confluence Score (max 4, regime-aware) ---
    # Scoring adapts to market regime so the bot captures BOTH pullbacks (ranging)
    # and momentum breakouts (trending) rather than always waiting for a dip.
    #
    # TRENDING regime (ADX > 25, +DI leads by ≥8): momentum entry
    #   — price above VWAP confirms the trend; RSI 45-65 means "in gear, not overextended"
    # RANGING regime (ADX < 20): mean-reversion pullback entry (original QC logic)
    #   — RSI < 50 = dip; below VWAP = good entry vs fair value
    # MIXED (ADX 20-25): relaxed pullback; RSI < 55 threshold
    score = 0
    if regime == "trending":
        # 1. EMA crossover confirms uptrend direction
        if ema_bullish:
            score += 1
        # 2. ADX strong AND +DI dominant — real momentum, not noise
        if adx_trending:
            score += 1
        # 3. RSI 45-65 — price has momentum but isn't overextended
        #    Suppressed if RSI > RSI_ENTRY_CEILING (overbought long blocked)
        if 45 <= rsi_value <= 65 and not rsi_above_ceiling:
            score += 1
        # 4. Price above VWAP — institutional buyers confirm the move
        if vwap_bull:
            score += 1
        log.debug("REGIME=trending for %s: score=%d ADX=%.1f DI_spread=%.1f RSI=%.1f",
                  symbol, score, adx_value, plus_di - minus_di, rsi_value)
    else:
        # Ranging or mixed: mean-reversion pullback logic (QC-validated)
        rsi_threshold = 50 if regime == "ranging" else 55
        # 1. EMA bullish crossover — trend direction
        if ema_bullish:
            score += 1
        # 2. ADX confirms real trend strength (+DI > -DI means upward momentum)
        if adx_trending:
            score += 1
        # 3. RSI below threshold — price showing relative weakness/dip
        #    QC: avg losing RSI was 70.1; all wins had RSI ≤ 64
        #    Suppressed if RSI > RSI_ENTRY_CEILING (overbought long blocked)
        if rsi_value < rsi_threshold and not rsi_above_ceiling:
            score += 1
        # 4. Price below VWAP = mean-reversion pullback entry (good risk/reward)
        #    QC: all 3 wins had VWAP=bear; most losses had VWAP=bull
        if not vwap_bull:
            score += 1
        # Volume spike intentionally excluded:
        #    QC: VolSpike=True trades went 0-for-17 (exhaustion, not accumulation)

    # --- Short Score (0-4, unconditional — not regime-gated) ---
    # Each condition below signals a bearish setup worth shorting.
    short_score = 0
    # 1. EMA bearish crossover — downtrend direction
    if not ema_bullish:
        short_score += 1
    # 2. ADX strong AND -DI leads +DI — real downward momentum
    if adx_value > 20 and minus_di > plus_di:
        short_score += 1
    # 3. RSI overbought (>70) — extended, due for reversal
    if rsi_value > 70:
        short_score += 1
    # 4. Price above VWAP — extended above fair value, good short entry
    if vwap_bull:
        short_score += 1

    # --- 4H Trend Filter ---
    trend_4h = "unknown"
    if bars_4h is not None and len(bars_4h) >= 21:
        closes_4h = [b["close"] for b in bars_4h]
        ema9_4h = _ema(closes_4h, profile.ema_fast)
        ema21_4h = _ema(closes_4h, profile.ema_slow)
        if ema9_4h and ema21_4h:
            if ema9_4h[-1] > ema21_4h[-1]:
                trend_4h = "bullish"
            elif ema9_4h[-1] < ema21_4h[-1]:
                trend_4h = "bearish"
            else:
                trend_4h = "neutral"

    # Return None only when the signal is completely neutral in both directions
    if score == 0 and short_score == 0:
        log.debug("NO SIGNAL %s: long=0 short=0 — skipping", symbol)
        return None

    details = {
        "ema9": round(ema9_latest, 6),
        "ema21": round(ema21_latest, 6),
        "adx": round(adx_value, 2),
        "plus_di": round(plus_di, 2),
        "minus_di": round(minus_di, 2),
        "rsi": round(rsi_value, 2),
        "vwap_bull": vwap_bull,
        "market_regime": regime,
        "volume_spike_ratio": round(
            volumes[-1] / (sum(volumes[-21:-1]) / 20) if len(volumes) >= 21 and sum(volumes[-21:-1]) > 0 else 0, 2
        ),
        "latest_close": closes[-1],
        "latest_volume": volumes[-1],
        "short_score": short_score,
        "trend_4h": trend_4h,
    }

    return Signal(
        symbol=symbol,
        ema_bullish=ema_bullish,
        adx_value=adx_value,
        adx_trending=adx_trending,
        plus_di=plus_di,
        minus_di=minus_di,
        rsi_value=rsi_value,
        rsi_signal=rsi_signal,
        volume_spike=vol_spike,
        vwap_bullish=vwap_bull,
        confluence_score=score,
        details=details,
        market_regime=regime,
        short_score=short_score,
        trend_4h=trend_4h,
        atr_value=atr_value,
    )


def scan_assets(
    alpaca_client,
    symbols: list[str],
    timeframe: str = "1Hour",
    bar_count: int = 50,
    fetch_4h: bool = True,
    profile=SWING,
) -> list[Signal]:
    """Scan multiple assets and return signals sorted by confluence score.

    Parameters
    ----------
    alpaca_client : AlpacaClient
        Client for fetching bar data.
    symbols : list[str]
        Symbols to scan (e.g. ["BTC/USD", "ETH/USD"]).
    timeframe : str
        Bar timeframe (default "1Hour" for swing trading).
    bar_count : int
        Number of bars to fetch per asset (default 50).
    fetch_4h : bool
        When True (default), also fetch 4-hour bars and populate trend_4h.
        Set to False for backtesting to avoid extra API calls.

    Returns
    -------
    list[Signal]
        Signals with confluence_score >= 1 or short_score >= 1, sorted
        descending by confluence_score.
    """
    signals = []
    for symbol in symbols:
        try:
            bars = alpaca_client.get_bars(symbol, timeframe=profile.timeframe, limit=profile.bar_count)
            if not bars:
                log.warning("No bars returned for %s", symbol)
                continue

            bars_4h = None
            if fetch_4h:
                try:
                    bars_4h = alpaca_client.get_bars(symbol, timeframe=profile.htf_filter_timeframe, limit=30)
                except Exception as exc_4h:
                    log.debug("Could not fetch 4H bars for %s: %s", symbol, exc_4h)

            signal = analyze(symbol, bars, bars_4h=bars_4h, profile=profile)
            if signal and (signal.confluence_score >= 1 or signal.short_score >= 1):
                signals.append(signal)
                log.info(
                    "SIGNAL %s: long=%d short=%d ema=%s adx=%.1f rsi=%.1f trend_4h=%s",
                    symbol, signal.confluence_score, signal.short_score, signal.ema_bullish,
                    signal.adx_value, signal.rsi_value, signal.trend_4h,
                )
        except Exception as exc:
            log.warning("Failed to analyze %s: %s", symbol, exc)
            continue

    signals.sort(key=lambda s: s.confluence_score, reverse=True)
    return signals
