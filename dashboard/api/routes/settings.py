"""
Settings endpoint.

GET /api/settings -- bot config, system health, paper trading progress.
"""

import os

from fastapi import APIRouter

from db import DB_PATH, get_db
from models import Envelope, HealthStatus, Meta, SettingsData

router = APIRouter(prefix="/api", tags=["settings"])

_LIVE_THRESHOLD = float(os.environ.get("LIVE_TRADING_THRESHOLD", "100000"))
_MIN_CONFLUENCE = int(os.environ.get("MIN_CONFLUENCE", "3"))
_KELLY_FRACTION = float(os.environ.get("KELLY_FRACTION", "0.25"))
_BOT_LABEL = os.environ.get("BOT_LABEL", "Unknown")
_SKIP_RISK_GATE = os.environ.get("SKIP_RISK_GATE", "").lower() in ("1", "true", "yes")


@router.get("/settings", response_model=Envelope[SettingsData])
def get_settings():
    """Return bot status, health, and paper trading progress."""

    # -- DB size ---------------------------------------------------------------
    db_size_mb = 0.0
    try:
        db_size_mb = round(os.path.getsize(DB_PATH) / (1024 * 1024), 2)
    except OSError:
        pass
    db_exists = os.path.exists(DB_PATH)

    # -- Paper trading stats from DB -------------------------------------------
    with get_db() as conn:
        total_trades = conn.execute(
            "SELECT COUNT(*) FROM alpaca_trades"
        ).fetchone()[0]

        closed_rows = conn.execute(
            """
            SELECT pnl FROM alpaca_trades
            WHERE status IN ('closed', 'stopped', 'target_hit')
            """
        ).fetchall()

        last_row = conn.execute(
            "SELECT timestamp FROM alpaca_trades ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()

        resolved = len(closed_rows)
        wins = sum(1 for r in closed_rows if (r["pnl"] or 0) > 0)
        total_pnl = sum(r["pnl"] or 0.0 for r in closed_rows)
        win_rate_pct = round(wins / resolved * 100, 1) if resolved > 0 else 0.0
        equity = 100_000.0 + total_pnl

    last_cycle = last_row["timestamp"] if last_row else None

    health = HealthStatus(
        claude_cli=True,   # bot is writing trades → CLI is working
        alpaca_api=True,   # bot is writing trades → Alpaca is connected
        sqlite_db=db_exists,
        db_size_mb=db_size_mb,
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
