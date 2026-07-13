"""
Postgres connection pool and core database functions for the trading bot.

All functions take `bot_id` as the first argument (either "A" or "B").
The pool is initialized lazily on first use; the schema is bootstrapped once.
"""

import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None


def _create_pool() -> ConnectionPool:
    url = os.environ["DATABASE_URL"]
    for attempt in range(3):
        try:
            pool = ConnectionPool(
                conninfo=url,
                min_size=2,
                max_size=10,
                kwargs={"row_factory": dict_row},
                open=True,
            )
            return pool
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")  # pragma: no cover


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = _create_pool()
        _bootstrap_schema()
    return _pool


def _bootstrap_schema() -> None:
    schema_path = os.path.join(os.path.dirname(__file__), "db_schema.sql")
    with open(schema_path) as f:
        sql = f.read()
    with get_pool().connection() as conn:
        conn.execute(sql)


@contextmanager
def connection() -> Generator[psycopg.Connection, None, None]:
    """Yield a psycopg3 connection from the pool."""
    with get_pool().connection() as conn:
        yield conn


# ── Alpaca trades ─────────────────────────────────────────────────────────────

def log_alpaca_trade(bot_id: str, trade_data: dict) -> int:
    timestamp = datetime.now(timezone.utc).isoformat()
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO alpaca_trades (
                bot_id, timestamp, symbol, asset_class, side, qty,
                entry_price, mirofish_prob, market_sentiment,
                target_price, stop_loss, simulation_id, notes,
                status, order_id, order_type, filled_qty, filled_avg_price
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                bot_id, timestamp,
                trade_data["symbol"],
                trade_data["asset_class"],
                trade_data["side"],
                trade_data["qty"],
                trade_data["entry_price"],
                trade_data["mirofish_prob"],
                trade_data.get("market_sentiment"),
                trade_data.get("target_price"),
                trade_data.get("stop_loss"),
                trade_data.get("simulation_id"),
                trade_data.get("notes"),
                trade_data.get("status", "submitted"),
                trade_data.get("order_id"),
                trade_data.get("order_type"),
                trade_data.get("filled_qty"),
                trade_data.get("filled_avg_price"),
            ),
        ).fetchone()
        return row["id"]


def update_alpaca_trade(
    bot_id: str,
    trade_id: int,
    status: str,
    exit_price: float | None = None,
    pnl: float | None = None,
    fees: float | None = None,
) -> None:
    closed_at = (
        datetime.now(timezone.utc).isoformat()
        if status in ("closed", "stopped", "target_hit", "canceled", "expired", "rejected")
        else None
    )
    with connection() as conn:
        conn.execute(
            """
            UPDATE alpaca_trades
            SET status = %s, exit_price = %s, pnl = %s, fees = %s, closed_at = %s
            WHERE id = %s AND bot_id = %s
            """,
            (status, exit_price, pnl, fees, closed_at, trade_id, bot_id),
        )


def get_open_alpaca_positions(bot_id: str) -> list[dict]:
    with connection() as conn:
        return conn.execute(
            "SELECT * FROM alpaca_trades WHERE bot_id = %s AND status = 'open' ORDER BY timestamp DESC",
            (bot_id,),
        ).fetchall()


def get_pending_alpaca_orders(bot_id: str) -> list[dict]:
    """Submitted (pre-terminal) orders awaiting lifecycle resolution.

    Drives the Wave 2 resolver: a restarted bot re-polls in-flight orders from
    the DB. Columns match 11-02's interface note exactly.
    """
    with connection() as conn:
        return conn.execute(
            """
            SELECT id, order_id, symbol, qty, side, order_type, timestamp, status
            FROM alpaca_trades
            WHERE bot_id = %s AND status = 'submitted'
            ORDER BY timestamp DESC
            """,
            (bot_id,),
        ).fetchall()


def get_stale_alpaca_candidates(bot_id: str, older_than_minutes: int = 30) -> list[dict]:
    """Non-terminal rows WITH an order_id, older than a guard window — Phase-14 backfill set.

    ``status IN ('open','submitted')`` AND ``order_id IS NOT NULL`` AND older than
    the guard window (avoid racing live in-flight orders). Read-only. Idempotent:
    a row that reaches a terminal status drops out of this set on the next run.
    Returns every column the resolution ladder needs (no second query).
    """
    with connection() as conn:
        return conn.execute(
            """
            SELECT id, order_id, symbol, side, qty, entry_price,
                   filled_qty, filled_avg_price, order_type, status, timestamp
            FROM alpaca_trades
            WHERE bot_id = %s
              AND status IN ('open', 'submitted')
              AND order_id IS NOT NULL
              AND timestamp::timestamptz < NOW() - (%s || ' minutes')::interval
            ORDER BY timestamp ASC
            """,
            (bot_id, str(older_than_minutes)),
        ).fetchall()


def count_unresolvable_alpaca_rows(bot_id: str) -> int:
    """Count non-terminal rows with NO order_id (pre-Phase-11 legacy residue).

    These cannot be resolved from Alpaca history — reported, never guessed.
    Read-only.
    """
    with connection() as conn:
        return conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM alpaca_trades
            WHERE bot_id = %s
              AND status IN ('open', 'submitted')
              AND order_id IS NULL
            """,
            (bot_id,),
        ).fetchone()["n"]


def get_recent_loss_symbols(bot_id: str, hours: int = 24) -> set[str]:
    """Symbols this bot closed at a loss within `hours` — used as re-entry cooldown."""
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT symbol FROM alpaca_trades
            WHERE bot_id = %s
              AND status IN ('closed', 'stopped')
              AND pnl < 0
              AND closed_at IS NOT NULL
              AND closed_at::timestamptz >= NOW() - (%s || ' hours')::interval
            """,
            (bot_id, str(hours)),
        ).fetchall()
    return {r["symbol"] for r in rows}


def get_alpaca_accuracy(bot_id: str, last_n: int | None = None) -> dict:
    with connection() as conn:
        base = """
            SELECT status, pnl, symbol, asset_class FROM alpaca_trades
            WHERE bot_id = %s AND status IN ('closed', 'stopped', 'target_hit')
            ORDER BY closed_at DESC
        """
        if last_n:
            rows = conn.execute(base + " LIMIT %s", (bot_id, last_n)).fetchall()
        else:
            rows = conn.execute(base, (bot_id,)).fetchall()

        total_trades = conn.execute(
            "SELECT COUNT(*) AS n FROM alpaca_trades WHERE bot_id = %s", (bot_id,)
        ).fetchone()["n"]

    resolved = len(rows)
    wins = sum(1 for r in rows if (r["pnl"] or 0) > 0)
    losses = resolved - wins
    total_pnl = sum(r["pnl"] or 0.0 for r in rows)
    return {
        "total_trades": total_trades,
        "resolved": resolved,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / resolved if resolved > 0 else 0.0,
        "total_pnl": total_pnl,
        "avg_pnl": total_pnl / resolved if resolved > 0 else 0.0,
        "crypto_pnl": sum(r["pnl"] or 0.0 for r in rows if r["asset_class"] == "crypto"),
        "stock_pnl": sum(r["pnl"] or 0.0 for r in rows if r["asset_class"] == "us_equity"),
    }


# ── Reconciliation (PNL-03) ────────────────────────────────────────────────────

def get_realized_pnl(bot_id: str) -> float:
    """Sum trade-log realized P&L for a bot over the three position-closed terminals.

    Mirrors get_alpaca_accuracy's status set — 'closed','stopped','target_hit' all
    carry real pnl; summing 'closed' alone drops every stop/target exit. NULL pnl
    (unfilled canceled/rejected/expired) is guarded to 0.0.
    """
    with connection() as conn:
        rows = conn.execute(
            "SELECT pnl FROM alpaca_trades WHERE bot_id = %s "
            "AND status IN ('closed', 'stopped', 'target_hit')",
            (bot_id,),
        ).fetchall()
    return sum((r["pnl"] or 0.0) for r in rows)


def get_resolved_trades(bot_id: str | None = None, since=None) -> list[dict]:
    """Position-closed rows for per-symbol stats (TUNE-02). READ-ONLY.

    Terminal set mirrors get_alpaca_accuracy (db.py:215) / get_realized_pnl
    (db.py:256-257) EXACTLY: ('closed','stopped','target_hit'). Non-position
    terminals (canceled/cancelled/expired/rejected) never held a position — and a
    Phase-15 gate block writes a 'rejected' row with pnl=0 (bot_thread.py:309),
    which would otherwise score as a LOSS.

    NOTE: a 'closed' row may ALSO carry pnl=0.0 — the external-exit sentinel at
    alpaca_orchestrator.py:167-176 (same shape at bot_c/strategy.py:393 and
    trend_strategy.py:172). SQL cannot distinguish that from a genuine flat trade,
    so it is returned as-is and symbol_stats buckets it into zero_pnl. A NULL pnl
    is likewise returned as-is: db.py:228 and db.py:259 coerce it to zero — this
    function must NOT copy that idiom.

    fees may be NULL: bot_c/strategy.py:393-395 and trend_strategy.py:172-173 store
    a GROSS pnl and pass no fees arg. NULL fees is the TELL that pnl is gross —
    symbol_stats flags it as gross_pnl_rows. Do not paper over it here.

    `timestamp` is a TEXT column (db_schema.sql:28), so it is cast to timestamptz in
    BOTH the window filter and the sort — a bare compare/sort would be lexicographic.
    bot_id and since reach SQL only as %s params.
    """
    clauses = [
        'SELECT bot_id, symbol, asset_class, side, status, pnl, fees,',
        '       "timestamp" AS entry_ts, closed_at',
        "FROM alpaca_trades",
        "WHERE status IN ('closed', 'stopped', 'target_hit')",
    ]
    params: list = []
    if bot_id:
        clauses.append("AND bot_id = %s")
        params.append(bot_id)
    if since is not None:
        clauses.append('AND "timestamp"::timestamptz >= %s')
        params.append(since)
    clauses.append('ORDER BY "timestamp"::timestamptz ASC')

    with connection() as conn:
        return conn.execute("\n".join(clauses), tuple(params)).fetchall()


def get_starting_equity(bot_id: str) -> float:
    """Read the reconciliation baseline from the bot's row (never hardcode 100000)."""
    with connection() as conn:
        row = conn.execute(
            "SELECT starting_equity FROM bots WHERE bot_id = %s",
            (bot_id,),
        ).fetchone()
    if row is None:
        return 100000.0  # missing-row fallback only
    return row["starting_equity"]


def record_reconciliation(bot_id: str, result: dict) -> None:
    """Upsert the latest reconciliation result for a bot (single row per bot)."""
    with connection() as conn:
        conn.execute(
            "INSERT INTO reconciliation (bot_id, checked_at, trade_log_pnl, "
            "alpaca_realized_pnl, delta, within_tolerance, tolerance) "
            "VALUES (%s, NOW(), %s, %s, %s, %s, %s) "
            "ON CONFLICT (bot_id) DO UPDATE SET "
            "checked_at = EXCLUDED.checked_at, "
            "trade_log_pnl = EXCLUDED.trade_log_pnl, "
            "alpaca_realized_pnl = EXCLUDED.alpaca_realized_pnl, "
            "delta = EXCLUDED.delta, "
            "within_tolerance = EXCLUDED.within_tolerance, "
            "tolerance = EXCLUDED.tolerance",
            (
                bot_id,
                result["trade_log_pnl"],
                result["alpaca_realized_pnl"],
                result["delta"],
                result["within_tolerance"],
                result["tolerance"],
            ),
        )


# ── Legacy Kalshi trades ───────────────────────────────────────────────────────

def log_trade(bot_id: str, trade_data: dict) -> int:
    timestamp = datetime.now(timezone.utc).isoformat()
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO trades (
                bot_id, timestamp, kalshi_ticker, event_title, side, contracts,
                entry_price_cents, mirofish_prob, kalshi_price_at_entry,
                gap, kelly_pct, dollar_amount, simulation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                bot_id, timestamp,
                trade_data["kalshi_ticker"],
                trade_data["event_title"],
                trade_data["side"],
                trade_data["contracts"],
                trade_data["entry_price_cents"],
                trade_data["mirofish_prob"],
                trade_data["kalshi_price_at_entry"],
                trade_data["gap"],
                trade_data["kelly_pct"],
                trade_data["dollar_amount"],
                trade_data.get("simulation_id"),
            ),
        ).fetchone()
        return row["id"]


def update_trade(
    bot_id: str,
    trade_id: int,
    status: str,
    exit_price_cents: int | None = None,
    pnl: float | None = None,
) -> None:
    resolution_date = (
        datetime.now(timezone.utc).isoformat()
        if status in ("won", "lost", "sold")
        else None
    )
    with connection() as conn:
        conn.execute(
            """
            UPDATE trades
            SET status = %s, exit_price_cents = %s, pnl = %s, resolution_date = %s
            WHERE id = %s AND bot_id = %s
            """,
            (status, exit_price_cents, pnl, resolution_date, trade_id, bot_id),
        )


def get_accuracy(bot_id: str, last_n: int | None = None) -> dict:
    with connection() as conn:
        base = """
            SELECT status, pnl, gap FROM trades
            WHERE bot_id = %s AND status IN ('won', 'lost')
            ORDER BY resolution_date DESC
        """
        if last_n:
            rows = conn.execute(base + " LIMIT %s", (bot_id, last_n)).fetchall()
        else:
            rows = conn.execute(base, (bot_id,)).fetchall()

        total_trades = conn.execute(
            "SELECT COUNT(*) AS n FROM trades WHERE bot_id = %s", (bot_id,)
        ).fetchone()["n"]

    resolved = len(rows)
    wins = sum(1 for r in rows if r["status"] == "won")
    losses = resolved - wins
    total_pnl = sum(r["pnl"] or 0.0 for r in rows)
    avg_gap = sum(r["gap"] for r in rows) / resolved if resolved > 0 else 0.0
    return {
        "total_trades": total_trades,
        "resolved": resolved,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / resolved if resolved > 0 else 0.0,
        "total_pnl": total_pnl,
        "avg_gap": avg_gap,
    }


def get_daily_summary(bot_id: str) -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with connection() as conn:
        placed = conn.execute(
            "SELECT COUNT(*) AS n FROM trades WHERE bot_id = %s AND timestamp LIKE %s",
            (bot_id, f"{today}%"),
        ).fetchone()["n"]

        rows = conn.execute(
            """
            SELECT status, pnl FROM trades
            WHERE bot_id = %s AND resolution_date LIKE %s AND status IN ('won', 'lost')
            """,
            (bot_id, f"{today}%"),
        ).fetchall()

    resolved = len(rows)
    wins = sum(1 for r in rows if r["status"] == "won")
    daily_pnl = sum(r["pnl"] or 0.0 for r in rows)
    return {
        "date": today,
        "trades_placed": placed,
        "trades_resolved": resolved,
        "wins": wins,
        "losses": resolved - wins,
        "daily_pnl": daily_pnl,
        "accuracy": wins / resolved if resolved > 0 else 0.0,
    }


def get_simulated_tickers_today(bot_id: str) -> set[str]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT kalshi_ticker FROM simulations WHERE bot_id = %s AND timestamp LIKE %s",
            (bot_id, f"{today}%"),
        ).fetchall()
    return {r["kalshi_ticker"] for r in rows}


def log_simulation(
    bot_id: str,
    sim_id: str,
    market: dict,
    mirofish_prob: float,
    kalshi_price: float,
    estimated_cost: float,
) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    gap = mirofish_prob - kalshi_price
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO simulations (
                bot_id, id, timestamp, kalshi_ticker, event_title,
                agent_count, rounds, mirofish_prob,
                kalshi_price_at_sim, gap, estimated_cost
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (bot_id, id) DO NOTHING
            """,
            (
                bot_id, sim_id, timestamp,
                market.get("ticker", ""),
                market.get("title", market.get("event_title", "")),
                market.get("agent_count"),
                market.get("rounds"),
                mirofish_prob,
                kalshi_price,
                gap,
                estimated_cost,
            ),
        )


def log_validation(bot_id: str, data: dict) -> int:
    timestamp = datetime.now(timezone.utc).isoformat()
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO validations (
                bot_id, timestamp, kalshi_ticker, event_title, mirofish_prob,
                kalshi_price, gap, proposed_side, decision, confidence,
                adjusted_probability, size_multiplier, sentiment_report,
                news_report, contrarian_report, risk_assessment,
                veto_reason, trade_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                bot_id, timestamp,
                data["kalshi_ticker"],
                data["event_title"],
                data["mirofish_prob"],
                data["kalshi_price"],
                data["gap"],
                data["proposed_side"],
                data["decision"],
                data.get("confidence"),
                data.get("adjusted_probability"),
                data.get("size_multiplier", 1.0),
                data.get("sentiment_report"),
                data.get("news_report"),
                data.get("contrarian_report"),
                data.get("risk_assessment"),
                data.get("veto_reason"),
                data.get("trade_id"),
            ),
        ).fetchone()
        return row["id"]


def log_screening(bot_id: str, data: dict) -> int:
    timestamp = datetime.now(timezone.utc).isoformat()
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO screenings (
                bot_id, timestamp, kalshi_ticker, event_title, quick_probability,
                quick_confidence, kalshi_price, gap, promoted_to_full_sim
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                bot_id, timestamp,
                data["kalshi_ticker"],
                data["event_title"],
                data["quick_probability"],
                data.get("quick_confidence"),
                data["kalshi_price"],
                data["gap"],
                data.get("promoted_to_full_sim", False),
            ),
        ).fetchone()
        return row["id"]


def persist_scan_signals(bot_id: str, signals: list) -> None:
    """Replace the latest scan results for this bot in the signals table.

    Deletes any existing rows for the bot and inserts fresh signal rows.
    Called by BotThread after each technical scan so the dashboard shows live data.
    """
    if not signals:
        return
    now = datetime.now(timezone.utc).isoformat()
    with connection() as conn:
        conn.execute("DELETE FROM signals WHERE bot_id = %s", (bot_id,))
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO signals (scanned_at, bot_id, symbol, ema_bullish, adx_value,
                                     rsi_value, volume_spike, vwap_bullish, confluence_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        now, bot_id,
                        s.symbol,
                        s.ema_bullish,
                        s.adx_value,
                        s.rsi_value,
                        s.volume_spike,
                        s.vwap_bullish,
                        s.confluence_score,
                    )
                    for s in signals
                ],
            )


def get_veto_history(bot_id: str, last_n: int = 20) -> list[dict]:
    with connection() as conn:
        return conn.execute(
            """
            SELECT * FROM validations
            WHERE bot_id = %s AND decision = 'VETO'
            ORDER BY timestamp DESC
            LIMIT %s
            """,
            (bot_id, last_n),
        ).fetchall()
