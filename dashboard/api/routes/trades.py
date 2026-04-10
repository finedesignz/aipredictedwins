"""
Trade history endpoints.

GET /api/trades      -- all alpaca_trades from both bots with filtering
GET /api/trades/csv  -- CSV export of filtered trades
"""

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from db import get_db

router = APIRouter(prefix="/api/trades", tags=["trades"])


def _default_date_from() -> str:
    """Return ISO date string 30 days ago (default lookback)."""
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    return thirty_days_ago.strftime("%Y-%m-%d")


def _fetch_trades(
    bot: str,
    status: Optional[str],
    symbol: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    limit: int,
    offset: int,
) -> list[dict]:
    """Fetch trades from the unified Postgres table with optional bot/field filters."""
    clauses: list[str] = []
    params: list = []

    if bot in ("A", "B"):
        clauses.append("bot_id = %s")
        params.append(bot)
    if status:
        clauses.append("status = %s")
        params.append(status)
    if symbol:
        clauses.append("symbol = %s")
        params.append(symbol)
    if date_from:
        clauses.append("timestamp >= %s")
        params.append(date_from)
    if date_to:
        clauses.append("timestamp <= %s")
        params.append(date_to)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    query = f"""
        SELECT id, timestamp, symbol, asset_class, side, qty,
               entry_price, exit_price, pnl, mirofish_prob,
               market_sentiment, target_price, stop_loss,
               status, closed_at, simulation_id, notes, bot_id
        FROM alpaca_trades
        {where}
        ORDER BY timestamp DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()

    result = []
    for r in rows:
        r = dict(r)
        prob = r.get("mirofish_prob") or 0.0
        r["confluence_score"] = round(prob * 5, 1)
        r["quantity"] = r.get("qty") or 0.0
        entry = r.get("entry_price")
        exit_ = r.get("exit_price")
        if entry and exit_ and entry != 0:
            r["pnl_percent"] = round((exit_ - entry) / entry * 100, 4)
        else:
            r["pnl_percent"] = None
        r["close_reason"] = r.get("notes")
        raw_side = r.get("side", "buy") or "buy"
        r["side"] = "long" if raw_side.lower() in ("buy", "long") else "short"
        r["status"] = r.get("status") or "open"
        result.append(r)
    return result


@router.get("")
def get_trades(
    bot: Literal["A", "B", "both"] = Query("both"),
    status: Optional[str] = Query(None, description="Filter by status: open, closed, stopped, target_hit"),
    symbol: Optional[str] = Query(None, description="Filter by symbol, e.g. BTC/USD"),
    date_from: Optional[str] = Query(None, description="Start date (ISO format). Defaults to 30 days ago."),
    date_to: Optional[str] = Query(None, description="End date (ISO format)"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Return all alpaca trades with optional bot/field filtering and pagination."""
    effective_date_from = date_from if date_from else _default_date_from()
    rows = _fetch_trades(bot, status, symbol, effective_date_from, date_to, limit, offset)
    return {"data": rows, "meta": {"timestamp": datetime.now(timezone.utc).isoformat(), "count": len(rows)}}


@router.get("/csv")
def export_trades_csv(
    bot: Literal["A", "B", "both"] = Query("both"),
    status: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(10000, ge=1, le=100000),
    offset: int = Query(0, ge=0),
):
    """Export filtered trades as a CSV file download."""
    effective_date_from = date_from if date_from else _default_date_from()
    rows = _fetch_trades(bot, status, symbol, effective_date_from, date_to, limit, offset)

    if not rows:
        return StreamingResponse(
            iter(["No trades found"]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=trades.csv"},
        )

    columns = list(rows[0].keys())
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=trades.csv"},
    )
