"""
Settings endpoint.
GET /api/settings?bot=A|B|both
"""

import os
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Query, Request

from db import KNOWN_BOTS, get_db, get_heartbeat, heartbeat_is_fresh
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
        # THE RAW ROW COUNT — REPORTED, never again the GATE figure.
        #
        # This used to BE `paper_trades_completed`: a bare, unfiltered COUNT(*) fed
        # straight to the 50-trade gate that guards LIVE TRADING. It counts `submitted`
        # rows, `rejected` gate-blocks and canceled 0-fill entries — rows that never
        # became a POSITION at all (src/bot_thread.py:362,376,382 writes them). A gate
        # satisfied by rows that were never trades is not a gate. Same class of error as
        # the fabricated-$100k-bankroll hardcode Phase 19 deleted below.
        #
        # It stays on the payload as `total_rows` so that a user watching
        # paper_trades_completed FALL can see exactly where the rows went.
        total_rows = conn.execute(
            f"SELECT COUNT(*) AS total FROM alpaca_trades WHERE bot_id IN ({bot_placeholders})",
            tuple(bot_ids),
        ).fetchone()["total"]
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

    # THE PAPER GATE NOW COUNTS TRADES. `resolved` is the CANONICAL RESOLVED population
    # (src/db.py:95 is_resolved) already computed above for the win rate — no new SQL, and
    # no sixth spelling of the predicate.
    #
    # THE GATE WILL READ WORSE. THAT IS THE INTENDED OUTCOME AND IT IS NOT TO BE TUNED
    # BACK. Making the gate HONEST is not the same as OPENING it: paper_trades_target
    # stays 50, win_rate_target stays 40.0, mode stays "paper".
    #
    # The before/after magnitude is MEASURED per bot by scripts/e2e_verify.py — never
    # predicted. RESEARCH R1 REFUTED the "655 -> ~260" projection: it conflates two
    # different bot sets (KNOWN_BOTS A/B/C/D vs Phase 17's A/B/C/E) AND two different
    # status filters.
    paper_trades_completed = resolved

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
    hb = None
    try:
        with get_db() as conn:
            conn.execute("SELECT 1")
            hb = get_heartbeat(conn)
        db_ok = True
    except Exception:
        db_ok = False

    # ABSENCE IS THE SIGNAL (research N10). `if hb else False` is LOAD-BEARING: the
    # watchdog (bot_manager.py:79) starts AFTER the start_all query that can throw at
    # :67-70, so it cannot report its own non-existence. A missing row means DEAD.
    # (`running` above answers a DIFFERENT question — "does the manager think a thread is
    # alive". `manager_alive` answers "is the manager itself alive AT ALL".)
    manager_alive = heartbeat_is_fresh(hb["beat_at"]) if hb else False
    bots_alive = hb["bots_alive"] if hb else 0
    bots_enabled = hb["bots_enabled"] if hb else 0
    last_heartbeat = (
        hb["beat_at"].isoformat() if hb and hb.get("beat_at") is not None else None
    )

    # CONFIG PRESENCE != DELIVERY. send_alert swallows every failure (notifier.py:59-61),
    # so a valid-LOOKING config can still be dropping every alert on an unverified SES
    # identity — alerts_last_error is what makes that visible. The import is FUNCTION-LOCAL
    # and guarded: no dashboard route imports `src.*` today, so a module-level import that
    # failed would take the whole route module down at startup. (This is not the 19-04
    # fence, which is specifically NO `src.db` import — i.e. no second connection pool.)
    try:
        from src.notifier import alerts_configured as _ac, last_alert_error as _lae
        alerts_ok, alerts_err = bool(_ac()), _lae()
    except Exception:
        alerts_ok, alerts_err = False, None       # PESSIMISTIC, never a cheerful default

    health = HealthStatus(
        claude_cli=True,
        alpaca_api=(alpaca_status in ("ok", "unknown")),
        database=db_ok,
        db_size_mb=0.0,
        manager_alive=manager_alive,
        alerts_configured=alerts_ok,
        alerts_last_error=alerts_err,
        bots_alive=bots_alive,
        bots_enabled=bots_enabled,
        last_heartbeat=last_heartbeat,
    )

    data = SettingsData(
        mode="paper",
        running=running,
        last_cycle=last_cycle,
        uptime_seconds=uptime_seconds,
        cycle_count=cycle_count,
        paper_trades_completed=paper_trades_completed,
        paper_trades_target=50,
        win_rate=win_rate_pct,
        win_rate_target=40.0,
        equity=equity,
        equity_target=_LIVE_THRESHOLD,
        total_rows=total_rows,
        unresolved=unresolved,
        health=health,
        config=config,
    )
    return Envelope(data=data, meta=Meta(count=1))
