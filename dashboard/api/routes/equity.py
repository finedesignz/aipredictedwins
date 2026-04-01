"""Equity curve endpoint — computes daily equity from trade history."""

from datetime import datetime, timezone

from fastapi import APIRouter

from db import get_db, rows_to_list
from models import Envelope, Meta

router = APIRouter()


@router.get("/api/equity")
def get_equity():
    """Return equity curve data points from closed trade P&L history."""
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT closed_at, pnl
            FROM alpaca_trades
            WHERE status IN ('closed', 'stopped', 'target_hit')
              AND closed_at IS NOT NULL
            ORDER BY closed_at ASC
            """
        ).fetchall()
        rows = rows_to_list(rows)
    finally:
        conn.close()

    # Build cumulative equity curve
    starting_equity = 100000.0  # paper account start
    equity_points = []
    cumulative = starting_equity

    for row in rows:
        cumulative += row.get("pnl", 0) or 0
        equity_points.append({
            "timestamp": row.get("closed_at", ""),
            "equity": round(cumulative, 2),
        })

    # If no closed trades, return a single point with starting equity
    if not equity_points:
        equity_points.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "equity": starting_equity,
        })

    return Envelope(
        data=equity_points,
        meta=Meta(
            timestamp=datetime.now(timezone.utc).isoformat(),
            count=len(equity_points),
        ),
    )
