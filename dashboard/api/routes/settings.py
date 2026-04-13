"""
Settings endpoint.
GET /api/settings?bot=A|B|both
"""

import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Query, Request

from db import get_db
from models import Envelope, HealthStatus, Meta, SettingsData
from alpaca_health import get_account_health

router = APIRouter(prefix="/api", tags=["settings"])

_LIVE_THRESHOLD = float(os.environ.get("LIVE_TRADING_THRESHOLD", "100000"))


@router.get("/settings", response_model=Envelope[SettingsData])
def get_settings(
    request: Request,
    bot: Literal["A", "B", "both"] = Query("both"),
):
    bot_ids = ["A", "B"] if bot == "both" else [bot]

    with get_db() as conn:
        # Total and closed trades
        if bot == "both":
            total_trades = conn.execute(
                "SELECT COUNT(*) AS n FROM alpaca_trades WHERE bot_id IN ('A','B')"
            ).fetchone()["n"]
            closed_rows = conn.execute(
                """SELECT pnl FROM alpaca_trades
                   WHERE bot_id IN ('A','B')
                     AND status IN ('closed', 'stopped', 'target_hit')"""
            ).fetchall()
            last_row = conn.execute(
                "SELECT timestamp FROM alpaca_trades ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
        else:
            total_trades = conn.execute(
                "SELECT COUNT(*) AS n FROM alpaca_trades WHERE bot_id = %s", (bot,)
            ).fetchone()["n"]
            closed_rows = conn.execute(
                """SELECT pnl FROM alpaca_trades
                   WHERE bot_id = %s
                     AND status IN ('closed', 'stopped', 'target_hit')""",
                (bot,),
            ).fetchall()
            last_row = conn.execute(
                "SELECT timestamp FROM alpaca_trades WHERE bot_id = %s ORDER BY timestamp DESC LIMIT 1",
                (bot,),
            ).fetchone()

        # Bot rows for config and running status
        if bot == "both":
            bot_rows = conn.execute(
                "SELECT * FROM bots ORDER BY bot_id"
            ).fetchall()
        else:
            bot_rows = conn.execute(
                "SELECT * FROM bots WHERE bot_id = %s ORDER BY bot_id", (bot,)
            ).fetchall()

        # Cycle count: number of distinct scan batches in signals table
        if bot == "both":
            cycle_count = conn.execute(
                "SELECT COUNT(DISTINCT DATE_TRUNC('second', scanned_at)) AS n FROM signals"
            ).fetchone()["n"] or 0
        else:
            cycle_count = conn.execute(
                "SELECT COUNT(DISTINCT DATE_TRUNC('second', scanned_at)) AS n FROM signals WHERE bot_id = %s",
                (bot,),
            ).fetchone()["n"] or 0

    resolved = len(closed_rows)
    wins = sum(1 for r in closed_rows if (r["pnl"] or 0) > 0)
    total_pnl = sum(r["pnl"] or 0.0 for r in closed_rows)
    win_rate_pct = round(wins / resolved * 100, 1) if resolved > 0 else 0.0
    equity = 100_000.0 * len(bot_ids) + total_pnl
    last_cycle = last_row["timestamp"] if last_row else None

    # Running status from BotManager
    mgr = getattr(request.app.state, "bot_manager", None)
    if mgr is not None:
        mgr_status = mgr.status()
        running = any(s.get("thread_alive", False) for s in mgr_status.values())
    else:
        # Fallback: check DB status column
        running = any(
            (r.get("status") or "stopped") == "running"
            for r in bot_rows
        )

    # Uptime: seconds since earliest "running" bot's updated_at
    uptime_seconds = 0
    for r in bot_rows:
        if (r.get("status") or "") == "running" and r.get("updated_at"):
            updated = r["updated_at"]
            if hasattr(updated, "tzinfo") and updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            secs = int((datetime.now(timezone.utc) - updated).total_seconds())
            uptime_seconds = max(uptime_seconds, secs)

    # Build config from DB bot rows (one section per bot, prefixed)
    config: dict = {}
    for r in bot_rows:
        bid = r.get("bot_id", "")
        prefix = f"{bid}." if len(bot_ids) > 1 else ""
        config[f"{prefix}kelly_fraction"] = r.get("kelly_fraction", 0.25)
        config[f"{prefix}min_confluence"] = r.get("min_confluence", 3)
        config[f"{prefix}rsi_ceiling"] = r.get("rsi_ceiling", 72.0)
        config[f"{prefix}skip_risk_gate"] = bool(r.get("skip_risk_gate", False))
        config[f"{prefix}max_position_pct"] = r.get("max_position_pct", 0.05)
        config[f"{prefix}hard_stop_pct"] = r.get("hard_stop_pct", -0.05)
        config[f"{prefix}soft_stop_pct"] = r.get("soft_stop_pct", -0.03)
        crypto_universe = r.get("crypto_universe") or "BTC/USD,ETH/USD,SOL/USD,XRP/USD"
        stock_universe = r.get("stock_universe") or ""
        all_symbols = "/".join(
            s.split("/")[0] for s in crypto_universe.split(",") if s.strip()
        )
        if stock_universe:
            all_symbols += "/" + "/".join(
                s.strip() for s in stock_universe.split(",") if s.strip()
            )
        config[f"{prefix}asset_universe"] = all_symbols

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
        running=running,
        last_cycle=last_cycle,
        uptime_seconds=uptime_seconds,
        cycle_count=cycle_count,
        paper_trades_completed=total_trades,
        paper_trades_target=50,
        win_rate=win_rate_pct,
        win_rate_target=40.0,
        equity=equity,
        equity_target=_LIVE_THRESHOLD,
        health=health,
        config=config,
    )
    return Envelope(data=data, meta=Meta(count=1))
