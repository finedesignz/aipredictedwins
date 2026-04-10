"""
Portfolio summary endpoint.

GET /api/portfolio?bot=A|B|both

Real equity/cash/unrealized P&L comes from the Alpaca account endpoint.
Win rate and trade counts come from the database (closed alpaca_trades).
Falls back to DB-only calculation when Alpaca keys are absent.
"""

import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Literal

from fastapi import APIRouter, Query

from db import get_db
from models import Envelope, Meta, MultiBotPortfolio, PortfolioData

router = APIRouter(prefix="/api", tags=["portfolio"])

_ALPACA_BASE = "https://paper-api.alpaca.markets"
_DEFAULT_STARTING_EQUITY = 100_000.0


def _fetch_alpaca_account(api_key: str, secret_key: str) -> dict:
    """Return the Alpaca account dict, or {} on failure."""
    if not api_key or not secret_key:
        return {}
    req = urllib.request.Request(
        f"{_ALPACA_BASE}/v2/account",
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
        return {}


def _portfolio_for_bot(conn, bot_id: str, days: int = 30) -> PortfolioData:
    # Starting equity from registry
    bot_row = conn.execute(
        "SELECT starting_equity FROM bots WHERE id = %s", (bot_id,)
    ).fetchone()
    starting_equity = bot_row["starting_equity"] if bot_row else _DEFAULT_STARTING_EQUITY

    # Closed trades filtered to window → win rate / trade counts
    since = datetime.now(timezone.utc) - timedelta(days=days)
    closed = conn.execute(
        """
        SELECT pnl FROM alpaca_trades
        WHERE bot_id = %s AND status IN ('closed', 'stopped', 'target_hit')
          AND (closed_at IS NULL OR closed_at::timestamptz >= %s)
        """,
        (bot_id, since),
    ).fetchall()

    closed_pnl = sum(r["pnl"] or 0.0 for r in closed)
    wins = sum(1 for r in closed if (r["pnl"] or 0) > 0)
    losses = len(closed) - wins
    resolved = len(closed)
    win_rate_pct = round(wins / resolved * 100, 1) if resolved > 0 else 0.0

    total_trades = conn.execute(
        "SELECT COUNT(*) AS n FROM alpaca_trades WHERE bot_id = %s", (bot_id,)
    ).fetchone()["n"]

    open_count = conn.execute(
        "SELECT COUNT(*) AS n FROM alpaca_trades WHERE bot_id = %s AND status = 'open'",
        (bot_id,),
    ).fetchone()["n"]

    # Daily P&L (closed trades today)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_rows = conn.execute(
        """
        SELECT pnl FROM alpaca_trades
        WHERE bot_id = %s AND status IN ('closed', 'stopped', 'target_hit')
          AND closed_at LIKE %s
        """,
        (bot_id, f"{today}%"),
    ).fetchall()
    daily_pnl = sum(r["pnl"] or 0.0 for r in daily_rows)

    # Real-time equity from Alpaca account
    key = os.environ.get(f"ALPACA_API_KEY_{bot_id}", "")
    sec = os.environ.get(f"ALPACA_SECRET_KEY_{bot_id}", "")
    acct = _fetch_alpaca_account(key, sec)

    if acct:
        equity = float(acct.get("equity") or starting_equity)
        total_pnl = equity - starting_equity
        # Unrealized component already in equity; daily unrealized from Alpaca if available
        unrealized = float(acct.get("unrealized_pl") or 0.0)
        # Add today's unrealized change as part of daily P&L
        unrealized_today = float(acct.get("unrealized_intraday_pl") or 0.0)
        daily_pnl_total = daily_pnl + unrealized_today
    else:
        equity = starting_equity + closed_pnl
        total_pnl = closed_pnl
        daily_pnl_total = daily_pnl

    return PortfolioData(
        equity=round(equity, 2),
        total_pnl=round(total_pnl, 2),
        total_pnl_percent=round(total_pnl / starting_equity * 100, 2),
        win_rate=win_rate_pct,
        open_positions=open_count,
        daily_pnl=round(daily_pnl_total, 2),
        daily_pnl_percent=round(daily_pnl_total / starting_equity * 100, 2),
        mode="paper",
        trades_resolved=resolved,
        total_trades=total_trades,
        wins=wins,
        losses=losses,
    )


@router.get("/portfolio")
def get_portfolio(
    bot: Literal["A", "B", "both"] = Query("both"),
    days: int = Query(30, ge=1, le=365),
):
    """Return portfolio KPIs. bot=both returns {A: {...}, B: {...}} shape."""
    with get_db() as conn:
        if bot == "both":
            data = MultiBotPortfolio(
                A=_portfolio_for_bot(conn, "A", days),
                B=_portfolio_for_bot(conn, "B", days),
            )
        else:
            data = _portfolio_for_bot(conn, bot, days)
    return Envelope(data=data, meta=Meta(count=1))
