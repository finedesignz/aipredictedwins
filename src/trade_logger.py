"""
SQLite trade logging module for the Kalshi prediction market trading bot.

Tracks trades, daily statistics, and simulation results with raw sqlite3.
"""

import csv
import os
import sqlite3
from datetime import datetime, timezone


class TradeLogger:
    """Manages a SQLite database for trade logging, stats, and simulation tracking."""

    def __init__(self, db_path: str = "data/trades.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    kalshi_ticker TEXT NOT NULL,
                    event_title TEXT NOT NULL,
                    side TEXT NOT NULL,
                    contracts INTEGER NOT NULL,
                    entry_price_cents INTEGER NOT NULL,
                    mirofish_prob REAL NOT NULL,
                    kalshi_price_at_entry REAL NOT NULL,
                    gap REAL NOT NULL,
                    kelly_pct REAL NOT NULL,
                    dollar_amount REAL NOT NULL,
                    status TEXT DEFAULT 'open',
                    exit_price_cents INTEGER,
                    pnl REAL,
                    resolution_date TEXT,
                    simulation_id TEXT,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS daily_stats (
                    date TEXT PRIMARY KEY,
                    trades_placed INTEGER,
                    trades_resolved INTEGER,
                    wins INTEGER,
                    losses INTEGER,
                    daily_pnl REAL,
                    cumulative_pnl REAL,
                    bankroll REAL,
                    accuracy REAL
                );

                CREATE TABLE IF NOT EXISTS simulations (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    kalshi_ticker TEXT NOT NULL,
                    event_title TEXT NOT NULL,
                    agent_count INTEGER,
                    rounds INTEGER,
                    mirofish_prob REAL,
                    kalshi_price_at_sim REAL,
                    gap REAL,
                    estimated_cost REAL,
                    traded BOOLEAN DEFAULT FALSE
                );

                CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
                CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(kalshi_ticker);
                CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
                CREATE INDEX IF NOT EXISTS idx_simulations_ticker ON simulations(kalshi_ticker);
                CREATE INDEX IF NOT EXISTS idx_simulations_timestamp ON simulations(timestamp);
            """)
            conn.commit()
        finally:
            conn.close()

    def log_trade(self, trade_data: dict) -> int:
        """Insert a new trade record. Returns the trade ID."""
        timestamp = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                INSERT INTO trades (
                    timestamp, kalshi_ticker, event_title, side, contracts,
                    entry_price_cents, mirofish_prob, kalshi_price_at_entry,
                    gap, kelly_pct, dollar_amount, simulation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
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
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def update_trade(
        self,
        trade_id: int,
        status: str,
        exit_price_cents: int = None,
        pnl: float = None,
    ):
        """Update a trade's status, exit price, and P&L."""
        resolution_date = (
            datetime.now(timezone.utc).isoformat()
            if status in ("won", "lost", "sold")
            else None
        )
        conn = self._get_conn()
        try:
            conn.execute(
                """
                UPDATE trades
                SET status = ?, exit_price_cents = ?, pnl = ?, resolution_date = ?
                WHERE id = ?
                """,
                (status, exit_price_cents, pnl, resolution_date, trade_id),
            )
            conn.commit()
        finally:
            conn.close()

    def log_simulation(
        self,
        sim_id: str,
        market: dict,
        mirofish_prob: float,
        kalshi_price: float,
        estimated_cost: float,
    ):
        """Log a simulation result."""
        timestamp = datetime.now(timezone.utc).isoformat()
        gap = mirofish_prob - kalshi_price
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO simulations (
                    id, timestamp, kalshi_ticker, event_title,
                    agent_count, rounds, mirofish_prob,
                    kalshi_price_at_sim, gap, estimated_cost
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sim_id,
                    timestamp,
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
            conn.commit()
        finally:
            conn.close()

    def get_open_positions(self) -> list[dict]:
        """Return all trades with status 'open'."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM trades WHERE status = 'open' ORDER BY timestamp DESC"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_accuracy(self, last_n: int = None) -> dict:
        """Return accuracy and P&L statistics for resolved trades."""
        conn = self._get_conn()
        try:
            if last_n:
                rows = conn.execute(
                    """
                    SELECT status, pnl, gap FROM trades
                    WHERE status IN ('won', 'lost')
                    ORDER BY resolution_date DESC
                    LIMIT ?
                    """,
                    (last_n,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT status, pnl, gap FROM trades
                    WHERE status IN ('won', 'lost')
                    ORDER BY resolution_date DESC
                    """
                ).fetchall()

            total_trades = conn.execute(
                "SELECT COUNT(*) FROM trades"
            ).fetchone()[0]

            resolved = len(rows)
            wins = sum(1 for r in rows if r["status"] == "won")
            losses = sum(1 for r in rows if r["status"] == "lost")
            total_pnl = sum(r["pnl"] or 0.0 for r in rows)
            avg_gap = (
                sum(r["gap"] for r in rows) / resolved if resolved > 0 else 0.0
            )
            win_rate = wins / resolved if resolved > 0 else 0.0

            return {
                "total_trades": total_trades,
                "resolved": resolved,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                "total_pnl": total_pnl,
                "avg_gap": avg_gap,
            }
        finally:
            conn.close()

    def get_daily_summary(self) -> dict:
        """Return today's trading stats."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        conn = self._get_conn()
        try:
            placed = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE timestamp LIKE ?",
                (f"{today}%",),
            ).fetchone()[0]

            resolved_rows = conn.execute(
                """
                SELECT status, pnl FROM trades
                WHERE resolution_date LIKE ? AND status IN ('won', 'lost')
                """,
                (f"{today}%",),
            ).fetchall()

            resolved = len(resolved_rows)
            wins = sum(1 for r in resolved_rows if r["status"] == "won")
            losses = sum(1 for r in resolved_rows if r["status"] == "lost")
            daily_pnl = sum(r["pnl"] or 0.0 for r in resolved_rows)
            accuracy = wins / resolved if resolved > 0 else 0.0

            return {
                "date": today,
                "trades_placed": placed,
                "trades_resolved": resolved,
                "wins": wins,
                "losses": losses,
                "daily_pnl": daily_pnl,
                "accuracy": accuracy,
            }
        finally:
            conn.close()

    def get_simulated_tickers_today(self) -> set[str]:
        """Return set of tickers already simulated today (for deduplication)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT DISTINCT kalshi_ticker FROM simulations WHERE timestamp LIKE ?",
                (f"{today}%",),
            ).fetchall()
            return {row["kalshi_ticker"] for row in rows}
        finally:
            conn.close()

    def export_csv(self, filepath: str):
        """Export all trades to a CSV file."""
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY timestamp"
            ).fetchall()
            if not rows:
                return

            columns = rows[0].keys()
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                for row in rows:
                    writer.writerow(dict(row))
        finally:
            conn.close()
