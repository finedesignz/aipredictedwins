"""
Position endpoints.

GET /api/positions/open    -- open alpaca_trades with live Alpaca prices
GET /api/positions/closed  -- closed alpaca_trades mapped to frontend field names
"""

import os
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Query

from db import get_db
from models import Envelope, Meta, OpenPosition

router = APIRouter(prefix="/api/positions", tags=["positions"])

ALPACA_DATA = "https://data.alpaca.markets"


def _fetch_latest_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch latest crypto bar close prices from Alpaca.

    Tries bot A keys first, then bot B. Returns {symbol: close_price}.
    """
    if not symbols:
        return {}
    for bot_id in ("A", "B"):
        key = os.environ.get(f"ALPACA_API_KEY_{bot_id}", "")
        sec = os.environ.get(f"ALPACA_SECRET_KEY_{bot_id}", "")
        if not key or not sec:
            continue
        try:
            resp = httpx.get(
                f"{ALPACA_DATA}/v1beta3/crypto/us/latest/bars",
                params={"symbols": ",".join(symbols)},
                headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec},
                timeout=5.0,
            )
            if resp.status_code == 200:
                bars = resp.json().get("bars", {})
                return {sym: float(bar["c"]) for sym, bar in bars.items() if "c" in bar}
        except Exception:
            continue
    return {}


def _iso(val) -> str:
    """Convert a datetime or string to ISO string; empty string if None."""
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


@router.get("/open")
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

    if not rows:
        return Envelope(data=[], meta=Meta(count=0))

    # Fetch live prices for all unique symbols
    symbols = list({r["symbol"] for r in rows})
    live_prices = _fetch_latest_prices(symbols)

    data = []
    for r in rows:
        side = "long" if (r.get("side") or "buy").lower() in ("buy", "long") else "short"
        entry = float(r.get("entry_price") or 0.0)
        current = live_prices.get(r["symbol"], entry)
        qty = float(r.get("qty") or 0.0)
        prob = float(r.get("mirofish_prob") or 0.0)

        unrealized_pnl = (current - entry) * qty if side == "long" else (entry - current) * qty
        unrealized_pnl_pct = ((current - entry) / entry * 100) if entry > 0 else 0.0
        if side == "short":
            unrealized_pnl_pct = -unrealized_pnl_pct

        data.append(OpenPosition(
            id=r["id"],
            symbol=r["symbol"],
            side=side,
            entry_price=entry,
            current_price=current,
            quantity=qty,
            unrealized_pnl=round(unrealized_pnl, 4),
            unrealized_pnl_percent=round(unrealized_pnl_pct, 4),
            confluence_score=round(prob * 5),
            trailing_stop=r.get("stop_loss"),
            opened_at=_iso(r.get("timestamp")),
            bot=r.get("bot_id"),
        ))

    return Envelope(data=data, meta=Meta(count=len(data)))


@router.get("/closed")
def get_closed_positions(
    bot: Literal["A", "B", "both"] = Query("both"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    sql = """
        SELECT id, timestamp, symbol, side, qty,
               entry_price, exit_price, pnl, mirofish_prob,
               notes, status, closed_at, bot_id
        FROM alpaca_trades
        WHERE status IN ('closed', 'stopped', 'target_hit')
    """
    params: list = []
    if bot in ("A", "B"):
        sql += " AND bot_id = %s"
        params.append(bot)
    sql += " ORDER BY closed_at DESC NULLS LAST LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    data = []
    for r in rows:
        entry = float(r.get("entry_price") or 0.0)
        exit_p = float(r.get("exit_price") or 0.0)
        qty = float(r.get("qty") or 0.0)
        pnl = float(r.get("pnl") or 0.0)
        prob = float(r.get("mirofish_prob") or 0.0)
        cost = entry * qty
        pnl_pct = (pnl / cost * 100) if cost != 0 else 0.0
        side_raw = (r.get("side") or "buy").lower()
        side = "long" if side_raw in ("buy", "long") else "short"

        data.append({
            "id": r["id"],
            "symbol": r["symbol"],
            "side": side,
            "entry_price": entry,
            "exit_price": exit_p,
            "quantity": qty,
            "realized_pnl": round(pnl, 4),
            "realized_pnl_percent": round(pnl_pct, 4),
            "confluence_score": round(prob * 5),
            "close_reason": r.get("notes") or r.get("status") or "closed",
            "opened_at": _iso(r.get("timestamp")),
            "closed_at": _iso(r.get("closed_at")),
            "bot": r.get("bot_id"),
        })

    return Envelope(data=data, meta=Meta(count=len(data)))
