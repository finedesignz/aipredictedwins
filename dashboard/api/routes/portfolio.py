"""
Portfolio summary endpoint.

GET /api/portfolio -- KPI summary: equity, P&L, win rate, positions, daily P&L.
"""

from datetime import datetime, timezone

from fastapi import APIRouter

from db import get_db, rows_to_list
from models import Envelope, Meta, PortfolioData

router = APIRouter(prefix="/api", tags=["portfolio"])


@router.get("/portfolio", response_model=Envelope[PortfolioData])
def get_portfolio():
    """Return portfolio-level KPIs computed from alpaca_trades."""
    with get_db() as conn:
        # Open position count
        open_count = conn.execute(
            "SELECT COUNT(*) FROM alpaca_trades WHERE status = 'open'"
        ).fetchone()[0]

        # Total trades
        total_trades = conn.execute(
            "SELECT COUNT(*) FROM alpaca_trades"
        ).fetchone()[0]

        # Closed trades for win rate and P&L
        closed_rows = conn.execute(
            """
            SELECT status, pnl FROM alpaca_trades
            WHERE status IN ('closed', 'stopped', 'target_hit')
            """
        ).fetchall()

        resolved = len(closed_rows)
        wins = sum(1 for r in closed_rows if (r["pnl"] or 0) > 0)
        losses = sum(1 for r in closed_rows if (r["pnl"] or 0) <= 0)
        total_pnl = sum(r["pnl"] or 0.0 for r in closed_rows)
        win_rate = wins / resolved if resolved > 0 else 0.0

        # Equity = starting bankroll + total realized P&L
        # Unrealized P&L not included since we don't have live prices
        equity = 100_000.0 + total_pnl

        # Daily P&L -- trades closed today
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_rows = conn.execute(
            """
            SELECT pnl FROM alpaca_trades
            WHERE status IN ('closed', 'stopped', 'target_hit')
              AND closed_at LIKE ?
            """,
            (f"{today}%",),
        ).fetchall()
        daily_pnl = sum(r["pnl"] or 0.0 for r in daily_rows)

    starting_bankroll = 100_000.0  # paper account starting equity
    total_pnl_percent = round(total_pnl / starting_bankroll * 100, 2)
    daily_pnl_percent = round(daily_pnl / starting_bankroll * 100, 2)
    win_rate_pct = round(win_rate * 100, 1)  # convert 0-1 → 0-100

    data = PortfolioData(
        equity=equity,
        total_pnl=total_pnl,
        total_pnl_percent=total_pnl_percent,
        win_rate=win_rate_pct,
        open_positions=open_count,
        daily_pnl=daily_pnl,
        daily_pnl_percent=daily_pnl_percent,
        mode="paper",
        trades_resolved=resolved,
        total_trades=total_trades,
        wins=wins,
        losses=losses,
    )
    return Envelope(data=data, meta=Meta(count=1))
