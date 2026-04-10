"""
Position endpoints.

GET  /api/positions/open       -- open alpaca_trades with live Alpaca prices
GET  /api/positions/closed     -- closed alpaca_trades mapped to frontend field names
POST /api/positions/reconcile  -- sync DB open trades against Alpaca actual state
"""

import os
from datetime import datetime, timezone
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Query

from db import get_db
from models import Envelope, Meta, OpenPosition

router = APIRouter(prefix="/api/positions", tags=["positions"])

ALPACA_PAPER = "https://paper-api.alpaca.markets"
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


def _alpaca_open_symbols(api_key: str, secret_key: str) -> set[str]:
    """Return the set of symbols currently open in an Alpaca paper account."""
    if not api_key or not secret_key:
        return set()
    try:
        resp = httpx.get(
            f"{ALPACA_PAPER}/v2/positions",
            headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key},
            timeout=8.0,
        )
        if resp.status_code != 200:
            return set()
        positions = resp.json()
        if not isinstance(positions, list):
            return set()
        return {p.get("symbol", "") for p in positions}
    except Exception:
        return set()


@router.post("/reconcile")
def reconcile_positions():
    """Sync DB open trades against actual Alpaca paper account state.

    For every DB trade marked open where the symbol no longer exists in
    Alpaca, we mark it closed with the best-available price estimate.
    Returns a summary of what was reconciled.
    """
    # Load Alpaca keys for all known bots (A and B)
    bot_keys: dict[str, tuple[str, str]] = {}
    for bot_id in ("A", "B"):
        key = os.environ.get(f"ALPACA_API_KEY_{bot_id}", "")
        sec = os.environ.get(f"ALPACA_SECRET_KEY_{bot_id}", "")
        if key and sec:
            bot_keys[bot_id] = (key, sec)

    if not bot_keys:
        return Envelope(
            data={"reconciled": 0, "message": "No Alpaca API keys configured"},
            meta=Meta(),
        )

    # Fetch live open symbols per bot
    alpaca_open: dict[str, set[str]] = {
        bot_id: _alpaca_open_symbols(key, sec)
        for bot_id, (key, sec) in bot_keys.items()
    }

    # Fetch all DB-open trades
    with get_db() as conn:
        db_open = conn.execute(
            "SELECT id, bot_id, symbol, entry_price, qty, side FROM alpaca_trades WHERE status = 'open'"
        ).fetchall()

    if not db_open:
        return Envelope(
            data={"reconciled": 0, "message": "No open trades in DB to reconcile"},
            meta=Meta(),
        )

    # Find any valid keypair to look up current prices
    any_keys = next(iter(bot_keys.values())) if bot_keys else None

    def _latest_price(symbol: str) -> Optional[float]:
        if not any_keys:
            return None
        key, sec = any_keys
        try:
            resp = httpx.get(
                f"{ALPACA_DATA}/v1beta3/crypto/us/latest/bars",
                params={"symbols": symbol},
                headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec},
                timeout=5.0,
            )
            if resp.status_code == 200:
                bar = resp.json().get("bars", {}).get(symbol)
                if bar:
                    return float(bar.get("c", 0))
        except Exception:
            pass
        return None

    now_iso = datetime.now(timezone.utc).isoformat()
    reconciled = 0
    details = []

    with get_db() as conn:
        for trade in db_open:
            bot_id = trade.get("bot_id", "")
            symbol = trade.get("symbol", "")
            trade_id = trade.get("id")

            # If symbol is still open in this bot's Alpaca account → skip
            open_symbols = alpaca_open.get(bot_id, set())
            if bot_keys.get(bot_id) and symbol in open_symbols:
                continue

            # Symbol gone from Alpaca — estimate P&L from latest market price
            exit_price = _latest_price(symbol)
            entry_price = float(trade.get("entry_price") or 0)
            qty = float(trade.get("qty") or 0)
            side = (trade.get("side") or "buy").lower()

            if exit_price and entry_price and qty:
                pnl = round(
                    (exit_price - entry_price) * qty if side in ("buy", "long")
                    else (entry_price - exit_price) * qty,
                    4,
                )
            else:
                exit_price = None
                pnl = None

            conn.execute(
                """
                UPDATE alpaca_trades
                SET status = 'closed', exit_price = %s, pnl = %s, closed_at = %s,
                    notes = COALESCE(notes, '') || ' [reconciled]'
                WHERE id = %s
                """,
                (exit_price, pnl, now_iso, trade_id),
            )
            reconciled += 1
            details.append({
                "trade_id": trade_id,
                "symbol": symbol,
                "bot_id": bot_id,
                "exit_price": exit_price,
                "pnl": pnl,
            })

    return Envelope(
        data={
            "reconciled": reconciled,
            "message": f"Marked {reconciled} orphaned DB trade(s) as closed",
            "details": details,
        },
        meta=Meta(count=reconciled),
    )
