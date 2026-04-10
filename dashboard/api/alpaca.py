"""
Read-only Alpaca client for the dashboard.

Uses DASH_ALPACA_API_KEY / DASH_ALPACA_SECRET_KEY env vars (paper account,
market-data-only credentials, separate from the bots' trading keys).
"""

import os
import time
from typing import Literal

_CACHE: dict = {"value": "unknown", "ts": 0.0}
_CACHE_TTL = 30.0  # seconds


def get_account_health() -> Literal["ok", "degraded", "down", "unknown"]:
    """Ping Alpaca paper account. Returns cached result for 30s."""
    now = time.time()
    if now - _CACHE["ts"] < _CACHE_TTL:
        return _CACHE["value"]

    api_key = os.environ.get("DASH_ALPACA_API_KEY", "")
    secret_key = os.environ.get("DASH_ALPACA_SECRET_KEY", "")

    if not api_key or not secret_key:
        _CACHE.update({"value": "unknown", "ts": now})
        return "unknown"

    try:
        from alpaca.trading.client import TradingClient
        client = TradingClient(api_key, secret_key, paper=True)
        client.get_account()
        _CACHE.update({"value": "ok", "ts": now})
        return "ok"
    except Exception:
        _CACHE.update({"value": "down", "ts": now})
        return "down"
