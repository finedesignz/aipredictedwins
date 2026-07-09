"""
TradeLogger — thin shim over src.db (Postgres).

The public API is identical to the old SQLite implementation so all
call sites (orchestrator, risk_gate, exit_advisor) work unchanged.

BOT_ID env var must be set to 'A' or 'B' before instantiating.
"""

import os
from src import db as _db

# Single source of truth for valid orchestrator bot ids (env-var path).
KNOWN_BOT_IDS = ("A", "B", "C", "D")


class TradeLogger:
    def __init__(self, db_path: str = "data/trades.db", bot_id: str | None = None):
        # db_path is ignored — kept for backward compat with call sites.
        # bot_id kwarg takes priority and accepts any non-empty string (multi-bot
        # uses arbitrary UUIDs).  When not supplied, falls back to the BOT_ID env
        # var, which retains the old 'A'/'B' validation for backward compat.
        if bot_id is not None:
            if not bot_id:
                raise ValueError("bot_id must be a non-empty string")
            self.bot_id = bot_id
        else:
            self.bot_id = os.environ.get("BOT_ID", "").upper()
            if self.bot_id not in KNOWN_BOT_IDS:
                raise ValueError(
                    f"BOT_ID env var must be one of {'/'.join(KNOWN_BOT_IDS)}, "
                    f"got {self.bot_id!r}. Set BOT_ID before starting the bot."
                )

    # ── Alpaca trades ──────────────────────────────────────────────────

    def log_alpaca_trade(self, trade_data: dict) -> int:
        return _db.log_alpaca_trade(self.bot_id, trade_data)

    def update_alpaca_trade(
        self, trade_id: int, status: str, exit_price: float = None, pnl: float = None
    ):
        _db.update_alpaca_trade(self.bot_id, trade_id, status, exit_price, pnl)

    def get_open_alpaca_positions(self) -> list[dict]:
        return _db.get_open_alpaca_positions(self.bot_id)

    def get_pending_alpaca_orders(self) -> list[dict]:
        return _db.get_pending_alpaca_orders(self.bot_id)

    def get_alpaca_accuracy(self, last_n: int = None) -> dict:
        return _db.get_alpaca_accuracy(self.bot_id, last_n)

    # ── Legacy Kalshi trades ───────────────────────────────────────────

    def log_trade(self, trade_data: dict) -> int:
        return _db.log_trade(self.bot_id, trade_data)

    def update_trade(
        self,
        trade_id: int,
        status: str,
        exit_price_cents: int = None,
        pnl: float = None,
    ):
        _db.update_trade(self.bot_id, trade_id, status, exit_price_cents, pnl)

    def get_open_positions(self) -> list[dict]:
        # Legacy Kalshi open positions (trades table)
        from src.db import connection
        with connection() as conn:
            return conn.execute(
                "SELECT * FROM trades WHERE bot_id = %s AND status = 'open' ORDER BY timestamp DESC",
                (self.bot_id,),
            ).fetchall()

    def get_accuracy(self, last_n: int = None) -> dict:
        return _db.get_accuracy(self.bot_id, last_n)

    def get_daily_summary(self) -> dict:
        return _db.get_daily_summary(self.bot_id)

    def get_simulated_tickers_today(self) -> set[str]:
        return _db.get_simulated_tickers_today(self.bot_id)

    def log_simulation(
        self,
        sim_id: str,
        market: dict,
        mirofish_prob: float,
        kalshi_price: float,
        estimated_cost: float,
    ):
        _db.log_simulation(self.bot_id, sim_id, market, mirofish_prob, kalshi_price, estimated_cost)

    # ── Validations ────────────────────────────────────────────────────

    def log_validation(self, data: dict) -> int:
        return _db.log_validation(self.bot_id, data)

    def log_screening(self, data: dict) -> int:
        return _db.log_screening(self.bot_id, data)

    def log_veto(self, market: dict, signal: dict, validation: dict) -> int:
        """Convenience wrapper — builds validation dict and calls log_validation."""
        return self.log_validation({
            "kalshi_ticker": market.get("ticker", ""),
            "event_title": market.get("title", market.get("event_title", "")),
            "mirofish_prob": signal.get("mirofish_prob", 0.0),
            "kalshi_price": signal.get("kalshi_price", 0.0),
            "gap": signal.get("gap", signal.get("abs_gap", 0.0)),
            "proposed_side": signal.get("direction", signal.get("side", "unknown")),
            "decision": "VETO",
            "confidence": validation.get("confidence"),
            "adjusted_probability": validation.get("adjusted_probability"),
            "size_multiplier": validation.get("size_multiplier", 0.0),
            "sentiment_report": validation.get("sentiment_report"),
            "news_report": validation.get("news_report"),
            "contrarian_report": validation.get("contrarian_report"),
            "risk_assessment": validation.get("risk_assessment", validation.get("risk_assessment_report")),
            "veto_reason": validation.get("veto_reason", validation.get("reasoning", "")),
        })

    def get_veto_history(self, last_n: int = 20) -> list[dict]:
        return _db.get_veto_history(self.bot_id, last_n)

    def export_csv(self, filepath: str):
        """Export all legacy Kalshi trades to CSV."""
        import csv
        import os as _os
        from src.db import connection
        _os.makedirs(_os.path.dirname(filepath) or ".", exist_ok=True)
        with connection() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE bot_id = %s ORDER BY timestamp",
                (self.bot_id,),
            ).fetchall()
        if not rows:
            return
        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
