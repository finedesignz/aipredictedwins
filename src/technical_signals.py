"""
Technical Signal Engine for crypto swing trading.

Computes proven quantitative indicators from OHLCV bar data and
produces a confluence score (0-5) for trade decisions.

Indicators:
  1. EMA Crossover (9/21) — trend direction
  2. ADX (14-period) — trend strength
  3. RSI (14-period) — overbought/oversold
  4. Volume Spike — institutional interest
  5. VWAP — intraday value reference

No LLM calls. Pure math on price data.
"""

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class Signal:
    """Result of technical analysis for a single asset."""
    symbol: str
    ema_bullish: bool
    adx_value: float
    adx_trending: bool
    rsi_value: float
    rsi_signal: str          # "oversold", "overbought", or "neutral"
    volume_spike: bool
    vwap_bullish: bool
    confluence_score: int    # 0-5: how many indicators are bullish
    details: dict            # raw indicator values for logging


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


def _adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    """Average Directional Index (ADX) using Wilder's smoothing.

    Returns the latest ADX value, or None if insufficient data.
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

    return adx


def _volume_spike(volumes: list[float], lookback: int = 20, threshold: float = 1.5) -> bool:
    """True if the latest volume bar exceeds threshold * average of prior bars."""
    if len(volumes) < lookback + 1:
        return False
    avg_vol = sum(volumes[-(lookback + 1):-1]) / lookback
    if avg_vol <= 0:
        return False
    return volumes[-1] > avg_vol * threshold


def _vwap_bullish(closes: list[float], volumes: list[float], vwaps: list[float]) -> bool:
    """True if the latest close is above the latest VWAP.

    If VWAP data is not available from bars, we compute a rolling VWAP
    from the last 20 bars.
    """
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

def analyze(symbol: str, bars: list[dict]) -> Signal | None:
    """Run all technical indicators on OHLCV bars and return a Signal.

    Parameters
    ----------
    symbol : str
        Asset symbol (e.g. "BTC/USD").
    bars : list[dict]
        OHLCV bars from AlpacaClient.get_bars(). Each bar must have
        keys: open, high, low, close, volume, vwap (optional).
        Should be at least 50 bars for reliable indicators.

    Returns
    -------
    Signal or None if insufficient data.
    """
    if len(bars) < 30:
        log.warning("Insufficient bars for %s (%d < 30 needed)", symbol, len(bars))
        return None

    closes = [b["close"] for b in bars]
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    volumes = [b["volume"] for b in bars]
    vwaps = [b.get("vwap", 0) for b in bars]

    # --- EMA Crossover (9/21) ---
    ema9 = _ema(closes, 9)
    ema21 = _ema(closes, 21)
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
    adx_value = _adx(highs, lows, closes, 14)
    if adx_value is None:
        adx_value = 0.0
    adx_trending = adx_value > 20  # ADX > 20 = meaningful trend

    # --- RSI (14-period) ---
    rsi_value = _rsi(closes, 14)
    if rsi_value is None:
        rsi_value = 50.0
    if rsi_value < 30:
        rsi_signal = "oversold"
    elif rsi_value > 70:
        rsi_signal = "overbought"
    else:
        rsi_signal = "neutral"

    # --- Volume Spike ---
    vol_spike = _volume_spike(volumes, lookback=20, threshold=1.5)

    # --- VWAP ---
    vwap_bull = _vwap_bullish(closes, volumes, vwaps)

    # --- Confluence Score ---
    score = 0
    # EMA bullish crossover
    if ema_bullish:
        score += 1
    # ADX confirms trend exists AND EMA direction is up
    if adx_trending and ema_bullish:
        score += 1
    # RSI oversold = buy opportunity (bullish signal)
    # RSI neutral with bullish trend = OK too (count it)
    if rsi_signal == "oversold":
        score += 1
    elif rsi_signal == "neutral" and ema_bullish:
        score += 1
    # Volume spike confirms interest
    if vol_spike:
        score += 1
    # Price above VWAP
    if vwap_bull:
        score += 1

    details = {
        "ema9": round(ema9_latest, 6),
        "ema21": round(ema21_latest, 6),
        "adx": round(adx_value, 2),
        "rsi": round(rsi_value, 2),
        "volume_spike_ratio": round(
            volumes[-1] / (sum(volumes[-21:-1]) / 20) if len(volumes) >= 21 and sum(volumes[-21:-1]) > 0 else 0, 2
        ),
        "latest_close": closes[-1],
        "latest_volume": volumes[-1],
    }

    return Signal(
        symbol=symbol,
        ema_bullish=ema_bullish,
        adx_value=adx_value,
        adx_trending=adx_trending,
        rsi_value=rsi_value,
        rsi_signal=rsi_signal,
        volume_spike=vol_spike,
        vwap_bullish=vwap_bull,
        confluence_score=score,
        details=details,
    )


def scan_assets(alpaca_client, symbols: list[str], timeframe: str = "1Hour", bar_count: int = 50) -> list[Signal]:
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

    Returns
    -------
    list[Signal]
        Signals with confluence_score >= 1, sorted descending.
    """
    signals = []
    for symbol in symbols:
        try:
            bars = alpaca_client.get_bars(symbol, timeframe=timeframe, limit=bar_count)
            if not bars:
                log.warning("No bars returned for %s", symbol)
                continue

            signal = analyze(symbol, bars)
            if signal and signal.confluence_score >= 1:
                signals.append(signal)
                log.info(
                    "SIGNAL %s: score=%d ema=%s adx=%.1f rsi=%.1f vol_spike=%s vwap=%s",
                    symbol, signal.confluence_score, signal.ema_bullish,
                    signal.adx_value, signal.rsi_value, signal.volume_spike,
                    signal.vwap_bullish,
                )
        except Exception as exc:
            log.warning("Failed to analyze %s: %s", symbol, exc)
            continue

    signals.sort(key=lambda s: s.confluence_score, reverse=True)
    return signals
