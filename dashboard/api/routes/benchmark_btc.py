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

_ALPACA_KEY = os.environ.get("DASH_ALPACA_API_KEY", "")
_ALPACA_SECRET = os.environ.get("DASH_ALPACA_SECRET_KEY", "")

_btc_cache: dict = {"data": [], "ts": 0.0}
_CACHE_TTL = 300.0  # 5 minutes


def _fetch_btc_bars(start: datetime) -> list:
    import urllib.request
    import json

    if not _ALPACA_KEY or not _ALPACA_SECRET:
        return []

    start_str = start.strftime("%Y-%m-%d")
    url = (
        f"https://data.alpaca.markets/v1beta3/crypto/us/bars"
        f"?symbols=BTC%2FUSD&timeframe=1Day&start={start_str}&limit=120"
    )
    req = urllib.request.Request(
        url,
        headers={
            "APCA-API-KEY-ID": _ALPACA_KEY,
            "APCA-API-SECRET-KEY": _ALPACA_SECRET,
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
    now = time.time()
    if now - _btc_cache["ts"] < _CACHE_TTL and _btc_cache["data"]:
        return Envelope(data=_btc_cache["data"], meta=Meta())

    if not _ALPACA_KEY or not _ALPACA_SECRET:
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

    _btc_cache.update({"data": points, "ts": now})
    return Envelope(data=points, meta=Meta(count=len(points)))
