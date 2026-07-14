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
# Missing-row fallback ONLY — mirrors src/db.py:322-331. Never a per-bot default.
_DEFAULT_STARTING_EQUITY = 100_000.0


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
        # RESOLVED := `pnl IS NOT NULL AND pnl <> 0` (Phase 19). THIS win_rate IS THE PAPER
        # GATE (win_rate vs win_rate_target=40.0) — the gate that guards LIVE TRADING. It
        # was counting ~395 historical `pnl = 0.0` sentinels as LOSSES. Making it honest
        # may make it read WORSE; that is the point, and it is NOT to be tuned away.
        closed_rows = conn.execute(
            f"""SELECT pnl FROM alpaca_trades
               WHERE bot_id IN ({bot_placeholders})
                 AND status IN ('closed', 'stopped', 'target_hit')
                 AND pnl IS NOT NULL AND pnl <> 0""",
            tuple(bot_ids),
        ).fetchall()
        unresolved = conn.execute(
            f"""SELECT COUNT(*) AS n FROM alpaca_trades
               WHERE bot_id IN ({bot_placeholders})
                 AND status IN ('closed', 'stopped', 'target_hit')
                 AND (pnl IS NULL OR pnl = 0)""",
            tuple(bot_ids),
        ).fetchone()["n"]
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
    wins = sum(1 for r in closed_rows if r["pnl"] > 0)
    total_pnl = sum(r["pnl"] for r in closed_rows)
    win_rate_pct = round(wins / resolved * 100, 1) if resolved > 0 else 0.0

    # THE $100k HARDCODE IS DELETED. The old line multiplied a fabricated $100k bankroll by
    # the bot count and fed it to the readout of the gate that guards LIVE TRADING —
    # exactly how a gate gets passed by a bug. starting_equity now comes from the bot_rows
    # already fetched above (a SELECT *); the default below fires ONLY for a bot_id that
    # has no row at all, mirroring src/db.py:322-331's missing-row-only fallback.
    equity_by_bot = {
        r.get("bot_id"): r.get("starting_equity")
        for r in bot_rows
        if r.get("starting_equity") is not None
    }
    starting_equity_total = sum(
        equity_by_bot.get(bid, _DEFAULT_STARTING_EQUITY) for bid in bot_ids
    )
    equity = starting_equity_total + total_pnl
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
        unresolved=unresolved,
        health=health,
        config=config,
    )
    return Envelope(data=data, meta=Meta(count=1))
