"""
Activity stream endpoint (Server-Sent Events).

GET /api/activity/stream -- SSE endpoint polling Postgres every 5 seconds.
GET /api/activity/recent -- Polling alternative returning recent activity as JSON.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from db import get_db

router = APIRouter(prefix="/api/activity", tags=["activity"])
POLL_INTERVAL = 5


async def _fetch_activity(since: str) -> dict:
    """Run DB queries in a thread to avoid blocking the async event loop."""
    def _sync():
        with get_db() as conn:
            trades = conn.execute(
                """
                SELECT id, timestamp, symbol, side, qty, entry_price, status, bot_id
                FROM alpaca_trades
                WHERE timestamp > %s
                ORDER BY timestamp ASC
                """,
                (since,),
            ).fetchall()
            closed = conn.execute(
                """
                SELECT id, symbol, side, qty, entry_price, exit_price, pnl,
                       status, closed_at, bot_id
                FROM alpaca_trades
                WHERE closed_at > %s
                  AND status IN ('closed', 'stopped', 'target_hit')
                ORDER BY closed_at ASC
                """,
                (since,),
            ).fetchall()
            vals = conn.execute(
                """
                SELECT id, timestamp, kalshi_ticker, decision, veto_reason,
                       risk_assessment, confidence, bot_id
                FROM validations
                WHERE timestamp > %s
                ORDER BY timestamp ASC
                """,
                (since,),
            ).fetchall()
        return {
            "trades": [dict(r) for r in trades],
            "closed": [dict(r) for r in closed],
            "validations": [dict(r) for r in vals],
        }

    return await asyncio.to_thread(_sync)


async def _event_generator():
    """Poll the database and yield SSE events for new activity."""
    last_check = datetime.now(timezone.utc).isoformat()

    yield {
        "event": "heartbeat",
        "data": json.dumps({"type": "heartbeat", "timestamp": last_check}),
    }

    while True:
        await asyncio.sleep(POLL_INTERVAL)
        now = datetime.now(timezone.utc).isoformat()

        try:
            activity = await _fetch_activity(last_check)

            for trade in activity["trades"]:
                yield {
                    "event": "trade_placed",
                    "data": json.dumps({
                        "type": "trade_placed",
                        "data": trade,
                        "timestamp": trade.get("timestamp", now),
                    }),
                }

            for pos in activity["closed"]:
                yield {
                    "event": "trade_closed",
                    "data": json.dumps({
                        "type": "trade_closed",
                        "data": pos,
                        "timestamp": pos.get("closed_at", now),
                    }),
                }

            for val in activity["validations"]:
                yield {
                    "event": "risk_decision",
                    "data": json.dumps({
                        "type": "risk_decision",
                        "data": val,
                        "timestamp": val.get("timestamp", now),
                    }),
                }
        except Exception:
            pass

        last_check = now


@router.get("/stream")
async def activity_stream():
    """SSE endpoint for live activity feed.

    Polls the database every 5 seconds and pushes events for:
    - trade_placed: new trade entered
    - trade_closed: position closed with P&L
    - risk_decision: PROCEED/VETO from the risk gate
    """
    return EventSourceResponse(_event_generator())


@router.get("/recent")
def activity_recent(since: str = "", limit: int = 50):
    """Polling alternative to SSE — returns recent activity events as JSON.

    since: ISO timestamp string; only events after this time are returned.
           Omit to get the last `limit` events regardless of time.
    limit: max events to return (default 50, capped at 200).
    """
    limit = min(limit, 200)
    now = datetime.now(timezone.utc).isoformat()

    if not since:
        since_dt = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    else:
        since_dt = since

    events: list[dict] = []
    try:
        with get_db() as conn:
            trades = conn.execute(
                """
                SELECT id, timestamp, symbol, side, qty, entry_price, status, bot_id
                FROM alpaca_trades
                WHERE timestamp > %s
                ORDER BY timestamp ASC
                """,
                (since_dt,),
            ).fetchall()
            closed = conn.execute(
                """
                SELECT id, symbol, side, qty, entry_price, exit_price, pnl,
                       status, closed_at, bot_id
                FROM alpaca_trades
                WHERE closed_at > %s
                  AND status IN ('closed', 'stopped', 'target_hit')
                ORDER BY closed_at ASC
                """,
                (since_dt,),
            ).fetchall()

        for t in trades:
            events.append({
                "id": f"trade_{t['id']}",
                "type": "trade_placed",
                "message": f"Opened {(t.get('side') or 'buy').upper()} {t.get('qty')} {t.get('symbol')} @ ${(t.get('entry_price') or 0):.2f}",
                "detail": None,
                "timestamp": t.get("timestamp", now),
            })

        for p in closed:
            pnl = p.get("pnl") or 0
            sign = "+" if pnl >= 0 else ""
            events.append({
                "id": f"closed_{p['id']}",
                "type": "trade_closed",
                "message": f"Closed {p.get('symbol')} ({p.get('status')}) P&L {sign}${pnl:.2f}",
                "detail": None,
                "timestamp": p.get("closed_at", now),
            })
    except Exception:
        pass

    events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
    events = events[:limit]

    return {"data": events, "meta": {"count": len(events), "timestamp": now}}
