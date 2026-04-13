"""
SPY benchmark endpoint — uses yfinance (free, no API key required).

GET /api/benchmark/spy?since=<ISO>
Returns SPY daily closes normalized to return_pct starting at 0%.
Cached in memory for 5 minutes.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query

from models import BenchmarkPoint, Envelope, Meta

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])

_spy_cache: dict[str, dict] = {}
_CACHE_TTL = 300.0


def _fetch_spy_bars(start: datetime) -> list[dict]:
    import yfinance as yf

    ticker = yf.Ticker("SPY")
    hist = ticker.history(start=start.strftime("%Y-%m-%d"), interval="1d", auto_adjust=True)
    if hist.empty:
        return []
    return [
        {"date": ts.strftime("%Y-%m-%d"), "close": float(row["Close"])}
        for ts, row in hist.iterrows()
    ]


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

    base_close = bars[0]["close"]
    points = [
        BenchmarkPoint(
            timestamp=f"{b['date']}T00:00:00+00:00",
            return_pct=round((b["close"] - base_close) / base_close * 100, 4),
            price=round(b["close"], 2),
        ).model_dump()
        for b in bars
    ]

    _spy_cache[cache_key] = {"data": points, "ts": now}
    return Envelope(data=points, meta=Meta(count=len(points)))
