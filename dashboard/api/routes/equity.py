"""
Equity curve endpoint.

GET /api/equity?bot=A|B|both
Returns per-bot equity series with return_pct.
"""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Query

from db import get_db
from models import Envelope, EquityPoint, EquitySeries, Meta

router = APIRouter()

_DEFAULT_STARTING_EQUITY = 100_000.0


def _build_series(conn, bot_id: str) -> EquitySeries:
    bot_row = conn.execute(
        "SELECT starting_equity FROM bots WHERE id = %s", (bot_id,)
    ).fetchone()
    starting_equity = bot_row["starting_equity"] if bot_row else _DEFAULT_STARTING_EQUITY

    rows = conn.execute(
        """
        SELECT closed_at, pnl FROM alpaca_trades
        WHERE bot_id = %s
          AND status IN ('closed', 'stopped', 'target_hit')
          AND closed_at IS NOT NULL
        ORDER BY closed_at ASC
        """,
        (bot_id,),
    ).fetchall()

    points = []
    cumulative = starting_equity
    for r in rows:
        cumulative += r["pnl"] or 0
        return_pct = round((cumulative - starting_equity) / starting_equity * 100, 4)
        points.append(EquityPoint(
            timestamp=r["closed_at"],
            equity=round(cumulative, 2),
            return_pct=return_pct,
            bot_id=bot_id,
        ))

    if not points:
        points.append(EquityPoint(
            timestamp=datetime.now(timezone.utc).isoformat(),
            equity=starting_equity,
            return_pct=0.0,
            bot_id=bot_id,
        ))

    return EquitySeries(bot_id=bot_id, points=points)


@router.get("/api/equity")
def get_equity(bot: Literal["A", "B", "both"] = Query("both")):
    """Return equity series. bot=both returns two series."""
    with get_db() as conn:
        if bot == "both":
            series = [
                _build_series(conn, "A").model_dump(),
                _build_series(conn, "B").model_dump(),
            ]
        else:
            series = [_build_series(conn, bot).model_dump()]

    return Envelope(data={"series": series}, meta=Meta())
