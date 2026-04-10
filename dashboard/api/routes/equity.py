"""Equity curve endpoint — returns per-bot and combined equity series."""

from datetime import datetime, timezone

from fastapi import APIRouter

from db import get_db, get_db_b, rows_to_list
from models import Envelope, Meta

router = APIRouter()

_STARTING_EQUITY = 100_000.0  # each bot starts at $100k


def _build_curve(conn, label: str) -> list[dict]:
    """Build cumulative equity curve for one bot's DB connection."""
    rows = conn.execute(
        """
        SELECT closed_at, pnl
        FROM alpaca_trades
        WHERE status IN ('closed', 'stopped', 'target_hit')
          AND closed_at IS NOT NULL
        ORDER BY closed_at ASC
        """
    ).fetchall()
    rows = rows_to_list(rows)

    points = []
    cumulative = _STARTING_EQUITY
    for row in rows:
        cumulative += row.get("pnl", 0) or 0
        points.append({
            "timestamp": row.get("closed_at", ""),
            "equity": round(cumulative, 2),
            "bot": label,
        })

    if not points:
        points.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "equity": _STARTING_EQUITY,
            "bot": label,
        })
    return points


@router.get("/api/equity")
def get_equity():
    """Return equity data for both bots as {agentA: [...], agentB: [...], combined: [...]}."""
    with get_db() as conn:
        a_points = _build_curve(conn, "Agent A")
    with get_db_b() as conn:
        b_points = _build_curve(conn, "Agent B")

    # Build combined curve (merge & sort all closed trades, track total)
    all_closed = []
    with get_db() as conn:
        for row in rows_to_list(conn.execute(
            "SELECT closed_at, pnl FROM alpaca_trades WHERE status IN ('closed','stopped','target_hit') AND closed_at IS NOT NULL ORDER BY closed_at ASC"
        ).fetchall()):
            row["src"] = "a"
            all_closed.append(row)
    with get_db_b() as conn:
        for row in rows_to_list(conn.execute(
            "SELECT closed_at, pnl FROM alpaca_trades WHERE status IN ('closed','stopped','target_hit') AND closed_at IS NOT NULL ORDER BY closed_at ASC"
        ).fetchall()):
            row["src"] = "b"
            all_closed.append(row)

    all_closed.sort(key=lambda r: r.get("closed_at") or "")
    combined_points = []
    cumulative = _STARTING_EQUITY * 2  # $200k combined
    for row in all_closed:
        cumulative += row.get("pnl", 0) or 0
        combined_points.append({
            "timestamp": row.get("closed_at", ""),
            "equity": round(cumulative, 2),
        })

    if not combined_points:
        combined_points.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "equity": _STARTING_EQUITY * 2,
        })

    data = {
        "agentA": a_points,
        "agentB": b_points,
        "combined": combined_points,
    }

    return Envelope(
        data=data,
        meta=Meta(
            timestamp=datetime.now(timezone.utc).isoformat(),
            count=len(combined_points),
        ),
    )
