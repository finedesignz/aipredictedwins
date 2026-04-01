"""
Trade history endpoints.

GET /api/trades      -- all alpaca_trades with filtering
GET /api/trades/csv  -- CSV export of filtered trades
"""

import csv
import io
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from db import get_db, rows_to_list
from models import Envelope, Meta, TradeRecord

router = APIRouter(prefix="/api/trades", tags=["trades"])


def _build_trade_query(
    status: Optional[str],
    symbol: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    limit: int,
    offset: int,
) -> tuple[str, list]:
    """Build a parameterized query for alpaca_trades with filters."""
    clauses: list[str] = []
    params: list = []

    if status:
        clauses.append("status = ?")
        params.append(status)
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol)
    if date_from:
        clauses.append("timestamp >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("timestamp <= ?")
        params.append(date_to)

    where = ""
    if clauses:
        where = "WHERE " + " AND ".join(clauses)

    query = f"""
        SELECT id, timestamp, symbol, asset_class, side, qty,
               entry_price, exit_price, pnl, mirofish_prob,
               market_sentiment, target_price, stop_loss,
               status, closed_at, simulation_id, notes
        FROM alpaca_trades
        {where}
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])
    return query, params


@router.get("", response_model=Envelope[list[TradeRecord]])
def get_trades(
    status: Optional[str] = Query(None, description="Filter by status: open, closed, stopped, target_hit"),
    symbol: Optional[str] = Query(None, description="Filter by symbol, e.g. BTC/USD"),
    date_from: Optional[str] = Query(None, description="Start date (ISO format)"),
    date_to: Optional[str] = Query(None, description="End date (ISO format)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Return all alpaca trades with optional filtering and pagination."""
    query, params = _build_trade_query(status, symbol, date_from, date_to, limit, offset)
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    data = rows_to_list(rows)
    return Envelope(data=data, meta=Meta(count=len(data)))


@router.get("/csv")
def export_trades_csv(
    status: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(10000, ge=1, le=100000),
    offset: int = Query(0, ge=0),
):
    """Export filtered trades as a CSV file download."""
    query, params = _build_trade_query(status, symbol, date_from, date_to, limit, offset)
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()

    if not rows:
        return StreamingResponse(
            iter(["No trades found"]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=trades.csv"},
        )

    columns = rows[0].keys()
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow(dict(row))

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=trades.csv"},
    )
