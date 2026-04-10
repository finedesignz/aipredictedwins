"""
Shared Alpaca paper API client for dashboard routes.

Reads ALPACA_API_KEY_A / ALPACA_SECRET_KEY_A and
      ALPACA_API_KEY_B / ALPACA_SECRET_KEY_B from env vars.

All functions return empty/zero values gracefully when the API is
unreachable or keys are not configured.
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Optional

PAPER_BASE = "https://paper-api.alpaca.markets"
DATA_BASE = "https://data.alpaca.markets"


def _get_keys(bot: str) -> tuple[str, str]:
    """Return (api_key, secret_key) for 'a' or 'b'."""
    suffix = bot.upper()
    return (
        os.environ.get(f"ALPACA_API_KEY_{suffix}", ""),
        os.environ.get(f"ALPACA_SECRET_KEY_{suffix}", ""),
    )


def _request(url: str, api_key: str, secret_key: str) -> Optional[dict]:
    """Make an authenticated GET request; returns parsed JSON or None on error."""
    if not api_key or not secret_key:
        return None
    req = urllib.request.Request(
        url,
        headers={
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


# ── Account ──────────────────────────────────────────────────────────────────

def get_account(bot: str) -> dict:
    """Return account dict with equity, cash, buying_power, portfolio_value."""
    key, sec = _get_keys(bot)
    data = _request(f"{PAPER_BASE}/v2/account", key, sec)
    if not data:
        return {}
    return {
        "equity": float(data.get("equity") or 0),
        "cash": float(data.get("cash") or 0),
        "buying_power": float(data.get("buying_power") or 0),
        "portfolio_value": float(data.get("portfolio_value") or 0),
        "last_equity": float(data.get("last_equity") or 0),  # previous close
    }


# ── Positions ─────────────────────────────────────────────────────────────────

def get_open_positions(bot: str) -> list[dict]:
    """Return all open positions from Alpaca with live prices and unrealized P&L."""
    key, sec = _get_keys(bot)
    data = _request(f"{PAPER_BASE}/v2/positions", key, sec)
    if not isinstance(data, list):
        return []
    positions = []
    for p in data:
        qty = float(p.get("qty") or p.get("qty_available") or 0)
        entry = float(p.get("avg_entry_price") or 0)
        current = float(p.get("current_price") or entry)
        unrealized = float(p.get("unrealized_pl") or 0)
        unrealized_pct = float(p.get("unrealized_plpc") or 0) * 100  # API gives 0-1 fraction
        positions.append({
            "symbol": p.get("symbol", ""),
            "side": p.get("side", "long"),
            "qty": qty,
            "entry_price": entry,
            "current_price": current,
            "unrealized_pnl": round(unrealized, 2),
            "unrealized_pnl_percent": round(unrealized_pct, 2),
            "market_value": float(p.get("market_value") or 0),
            "cost_basis": float(p.get("cost_basis") or 0),
        })
    return positions


# ── Portfolio history ─────────────────────────────────────────────────────────

def get_daily_pnl(bot: str) -> float:
    """Return today's P&L = current equity - previous close equity."""
    acct = get_account(bot)
    equity = acct.get("equity", 0.0)
    last_equity = acct.get("last_equity", 0.0)
    if not last_equity:
        return 0.0
    return round(equity - last_equity, 2)
