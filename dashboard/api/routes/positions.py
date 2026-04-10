"""
Position endpoints.

GET /api/positions/open   -- all open alpaca_trades
GET /api/positions/closed -- closed alpaca_trades with P&L
"""

from fastapi import APIRouter, Query

from db import get_db, rows_to_list
from models import (
    ClosedPosition,
    Envelope,
    Meta,
    OpenPosition,
)

router = APIRouter(prefix="/api/positions", tags=["positions"])


@router.get("/open", response_model=Envelope[list[OpenPosition]])
def get_open_positions():
    """Return all open positions ordered by timestamp descending."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, timestamp, symbol, side, qty,
                   entry_price, mirofish_prob, stop_loss
            FROM alpaca_trades
            WHERE status = 'open'
            ORDER BY timestamp DESC
            """
        ).fetchall()

    data = []
    for r in rows_to_list(rows):
        # Map DB fields to the frontend Position type
        side = "long" if r.get("side", "buy").lower() in ("buy", "long") else "short"
        entry = r.get("entry_price") or 0.0
        prob = r.get("mirofish_prob") or 0.0
        data.append(OpenPosition(
            id=r["id"],
            symbol=r["symbol"],
            side=side,
            entry_price=entry,
            current_price=entry,          # no live price in DB
            quantity=r.get("qty") or 0.0,
            unrealized_pnl=0.0,
            unrealized_pnl_percent=0.0,
            confluence_score=round(prob * 5, 1),
            trailing_stop=r.get("stop_loss"),
            opened_at=r.get("timestamp") or "",
        ))
    return Envelope(data=data, meta=Meta(count=len(data)))


@router.get("/closed", response_model=Envelope[list[ClosedPosition]])
def get_closed_positions(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Return closed positions with P&L, exit price, and close reason."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, timestamp, symbol, asset_class, side, qty,
                   entry_price, exit_price, pnl, mirofish_prob,
                   market_sentiment, target_price, stop_loss,
                   status, closed_at, simulation_id, notes
            FROM alpaca_trades
            WHERE status IN ('closed', 'stopped', 'target_hit')
            ORDER BY closed_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    data = rows_to_list(rows)
    return Envelope(data=data, meta=Meta(count=len(data)))
