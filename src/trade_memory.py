"""
Trade Memory & Learning System

Tracks every trade decision with full context, analyzes outcomes,
extracts lessons, and adjusts strategy parameters dynamically.

Uses SQLite -- no vector DB dependency.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

log = logging.getLogger(__name__)


class TradeMemory:
    """Self-learning trade memory that stores context, finds patterns, and advises
    future trades based on historical outcomes.

    Sits on top of the existing trades.db used by TradeLogger.  Creates three
    additional tables (trade_lessons, trade_context, strategy_scores) without
    touching existing tables.
    """

    def __init__(self, db_path: str = "data/trades.db"):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db_path = db_path
        self._init_memory_tables()

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_memory_tables(self):
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS trade_lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    lesson_type TEXT NOT NULL,
                    symbol TEXT,
                    signal_type TEXT,
                    lesson TEXT NOT NULL,
                    confidence REAL,
                    sample_size INTEGER,
                    applies_to TEXT,
                    active BOOLEAN DEFAULT TRUE
                );

                CREATE TABLE IF NOT EXISTS trade_context (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id INTEGER,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    signal_type TEXT,
                    sentiment REAL,
                    confidence TEXT,
                    price_at_entry REAL,
                    price_change_24h REAL,
                    volume_24h REAL,
                    trajectory TEXT,
                    bull_arguments TEXT,
                    bear_arguments TEXT,
                    similar_past_trades TEXT,
                    outcome TEXT,
                    pnl REAL,
                    lesson_generated BOOLEAN DEFAULT FALSE
                );

                CREATE TABLE IF NOT EXISTS strategy_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    updated_at TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    symbol TEXT,
                    win_rate REAL,
                    avg_pnl REAL,
                    total_trades INTEGER,
                    recommended_threshold REAL,
                    recommended_position_pct REAL,
                    active BOOLEAN DEFAULT TRUE
                );

                CREATE INDEX IF NOT EXISTS idx_tc_symbol ON trade_context(symbol);
                CREATE INDEX IF NOT EXISTS idx_tc_signal ON trade_context(signal_type);
                CREATE INDEX IF NOT EXISTS idx_tc_outcome ON trade_context(outcome);
                CREATE INDEX IF NOT EXISTS idx_tc_trade_id ON trade_context(trade_id);
                CREATE INDEX IF NOT EXISTS idx_tl_signal ON trade_lessons(signal_type);
                CREATE INDEX IF NOT EXISTS idx_tl_active ON trade_lessons(active);
                CREATE INDEX IF NOT EXISTS idx_ss_signal ON strategy_scores(signal_type);
            """)
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_trade_context(self, trade_data: dict) -> int:
        """Called when a trade is placed. Stores full context including
        sentiment, arguments, and similar past trades.

        Expected keys:
            trade_id, symbol, signal_type, sentiment, price_at_entry
        Optional keys:
            confidence, price_change_24h, volume_24h, trajectory,
            bull_arguments (list), bear_arguments (list)

        Returns the context row ID.
        """
        symbol = trade_data["symbol"]
        signal_type = trade_data.get("signal_type", "unknown")
        sentiment = trade_data.get("sentiment", 0.5)
        price_change = trade_data.get("price_change_24h", 0.0)

        # Find similar past trades for reference
        similar = self.find_similar_trades(symbol, signal_type, sentiment, price_change)
        similar_ids = [t["id"] for t in similar[:10]]

        timestamp = datetime.now(timezone.utc).isoformat()
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                INSERT INTO trade_context (
                    trade_id, timestamp, symbol, signal_type, sentiment,
                    confidence, price_at_entry, price_change_24h, volume_24h,
                    trajectory, bull_arguments, bear_arguments,
                    similar_past_trades, outcome
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
                """,
                (
                    trade_data.get("trade_id"),
                    timestamp,
                    symbol,
                    signal_type,
                    sentiment,
                    trade_data.get("confidence"),
                    trade_data.get("price_at_entry", 0.0),
                    price_change,
                    trade_data.get("volume_24h", 0.0),
                    trade_data.get("trajectory"),
                    json.dumps(trade_data.get("bull_arguments", [])),
                    json.dumps(trade_data.get("bear_arguments", [])),
                    json.dumps(similar_ids),
                ),
            )
            conn.commit()
            context_id = cursor.lastrowid
            log.info(
                "Recorded trade context #%d for %s (%s) -- %d similar past trades",
                context_id, symbol, signal_type, len(similar),
            )
            return context_id
        finally:
            conn.close()

    def find_similar_trades(
        self,
        symbol: str,
        signal_type: str,
        sentiment: float,
        price_change: float,
    ) -> list[dict]:
        """Find past trades with similar conditions.

        Matching tiers (weighted by relevance):
          1. Exact symbol + signal_type match
          2. Same asset class + signal_type match (e.g. all crypto + bullish_divergence)
          3. Any asset + same signal_type within sentiment range

        Returns top 10 most similar, sorted by recency.
        """
        is_crypto = "/" in symbol
        sentiment_lo = sentiment - 0.10
        sentiment_hi = sentiment + 0.10
        price_lo = price_change - 2.0
        price_hi = price_change + 2.0

        conn = self._get_conn()
        try:
            results = []
            seen_ids = set()

            # Tier 1: exact symbol + signal match
            rows = conn.execute(
                """
                SELECT tc.*, 3 AS relevance_weight
                FROM trade_context tc
                WHERE tc.symbol = ?
                  AND tc.signal_type = ?
                  AND tc.sentiment BETWEEN ? AND ?
                ORDER BY tc.timestamp DESC
                LIMIT 10
                """,
                (symbol, signal_type, sentiment_lo, sentiment_hi),
            ).fetchall()
            for row in rows:
                d = dict(row)
                if d["id"] not in seen_ids:
                    results.append(d)
                    seen_ids.add(d["id"])

            # Tier 2: same asset class + signal match
            if is_crypto:
                class_filter = "tc.symbol LIKE '%/%'"
            else:
                class_filter = "tc.symbol NOT LIKE '%/%'"

            rows = conn.execute(
                f"""
                SELECT tc.*, 2 AS relevance_weight
                FROM trade_context tc
                WHERE {class_filter}
                  AND tc.signal_type = ?
                  AND tc.sentiment BETWEEN ? AND ?
                  AND tc.price_change_24h BETWEEN ? AND ?
                ORDER BY tc.timestamp DESC
                LIMIT 10
                """,
                (signal_type, sentiment_lo, sentiment_hi, price_lo, price_hi),
            ).fetchall()
            for row in rows:
                d = dict(row)
                if d["id"] not in seen_ids:
                    results.append(d)
                    seen_ids.add(d["id"])

            # Tier 3: any asset + same signal within sentiment range
            rows = conn.execute(
                """
                SELECT tc.*, 1 AS relevance_weight
                FROM trade_context tc
                WHERE tc.signal_type = ?
                  AND tc.sentiment BETWEEN ? AND ?
                ORDER BY tc.timestamp DESC
                LIMIT 10
                """,
                (signal_type, sentiment_lo, sentiment_hi),
            ).fetchall()
            for row in rows:
                d = dict(row)
                if d["id"] not in seen_ids:
                    results.append(d)
                    seen_ids.add(d["id"])

            # Sort by relevance weight desc, then recency
            results.sort(key=lambda r: (-r["relevance_weight"], r["timestamp"]), reverse=False)
            # Actually: highest weight first, then most recent first within weight
            results.sort(key=lambda r: (-r["relevance_weight"], ""), reverse=False)
            # Stable sort by timestamp desc within each weight group
            results.sort(key=lambda r: r["timestamp"], reverse=True)
            results.sort(key=lambda r: r["relevance_weight"], reverse=True)

            return results[:10]
        finally:
            conn.close()

    def update_trade_outcome(self, trade_id: int, outcome: str, pnl: float):
        """Called when a trade closes. Updates the context record.

        Args:
            trade_id: The alpaca_trades.id of the closed trade.
            outcome: "win" or "loss".
            pnl: Realized profit/loss in dollars.
        """
        conn = self._get_conn()
        try:
            conn.execute(
                """
                UPDATE trade_context
                SET outcome = ?, pnl = ?
                WHERE trade_id = ?
                """,
                (outcome, pnl, trade_id),
            )
            conn.commit()
            log.info("Updated trade context for trade_id=%d: outcome=%s pnl=$%.2f",
                     trade_id, outcome, pnl)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Learning
    # ------------------------------------------------------------------

    def generate_lessons(self, min_sample: int = 3) -> list[dict]:
        """Analyze closed trades and generate lessons.

        Groups trades by signal_type + symbol, calculates win rates, and
        writes natural-language lessons when we have >= min_sample closed
        trades for a pattern.

        Returns list of newly created lesson dicts.
        """
        conn = self._get_conn()
        try:
            # Get all closed trades without lessons yet, grouped by pattern
            rows = conn.execute(
                """
                SELECT id, trade_id, symbol, signal_type, sentiment, confidence,
                       price_at_entry, price_change_24h, volume_24h, trajectory,
                       outcome, pnl
                FROM trade_context
                WHERE outcome IN ('win', 'loss')
                ORDER BY signal_type, symbol
                """
            ).fetchall()

            if not rows:
                return []

            trades = [dict(r) for r in rows]

            # Group by (signal_type, symbol)
            groups: dict[tuple, list[dict]] = {}
            for t in trades:
                key = (t["signal_type"], t["symbol"])
                groups.setdefault(key, []).append(t)

            # Also group by signal_type alone (cross-symbol patterns)
            signal_groups: dict[str, list[dict]] = {}
            for t in trades:
                signal_groups.setdefault(t["signal_type"], []).append(t)

            new_lessons = []
            timestamp = datetime.now(timezone.utc).isoformat()

            # Per-symbol lessons
            for (signal_type, symbol), group_trades in groups.items():
                if len(group_trades) < min_sample:
                    continue

                analysis = self._analyze_pattern(group_trades)
                lesson_text = (
                    f"Pattern '{signal_type}' on {symbol}: "
                    f"{analysis['win_rate']:.0%} win rate over {analysis['sample_size']} trades. "
                    f"Avg P&L: ${analysis['avg_pnl']:+.2f}. "
                )
                if analysis["win_rate"] < 0.30:
                    lesson_text += f"AVOID this pattern on {symbol} -- consistently losing."
                    lesson_type = "asset"
                elif analysis["win_rate"] > 0.60:
                    lesson_text += f"INCREASE size for this pattern on {symbol} -- strong performer."
                    lesson_type = "asset"
                else:
                    lesson_text += "Moderate performance -- use default sizing."
                    lesson_type = "pattern"

                applies_to = json.dumps({
                    "signal_type": signal_type,
                    "symbol": symbol,
                })

                conn.execute(
                    """
                    INSERT INTO trade_lessons (
                        timestamp, lesson_type, symbol, signal_type, lesson,
                        confidence, sample_size, applies_to, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, TRUE)
                    """,
                    (
                        timestamp,
                        lesson_type,
                        symbol,
                        signal_type,
                        lesson_text,
                        min(analysis["win_rate"], 1.0 - analysis["win_rate"]) * 2,  # confidence based on clarity
                        analysis["sample_size"],
                        applies_to,
                    ),
                )

                new_lessons.append({
                    "lesson_type": lesson_type,
                    "symbol": symbol,
                    "signal_type": signal_type,
                    "lesson": lesson_text,
                    "sample_size": analysis["sample_size"],
                    "win_rate": analysis["win_rate"],
                })

            # Cross-symbol signal lessons
            for signal_type, group_trades in signal_groups.items():
                if len(group_trades) < min_sample:
                    continue

                analysis = self._analyze_pattern(group_trades)
                lesson_text = (
                    f"Signal '{signal_type}' across all assets: "
                    f"{analysis['win_rate']:.0%} win rate over {analysis['sample_size']} trades. "
                    f"Avg P&L: ${analysis['avg_pnl']:+.2f}. "
                )
                if analysis["win_rate"] < 0.35:
                    lesson_text += "Consider DISABLING this signal type entirely."
                elif analysis["win_rate"] > 0.55:
                    lesson_text += "This signal type is working well -- keep it active."
                else:
                    lesson_text += "Marginal performance -- monitor closely."

                applies_to = json.dumps({
                    "signal_type": signal_type,
                    "symbol": None,
                })

                conn.execute(
                    """
                    INSERT INTO trade_lessons (
                        timestamp, lesson_type, symbol, signal_type, lesson,
                        confidence, sample_size, applies_to, active
                    ) VALUES (?, 'threshold', NULL, ?, ?, ?, ?, ?, TRUE)
                    """,
                    (
                        timestamp,
                        signal_type,
                        lesson_text,
                        min(analysis["win_rate"], 1.0 - analysis["win_rate"]) * 2,
                        analysis["sample_size"],
                        applies_to,
                    ),
                )

                new_lessons.append({
                    "lesson_type": "threshold",
                    "symbol": None,
                    "signal_type": signal_type,
                    "lesson": lesson_text,
                    "sample_size": analysis["sample_size"],
                    "win_rate": analysis["win_rate"],
                })

            # Mark all closed trades as lesson-generated
            conn.execute(
                """
                UPDATE trade_context
                SET lesson_generated = TRUE
                WHERE outcome IN ('win', 'loss') AND lesson_generated = FALSE
                """
            )
            conn.commit()

            log.info("Generated %d new lessons from trade patterns", len(new_lessons))
            return new_lessons
        finally:
            conn.close()

    def _analyze_pattern(self, trades: list[dict]) -> dict:
        """For a group of similar trades, calculate statistics and
        recommend threshold/position adjustments.

        Returns:
            dict with: win_rate, avg_pnl, sample_size, common_conditions,
            recommended_threshold, recommended_position_size.
        """
        total = len(trades)
        wins = sum(1 for t in trades if t["outcome"] == "win")
        win_rate = wins / total if total > 0 else 0.0
        avg_pnl = sum(t.get("pnl", 0) or 0 for t in trades) / total if total > 0 else 0.0
        avg_sentiment = sum(t.get("sentiment", 0.5) or 0.5 for t in trades) / total if total > 0 else 0.5

        # Determine recommended threshold based on where wins cluster
        winning_trades = [t for t in trades if t["outcome"] == "win"]
        if winning_trades:
            avg_win_sentiment = sum(t.get("sentiment", 0.5) or 0.5 for t in winning_trades) / len(winning_trades)
        else:
            avg_win_sentiment = 0.5

        # Recommended threshold: midpoint between average sentiment and neutral
        # If wins happen at higher sentiment, raise the threshold
        recommended_threshold = (avg_win_sentiment + 0.50) / 2.0

        # Position sizing recommendation based on win rate
        if win_rate >= 0.60:
            recommended_position_pct = 0.05  # max allowed
        elif win_rate >= 0.50:
            recommended_position_pct = 0.04
        elif win_rate >= 0.40:
            recommended_position_pct = 0.03
        elif win_rate >= 0.30:
            recommended_position_pct = 0.02
        else:
            recommended_position_pct = 0.0  # don't trade

        # Common conditions
        sentiments = [t.get("sentiment", 0.5) for t in trades]
        price_changes = [t.get("price_change_24h", 0) or 0 for t in trades]

        return {
            "win_rate": win_rate,
            "avg_pnl": avg_pnl,
            "sample_size": total,
            "avg_sentiment": avg_sentiment,
            "common_conditions": {
                "sentiment_range": [min(sentiments), max(sentiments)],
                "price_change_range": [min(price_changes), max(price_changes)],
            },
            "recommended_threshold": round(recommended_threshold, 3),
            "recommended_position_size": recommended_position_pct,
        }

    # ------------------------------------------------------------------
    # Advising
    # ------------------------------------------------------------------

    def get_advice(
        self,
        symbol: str,
        signal_type: str,
        sentiment: float,
        price_change: float,
    ) -> dict:
        """Called before placing a trade. Returns an advice dict with
        should_trade, confidence_adjustment, similar trades, lessons,
        win rate, and reasoning.
        """
        similar = self.find_similar_trades(symbol, signal_type, sentiment, price_change)
        lessons = self._get_active_lessons(symbol, signal_type)

        if not similar:
            return {
                "should_trade": True,
                "confidence_adjustment": 1.0,
                "similar_trades": [],
                "lessons": lessons,
                "win_rate_for_pattern": None,
                "sample_size": 0,
                "reasoning": f"No historical data for '{signal_type}' on {symbol} -- proceeding with default sizing.",
            }

        closed = [t for t in similar if t.get("outcome") in ("win", "loss")]
        if len(closed) < 2:
            return {
                "should_trade": True,
                "confidence_adjustment": 1.0,
                "similar_trades": [_sanitize_trade(t) for t in similar[:5]],
                "lessons": lessons,
                "win_rate_for_pattern": None,
                "sample_size": len(closed),
                "reasoning": (
                    f"Only {len(closed)} closed similar trade(s) for '{signal_type}' on {symbol} "
                    f"-- insufficient data, proceeding with default sizing."
                ),
            }

        win_rate = sum(1 for t in closed if t["outcome"] == "win") / len(closed)
        avg_pnl = sum(t.get("pnl", 0) or 0 for t in closed) / len(closed)

        # Decision rules
        if win_rate < 0.30 and len(closed) >= 3:
            should_trade = False
            adjustment = 0.0
        elif win_rate < 0.50:
            should_trade = True
            adjustment = 0.5
        elif win_rate > 0.60:
            should_trade = True
            adjustment = min(1.5, 1.0 + (win_rate - 0.60))
        else:
            should_trade = True
            adjustment = 1.0

        return {
            "should_trade": should_trade,
            "confidence_adjustment": adjustment,
            "similar_trades": [_sanitize_trade(t) for t in similar[:5]],
            "lessons": lessons,
            "win_rate_for_pattern": win_rate,
            "sample_size": len(closed),
            "reasoning": (
                f"Pattern '{signal_type}' on {symbol}: {win_rate:.0%} win rate "
                f"over {len(closed)} trades (avg P&L: ${avg_pnl:+.2f})"
            ),
        }

    def get_dynamic_thresholds(self) -> dict:
        """Return adjusted thresholds based on what signal types are
        actually working, derived from closed trade outcomes.
        """
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT signal_type, outcome, pnl
                FROM trade_context
                WHERE outcome IN ('win', 'loss')
                """
            ).fetchall()

            if not rows:
                # No data -- return safe defaults
                return {
                    "bullish_threshold": 0.53,
                    "bearish_threshold": 0.47,
                    "min_position_pct": 0.02,
                    "max_position_pct": 0.05,
                    "signal_scores": {},
                }

            # Group by signal_type
            signal_stats: dict[str, dict] = {}
            for row in rows:
                st = row["signal_type"] or "unknown"
                if st not in signal_stats:
                    signal_stats[st] = {"wins": 0, "losses": 0, "total_pnl": 0.0}
                if row["outcome"] == "win":
                    signal_stats[st]["wins"] += 1
                else:
                    signal_stats[st]["losses"] += 1
                signal_stats[st]["total_pnl"] += row["pnl"] or 0.0

            signal_scores = {}
            for st, stats in signal_stats.items():
                total = stats["wins"] + stats["losses"]
                wr = stats["wins"] / total if total > 0 else 0.0
                signal_scores[st] = {
                    "win_rate": round(wr, 3),
                    "trades": total,
                    "avg_pnl": round(stats["total_pnl"] / total, 2) if total > 0 else 0.0,
                    "recommended": wr >= 0.40 and total >= 3,
                }

            # Adjust thresholds based on overall performance
            total_trades = sum(s["wins"] + s["losses"] for s in signal_stats.values())
            total_wins = sum(s["wins"] for s in signal_stats.values())
            overall_wr = total_wins / total_trades if total_trades > 0 else 0.5

            # If we're winning a lot, we can be slightly less selective
            # If we're losing, raise the bar
            if overall_wr > 0.55 and total_trades >= 10:
                bullish_threshold = 0.51
                bearish_threshold = 0.49
            elif overall_wr < 0.40 and total_trades >= 10:
                bullish_threshold = 0.58
                bearish_threshold = 0.42
            else:
                bullish_threshold = 0.53
                bearish_threshold = 0.47

            # Position sizing: tighten if losing, loosen if winning
            if overall_wr > 0.55:
                min_pos = 0.02
                max_pos = 0.05
            elif overall_wr < 0.40:
                min_pos = 0.01
                max_pos = 0.03
            else:
                min_pos = 0.02
                max_pos = 0.04

            return {
                "bullish_threshold": bullish_threshold,
                "bearish_threshold": bearish_threshold,
                "min_position_pct": min_pos,
                "max_position_pct": max_pos,
                "signal_scores": signal_scores,
                "overall_win_rate": round(overall_wr, 3),
                "total_closed_trades": total_trades,
            }
        finally:
            conn.close()

    def _get_active_lessons(self, symbol: str, signal_type: str) -> list[dict]:
        """Retrieve active lessons that apply to the given symbol/signal."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT * FROM trade_lessons
                WHERE active = TRUE
                  AND (
                    (symbol = ? AND signal_type = ?)
                    OR (symbol IS NULL AND signal_type = ?)
                    OR (symbol = ? AND signal_type IS NULL)
                  )
                ORDER BY sample_size DESC, timestamp DESC
                LIMIT 10
                """,
                (symbol, signal_type, signal_type, symbol),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def update_strategy_scores(self):
        """Recalculate win rates per signal_type per symbol.

        Called after lessons are generated to keep the strategy_scores table
        current.  Existing scores are deactivated and replaced.
        """
        conn = self._get_conn()
        try:
            # Deactivate all existing scores
            conn.execute("UPDATE strategy_scores SET active = FALSE")

            # Calculate per signal_type (all symbols)
            rows = conn.execute(
                """
                SELECT signal_type,
                       COUNT(*) AS total,
                       SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) AS wins,
                       AVG(pnl) AS avg_pnl
                FROM trade_context
                WHERE outcome IN ('win', 'loss')
                GROUP BY signal_type
                """
            ).fetchall()

            timestamp = datetime.now(timezone.utc).isoformat()

            for row in rows:
                total = row["total"]
                wins = row["wins"]
                wr = wins / total if total > 0 else 0.0

                # Threshold and position recommendations
                if wr >= 0.60:
                    rec_threshold = 0.51
                    rec_pos = 0.05
                elif wr >= 0.50:
                    rec_threshold = 0.53
                    rec_pos = 0.04
                elif wr >= 0.40:
                    rec_threshold = 0.55
                    rec_pos = 0.03
                else:
                    rec_threshold = 0.60
                    rec_pos = 0.0

                conn.execute(
                    """
                    INSERT INTO strategy_scores (
                        updated_at, signal_type, symbol, win_rate, avg_pnl,
                        total_trades, recommended_threshold,
                        recommended_position_pct, active
                    ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, TRUE)
                    """,
                    (timestamp, row["signal_type"], wr, row["avg_pnl"],
                     total, rec_threshold, rec_pos),
                )

            # Calculate per signal_type + symbol
            rows = conn.execute(
                """
                SELECT signal_type, symbol,
                       COUNT(*) AS total,
                       SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) AS wins,
                       AVG(pnl) AS avg_pnl
                FROM trade_context
                WHERE outcome IN ('win', 'loss')
                GROUP BY signal_type, symbol
                HAVING COUNT(*) >= 2
                """
            ).fetchall()

            for row in rows:
                total = row["total"]
                wins = row["wins"]
                wr = wins / total if total > 0 else 0.0

                if wr >= 0.60:
                    rec_threshold = 0.51
                    rec_pos = 0.05
                elif wr >= 0.50:
                    rec_threshold = 0.53
                    rec_pos = 0.04
                elif wr >= 0.40:
                    rec_threshold = 0.55
                    rec_pos = 0.03
                else:
                    rec_threshold = 0.60
                    rec_pos = 0.0

                conn.execute(
                    """
                    INSERT INTO strategy_scores (
                        updated_at, signal_type, symbol, win_rate, avg_pnl,
                        total_trades, recommended_threshold,
                        recommended_position_pct, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, TRUE)
                    """,
                    (timestamp, row["signal_type"], row["symbol"], wr,
                     row["avg_pnl"], total, rec_threshold, rec_pos),
                )

            conn.commit()
            log.info("Strategy scores updated")
        finally:
            conn.close()

    def get_strategy_report(self) -> str:
        """Return a human-readable report of what strategies are working
        and what are not.
        """
        conn = self._get_conn()
        try:
            # Overall stats
            overall = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN outcome = 'loss' THEN 1 ELSE 0 END) AS losses,
                       SUM(CASE WHEN outcome = 'open' THEN 1 ELSE 0 END) AS open_count,
                       AVG(CASE WHEN outcome IN ('win', 'loss') THEN pnl END) AS avg_pnl,
                       SUM(CASE WHEN outcome IN ('win', 'loss') THEN pnl ELSE 0 END) AS total_pnl
                FROM trade_context
                """
            ).fetchone()

            total = overall["total"] or 0
            wins = overall["wins"] or 0
            losses = overall["losses"] or 0
            open_count = overall["open_count"] or 0
            avg_pnl = overall["avg_pnl"] or 0
            total_pnl = overall["total_pnl"] or 0
            closed = wins + losses
            wr = wins / closed if closed > 0 else 0

            lines = [
                "=" * 60,
                "TRADE MEMORY -- STRATEGY REPORT",
                "=" * 60,
                f"Total trades tracked: {total} ({open_count} open, {closed} closed)",
                f"Win rate: {wr:.1%} ({wins}W / {losses}L)",
                f"Total P&L: ${total_pnl:+,.2f}  |  Avg P&L: ${avg_pnl:+,.2f}",
                "",
            ]

            # Per-signal breakdown
            scores = conn.execute(
                """
                SELECT * FROM strategy_scores
                WHERE active = TRUE AND symbol IS NULL
                ORDER BY win_rate DESC
                """
            ).fetchall()

            if scores:
                lines.append("SIGNAL TYPE PERFORMANCE:")
                lines.append("-" * 50)
                for s in scores:
                    status = "RECOMMENDED" if s["recommended_position_pct"] > 0 else "AVOID"
                    lines.append(
                        f"  {s['signal_type']:25s} | "
                        f"WR: {s['win_rate']:.0%} | "
                        f"Trades: {s['total_trades']:3d} | "
                        f"Avg P&L: ${s['avg_pnl']:+6.2f} | "
                        f"{status}"
                    )
                lines.append("")

            # Per-symbol breakdown (top and bottom performers)
            symbol_scores = conn.execute(
                """
                SELECT * FROM strategy_scores
                WHERE active = TRUE AND symbol IS NOT NULL
                ORDER BY win_rate DESC
                """
            ).fetchall()

            if symbol_scores:
                lines.append("TOP PERFORMING SYMBOL + SIGNAL COMBOS:")
                lines.append("-" * 50)
                for s in symbol_scores[:5]:
                    lines.append(
                        f"  {s['symbol']:12s} + {s['signal_type']:20s} | "
                        f"WR: {s['win_rate']:.0%} | "
                        f"Trades: {s['total_trades']}"
                    )

                worst = [s for s in symbol_scores if s["win_rate"] < 0.40]
                if worst:
                    lines.append("")
                    lines.append("WORST PERFORMING (consider avoiding):")
                    lines.append("-" * 50)
                    for s in worst[:5]:
                        lines.append(
                            f"  {s['symbol']:12s} + {s['signal_type']:20s} | "
                            f"WR: {s['win_rate']:.0%} | "
                            f"Trades: {s['total_trades']}"
                        )
                lines.append("")

            # Active lessons
            lessons = conn.execute(
                """
                SELECT * FROM trade_lessons
                WHERE active = TRUE
                ORDER BY sample_size DESC
                LIMIT 10
                """
            ).fetchall()

            if lessons:
                lines.append("ACTIVE LESSONS:")
                lines.append("-" * 50)
                for l in lessons:
                    lines.append(f"  [{l['lesson_type']:9s}] {l['lesson']}")
                lines.append("")

            # Dynamic thresholds
            thresholds = self.get_dynamic_thresholds()
            lines.append("DYNAMIC THRESHOLDS (recommended):")
            lines.append("-" * 50)
            lines.append(f"  Bullish threshold : {thresholds['bullish_threshold']:.2f}")
            lines.append(f"  Bearish threshold : {thresholds['bearish_threshold']:.2f}")
            lines.append(f"  Min position %    : {thresholds['min_position_pct']:.1%}")
            lines.append(f"  Max position %    : {thresholds['max_position_pct']:.1%}")
            lines.append("=" * 60)

            return "\n".join(lines)
        finally:
            conn.close()


def _sanitize_trade(trade: dict) -> dict:
    """Remove internal fields and prepare a trade dict for external use."""
    safe = {}
    for key in ("id", "trade_id", "symbol", "signal_type", "sentiment",
                "price_at_entry", "price_change_24h", "outcome", "pnl",
                "timestamp", "confidence", "trajectory"):
        if key in trade:
            safe[key] = trade[key]
    return safe
