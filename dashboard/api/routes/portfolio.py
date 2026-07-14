"""
Portfolio summary endpoint.

GET /api/portfolio?bot=A|B|both

Real equity/cash/unrealized P&L comes from the Alpaca account endpoint.
Win rate and trade counts come from the database (closed alpaca_trades).
Falls back to DB-only calculation when Alpaca keys are absent.
"""

import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Literal

from fastapi import APIRouter, Query

from db import get_db
from models import Envelope, Meta, MultiBotPortfolio, PortfolioData

router = APIRouter(prefix="/api", tags=["portfolio"])

_ALPACA_BASE = "https://paper-api.alpaca.markets"
_DEFAULT_STARTING_EQUITY = 100_000.0
# Same env var the watchdog's _maybe_reconcile uses (bot_manager._RECONCILE_INTERVAL_HOURS).
_RECONCILE_INTERVAL_HOURS = float(os.environ.get("RECONCILE_INTERVAL_HOURS", "1"))


def _reconciliation_for_bot(conn, bot_id: str) -> dict | None:
    """The bot's latest reconciliation row, or None (incl. on a pre-migration DB)."""
    try:
        return conn.execute(
            "SELECT checked_at, trade_log_pnl, alpaca_realized_pnl, delta, within_tolerance "
            "FROM reconciliation WHERE bot_id = %s",
            (bot_id,),
        ).fetchone()
    except Exception:
        return None


def _fetch_alpaca_account(api_key: str, secret_key: str) -> dict:
    """Return the Alpaca account dict, or {} on failure."""
    if not api_key or not secret_key:
        return {}
    req = urllib.request.Request(
        f"{_ALPACA_BASE}/v2/account",
        headers={
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return {}


def _portfolio_for_bot(conn, bot_id: str, days: int = 30) -> PortfolioData:
    # Starting equity + Alpaca keys from registry (keys are the source of truth —
    # the bot threads load them from this same table, env vars may be stale).
    bot_row = conn.execute(
        "SELECT starting_equity, alpaca_api_key, alpaca_secret_key "
        "FROM bots WHERE bot_id = %s",
        (bot_id,),
    ).fetchone()
    starting_equity = (
        bot_row["starting_equity"]
        if bot_row and bot_row.get("starting_equity") is not None
        else _DEFAULT_STARTING_EQUITY
    )

    # Closed trades filtered to window → win rate / trade counts.
    #
    # RESOLVED := `pnl IS NOT NULL AND pnl <> 0` (Phase 19). 0.0 is NOT NULL, so Phase 18's
    # filter alone passed the ~395 historical `pnl = 0.0` external-exit sentinels straight
    # through, and `losses = len(closed) - wins` then booked every one of them as a LOSS.
    # A sentinel leaves the win-rate NUMERATOR *and DENOMINATOR* and the realized sum, and
    # is reported as its own `unresolved` count — never folded into losses.
    since = datetime.now(timezone.utc) - timedelta(days=days)
    closed = conn.execute(
        """
        SELECT pnl FROM alpaca_trades
        WHERE bot_id = %s AND status IN ('closed', 'stopped', 'target_hit')
          AND pnl IS NOT NULL AND pnl <> 0
          AND (closed_at IS NULL OR closed_at::timestamptz >= %s)
        """,
        (bot_id, since),
    ).fetchall()
    # The terminal rows that FAIL the predicate, over the same window. Counted, not hidden.
    unresolved = conn.execute(
        """
        SELECT COUNT(*) AS n FROM alpaca_trades
        WHERE bot_id = %s AND status IN ('closed', 'stopped', 'target_hit')
          AND (pnl IS NULL OR pnl = 0)
          AND (closed_at IS NULL OR closed_at::timestamptz >= %s)
        """,
        (bot_id, since),
    ).fetchone()["n"]

    closed_pnl = sum(r["pnl"] for r in closed)
    wins = sum(1 for r in closed if r["pnl"] > 0)
    losses = len(closed) - wins
    resolved = len(closed)
    win_rate_pct = round(wins / resolved * 100, 1) if resolved > 0 else 0.0

    total_trades = conn.execute(
        "SELECT COUNT(*) AS n FROM alpaca_trades WHERE bot_id = %s", (bot_id,)
    ).fetchone()["n"]

    open_count = conn.execute(
        "SELECT COUNT(*) AS n FROM alpaca_trades WHERE bot_id = %s AND status = 'open'",
        (bot_id,),
    ).fetchone()["n"]

    # Daily P&L (closed trades today) — THE FIFTH READER (research N7). It had NO pnl
    # filter at all. Zeros sum to zero so the number does not move, but a fifth reader
    # with a fifth opinion about what a resolved trade IS is exactly how this class of
    # bug survives. All five now share one predicate.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_rows = conn.execute(
        """
        SELECT pnl FROM alpaca_trades
        WHERE bot_id = %s AND status IN ('closed', 'stopped', 'target_hit')
          AND pnl IS NOT NULL AND pnl <> 0
          AND DATE(closed_at::timestamptz) = %s::date
        """,
        (bot_id, today),
    ).fetchall()
    daily_pnl = sum(r["pnl"] for r in daily_rows)

    # Real-time equity from Alpaca account — prefer DB-stored keys (same source
    # the bot threads use); fall back to env vars only if the row has none.
    key = (bot_row.get("alpaca_api_key") if bot_row else None) \
        or os.environ.get(f"ALPACA_API_KEY_{bot_id}", "")
    sec = (bot_row.get("alpaca_secret_key") if bot_row else None) \
        or os.environ.get(f"ALPACA_SECRET_KEY_{bot_id}", "")
    acct = _fetch_alpaca_account(key, sec)
    unrealized_today = float(acct.get("unrealized_intraday_pl") or 0.0) if acct else 0.0
    daily_pnl_total = daily_pnl + unrealized_today

    # THE HEADLINE (RUN-02). 017_reconciliation.sql's own header says "Consumed by the
    # dashboard headline in Phase 19" — and nothing consumed it. Worse, the Alpaca ->
    # trade-log fallback below was SILENT: no flag on the response, so nobody could tell
    # WHICH number they were looking at. `pnl_source` is now set on EVERY branch.
    rec = _reconciliation_for_bot(conn, bot_id)
    checked_at = rec.get("checked_at") if rec else None
    stale = True
    if checked_at is not None:
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - checked_at).total_seconds()
        stale = age > 2 * _RECONCILE_INTERVAL_HOURS * 3600

    if rec is not None:
        # The reconciler's own identity (src/reconciliation.py:33):
        #   starting + alpaca_realized + unrealized = equity
        pnl_source = "reconciled"
        unrealized = float(acct.get("unrealized_pl") or 0.0) if acct else 0.0
        total_pnl = float(rec["alpaca_realized_pnl"]) + unrealized
        equity = float(acct.get("equity")) if acct and acct.get("equity") \
            else starting_equity + total_pnl
    elif acct:
        pnl_source = "alpaca_live"
        equity = float(acct.get("equity") or starting_equity)
        total_pnl = equity - starting_equity
    else:
        pnl_source = "trade_log"
        equity = starting_equity + closed_pnl
        total_pnl = closed_pnl

    reconciled = None
    if rec is not None:
        reconciled = {
            "alpaca_realized_pnl": float(rec["alpaca_realized_pnl"]),
            "trade_log_pnl": float(rec["trade_log_pnl"]),
            "delta": float(rec["delta"]),
            "within_tolerance": bool(rec["within_tolerance"]),
            "checked_at": checked_at.isoformat() if checked_at else None,
        }

    return PortfolioData(
        equity=round(equity, 2),
        total_pnl=round(total_pnl, 2),
        total_pnl_percent=round(total_pnl / starting_equity * 100, 2),
        win_rate=win_rate_pct,
        open_positions=open_count,
        daily_pnl=round(daily_pnl_total, 2),
        daily_pnl_percent=round(daily_pnl_total / starting_equity * 100, 2),
        mode="paper",
        trades_resolved=resolved,
        total_trades=total_trades,
        wins=wins,
        losses=losses,
        unresolved=unresolved,
        pnl_source=pnl_source,
        stale=stale,
        reconciled=reconciled,
    )


@router.get("/portfolio")
def get_portfolio(
    bot: str = Query("both"),
    days: int = Query(30, ge=1, le=365),
):
    """Return portfolio KPIs. bot=both returns {A: {...}, B: {...}} shape."""
    if bot == "all":
        bot = "both"
    with get_db() as conn:
        if bot == "both":
            data = MultiBotPortfolio(
                A=_portfolio_for_bot(conn, "A", days),
                B=_portfolio_for_bot(conn, "B", days),
            )
        else:
            data = _portfolio_for_bot(conn, bot, days)
    return Envelope(data=data, meta=Meta(count=1))
