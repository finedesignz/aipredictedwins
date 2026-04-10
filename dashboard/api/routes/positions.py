"""
Position endpoints.

GET /api/positions/open   -- live open positions from Alpaca (both bots),
                             merged with SQLite for confluence score & opened_at
GET /api/positions/closed -- closed trade records from SQLite (both bots)
"""

import itertools
from fastapi import APIRouter, Query

from alpaca_client import get_open_positions
from db import get_db, get_db_b, query_both, rows_to_list
from models import ClosedPosition, Envelope, Meta, OpenPosition

router = APIRouter(prefix="/api/positions", tags=["positions"])


def _sqlite_open(db_ctx) -> dict[str, dict]:
    """Return a dict keyed by symbol of open SQLite records (for metadata)."""
    with db_ctx() as conn:
        rows = conn.execute(
            """
            SELECT id, timestamp, symbol, mirofish_prob, stop_loss
            FROM alpaca_trades
            WHERE status = 'open'
            ORDER BY timestamp DESC
            """
        ).fetchall()
    by_symbol: dict[str, dict] = {}
    for r in rows_to_list(rows):
        sym = r.get("symbol", "")
        if sym not in by_symbol:
            by_symbol[sym] = r
    return by_symbol


@router.get("/open", response_model=Envelope[list[OpenPosition]])
def get_open_positions_live():
    """Return live open positions from Alpaca merged with SQLite metadata."""
    # Fetch live positions from both Alpaca accounts
    alpaca_a = get_open_positions("a")
    alpaca_b = get_open_positions("b")

    # Fetch SQLite metadata for confluence score + opened_at
    sqlite_a = _sqlite_open(get_db)
    sqlite_b = _sqlite_open(get_db_b)

    data = []
    uid = itertools.count(1)  # synthetic id when SQLite record not found

    for bot_label, alpaca_positions, sqlite_meta in [
        ("Agent A", alpaca_a, sqlite_a),
        ("Agent B", alpaca_b, sqlite_b),
    ]:
        for pos in alpaca_positions:
            symbol = pos["symbol"]
            meta = sqlite_meta.get(symbol, {})
            prob = meta.get("mirofish_prob") or 0.0

            data.append(OpenPosition(
                id=meta.get("id") or next(uid),
                symbol=symbol,
                side=pos["side"],
                entry_price=pos["entry_price"],
                current_price=pos["current_price"],
                quantity=pos["qty"],
                unrealized_pnl=pos["unrealized_pnl"],
                unrealized_pnl_percent=pos["unrealized_pnl_percent"],
                confluence_score=round(prob * 5, 1),
                trailing_stop=meta.get("stop_loss"),
                opened_at=meta.get("timestamp") or "",
                bot=bot_label,
            ))

    # Sort by unrealized P&L descending (best positions first)
    data.sort(key=lambda p: p.unrealized_pnl, reverse=True)
    return Envelope(data=data, meta=Meta(count=len(data)))


@router.get("/closed", response_model=Envelope[list[ClosedPosition]])
def get_closed_positions(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Return closed positions with P&L from both bots (SQLite)."""
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
    rows.sort(key=lambda r: r.get("closed_at") or "", reverse=True)
    rows = rows[offset: offset + limit]
    return Envelope(data=rows, meta=Meta(count=len(rows)))
