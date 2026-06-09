"""
Trade Memory & Learning System

Tracks every trade decision with full context, analyzes outcomes,
extracts lessons, and adjusts strategy parameters dynamically.

Backed by Postgres via src.db — no SQLite dependency.

BOT_ID must be a non-empty string (e.g. 'A', 'B', 'C') before instantiating.
"""

import json
import logging
import os
from datetime import datetime, timezone

from src.db import connection

log = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Pure intraday-dimension helpers (Phase 8 — no DB, side-effect-free)
# ----------------------------------------------------------------------

def time_of_day_bucket(entry_iso: str | None) -> str:
    """Map an ISO-8601 entry timestamp to a UTC session label.

    Buckets (UTC hour): asia 00-07, eu 07-13, us_am 13-17, us_pm 17-21,
    off 21-24. Returns "unknown" if entry_iso is None or unparseable.
    """
    if not entry_iso:
        return "unknown"
    try:
        dt = datetime.fromisoformat(entry_iso)
    except (ValueError, TypeError):
        return "unknown"
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    h = dt.hour
    if h < 7:
        return "asia"
    if h < 13:
        return "eu"
    if h < 17:
        return "us_am"
    if h < 21:
        return "us_pm"
    return "off"


def volatility_regime(atr: float, price: float) -> str:
    """Classify volatility from ATR as a percentage of price.

    r = atr/price; low < 0.01, med 0.01-0.025, high >= 0.025.
    Returns "unknown" if atr <= 0 or price <= 0.
    """
    if atr is None or atr <= 0 or price is None or price <= 0:
        return "unknown"
    r = atr / price
    if r < 0.01:
        return "low"
    if r < 0.025:
        return "med"
    return "high"


class TradeMemory:
    """Self-learning trade memory that stores context, finds patterns, and advises
    future trades based on historical outcomes.

    Uses the shared Postgres pool from src.db.  Tables: trade_lessons,
    trade_context, strategy_scores (all with bot_id column).
    """

    def __init__(self, bot_id: str = "", db_path: str = "data/trades.db"):
        # db_path is ignored — kept for backward compat with call sites.
        # bot_id kwarg takes priority over BOT_ID env var, matching TradeLogger pattern.
        self.bot_id = bot_id or os.environ.get("BOT_ID", "")
        if not self.bot_id:
            raise ValueError(
                "bot_id must be provided. Pass bot_id= to __init__ or set the BOT_ID env var."
            )

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
        tod_bucket = time_of_day_bucket(timestamp)
        vol_regime = volatility_regime(
            trade_data.get("atr_value", 0.0),
            trade_data.get("price_at_entry", 0.0),
        )
        with connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO trade_context (
                    bot_id, trade_id, timestamp, symbol, signal_type, sentiment,
                    confidence, price_at_entry, price_change_24h, volume_24h,
                    trajectory, bull_arguments, bear_arguments,
                    similar_past_trades, time_of_day_bucket, volatility_regime, outcome
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'open')
                RETURNING id
                """,
                (
                    self.bot_id,
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
                    tod_bucket,
                    vol_regime,
                ),
            )
            row = cursor.fetchone()
            context_id = row["id"]
        log.info(
            "Recorded trade context #%d for %s (%s) -- %d similar past trades",
            context_id, symbol, signal_type, len(similar),
        )
        return context_id

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

        with connection() as conn:
            results = []
            seen_ids = set()

            # Tier 1: exact symbol + signal match
            rows = conn.execute(
                """
                SELECT tc.*, 3 AS relevance_weight
                FROM trade_context tc
                WHERE tc.bot_id = %s
                  AND tc.symbol = %s
                  AND tc.signal_type = %s
                  AND tc.sentiment BETWEEN %s AND %s
                ORDER BY tc.timestamp DESC
                LIMIT 10
                """,
                (self.bot_id, symbol, signal_type, sentiment_lo, sentiment_hi),
            ).fetchall()
            for row in rows:
                if row["id"] not in seen_ids:
                    results.append(dict(row))
                    seen_ids.add(row["id"])

            # Tier 2: same asset class + signal match
            if is_crypto:
                class_filter = "tc.symbol LIKE '%%/%%'"
            else:
                class_filter = "tc.symbol NOT LIKE '%%/%%'"

            rows = conn.execute(
                f"""
                SELECT tc.*, 2 AS relevance_weight
                FROM trade_context tc
                WHERE tc.bot_id = %s
                  AND {class_filter}
                  AND tc.signal_type = %s
                  AND tc.sentiment BETWEEN %s AND %s
                  AND tc.price_change_24h BETWEEN %s AND %s
                ORDER BY tc.timestamp DESC
                LIMIT 10
                """,
                (self.bot_id, signal_type, sentiment_lo, sentiment_hi, price_lo, price_hi),
            ).fetchall()
            for row in rows:
                if row["id"] not in seen_ids:
                    results.append(dict(row))
                    seen_ids.add(row["id"])

            # Tier 3: any asset + same signal within sentiment range
            rows = conn.execute(
                """
                SELECT tc.*, 1 AS relevance_weight
                FROM trade_context tc
                WHERE tc.bot_id = %s
                  AND tc.signal_type = %s
                  AND tc.sentiment BETWEEN %s AND %s
                ORDER BY tc.timestamp DESC
                LIMIT 10
                """,
                (self.bot_id, signal_type, sentiment_lo, sentiment_hi),
            ).fetchall()
            for row in rows:
                if row["id"] not in seen_ids:
                    results.append(dict(row))
                    seen_ids.add(row["id"])

        # Sort by relevance weight desc, then recency
        results.sort(key=lambda r: r["timestamp"], reverse=True)
        results.sort(key=lambda r: r["relevance_weight"], reverse=True)

        return results[:10]

    def update_trade_outcome(
        self,
        trade_id: int,
        outcome: str,
        pnl: float,
        hold_minutes: float | None = None,
    ):
        """Called when a trade closes. Updates the context record.

        Args:
            trade_id: The alpaca_trades.id of the closed trade.
            outcome: "win" or "loss".
            pnl: Realized profit/loss in dollars.
            hold_minutes: Optional holding time in minutes (computed at close).
                When None, the column is left unchanged (back-compat).
        """
        with connection() as conn:
            if hold_minutes is None:
                conn.execute(
                    """
                    UPDATE trade_context
                    SET outcome = %s, pnl = %s
                    WHERE bot_id = %s AND trade_id = %s
                    """,
                    (outcome, pnl, self.bot_id, trade_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE trade_context
                    SET outcome = %s, pnl = %s, hold_minutes = %s
                    WHERE bot_id = %s AND trade_id = %s
                    """,
                    (outcome, pnl, hold_minutes, self.bot_id, trade_id),
                )
        log.info("Updated trade context for trade_id=%d: outcome=%s pnl=$%.2f",
                 trade_id, outcome, pnl)

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
        with connection() as conn:
            # Get all closed trades without lessons yet, grouped by pattern
            rows = conn.execute(
                """
                SELECT id, trade_id, symbol, signal_type, sentiment, confidence,
                       price_at_entry, price_change_24h, volume_24h, trajectory,
                       outcome, pnl, time_of_day_bucket, volatility_regime, hold_minutes
                FROM trade_context
                WHERE bot_id = %s
                  AND outcome IN ('win', 'loss')
                ORDER BY signal_type, symbol
                """,
                (self.bot_id,),
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
                        bot_id, timestamp, lesson_type, symbol, signal_type, lesson,
                        confidence, sample_size, applies_to, active
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                    """,
                    (
                        self.bot_id,
                        timestamp,
                        lesson_type,
                        symbol,
                        signal_type,
                        lesson_text,
                        min(analysis["win_rate"], 1.0 - analysis["win_rate"]) * 2,
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
                        bot_id, timestamp, lesson_type, symbol, signal_type, lesson,
                        confidence, sample_size, applies_to, active
                    ) VALUES (%s, %s, 'threshold', NULL, %s, %s, %s, %s, %s, TRUE)
                    """,
                    (
                        self.bot_id,
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

            # Additive dimension-conditioned passes (Phase 8 / LEARN-05).
            # Group by (signal_type, dimension); skip NULL/"unknown" dimension
            # rows so legacy data never forms a bogus group. Existing lessons
            # above are untouched; advice key (symbol, signal_type) unchanged.
            for dim in ("time_of_day_bucket", "volatility_regime"):
                dim_groups: dict[tuple, list[dict]] = {}
                for t in trades:
                    dval = t.get(dim)
                    if not dval or dval == "unknown":
                        continue
                    dim_groups.setdefault((t["signal_type"], dval), []).append(t)

                for (signal_type, dval), group_trades in dim_groups.items():
                    if len(group_trades) < min_sample:
                        continue

                    analysis = self._analyze_pattern(group_trades)
                    lesson_text = (
                        f"Signal '{signal_type}' during {dim}={dval}: "
                        f"{analysis['win_rate']:.0%} win rate over "
                        f"{analysis['sample_size']} trades. "
                        f"Avg P&L: ${analysis['avg_pnl']:+.2f}."
                    )

                    applies_to = json.dumps({
                        "signal_type": signal_type,
                        "symbol": None,
                        "dimension": dim,
                        "dimension_value": dval,
                    })

                    conn.execute(
                        """
                        INSERT INTO trade_lessons (
                            bot_id, timestamp, lesson_type, symbol, signal_type, lesson,
                            confidence, sample_size, applies_to, active
                        ) VALUES (%s, %s, 'dimension', NULL, %s, %s, %s, %s, %s, TRUE)
                        """,
                        (
                            self.bot_id,
                            timestamp,
                            signal_type,
                            lesson_text,
                            min(analysis["win_rate"], 1.0 - analysis["win_rate"]) * 2,
                            analysis["sample_size"],
                            applies_to,
                        ),
                    )

                    new_lessons.append({
                        "lesson_type": "dimension",
                        "symbol": None,
                        "signal_type": signal_type,
                        "dimension": dim,
                        "dimension_value": dval,
                        "lesson": lesson_text,
                        "sample_size": analysis["sample_size"],
                        "win_rate": analysis["win_rate"],
                    })

            # Mark all closed trades as lesson-generated
            conn.execute(
                """
                UPDATE trade_context
                SET lesson_generated = TRUE
                WHERE bot_id = %s AND outcome IN ('win', 'loss') AND lesson_generated = FALSE
                """,
                (self.bot_id,),
            )

        log.info("Generated %d new lessons from trade patterns", len(new_lessons))
        return new_lessons

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
        recommended_threshold = (avg_win_sentiment + 0.50) / 2.0

        # Position sizing recommendation based on win rate
        if win_rate >= 0.60:
            recommended_position_pct = 0.05
        elif win_rate >= 0.50:
            recommended_position_pct = 0.04
        elif win_rate >= 0.40:
            recommended_position_pct = 0.03
        elif win_rate >= 0.30:
            recommended_position_pct = 0.02
        else:
            recommended_position_pct = 0.0

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
        with connection() as conn:
            rows = conn.execute(
                """
                SELECT signal_type, outcome, pnl
                FROM trade_context
                WHERE bot_id = %s AND outcome IN ('win', 'loss')
                """,
                (self.bot_id,),
            ).fetchall()

        if not rows:
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

        total_trades = sum(s["wins"] + s["losses"] for s in signal_stats.values())
        total_wins = sum(s["wins"] for s in signal_stats.values())
        overall_wr = total_wins / total_trades if total_trades > 0 else 0.5

        if overall_wr > 0.55 and total_trades >= 10:
            bullish_threshold = 0.51
            bearish_threshold = 0.49
        elif overall_wr < 0.40 and total_trades >= 10:
            bullish_threshold = 0.58
            bearish_threshold = 0.42
        else:
            bullish_threshold = 0.53
            bearish_threshold = 0.47

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

    def _get_active_lessons(self, symbol: str, signal_type: str) -> list[dict]:
        """Retrieve active lessons that apply to the given symbol/signal."""
        with connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM trade_lessons
                WHERE bot_id = %s
                  AND active = TRUE
                  AND (
                    (symbol = %s AND signal_type = %s)
                    OR (symbol IS NULL AND signal_type = %s)
                    OR (symbol = %s AND signal_type IS NULL)
                  )
                ORDER BY sample_size DESC, timestamp DESC
                LIMIT 10
                """,
                (self.bot_id, symbol, signal_type, signal_type, symbol),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def update_strategy_scores(self):
        """Recalculate win rates per signal_type per symbol.

        Called after lessons are generated to keep the strategy_scores table
        current.  Existing scores are deactivated and replaced.
        """
        with connection() as conn:
            # Deactivate all existing scores for this bot
            conn.execute(
                "UPDATE strategy_scores SET active = FALSE WHERE bot_id = %s",
                (self.bot_id,),
            )

            # Calculate per signal_type (all symbols)
            rows = conn.execute(
                """
                SELECT signal_type,
                       COUNT(*) AS total,
                       SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) AS wins,
                       AVG(pnl) AS avg_pnl
                FROM trade_context
                WHERE bot_id = %s AND outcome IN ('win', 'loss')
                GROUP BY signal_type
                """,
                (self.bot_id,),
            ).fetchall()

            timestamp = datetime.now(timezone.utc).isoformat()

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
                        bot_id, updated_at, signal_type, symbol, win_rate, avg_pnl,
                        total_trades, recommended_threshold,
                        recommended_position_pct, active
                    ) VALUES (%s, %s, %s, NULL, %s, %s, %s, %s, %s, TRUE)
                    """,
                    (self.bot_id, timestamp, row["signal_type"], wr, row["avg_pnl"],
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
                WHERE bot_id = %s AND outcome IN ('win', 'loss')
                GROUP BY signal_type, symbol
                HAVING COUNT(*) >= 2
                """,
                (self.bot_id,),
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
                        bot_id, updated_at, signal_type, symbol, win_rate, avg_pnl,
                        total_trades, recommended_threshold,
                        recommended_position_pct, active
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
                    """,
                    (self.bot_id, timestamp, row["signal_type"], row["symbol"], wr,
                     row["avg_pnl"], total, rec_threshold, rec_pos),
                )

            # Additive dimension passes (Phase 8 / LEARN-05): encode the
            # dimension into signal_type ("<signal_type>@<value>") so no schema
            # change is needed. Skip NULL/"unknown"; HAVING COUNT(*) >= 2.
            for dim_col in ("time_of_day_bucket", "volatility_regime"):
                rows = conn.execute(
                    f"""
                    SELECT signal_type, {dim_col} AS dim_value,
                           COUNT(*) AS total,
                           SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END) AS wins,
                           AVG(pnl) AS avg_pnl
                    FROM trade_context
                    WHERE bot_id = %s AND outcome IN ('win', 'loss')
                      AND {dim_col} IS NOT NULL AND {dim_col} <> 'unknown'
                    GROUP BY signal_type, {dim_col}
                    HAVING COUNT(*) >= 2
                    """,
                    (self.bot_id,),
                ).fetchall()

                for row in rows:
                    total = row["total"]
                    wins = row["wins"]
                    wr = wins / total if total > 0 else 0.0

                    if wr >= 0.60:
                        rec_threshold, rec_pos = 0.51, 0.05
                    elif wr >= 0.50:
                        rec_threshold, rec_pos = 0.53, 0.04
                    elif wr >= 0.40:
                        rec_threshold, rec_pos = 0.55, 0.03
                    else:
                        rec_threshold, rec_pos = 0.60, 0.0

                    encoded = f"{row['signal_type']}@{row['dim_value']}"
                    conn.execute(
                        """
                        INSERT INTO strategy_scores (
                            bot_id, updated_at, signal_type, symbol, win_rate, avg_pnl,
                            total_trades, recommended_threshold,
                            recommended_position_pct, active
                        ) VALUES (%s, %s, %s, NULL, %s, %s, %s, %s, %s, TRUE)
                        """,
                        (self.bot_id, timestamp, encoded, wr, row["avg_pnl"],
                         total, rec_threshold, rec_pos),
                    )

        log.info("Strategy scores updated")

    def get_strategy_report(self) -> str:
        """Return a human-readable report of what strategies are working
        and what are not.
        """
        with connection() as conn:
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
                WHERE bot_id = %s
                """,
                (self.bot_id,),
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
                WHERE bot_id = %s AND active = TRUE AND symbol IS NULL
                ORDER BY win_rate DESC
                """,
                (self.bot_id,),
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
                WHERE bot_id = %s AND active = TRUE AND symbol IS NOT NULL
                ORDER BY win_rate DESC
                """,
                (self.bot_id,),
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
                WHERE bot_id = %s AND active = TRUE
                ORDER BY sample_size DESC
                LIMIT 10
                """,
                (self.bot_id,),
            ).fetchall()

            if lessons:
                lines.append("ACTIVE LESSONS:")
                lines.append("-" * 50)
                for l in lessons:
                    lines.append(f"  [{l['lesson_type']:9s}] {l['lesson']}")
                lines.append("")

        # Dynamic thresholds (calls connection internally)
        thresholds = self.get_dynamic_thresholds()
        lines.append("DYNAMIC THRESHOLDS (recommended):")
        lines.append("-" * 50)
        lines.append(f"  Bullish threshold : {thresholds['bullish_threshold']:.2f}")
        lines.append(f"  Bearish threshold : {thresholds['bearish_threshold']:.2f}")
        lines.append(f"  Min position %    : {thresholds['min_position_pct']:.1%}")
        lines.append(f"  Max position %    : {thresholds['max_position_pct']:.1%}")
        lines.append("=" * 60)

        return "\n".join(lines)


def _sanitize_trade(trade: dict) -> dict:
    """Remove internal fields and prepare a trade dict for external use."""
    safe = {}
    for key in ("id", "trade_id", "symbol", "signal_type", "sentiment",
                "price_at_entry", "price_change_24h", "outcome", "pnl",
                "timestamp", "confidence", "trajectory"):
        if key in trade:
            safe[key] = trade[key]
    return safe
