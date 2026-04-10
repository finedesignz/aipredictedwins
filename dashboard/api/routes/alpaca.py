"""
Alpaca live data endpoint.

GET /api/alpaca/equity?days=30  -- portfolio history from Alpaca paper API
                                    for both bots, returns per-bot equity series.

Reads ALPACA_API_KEY_A / ALPACA_SECRET_KEY_A and
      ALPACA_API_KEY_B / ALPACA_SECRET_KEY_B from env vars (set in Coolify).
"""

import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Query
from models import Envelope, Meta

router = APIRouter(prefix="/api/alpaca", tags=["alpaca"])

ALPACA_BASE = "https://paper-api.alpaca.markets"


def _fetch_portfolio_history(api_key: str, secret_key: str, days: int) -> list[dict]:
    """Fetch daily equity curve from Alpaca portfolio history endpoint."""
    if not api_key or not secret_key:
        return []

    # period like "30D", timeframe "1D" gives one point per calendar day
    url = f"{ALPACA_BASE}/v2/account/portfolio/history?period={days}D&timeframe=1D&extended_hours=false"
    req = urllib.request.Request(
        url,
        headers={
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Alpaca {e.code}: {body[:200]}")

    timestamps = data.get("timestamp", [])
    equity_values = data.get("equity", [])

    points = []
    for ts, eq in zip(timestamps, equity_values):
        # Skip null or zero values (Alpaca returns 0 for days before account opened)
        if not eq:
            continue
        # Truncate to date-only ISO so timestamps align with SPY bars
        day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        iso = f"{day}T00:00:00+00:00"
        points.append({"timestamp": iso, "equity": round(float(eq), 2)})

    return points


def _fetch_account(api_key: str, secret_key: str) -> dict:
    """Fetch current account state (equity, cash, buying power)."""
    if not api_key or not secret_key:
        return {}
    url = f"{ALPACA_BASE}/v2/account"
    req = urllib.request.Request(
        url,
        headers={
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return {}


def _fetch_crypto_benchmark(api_key: str, secret_key: str, days: int) -> list[dict]:
    """Fetch BTC/USD daily bars from Alpaca crypto API, normalized to $100k start."""
    if not api_key or not secret_key:
        return []
    try:
        start = (datetime.now(timezone.utc) - timedelta(days=days + 5)).strftime("%Y-%m-%d")
        url = (
            f"https://data.alpaca.markets/v1beta3/crypto/us/bars"
            f"?symbols=BTC%2FUSD&timeframe=1Day&start={start}&limit={days + 10}"
        )
        req = urllib.request.Request(
            url,
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": secret_key,
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        bars = data.get("bars", {}).get("BTC/USD", [])
        if not bars:
            return []

        bars = bars[-days:]
        first_close = bars[0]["c"]
        points = []
        for bar in bars:
            close = bar["c"]
            normalized = round((close / first_close) * 100_000.0, 2)
            ts = bar["t"][:10] + "T00:00:00+00:00"
            points.append({"timestamp": ts, "equity": normalized})
        return points
    except Exception:
        return []


def _fetch_sp500(api_key: str, secret_key: str, days: int) -> list[dict]:
    """Fetch SPY daily bars from Alpaca market data API, normalized to $100k start."""
    if not api_key or not secret_key:
        return []
    try:
        start = (datetime.now(timezone.utc) - timedelta(days=days + 5)).strftime("%Y-%m-%d")
        url = (
            f"https://data.alpaca.markets/v2/stocks/SPY/bars"
            f"?timeframe=1Day&start={start}&limit={days + 10}&feed=iex"
        )
        req = urllib.request.Request(
            url,
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": secret_key,
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        bars = data.get("bars", [])
        if not bars:
            return []

        # Keep only the most recent `days` bars
        bars = bars[-days:]

        first_close = bars[0]["c"]
        points = []
        for bar in bars:
            close = bar["c"]
            normalized = round((close / first_close) * 100_000.0, 2)
            # bar timestamp is like "2024-01-02T05:00:00Z" — truncate to date for alignment
            ts = bar["t"][:10] + "T00:00:00+00:00"
            points.append({"timestamp": ts, "equity": normalized})
        return points
    except Exception:
        return []


@router.get("/equity")
def get_alpaca_equity(days: int = Query(30, ge=1, le=90)):
    """Return portfolio history for both bots from Alpaca live API."""
    key_a = os.environ.get("ALPACA_API_KEY_A", "")
    sec_a = os.environ.get("ALPACA_SECRET_KEY_A", "")
    key_b = os.environ.get("ALPACA_API_KEY_B", "")
    sec_b = os.environ.get("ALPACA_SECRET_KEY_B", "")

    errors = []

    try:
        a_points = _fetch_portfolio_history(key_a, sec_a, days)
    except Exception as e:
        a_points = []
        errors.append(f"Agent A: {e}")

    try:
        b_points = _fetch_portfolio_history(key_b, sec_b, days)
    except Exception as e:
        b_points = []
        errors.append(f"Agent B: {e}")

    sp500_points = _fetch_sp500(key_a, sec_a, days)
    crypto_points = _fetch_crypto_benchmark(key_a, sec_a, days)

    # Current account equity
    acct_a = _fetch_account(key_a, sec_a)
    acct_b = _fetch_account(key_b, sec_b)

    def _account_summary(acct: dict) -> dict:
        return {
            "equity": float(acct.get("equity", 0) or 0),
            "cash": float(acct.get("cash", 0) or 0),
            "buying_power": float(acct.get("buying_power", 0) or 0),
            "portfolio_value": float(acct.get("portfolio_value", 0) or 0),
            "daytrade_count": int(acct.get("daytrade_count", 0) or 0),
        }

    data = {
        "agentA": a_points,
        "agentB": b_points,
        "sp500": sp500_points,
        "cryptoBenchmark": crypto_points,
        "accountA": _account_summary(acct_a),
        "accountB": _account_summary(acct_b),
        "days": days,
        "errors": errors,
    }

    return Envelope(
        data=data,
        meta=Meta(
            timestamp=datetime.now(timezone.utc).isoformat(),
            count=len(a_points) + len(b_points),
        ),
    )
