#!/usr/bin/env python3
"""
Migrate both bots' SQLite trade databases to Postgres.

Usage:
    python scripts/migrate_sqlite_to_postgres.py \\
        --bot-a-db path/to/bot_a/trades.db \\
        --bot-b-db path/to/bot_b/trades.db

Requirements:
    - DATABASE_URL env var pointing to the target Postgres instance
    - Both SQLite files must be readable
    - Backups are created before any writes

Idempotency:
    Re-running is safe. Every migrated row has a source_id = original SQLite rowid.
    Inserts use ON CONFLICT DO NOTHING on (bot_id, source_id).
"""

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row


def backup_db(src_path: str, bot_id: str) -> str:
    """Copy the SQLite file to backups/ before touching anything."""
    os.makedirs("backups", exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = f"backups/trades-{bot_id}-{ts}.db"
    shutil.copy2(src_path, dest)
    print(f"  [backup] {src_path} → {dest}")
    return dest


def open_sqlite(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_pg_conn(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, row_factory=dict_row)


def migrate_alpaca_trades(sqlite_conn, pg_conn, bot_id: str) -> int:
    rows = sqlite_conn.execute("SELECT rowid AS source_id, * FROM alpaca_trades").fetchall()
    count = 0
    for r in rows:
        r = dict(r)
        src_id = r.pop("source_id", None)
        pg_conn.execute(
            """
            INSERT INTO alpaca_trades (
                source_id, bot_id, timestamp, symbol, asset_class, side, qty,
                entry_price, mirofish_prob, market_sentiment, target_price,
                stop_loss, status, exit_price, pnl, closed_at, simulation_id, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (bot_id, source_id) DO NOTHING
            """,
            (
                src_id, bot_id,
                r.get("timestamp"), r.get("symbol"), r.get("asset_class"),
                r.get("side"), r.get("qty"), r.get("entry_price"),
                r.get("mirofish_prob"), r.get("market_sentiment"),
                r.get("target_price"), r.get("stop_loss"), r.get("status"),
                r.get("exit_price"), r.get("pnl"), r.get("closed_at"),
                r.get("simulation_id"), r.get("notes"),
            ),
        )
        count += 1
    pg_conn.commit()
    return count


def migrate_validations(sqlite_conn, pg_conn, bot_id: str) -> int:
    rows = sqlite_conn.execute("SELECT rowid AS source_id, * FROM validations").fetchall()
    count = 0
    for r in rows:
        r = dict(r)
        src_id = r.pop("source_id", None)
        # Remove id (was SQLite autoincrement — Postgres generates its own)
        r.pop("id", None)
        pg_conn.execute(
            """
            INSERT INTO validations (
                source_id, bot_id, timestamp, kalshi_ticker, event_title,
                mirofish_prob, kalshi_price, gap, proposed_side, decision,
                confidence, adjusted_probability, size_multiplier,
                sentiment_report, news_report, contrarian_report,
                risk_assessment, veto_reason, trade_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (bot_id, source_id) DO NOTHING
            """,
            (
                src_id, bot_id,
                r.get("timestamp"), r.get("kalshi_ticker"), r.get("event_title"),
                r.get("mirofish_prob"), r.get("kalshi_price"), r.get("gap"),
                r.get("proposed_side"), r.get("decision"), r.get("confidence"),
                r.get("adjusted_probability"), r.get("size_multiplier"),
                r.get("sentiment_report"), r.get("news_report"),
                r.get("contrarian_report"), r.get("risk_assessment"),
                r.get("veto_reason"), r.get("trade_id"),
            ),
        )
        count += 1
    pg_conn.commit()
    return count


def migrate_screenings(sqlite_conn, pg_conn, bot_id: str) -> int:
    rows = sqlite_conn.execute("SELECT rowid AS source_id, * FROM screenings").fetchall()
    count = 0
    for r in rows:
        r = dict(r)
        src_id = r.pop("source_id", None)
        r.pop("id", None)
        pg_conn.execute(
            """
            INSERT INTO screenings (
                source_id, bot_id, timestamp, kalshi_ticker, event_title,
                quick_probability, quick_confidence, kalshi_price, gap,
                promoted_to_full_sim
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (bot_id, source_id) DO NOTHING
            """,
            (
                src_id, bot_id,
                r.get("timestamp"), r.get("kalshi_ticker"), r.get("event_title"),
                r.get("quick_probability"), r.get("quick_confidence"),
                r.get("kalshi_price"), r.get("gap"),
                bool(r.get("promoted_to_full_sim", False)),
            ),
        )
        count += 1
    pg_conn.commit()
    return count


def migrate_simulations(sqlite_conn, pg_conn, bot_id: str) -> int:
    rows = sqlite_conn.execute("SELECT rowid AS source_id, * FROM simulations").fetchall()
    count = 0
    for r in rows:
        r = dict(r)
        src_id = r.pop("source_id", None)
        sim_id = r.get("id")
        pg_conn.execute(
            """
            INSERT INTO simulations (
                source_id, bot_id, id, timestamp, kalshi_ticker, event_title,
                agent_count, rounds, mirofish_prob, kalshi_price_at_sim,
                gap, estimated_cost, traded
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (bot_id, id) DO NOTHING
            """,
            (
                src_id, bot_id, sim_id,
                r.get("timestamp"), r.get("kalshi_ticker"), r.get("event_title"),
                r.get("agent_count"), r.get("rounds"), r.get("mirofish_prob"),
                r.get("kalshi_price_at_sim"), r.get("gap"), r.get("estimated_cost"),
                bool(r.get("traded", False)),
            ),
        )
        count += 1
    pg_conn.commit()
    return count


def migrate_daily_stats(sqlite_conn, pg_conn, bot_id: str) -> int:
    rows = sqlite_conn.execute("SELECT * FROM daily_stats").fetchall()
    count = 0
    for r in rows:
        r = dict(r)
        pg_conn.execute(
            """
            INSERT INTO daily_stats (
                bot_id, date, trades_placed, trades_resolved, wins, losses,
                daily_pnl, cumulative_pnl, bankroll, accuracy
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (bot_id, date) DO NOTHING
            """,
            (
                bot_id,
                r.get("date"), r.get("trades_placed"), r.get("trades_resolved"),
                r.get("wins"), r.get("losses"), r.get("daily_pnl"),
                r.get("cumulative_pnl"), r.get("bankroll"), r.get("accuracy"),
            ),
        )
        count += 1
    pg_conn.commit()
    return count


def migrate_trades(sqlite_conn, pg_conn, bot_id: str) -> int:
    rows = sqlite_conn.execute("SELECT rowid AS source_id, * FROM trades").fetchall()
    count = 0
    for r in rows:
        r = dict(r)
        src_id = r.pop("source_id", None)
        r.pop("id", None)
        pg_conn.execute(
            """
            INSERT INTO trades (
                source_id, bot_id, timestamp, kalshi_ticker, event_title,
                side, contracts, entry_price_cents, mirofish_prob,
                kalshi_price_at_entry, gap, kelly_pct, dollar_amount,
                status, exit_price_cents, pnl, resolution_date,
                simulation_id, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (bot_id, source_id) DO NOTHING
            """,
            (
                src_id, bot_id,
                r.get("timestamp"), r.get("kalshi_ticker"), r.get("event_title"),
                r.get("side"), r.get("contracts"), r.get("entry_price_cents"),
                r.get("mirofish_prob"), r.get("kalshi_price_at_entry"),
                r.get("gap"), r.get("kelly_pct"), r.get("dollar_amount"),
                r.get("status"), r.get("exit_price_cents"), r.get("pnl"),
                r.get("resolution_date"), r.get("simulation_id"), r.get("notes"),
            ),
        )
        count += 1
    pg_conn.commit()
    return count


def _table_exists(sqlite_conn, table: str) -> bool:
    row = sqlite_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def migrate_bot(sqlite_path: str, bot_id: str, pg_conn) -> dict:
    print(f"\n=== Migrating Bot {bot_id} from {sqlite_path} ===")
    sqlite_conn = open_sqlite(sqlite_path)

    results = {}
    migrate_fns = {
        "alpaca_trades": migrate_alpaca_trades,
        "validations": migrate_validations,
        "screenings": migrate_screenings,
        "simulations": migrate_simulations,
        "daily_stats": migrate_daily_stats,
        "trades": migrate_trades,
    }

    for table, fn in migrate_fns.items():
        if not _table_exists(sqlite_conn, table):
            print(f"  [skip] {table} — table not in source SQLite")
            results[table] = 0
            continue
        count = fn(sqlite_conn, pg_conn, bot_id)
        # Verify count
        sqlite_count = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        pg_filter = "date" if table == "daily_stats" else "source_id IS NOT NULL"
        pg_count_row = pg_conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE bot_id = %s AND {pg_filter}",
            (bot_id,),
        ).fetchone()
        pg_count = pg_count_row["n"]
        status = "PASS" if pg_count >= sqlite_count else "FAIL"
        print(f"  [{status}] {table}: SQLite={sqlite_count}, Postgres={pg_count}")
        if status == "FAIL":
            print(f"  ERROR: row count mismatch for {table} bot {bot_id}", file=sys.stderr)
        results[table] = count

    sqlite_conn.close()
    return results


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite trade DBs to Postgres")
    parser.add_argument("--bot-a-db", required=True, help="Path to Bot A's trades.db")
    parser.add_argument("--bot-b-db", required=True, help="Path to Bot B's trades.db")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL env var not set", file=sys.stderr)
        sys.exit(1)

    # Validate source files exist
    for path, label in [(args.bot_a_db, "Bot A"), (args.bot_b_db, "Bot B")]:
        if not os.path.exists(path):
            print(f"ERROR: {label} DB not found: {path}", file=sys.stderr)
            sys.exit(1)

    print("Step 1: Backing up source databases...")
    backup_db(args.bot_a_db, "A")
    backup_db(args.bot_b_db, "B")

    print("\nStep 2: Connecting to Postgres...")
    pg_conn = get_pg_conn(database_url)
    print("  Connected.")

    print("\nStep 3: Migrating...")
    migrate_bot(args.bot_a_db, "A", pg_conn)
    migrate_bot(args.bot_b_db, "B", pg_conn)

    pg_conn.close()
    print("\n=== Migration complete ===")


if __name__ == "__main__":
    main()
