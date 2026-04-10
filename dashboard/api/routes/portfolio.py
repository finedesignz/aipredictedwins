"""
Portfolio summary endpoint.

GET /api/portfolio -- KPI summary driven by Alpaca live account data.

Equity, daily P&L, and open position count come from the Alpaca paper API
(real account state). Win rate and resolved trade counts come from the
SQLite trade log (Alpaca doesn't track win/loss history).
"""

from fastapi import APIRouter

from alpaca_client import get_account, get_daily_pnl, get_open_positions
from db import query_both
from models import Envelope, Meta, PortfolioData

router = APIRouter(prefix="/api", tags=["portfolio"])

_STARTING_BANKROLL_EACH = 100_000.0


@router.get("/portfolio", response_model=Envelope[PortfolioData])
def get_portfolio():
    """Return combined portfolio KPIs for both bots."""
    # ── Live Alpaca data ───────────────────────────────────────────────────
    acct_a = get_account("a")
    acct_b = get_account("b")

    equity_a = acct_a.get("equity", _STARTING_BANKROLL_EACH)
    equity_b = acct_b.get("equity", _STARTING_BANKROLL_EACH)
    equity = equity_a + equity_b

    total_starting = _STARTING_BANKROLL_EACH * 2
    total_pnl = equity - total_starting

    daily_pnl_a = get_daily_pnl("a")
    daily_pnl_b = get_daily_pnl("b")
    daily_pnl = daily_pnl_a + daily_pnl_b

    # Open positions: count from Alpaca (live, includes pre-volume trades)
    pos_a = get_open_positions("a")
    pos_b = get_open_positions("b")
    open_count = len(pos_a) + len(pos_b)

    # ── SQLite trade log for win-rate stats ────────────────────────────────
    closed_rows = query_both(
        """
        SELECT pnl FROM alpaca_trades
        WHERE status IN ('closed', 'stopped', 'target_hit')
        """
    )
    total_trades = len(query_both("SELECT id FROM alpaca_trades"))

    resolved = len(closed_rows)
    wins = sum(1 for r in closed_rows if (r.get("pnl") or 0) > 0)
    losses = resolved - wins
    win_rate = round((wins / resolved * 100) if resolved > 0 else 0.0, 1)

    # ── Compute percentages ────────────────────────────────────────────────
    total_pnl_percent = round(total_pnl / total_starting * 100, 2)
    daily_pnl_percent = round(daily_pnl / total_starting * 100, 2)

    data = PortfolioData(
        equity=round(equity, 2),
        total_pnl=round(total_pnl, 2),
        total_pnl_percent=total_pnl_percent,
        win_rate=win_rate,
        open_positions=open_count,
        daily_pnl=round(daily_pnl, 2),
        daily_pnl_percent=daily_pnl_percent,
        mode="paper",
        trades_resolved=resolved,
        total_trades=total_trades,
        wins=wins,
        losses=losses,
    )
    return Envelope(data=data, meta=Meta(count=1))
