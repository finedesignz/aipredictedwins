"""
Activity stream endpoint (Server-Sent Events).

GET /api/activity/stream -- SSE endpoint that polls the database every 5
seconds for new trades, closed positions, and risk gate decisions. Yields
SSE events with type and data fields.
"""

import asyncio
import json
import sqlite3
import os
from datetime import datetime, timezone

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from db import DB_PATH

router = APIRouter(prefix="/api/activity", tags=["activity"])

# Polling interval in seconds
POLL_INTERVAL = 5


def _get_readonly_conn() -> sqlite3.Connection:
    """Get a read-only SQLite connection for the SSE polling loop.

    Uses a fresh connection per poll cycle rather than holding one open
    across the entire SSE session, since SSE connections can be long-lived.
    """
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA query_only=ON")
    return conn


def _fetch_new_trades(conn: sqlite3.Connection, since: str) -> list[dict]:
    """Fetch alpaca_trades created after the given ISO timestamp."""
    rows = conn.execute(
        """
        SELECT id, timestamp, symbol, side, qty, entry_price, status
        FROM alpaca_trades
        WHERE timestamp > ?
        ORDER BY timestamp ASC
        """,
        (since,),
    ).fetchall()
    return [dict(r) for r in rows]


def _fetch_closed_positions(conn: sqlite3.Connection, since: str) -> list[dict]:
    """Fetch alpaca_trades closed after the given ISO timestamp."""
    rows = conn.execute(
        """
        SELECT id, symbol, side, qty, entry_price, exit_price, pnl,
               status, closed_at
        FROM alpaca_trades
        WHERE closed_at > ?
          AND status IN ('closed', 'stopped', 'target_hit')
        ORDER BY closed_at ASC
        """,
        (since,),
    ).fetchall()
    return [dict(r) for r in rows]


def _fetch_new_validations(conn: sqlite3.Connection, since: str) -> list[dict]:
    """Fetch validations created after the given ISO timestamp."""
    rows = conn.execute(
        """
        SELECT id, timestamp, kalshi_ticker, decision, veto_reason,
               risk_assessment, confidence
        FROM validations
        WHERE timestamp > ?
        ORDER BY timestamp ASC
        """,
        (since,),
    ).fetchall()
    return [dict(r) for r in rows]


async def _event_generator():
    """Poll the database and yield SSE events for new activity."""
    # Start watching from now
    last_check = datetime.now(timezone.utc).isoformat()

    # Send an initial heartbeat so the client knows the connection is alive
    yield {
        "event": "heartbeat",
        "data": json.dumps({
            "type": "heartbeat",
            "timestamp": last_check,
        }),
    }

    while True:
        await asyncio.sleep(POLL_INTERVAL)

        now = datetime.now(timezone.utc).isoformat()

        try:
            conn = _get_readonly_conn()
            try:
                # Check for new trades (opened)
                new_trades = _fetch_new_trades(conn, last_check)
                for trade in new_trades:
                    yield {
                        "event": "trade_placed",
                        "data": json.dumps({
                            "type": "trade_placed",
                            "data": trade,
                            "timestamp": trade.get("timestamp", now),
                        }),
                    }

                # Check for closed positions
                closed = _fetch_closed_positions(conn, last_check)
                for pos in closed:
                    yield {
                        "event": "trade_closed",
                        "data": json.dumps({
                            "type": "trade_closed",
                            "data": pos,
                            "timestamp": pos.get("closed_at", now),
                        }),
                    }

                # Check for new risk gate decisions
                validations = _fetch_new_validations(conn, last_check)
                for val in validations:
                    yield {
                        "event": "risk_decision",
                        "data": json.dumps({
                            "type": "risk_decision",
                            "data": val,
                            "timestamp": val.get("timestamp", now),
                        }),
                    }
            finally:
                conn.close()
        except Exception:
            # If the database is temporarily unavailable, skip this cycle
            # and try again next interval. Do not crash the SSE stream.
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

    events: list[dict] = []
    try:
        conn = _get_readonly_conn()
        try:
            # Anchor: if no since, look back 24 h so the feed isn't empty on first load
            if not since:
                from datetime import timedelta
                since_dt = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            else:
                since_dt = since

            trades = _fetch_new_trades(conn, since_dt)
            for t in trades:
                events.append({
                    "id": f"trade_{t['id']}",
                    "type": "trade_placed",
                    "message": f"Opened {t['side'].upper()} {t['qty']} {t['symbol']} @ ${t['entry_price']:.2f}",
                    "detail": None,
                    "timestamp": t.get("timestamp", now),
                })

            closed = _fetch_closed_positions(conn, since_dt)
            for p in closed:
                pnl = p.get("pnl") or 0
                sign = "+" if pnl >= 0 else ""
                events.append({
                    "id": f"closed_{p['id']}",
                    "type": "trade_closed",
                    "message": f"Closed {p['symbol']} ({p['status']}) P&L {sign}${pnl:.2f}",
                    "detail": None,
                    "timestamp": p.get("closed_at", now),
                })
        finally:
            conn.close()
    except Exception:
        pass

    # Sort newest-first, cap to limit
    events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
    events = events[:limit]

    return {"data": events, "meta": {"count": len(events), "timestamp": now}}
