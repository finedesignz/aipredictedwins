"""
Position endpoints.

GET /api/positions/open   -- all open alpaca_trades (both bots)
GET /api/positions/closed -- closed alpaca_trades with P&L (both bots)
"""

from fastapi import APIRouter, Query

from db import query_both
from models import (
    ClosedPosition,
    Envelope,
    Meta,
    OpenPosition,
)

router = APIRouter(prefix="/api/positions", tags=["positions"])


@router.get("/open", response_model=Envelope[list[OpenPosition]])
def get_open_positions():
    """Return all open positions from both bots, ordered by timestamp descending."""
    rows = query_both(
        """
        SELECT id, timestamp, symbol, side, qty,
               entry_price, mirofish_prob, stop_loss
        FROM alpaca_trades
        WHERE status = 'open'
        ORDER BY timestamp DESC
        """
    )
    # Sort combined by timestamp descending
    rows.sort(key=lambda r: r.get("timestamp") or "", reverse=True)

    data = []
    for r in rows:
        side = "long" if r.get("side", "buy").lower() in ("buy", "long") else "short"
        entry = r.get("entry_price") or 0.0
        prob = r.get("mirofish_prob") or 0.0
        data.append(OpenPosition(
            id=r["id"],
            symbol=r["symbol"],
            side=side,
            entry_price=entry,
            current_price=entry,
            quantity=r.get("qty") or 0.0,
            unrealized_pnl=0.0,
            unrealized_pnl_percent=0.0,
            confluence_score=round(prob * 5, 1),
            trailing_stop=r.get("stop_loss"),
            opened_at=r.get("timestamp") or "",
            bot=r.get("bot"),
        ))
    return Envelope(data=data, meta=Meta(count=len(data)))


@router.get("/closed", response_model=Envelope[list[ClosedPosition]])
def get_closed_positions(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Return closed positions with P&L from both bots."""
    rows = query_both(
        """
        SELECT id, timestamp, symbol, asset_class, side, qty,
               entry_price, exit_price, pnl, mirofish_prob,
               market_sentiment, target_price, stop_loss,
               status, closed_at, simulation_id, notes
        FROM alpaca_trades
        WHERE status IN ('closed', 'stopped', 'target_hit')
        ORDER BY closed_at DESC
        """
    )
    # Sort combined then apply pagination
    rows.sort(key=lambda r: r.get("closed_at") or "", reverse=True)
    rows = rows[offset: offset + limit]
    return Envelope(data=rows, meta=Meta(count=len(rows)))
