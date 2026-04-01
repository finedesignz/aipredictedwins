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

        # Equity = starting bankroll (1000) + total realized P&L
        # Unrealized P&L not included since we don't have live prices
        equity = 1000.0 + total_pnl

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

    data = PortfolioData(
        equity=equity,
        total_pnl=total_pnl,
        win_rate=win_rate,
        open_positions=open_count,
        daily_pnl=daily_pnl,
        trades_resolved=resolved,
        total_trades=total_trades,
        wins=wins,
        losses=losses,
    )
    return Envelope(data=data, meta=Meta(count=1))
