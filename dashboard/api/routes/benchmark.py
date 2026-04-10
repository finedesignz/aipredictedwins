"""
SPY benchmark endpoint.

GET /api/benchmark/spy?since=<ISO>
Returns SPY daily closes normalized to return_pct starting at 0%.
Cached in memory for 5 minutes.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query

from models import BenchmarkPoint, Envelope, Meta

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])

_spy_cache: dict[str, dict] = {}  # keyed by since string
_CACHE_TTL = 300.0  # 5 minutes


def _fetch_spy_bars(start: datetime) -> list:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    # Read keys lazily — prefer dedicated dashboard key, fall back to Bot A keys
    key = (
        os.environ.get("DASH_ALPACA_API_KEY")
        or os.environ.get("ALPACA_API_KEY_A")
        or os.environ.get("ALPACA_API_KEY", "")
    )
    secret = (
        os.environ.get("DASH_ALPACA_SECRET_KEY")
        or os.environ.get("ALPACA_SECRET_KEY_A")
        or os.environ.get("ALPACA_SECRET_KEY", "")
    )
    if not key or not secret:
        return []

    client = StockHistoricalDataClient(key, secret)
    req = StockBarsRequest(
        symbol_or_symbols="SPY",
        timeframe=TimeFrame.Day,
        start=start,
    )
    bars_dict = client.get_stock_bars(req).data
    return bars_dict.get("SPY", [])


@router.get("/spy")
def get_spy_benchmark(
    since: Optional[str] = Query(None, description="ISO date. Defaults to 90 days ago."),
):
    """Return SPY daily return_pct normalized to 0% at first data point."""
    cache_key = since or "default"
    now = time.time()
    cached = _spy_cache.get(cache_key)
    if cached and now - cached["ts"] < _CACHE_TTL and cached["data"]:
        return Envelope(data=cached["data"], meta=Meta())

    if not (os.environ.get("DASH_ALPACA_API_KEY") or os.environ.get("ALPACA_API_KEY_A") or os.environ.get("ALPACA_API_KEY")):
        return Envelope(data=[], meta=Meta())

    if since:
        try:
            start = datetime.fromisoformat(since)
        except ValueError:
            start = datetime.now(timezone.utc) - timedelta(days=90)
    else:
        start = datetime.now(timezone.utc) - timedelta(days=90)

    try:
        bars = _fetch_spy_bars(start)
    except Exception:
        return Envelope(data=[], meta=Meta())

    if not bars:
        return Envelope(data=[], meta=Meta())

    base_close = bars[0].close
    points = []
    for bar in bars:
        return_pct = round((bar.close - base_close) / base_close * 100, 4)
        # Normalise to midnight UTC so timestamps align with bot portfolio points
        day = bar.timestamp.strftime("%Y-%m-%d")
        points.append(BenchmarkPoint(
            timestamp=f"{day}T00:00:00+00:00",
            return_pct=return_pct,
        ).model_dump())

    _spy_cache[cache_key] = {"data": points, "ts": now}
    return Envelope(data=points, meta=Meta(count=len(points)))
