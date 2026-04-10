"""
Portfolio summary endpoint.

GET /api/portfolio?bot=A|B|both
"""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Query

from db import get_db
from models import Envelope, Meta, MultiBotPortfolio, PortfolioData

router = APIRouter(prefix="/api", tags=["portfolio"])

_DEFAULT_STARTING_EQUITY = 100_000.0


def _portfolio_for_bot(conn, bot_id: str) -> PortfolioData:
    # Get starting equity from bots registry
    bot_row = conn.execute(
        "SELECT starting_equity FROM bots WHERE id = %s", (bot_id,)
    ).fetchone()
    starting_equity = bot_row["starting_equity"] if bot_row else _DEFAULT_STARTING_EQUITY

    # Closed trades
    closed = conn.execute(
        """
        SELECT pnl FROM alpaca_trades
        WHERE bot_id = %s AND status IN ('closed', 'stopped', 'target_hit')
        """,
        (bot_id,),
    ).fetchall()

    total_pnl = sum(r["pnl"] or 0.0 for r in closed)
    wins = sum(1 for r in closed if (r["pnl"] or 0) > 0)
    losses = len(closed) - wins
    equity = starting_equity + total_pnl

    # Counts
    total_trades = conn.execute(
        "SELECT COUNT(*) AS n FROM alpaca_trades WHERE bot_id = %s", (bot_id,)
    ).fetchone()["n"]

    open_count = conn.execute(
        "SELECT COUNT(*) AS n FROM alpaca_trades WHERE bot_id = %s AND status = 'open'",
        (bot_id,),
    ).fetchone()["n"]

    # Daily P&L
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

    resolved = len(closed)
    win_rate_pct = round(wins / resolved * 100, 1) if resolved > 0 else 0.0

    return PortfolioData(
        equity=round(equity, 2),
        total_pnl=round(total_pnl, 2),
        total_pnl_percent=round(total_pnl / starting_equity * 100, 2),
        win_rate=win_rate_pct,
        open_positions=open_count,
        daily_pnl=round(daily_pnl, 2),
        daily_pnl_percent=round(daily_pnl / starting_equity * 100, 2),
        mode="paper",
        trades_resolved=resolved,
        total_trades=total_trades,
        wins=wins,
        losses=losses,
    )


@router.get("/portfolio")
def get_portfolio(bot: Literal["A", "B", "both"] = Query("both")):
    """Return portfolio KPIs. bot=both returns {A: {...}, B: {...}} shape."""
    with get_db() as conn:
        if bot == "both":
            data = MultiBotPortfolio(
                A=_portfolio_for_bot(conn, "A"),
                B=_portfolio_for_bot(conn, "B"),
            )
        else:
            data = _portfolio_for_bot(conn, bot)
    return Envelope(data=data, meta=Meta(count=1))
