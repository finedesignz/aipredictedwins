"""
BTC/USD benchmark endpoint.

GET /api/benchmark/btc?since=<ISO>
Returns BTC daily closes normalized to return_pct starting at 0%.
Cached in memory for 5 minutes.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Query

from models import BenchmarkPoint, Envelope, Meta

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])

_btc_cache: dict[str, dict] = {}  # keyed by since string
_CACHE_TTL = 300.0  # 5 minutes


def _fetch_btc_bars(start: datetime) -> list:
    import urllib.request
    import json

    # Read keys lazily so a missing-at-startup env var is picked up after restart
    key = os.environ.get("DASH_ALPACA_API_KEY", "")
    secret = os.environ.get("DASH_ALPACA_SECRET_KEY", "")
    if not key or not secret:
        return []

    start_str = start.strftime("%Y-%m-%d")
    url = (
        f"https://data.alpaca.markets/v1beta3/crypto/us/bars"
        f"?symbols=BTC%2FUSD&timeframe=1Day&start={start_str}&limit=120"
    )
    req = urllib.request.Request(
        url,
        headers={
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data.get("bars", {}).get("BTC/USD", [])
    except Exception:
        return []


@router.get("/btc")
def get_btc_benchmark(
    since: Optional[str] = Query(None, description="ISO date. Defaults to 90 days ago."),
):
    """Return BTC/USD daily return_pct normalized to 0% at first data point."""
    cache_key = since or "default"
    now = time.time()
    cached = _btc_cache.get(cache_key)
    if cached and now - cached["ts"] < _CACHE_TTL and cached["data"]:
        return Envelope(data=cached["data"], meta=Meta())

    if not os.environ.get("DASH_ALPACA_API_KEY"):
        return Envelope(data=[], meta=Meta())

    if since:
        try:
            start = datetime.fromisoformat(since)
        except ValueError:
            start = datetime.now(timezone.utc) - timedelta(days=90)
    else:
        start = datetime.now(timezone.utc) - timedelta(days=90)

    bars = _fetch_btc_bars(start)

    if not bars:
        return Envelope(data=[], meta=Meta())

    base_close = bars[0]["c"]
    points = []
    for bar in bars:
        return_pct = round((bar["c"] - base_close) / base_close * 100, 4)
        ts = bar["t"][:10] + "T00:00:00+00:00"
        points.append(BenchmarkPoint(
            timestamp=ts,
            return_pct=return_pct,
        ).model_dump())

    _btc_cache[cache_key] = {"data": points, "ts": now}
    return Envelope(data=points, meta=Meta(count=len(points)))
