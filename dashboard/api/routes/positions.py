"""
Position endpoints.

GET /api/positions/open    -- open alpaca_trades
GET /api/positions/closed  -- closed alpaca_trades with P&L
"""

from typing import Literal

from fastapi import APIRouter, Query

from db import get_db
from models import ClosedPosition, Envelope, Meta, OpenPosition

router = APIRouter(prefix="/api/positions", tags=["positions"])


@router.get("/open", response_model=Envelope[list[OpenPosition]])
def get_open_positions(bot: Literal["A", "B", "both"] = Query("both")):
    sql = """
        SELECT id, timestamp, symbol, side, qty,
               entry_price, mirofish_prob, stop_loss, bot_id
        FROM alpaca_trades
        WHERE status = 'open'
    """
    params: list = []
    if bot in ("A", "B"):
        sql += " AND bot_id = %s"
        params.append(bot)
    sql += " ORDER BY timestamp DESC"

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    data = []
    for r in rows:
        side = "long" if (r.get("side") or "buy").lower() in ("buy", "long") else "short"
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
            bot=r.get("bot_id"),
        ))
    return Envelope(data=data, meta=Meta(count=len(data)))


@router.get("/closed", response_model=Envelope[list[ClosedPosition]])
def get_closed_positions(
    bot: Literal["A", "B", "both"] = Query("both"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    sql = """
        SELECT id, timestamp, symbol, asset_class, side, qty,
               entry_price, exit_price, pnl, mirofish_prob,
               market_sentiment, target_price, stop_loss,
               status, closed_at, simulation_id, notes, bot_id
        FROM alpaca_trades
        WHERE status IN ('closed', 'stopped', 'target_hit')
    """
    params: list = []
    if bot in ("A", "B"):
        sql += " AND bot_id = %s"
        params.append(bot)
    sql += " ORDER BY closed_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    return Envelope(data=list(rows), meta=Meta(count=len(rows)))
