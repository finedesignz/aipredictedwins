"""
Portfolio summary endpoint.

GET /api/portfolio -- KPI summary: equity, P&L, win rate, positions, daily P&L.
Aggregates data from both Bot A and Bot B databases.
"""

from datetime import datetime, timezone

from fastapi import APIRouter

from db import query_both, get_db, get_db_b
from models import Envelope, Meta, PortfolioData

router = APIRouter(prefix="/api", tags=["portfolio"])

_STARTING_BANKROLL_EACH = 100_000.0  # each bot starts with $100k paper account


@router.get("/portfolio", response_model=Envelope[PortfolioData])
def get_portfolio():
    """Return combined portfolio KPIs from both Bot A and Bot B."""
    # Open position count — sum from both bots
    open_count = 0
    total_trades = 0
    for db_ctx in (get_db, get_db_b):
        with db_ctx() as conn:
            open_count += conn.execute(
                "SELECT COUNT(*) FROM alpaca_trades WHERE status = 'open'"
            ).fetchone()[0]
            total_trades += conn.execute(
                "SELECT COUNT(*) FROM alpaca_trades"
            ).fetchone()[0]

    # Closed trades aggregated from both bots
    closed_rows = query_both(
        """
        SELECT status, pnl FROM alpaca_trades
        WHERE status IN ('closed', 'stopped', 'target_hit')
        """
    )

    resolved = len(closed_rows)
    wins = sum(1 for r in closed_rows if (r.get("pnl") or 0) > 0)
    losses = sum(1 for r in closed_rows if (r.get("pnl") or 0) <= 0)
    total_pnl = sum(r.get("pnl") or 0.0 for r in closed_rows)
    win_rate = wins / resolved if resolved > 0 else 0.0

    # Combined equity: both bots start at $100k each
    total_starting = _STARTING_BANKROLL_EACH * 2  # $200k combined
    equity = total_starting + total_pnl

    # Daily P&L — trades closed today from both bots
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_rows = query_both(
        """
        SELECT pnl FROM alpaca_trades
        WHERE status IN ('closed', 'stopped', 'target_hit')
          AND closed_at LIKE ?
        """,
        (f"{today}%",),
    )
    daily_pnl = sum(r.get("pnl") or 0.0 for r in daily_rows)

    total_pnl_percent = round(total_pnl / total_starting * 100, 2)
    daily_pnl_percent = round(daily_pnl / total_starting * 100, 2)
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
