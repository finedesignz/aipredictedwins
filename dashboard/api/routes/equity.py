"""
Equity curve endpoint.

GET /api/equity?bot=A|B|both&days=30

Primary source: Alpaca portfolio history (ALPACA_API_KEY_A/B env vars).
Fallback: cumulative closed-trade P&L from the database (used when
Alpaca keys are missing or the API is unreachable).
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Query

from db import get_db
from models import Envelope, EquityPoint, EquitySeries, Meta

router = APIRouter()

_ALPACA_BASE = "https://paper-api.alpaca.markets"
_DEFAULT_STARTING_EQUITY = 100_000.0


# ── Alpaca portfolio history ────────────────────────────────────────────────

def _fetch_alpaca_series(api_key: str, secret_key: str, days: int, bot_id: str) -> EquitySeries | None:
    """Fetch daily equity from Alpaca and return a normalised EquitySeries.

    Returns None if the fetch fails or keys are absent.
    """
    if not api_key or not secret_key:
        return None

    url = (
        f"{_ALPACA_BASE}/v2/account/portfolio/history"
        f"?period={days}D&timeframe=1D&extended_hours=false"
    )
    req = urllib.request.Request(
        url,
        headers={
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None

    timestamps = data.get("timestamp", [])
    equity_values = data.get("equity", [])

    if not timestamps or not equity_values:
        return None

    # Find the first non-zero value to use as the baseline
    baseline = next((float(e) for e in equity_values if e), None)
    if baseline is None:
        return None

    points: list[EquityPoint] = []
    for ts, eq in zip(timestamps, equity_values):
        if not eq:
            continue
        eq = float(eq)
        day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        return_pct = round((eq - baseline) / baseline * 100, 4)
        points.append(EquityPoint(
            timestamp=f"{day}T00:00:00+00:00",
            equity=round(eq, 2),
            return_pct=return_pct,
            bot_id=bot_id,
        ))

    if not points:
        return None

    return EquitySeries(bot_id=bot_id, points=points)


# ── Database fallback ────────────────────────────────────────────────────────

def _build_db_series(conn, bot_id: str) -> EquitySeries:
    """Build equity series from cumulative closed-trade P&L in the database."""
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

    points: list[EquityPoint] = []
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


# ── Route ────────────────────────────────────────────────────────────────────

@router.get("/api/equity")
def get_equity(
    bot: Literal["A", "B", "both"] = Query("both"),
    days: int = Query(30, ge=1, le=90),
):
    """Return equity series. Primary: Alpaca portfolio history. Fallback: DB."""
    bot_ids = ["A", "B"] if bot == "both" else [bot]

    series = []
    for bot_id in bot_ids:
        key = os.environ.get(f"ALPACA_API_KEY_{bot_id}", "")
        sec = os.environ.get(f"ALPACA_SECRET_KEY_{bot_id}", "")

        alpaca_series = _fetch_alpaca_series(key, sec, days, bot_id)

        if alpaca_series is not None:
            series.append(alpaca_series.model_dump())
        else:
            with get_db() as conn:
                series.append(_build_db_series(conn, bot_id).model_dump())

    return Envelope(data={"series": series}, meta=Meta())
