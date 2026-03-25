"""
Learning Loop -- background process that runs after each trade cycle.

Checks for newly closed trades, updates outcomes in trade_context,
generates lessons from patterns, updates strategy scores, and logs
a learning report.
"""

import logging
from datetime import datetime, timezone

from src.trade_logger import TradeLogger
from src.trade_memory import TradeMemory

log = logging.getLogger(__name__)


class LearningLoop:
    """Periodic learning cycle that turns trade outcomes into actionable
    intelligence.

    Designed to be called once per trade cycle (e.g. every 30 min) by the
    orchestrator, or run standalone for batch analysis.
    """

    def __init__(self, memory: TradeMemory, logger: TradeLogger):
        self.memory = memory
        self.logger = logger
        self.cycles_run = 0
        self.total_lessons_generated = 0

    def run_cycle(self) -> dict:
        """Run one learning cycle.

        Steps:
          1. Find newly closed Alpaca trades that lack context outcomes.
          2. Update their outcomes in trade_context.
          3. Generate lessons from accumulated patterns.
          4. Update strategy scores.
          5. Return a summary dict.

        Returns:
            dict with keys: outcomes_updated, lessons_generated,
            scores_updated, cycle_number.
        """
        self.cycles_run += 1
        cycle_start = datetime.now(timezone.utc).isoformat()
        outcomes_updated = 0
        lessons_generated = 0

        # Step 1 & 2: Sync closed Alpaca trades into trade_context
        outcomes_updated = self._sync_trade_outcomes()

        # Step 3: Generate lessons from patterns
        new_lessons = self.memory.generate_lessons(min_sample=3)
        lessons_generated = len(new_lessons)
        self.total_lessons_generated += lessons_generated

        # Step 4: Update strategy scores
        self.memory.update_strategy_scores()

        summary = {
            "cycle_number": self.cycles_run,
            "cycle_start": cycle_start,
            "outcomes_updated": outcomes_updated,
            "lessons_generated": lessons_generated,
            "total_lessons_to_date": self.total_lessons_generated,
            "new_lessons": new_lessons,
        }

        if outcomes_updated > 0 or lessons_generated > 0:
            log.info(
                "Learning cycle #%d: %d outcomes updated, %d new lessons",
                self.cycles_run, outcomes_updated, lessons_generated,
            )
        else:
            log.debug("Learning cycle #%d: no new data to learn from", self.cycles_run)

        return summary

    def _sync_trade_outcomes(self) -> int:
        """Find closed Alpaca trades whose trade_context outcome is still
        'open' and update them.

        Joins alpaca_trades (source of truth for close status) with
        trade_context (where we track learning state).

        Returns the number of outcomes updated.
        """
        conn = self.memory._get_conn()
        try:
            # Find closed alpaca trades that have a context record still marked open
            rows = conn.execute(
                """
                SELECT at.id AS trade_id,
                       at.status,
                       at.pnl,
                       at.exit_price,
                       tc.id AS context_id
                FROM alpaca_trades at
                INNER JOIN trade_context tc ON tc.trade_id = at.id
                WHERE tc.outcome = 'open'
                  AND at.status IN ('closed', 'stopped', 'target_hit')
                """
            ).fetchall()

            updated = 0
            for row in rows:
                pnl = row["pnl"] or 0.0
                outcome = "win" if pnl > 0 else "loss"
                self.memory.update_trade_outcome(
                    trade_id=row["trade_id"],
                    outcome=outcome,
                    pnl=pnl,
                )
                updated += 1

            return updated
        finally:
            conn.close()

    def print_report(self):
        """Print the current learning state to console."""
        report = self.memory.get_strategy_report()
        print(report)
        print(f"\nLearning cycles completed: {self.cycles_run}")
        print(f"Total lessons generated:   {self.total_lessons_generated}")

    def get_summary_for_log(self) -> str:
        """Return a compact one-line summary suitable for bot output logs."""
        thresholds = self.memory.get_dynamic_thresholds()
        wr = thresholds.get("overall_win_rate", 0)
        total = thresholds.get("total_closed_trades", 0)
        scores = thresholds.get("signal_scores", {})

        active_signals = [s for s, v in scores.items() if v.get("recommended")]
        avoid_signals = [s for s, v in scores.items() if not v.get("recommended") and v.get("trades", 0) >= 3]

        parts = [f"WR={wr:.0%} ({total} trades)"]
        if active_signals:
            parts.append(f"active=[{', '.join(active_signals)}]")
        if avoid_signals:
            parts.append(f"avoid=[{', '.join(avoid_signals)}]")

        return " | ".join(parts)
