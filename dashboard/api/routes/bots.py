"""
Bot CRUD endpoints.

GET    /api/bots              -- list all bots with live status
GET    /api/bots/{bot_id}/universe -- effective trading universe (read-only)
POST   /api/bots              -- insert a new bot + spawn thread
PUT    /api/bots/{bot_id}     -- update DB fields + push to live thread
DELETE /api/bots/{bot_id}     -- stop thread + delete row
POST   /api/bots/{bot_id}/enable   -- set enabled=TRUE + spawn thread
POST   /api/bots/{bot_id}/disable  -- graceful stop + set enabled=FALSE
"""

from fastapi import APIRouter, HTTPException, Request

from db import get_db
from models import BotCreate, BotFull, BotUniverse, BotUpdate, Envelope, Meta

router = APIRouter(prefix="/api", tags=["bots"])

# Columns returned for list/get — never expose raw alpaca keys
_BOT_COLS = """bot_id, label, kelly_fraction, min_confluence, hard_stop_pct,
    soft_stop_pct, rsi_ceiling, crypto_universe, stock_universe, asset_class, skip_risk_gate,
    max_position_pct, min_short_confluence, tradingagents_enabled,
    strategy, trend_ma_window, trend_symbol, trend_benchmark,
    quarantined_symbols,
    enabled, status, status_detail"""


def _mgr(request: Request):
    """Return the BotManager from app state, or None if unavailable."""
    return getattr(request.app.state, "bot_manager", None)


def _enrich(row: dict, mgr) -> BotFull:
    """Merge DB row with live manager status into a BotFull model."""
    mgr_status: dict = {}
    if mgr is not None:
        try:
            mgr_status = mgr.status().get(row["bot_id"], {})
        except Exception:
            pass
    return BotFull(
        **{k: v for k, v in row.items() if k in BotFull.model_fields},
        thread_alive=mgr_status.get("thread_alive", False),
    )


# ---------------------------------------------------------------------------
# GET /api/bots
# ---------------------------------------------------------------------------

@router.get("/bots")
def get_bots(request: Request):
    """Return all registered bots with live thread status."""
    mgr = _mgr(request)
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT {_BOT_COLS} FROM bots ORDER BY bot_id"
        ).fetchall()
    data = [_enrich(r, mgr) for r in rows]
    return Envelope(data=data, meta=Meta(count=len(data)))


# ---------------------------------------------------------------------------
# GET /api/bots/{bot_id}/universe
# ---------------------------------------------------------------------------

@router.get("/bots/{bot_id}/universe")
def get_bot_universe(bot_id: str):
    """Return what this bot can ACTUALLY trade, and why not the rest.

    Read-only: two SELECTs, no writes, no Alpaca client, no BotManager.

    Reports what the ENTRY GATE permits (src/universe.entry_allowed), minus the two
    shadow deny-lists ON THE CONFLUENCE PATH ONLY (they are enforced solely in the
    confluence selectors, src/bot_thread.py:144-145,163-164).

    NOT valid for a CLI-run bot (`python -m src.alpaca_orchestrator`) — that is not
    a `bots` row.
    """
    from src.bot_config import BotConfig  # noqa: PLC0415
    from src.effective_universe import resolve_universe  # noqa: PLC0415
    from src.universe import normalize  # noqa: PLC0415

    with get_db() as conn:
        row = conn.execute(
            f"SELECT {_BOT_COLS} FROM bots WHERE bot_id = %s", (bot_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")

    # Per-symbol exposure — the leak evidence. `timestamp` is TEXT
    # (src/db_schema.sql:28), so the ::timestamptz cast is required. Its own
    # connection block: a failed cast must not poison the row-fetch transaction.
    exposure: dict = {}
    exposure_loaded = True
    try:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT symbol,
                       COUNT(*) FILTER (WHERE status = 'open') AS open_positions,
                       COUNT(*) FILTER (
                           WHERE "timestamp"::timestamptz > NOW() - INTERVAL '30 days'
                       ) AS recent_trades
                FROM alpaca_trades
                WHERE bot_id = %s
                GROUP BY symbol
                """,
                (bot_id,),
            ).fetchall()
        for r in rows:
            exposure[normalize(r["symbol"])] = {
                "open": int(r["open_positions"]),
                "recent": int(r["recent_trades"]),
                "display": r["symbol"],
            }
    except Exception:
        # Never fail silent: an empty leak list must not read as an all-clear.
        exposure, exposure_loaded = {}, False

    cfg = BotConfig.from_row(row)
    result = resolve_universe(cfg, exposure=exposure, exposure_loaded=exposure_loaded)
    return Envelope(data=BotUniverse(**result), meta=Meta(count=len(result["effective"])))


# ---------------------------------------------------------------------------
# POST /api/bots
# ---------------------------------------------------------------------------

@router.post("/bots", status_code=201)
def create_bot(body: BotCreate, request: Request):
    """Insert a new bot and spawn its trading thread."""
    mgr = _mgr(request)
    with get_db() as conn:
        # Check for duplicate
        exists = conn.execute(
            "SELECT 1 FROM bots WHERE bot_id = %s", (body.bot_id,)
        ).fetchone()
        if exists:
            raise HTTPException(status_code=409, detail=f"Bot '{body.bot_id}' already exists")

        conn.execute(
            """
            INSERT INTO bots (
                bot_id, label, alpaca_api_key, alpaca_secret_key,
                kelly_fraction, min_confluence, hard_stop_pct, soft_stop_pct,
                rsi_ceiling, crypto_universe, stock_universe, skip_risk_gate,
                max_position_pct, min_short_confluence, tradingagents_enabled,
                quarantined_symbols, enabled, status
            ) VALUES (
                %(bot_id)s, %(label)s, %(alpaca_api_key)s, %(alpaca_secret_key)s,
                %(kelly_fraction)s, %(min_confluence)s, %(hard_stop_pct)s, %(soft_stop_pct)s,
                %(rsi_ceiling)s, %(crypto_universe)s, %(stock_universe)s, %(skip_risk_gate)s,
                %(max_position_pct)s, %(min_short_confluence)s, %(tradingagents_enabled)s,
                %(quarantined_symbols)s, TRUE, 'stopped'
            )
            """,
            body.model_dump(),
        )
        # Fetch back including keys for manager.add()
        row = conn.execute(
            f"SELECT {_BOT_COLS}, alpaca_api_key, alpaca_secret_key FROM bots WHERE bot_id = %s",
            (body.bot_id,),
        ).fetchone()

    if mgr is not None and row is not None:
        try:
            mgr.add(dict(row))
        except Exception:
            pass  # manager unavailable; thread can be started later

    if row is None:
        raise HTTPException(status_code=500, detail="Bot created but could not be fetched")
    # Return without keys
    safe_row = {k: v for k, v in row.items() if k not in ("alpaca_api_key", "alpaca_secret_key")}
    return Envelope(data=_enrich(safe_row, mgr))


# ---------------------------------------------------------------------------
# PUT /api/bots/{bot_id}
# ---------------------------------------------------------------------------

@router.put("/bots/{bot_id}")
def update_bot(bot_id: str, body: BotUpdate, request: Request):
    """Update configurable fields on a bot and push changes to live thread."""
    mgr = _mgr(request)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")

    set_clauses = ", ".join(f"{col} = %({col})s" for col in updates)
    params = {**updates, "bot_id": bot_id}

    with get_db() as conn:
        result = conn.execute(
            f"UPDATE bots SET {set_clauses} WHERE bot_id = %(bot_id)s",
            params,
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
        row = conn.execute(
            f"SELECT {_BOT_COLS} FROM bots WHERE bot_id = %s", (bot_id,)
        ).fetchone()

    if mgr is not None:
        try:
            mgr.update(bot_id, updates)
        except Exception:
            pass

    return Envelope(data=_enrich(row, mgr))


# ---------------------------------------------------------------------------
# DELETE /api/bots/{bot_id}
# ---------------------------------------------------------------------------

@router.delete("/bots/{bot_id}", status_code=204)
def delete_bot(bot_id: str, request: Request):
    """Stop the bot's thread and remove it from the registry."""
    mgr = _mgr(request)
    if mgr is not None:
        try:
            mgr.stop_bot(bot_id)
        except Exception:
            pass

    with get_db() as conn:
        result = conn.execute("DELETE FROM bots WHERE bot_id = %s", (bot_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")


# ---------------------------------------------------------------------------
# POST /api/bots/{bot_id}/enable
# ---------------------------------------------------------------------------

@router.post("/bots/{bot_id}/enable")
def enable_bot(bot_id: str, request: Request):
    """Set enabled=TRUE and spawn (or resume) the bot's thread."""
    mgr = _mgr(request)
    with get_db() as conn:
        result = conn.execute(
            "UPDATE bots SET enabled = TRUE WHERE bot_id = %s", (bot_id,)
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
        row = conn.execute(
            f"SELECT {_BOT_COLS}, alpaca_api_key, alpaca_secret_key FROM bots WHERE bot_id = %s",
            (bot_id,),
        ).fetchone()

    if mgr is not None and row is not None:
        try:
            mgr.add(dict(row))
        except Exception:
            pass

    safe_row = {k: v for k, v in row.items() if k not in ("alpaca_api_key", "alpaca_secret_key")}
    return Envelope(data=_enrich(safe_row, mgr))


# ---------------------------------------------------------------------------
# POST /api/bots/{bot_id}/disable
# ---------------------------------------------------------------------------

@router.post("/bots/{bot_id}/disable")
def disable_bot(bot_id: str, request: Request):
    """Gracefully stop the bot's thread and set enabled=FALSE."""
    mgr = _mgr(request)
    if mgr is not None:
        try:
            mgr.stop_bot(bot_id)
        except Exception:
            pass

    with get_db() as conn:
        result = conn.execute(
            "UPDATE bots SET enabled = FALSE WHERE bot_id = %s", (bot_id,)
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
        row = conn.execute(
            f"SELECT {_BOT_COLS} FROM bots WHERE bot_id = %s", (bot_id,)
        ).fetchone()

    return Envelope(data=_enrich(row, mgr))
