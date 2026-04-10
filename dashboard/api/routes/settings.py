"""
Settings endpoint.
GET /api/settings?bot=A|B|both
"""

import os
from typing import Literal

from fastapi import APIRouter, Query

from db import get_db
from models import Envelope, HealthStatus, Meta, SettingsData
from alpaca import get_account_health

router = APIRouter(prefix="/api", tags=["settings"])

_LIVE_THRESHOLD = float(os.environ.get("LIVE_TRADING_THRESHOLD", "100000"))
_MIN_CONFLUENCE = int(os.environ.get("MIN_CONFLUENCE", "3"))
_KELLY_FRACTION = float(os.environ.get("KELLY_FRACTION", "0.25"))
_BOT_LABEL = os.environ.get("BOT_LABEL", "Unknown")
_SKIP_RISK_GATE = os.environ.get("SKIP_RISK_GATE", "").lower() in ("1", "true", "yes")


@router.get("/settings", response_model=Envelope[SettingsData])
def get_settings(bot: Literal["A", "B", "both"] = Query("both")):
    # Build bot_id filter
    bot_ids = ["A", "B"] if bot == "both" else [bot]

    with get_db() as conn:
        # Total trades
        if bot == "both":
            total_trades = conn.execute(
                "SELECT COUNT(*) AS n FROM alpaca_trades WHERE bot_id IN ('A','B')"
            ).fetchone()["n"]
        else:
            total_trades = conn.execute(
                "SELECT COUNT(*) AS n FROM alpaca_trades WHERE bot_id = %s", (bot,)
            ).fetchone()["n"]

        # Closed trades
        if bot == "both":
            closed_rows = conn.execute(
                """SELECT pnl FROM alpaca_trades
                   WHERE bot_id IN ('A','B')
                     AND status IN ('closed', 'stopped', 'target_hit')"""
            ).fetchall()
        else:
            closed_rows = conn.execute(
                """SELECT pnl FROM alpaca_trades
                   WHERE bot_id = %s
                     AND status IN ('closed', 'stopped', 'target_hit')""",
                (bot,),
            ).fetchall()

        # Last cycle
        if bot == "both":
            last_row = conn.execute(
                "SELECT timestamp FROM alpaca_trades ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
        else:
            last_row = conn.execute(
                "SELECT timestamp FROM alpaca_trades WHERE bot_id = %s ORDER BY timestamp DESC LIMIT 1",
                (bot,),
            ).fetchone()

    resolved = len(closed_rows)
    wins = sum(1 for r in closed_rows if (r["pnl"] or 0) > 0)
    total_pnl = sum(r["pnl"] or 0.0 for r in closed_rows)
    win_rate_pct = round(wins / resolved * 100, 1) if resolved > 0 else 0.0
    equity = 100_000.0 * len(bot_ids) + total_pnl
    last_cycle = last_row["timestamp"] if last_row else None

    # Health checks
    alpaca_status = get_account_health()
    try:
        with get_db() as conn:
            conn.execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False

    health = HealthStatus(
        claude_cli=True,
        alpaca_api=(alpaca_status in ("ok", "unknown")),
        database=db_ok,
        db_size_mb=0.0,
    )

    data = SettingsData(
        mode="paper",
        running=True,
        last_cycle=last_cycle,
        uptime_seconds=0,
        cycle_count=0,
        paper_trades_completed=total_trades,
        paper_trades_target=50,
        win_rate=win_rate_pct,
        win_rate_target=40.0,
        equity=equity,
        equity_target=_LIVE_THRESHOLD,
        health=health,
        config={
            "bot_label": _BOT_LABEL,
            "min_confluence": _MIN_CONFLUENCE,
            "kelly_fraction": _KELLY_FRACTION,
            "skip_risk_gate": _SKIP_RISK_GATE,
            "max_position_pct": 0.05,
            "hard_stop_pct": -0.04,
            "hard_take_profit_pct": 0.10,
            "soft_stop_pct": -0.02,
            "asset_universe": "BTC/ETH/SOL/XRP/ADA/AVAX/DOT/LINK",
        },
    )
    return Envelope(data=data, meta=Meta(count=1))
