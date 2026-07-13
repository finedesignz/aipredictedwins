"""
Settings endpoint.
GET /api/settings?bot=A|B|both
"""

import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Query, Request

from db import KNOWN_BOTS, get_db
from models import Envelope, HealthStatus, Meta, SettingsData
from alpaca_health import get_account_health

router = APIRouter(prefix="/api", tags=["settings"])

_LIVE_THRESHOLD = float(os.environ.get("LIVE_TRADING_THRESHOLD", "100000"))


@router.get("/settings", response_model=Envelope[SettingsData])
def get_settings(
    request: Request,
    bot: str = Query("both"),
):
    if bot == "all":
        bot = "both"
    bot_ids = list(KNOWN_BOTS) if bot == "both" else [bot]
    bot_placeholders = ",".join(["%s"] * len(bot_ids))

    with get_db() as conn:
        # Total and closed trades
        total_trades = conn.execute(
            f"SELECT COUNT(*) AS n FROM alpaca_trades WHERE bot_id IN ({bot_placeholders})",
            tuple(bot_ids),
        ).fetchone()["n"]
        # `AND pnl IS NOT NULL` (Phase 18): this win_rate IS the paper-gate readout
        # (win_rate vs win_rate_target=40.0). An unresolved row is not a loss.
        closed_rows = conn.execute(
            f"""SELECT pnl FROM alpaca_trades
               WHERE bot_id IN ({bot_placeholders})
                 AND status IN ('closed', 'stopped', 'target_hit')
                 AND pnl IS NOT NULL""",
            tuple(bot_ids),
        ).fetchall()
        last_row = conn.execute(
            f"SELECT timestamp FROM alpaca_trades WHERE bot_id IN ({bot_placeholders}) ORDER BY timestamp DESC LIMIT 1",
            tuple(bot_ids),
        ).fetchone()

        bot_rows = conn.execute(
            f"SELECT * FROM bots WHERE bot_id IN ({bot_placeholders}) ORDER BY bot_id",
            tuple(bot_ids),
        ).fetchall()

        cycle_count = conn.execute(
            f"SELECT COUNT(DISTINCT DATE_TRUNC('second', scanned_at)) AS n FROM signals WHERE bot_id IN ({bot_placeholders})",
            tuple(bot_ids),
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
