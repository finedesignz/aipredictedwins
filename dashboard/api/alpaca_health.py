"""
Read-only Alpaca health probe for the dashboard.

Prefers DASH_ALPACA_API_KEY / DASH_ALPACA_SECRET_KEY env vars, but falls back
to any bot's keys stored in the `bots` table when the dedicated dash keys are
absent or rotated out — so the health check survives credential rotation.
"""

import os
import time
from typing import Literal

_CACHE: dict = {"value": "unknown", "ts": 0.0}
_CACHE_TTL = 30.0  # seconds


def _candidate_keys() -> list[tuple[str, str]]:
    """Ordered list of (api_key, secret_key) pairs to try."""
    pairs: list[tuple[str, str]] = []
    env_key = os.environ.get("DASH_ALPACA_API_KEY", "")
    env_sec = os.environ.get("DASH_ALPACA_SECRET_KEY", "")
    if env_key and env_sec:
        pairs.append((env_key, env_sec))

    # Fall back to keys stored in the bots registry (source of truth).
    try:
        from db import get_db
        with get_db() as conn:
            rows = conn.execute(
                "SELECT alpaca_api_key, alpaca_secret_key FROM bots "
                "WHERE alpaca_api_key IS NOT NULL AND alpaca_api_key <> ''"
            ).fetchall()
        for r in rows:
            k, s = r.get("alpaca_api_key"), r.get("alpaca_secret_key")
            if k and s and (k, s) not in pairs:
                pairs.append((k, s))
    except Exception:
        pass
    return pairs


def get_account_health() -> Literal["ok", "degraded", "down", "unknown"]:
    """Ping Alpaca paper account. Returns cached result for 30s."""
    now = time.time()
    if now - _CACHE["ts"] < _CACHE_TTL:
        return _CACHE["value"]

    candidates = _candidate_keys()
    if not candidates:
        _CACHE.update({"value": "unknown", "ts": now})
        return "unknown"

    from alpaca.trading.client import TradingClient
    for api_key, secret_key in candidates:
        try:
            TradingClient(api_key, secret_key, paper=True).get_account()
            _CACHE.update({"value": "ok", "ts": now})
            return "ok"
        except Exception:
            continue

    _CACHE.update({"value": "down", "ts": now})
    return "down"
