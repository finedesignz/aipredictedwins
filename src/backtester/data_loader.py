"""
Backtester data loading utilities.

Priority order for bar data:
  1. fixture_dir (JSON files, for CI / unit tests)
  2. disk cache (data/bar_cache/<symbol>_<timeframe>.json)
  3. Alpaca API (requires credentials in env)

Symbol names use slash format: "BTC/USD" -> fixture file "BTC_USD.json"
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

BAR_CACHE_DIR = os.environ.get("BAR_CACHE_DIR", "data/bar_cache")


def normalise_bar(raw: dict) -> dict:
    """Ensure a bar dict has all required keys with correct types."""
    close = float(raw.get("close", 0))
    return {
        "timestamp": str(raw.get("timestamp", "")),
        "open":   float(raw.get("open", close)),
        "high":   float(raw.get("high", close)),
        "low":    float(raw.get("low", close)),
        "close":  close,
        "volume": float(raw.get("volume", 0)),
        "vwap":   float(raw.get("vwap", close)),
    }


def _symbol_to_filename(symbol: str) -> str:
    return symbol.replace("/", "_")


def load_bars_fixture(symbol: str, fixture_dir: str) -> list[dict]:
    """Load bars from a JSON fixture file. Raises FileNotFoundError if absent."""
    fname = _symbol_to_filename(symbol) + ".json"
    path = Path(fixture_dir) / fname
    if not path.exists():
        raise FileNotFoundError(f"No fixture for {symbol} at {path}")
    with open(path) as f:
        raw_bars = json.load(f)
    bars = [normalise_bar(b) for b in raw_bars]
    bars.sort(key=lambda b: b["timestamp"])
    return bars


def load_bars_cached(
    symbol: str,
    start_iso: str,
    end_iso: str,
    timeframe: str = "1Hour",
    cache_dir: str = BAR_CACHE_DIR,
) -> list[dict] | None:
    """Load bars from disk cache. Returns None if not cached."""
    fname = f"{_symbol_to_filename(symbol)}_{timeframe}.json"
    path = Path(cache_dir) / fname
    if not path.exists():
        return None
    with open(path) as f:
        all_bars = json.load(f)
    bars = [normalise_bar(b) for b in all_bars
            if start_iso[:10] <= str(b.get("timestamp", ""))[:10] <= end_iso[:10]]
    bars.sort(key=lambda b: b["timestamp"])
    log.debug("Bar cache HIT: %s %s bars (%s-%s)", symbol, len(bars), start_iso[:10], end_iso[:10])
    return bars or None


def save_bars_cache(
    symbol: str,
    bars: list[dict],
    timeframe: str = "1Hour",
    cache_dir: str = BAR_CACHE_DIR,
) -> None:
    """Write bars to disk cache (merges with any existing cached bars)."""
    fname = f"{_symbol_to_filename(symbol)}_{timeframe}.json"
    path = Path(cache_dir) / fname
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if path.exists():
        with open(path) as f:
            existing = json.load(f)
    by_ts: dict[str, dict] = {b["timestamp"]: b for b in existing}
    for b in bars:
        by_ts[b["timestamp"]] = b
    merged = sorted(by_ts.values(), key=lambda b: b["timestamp"])
    with open(path, "w") as f:
        json.dump(merged, f)


def load_bars_from_alpaca(
    symbol: str,
    start_iso: str,
    end_iso: str,
    timeframe: str = "1Hour",
    cache_dir: str = BAR_CACHE_DIR,
) -> list[dict]:
    """Fetch bars from Alpaca and write to disk cache. Requires ALPACA_API_KEY/SECRET in env."""
    from alpaca.data import CryptoHistoricalDataClient
    from alpaca.data.requests import CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    api_key = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")

    tf_map = {
        "1Hour": TimeFrame.Hour,
        "1Day": TimeFrame.Day,
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    }
    tf = tf_map.get(timeframe, TimeFrame.Hour)
    request = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=tf,
                                 start=start_iso, end=end_iso)
    # Alpaca's crypto market-data endpoint is PUBLIC. Use the account keys when they
    # are present, but fall back to the keyless client if they are absent or stale —
    # a rotated trading key must not be able to block a read-only backtest fetch.
    try:
        if not api_key or not secret_key:
            raise RuntimeError("no Alpaca keys in env — using the public crypto feed")
        response = CryptoHistoricalDataClient(api_key, secret_key).get_crypto_bars(request)
    except Exception as exc:
        log.info("Authenticated crypto-bar fetch unavailable (%s) — using the public feed", exc)
        response = CryptoHistoricalDataClient().get_crypto_bars(request)
    df = response.df.reset_index()
    bars = []
    for _, row in df.iterrows():
        bars.append(normalise_bar({
            "timestamp": str(row["timestamp"]),
            "open": row["open"], "high": row["high"],
            "low": row["low"], "close": row["close"],
            "volume": row["volume"], "vwap": row.get("vwap", row["close"]),
        }))
    bars.sort(key=lambda b: b["timestamp"])
    save_bars_cache(symbol, bars, timeframe=timeframe, cache_dir=cache_dir)
    return bars


def load_bars(
    symbol: str,
    start_iso: str,
    end_iso: str,
    timeframe: str = "1Hour",
    fixture_dir: str | None = None,
    cache_dir: str = BAR_CACHE_DIR,
) -> list[dict]:
    """Load bars: fixture -> disk cache -> Alpaca API."""
    if fixture_dir:
        return load_bars_fixture(symbol, fixture_dir=fixture_dir)
    cached = load_bars_cached(symbol, start_iso, end_iso, timeframe=timeframe, cache_dir=cache_dir)
    if cached:
        return cached
    log.info("Bar cache miss for %s — fetching from Alpaca", symbol)
    return load_bars_from_alpaca(symbol, start_iso, end_iso, timeframe=timeframe, cache_dir=cache_dir)
