"""Seed Bot A and Bot B rows from env vars on first container start.

Reads ALPACA_API_KEY_A / ALPACA_SECRET_KEY_A (and B) env vars that are
already set on the dashboard Coolify app, plus optional per-bot config
overrides (BOT_A_LABEL, BOT_A_KELLY, etc.).  Skips any bot that already
has a row in the DB — safe to run on every startup.
"""
import logging
import os
import sys

import psycopg

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[seed] %(message)s")


def seed_bots() -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        log.info("DATABASE_URL not set — skipping seed")
        return

    bots = []

    key_a = os.environ.get("ALPACA_API_KEY_A")
    secret_a = os.environ.get("ALPACA_SECRET_KEY_A")
    if key_a and secret_a:
        bots.append({
            "bot_id": "A",
            "label": os.environ.get("BOT_A_LABEL", "Agent A"),
            "alpaca_api_key": key_a,
            "alpaca_secret_key": secret_a,
            "kelly_fraction": float(os.environ.get("BOT_A_KELLY", "0.25")),
            "min_confluence": int(os.environ.get("BOT_A_CONFLUENCE", "3")),
            "skip_risk_gate": os.environ.get("BOT_A_SKIP_RISK_GATE", "false").lower() == "true",
            "hard_stop_pct": float(os.environ.get("BOT_A_HARD_STOP_PCT", "-0.05")),
            "soft_stop_pct": float(os.environ.get("BOT_A_SOFT_STOP_PCT", "-0.03")),
            "rsi_ceiling": float(os.environ.get("BOT_A_RSI_CEILING", "65.0")),
            "crypto_universe": os.environ.get("BOT_A_CRYPTO_UNIVERSE", "BTC/USD,ETH/USD,SOL/USD,XRP/USD,ADA/USD,AVAX/USD,DOT/USD,LINK/USD"),
            "stock_universe": os.environ.get("BOT_A_STOCK_UNIVERSE", "QQQ,SPY,AAPL,NVDA,MSFT,TSLA,AMZN,META"),
            "max_position_pct": float(os.environ.get("BOT_A_MAX_POSITION_PCT", "0.05")),
        })

    key_b = os.environ.get("ALPACA_API_KEY_B")
    secret_b = os.environ.get("ALPACA_SECRET_KEY_B")
    if key_b and secret_b:
        bots.append({
            "bot_id": "B",
            "label": os.environ.get("BOT_B_LABEL", "Agent B"),
            "alpaca_api_key": key_b,
            "alpaca_secret_key": secret_b,
            "kelly_fraction": float(os.environ.get("BOT_B_KELLY", "0.50")),
            "min_confluence": int(os.environ.get("BOT_B_CONFLUENCE", "2")),
            "skip_risk_gate": os.environ.get("BOT_B_SKIP_RISK_GATE", "false").lower() == "true",
            "hard_stop_pct": float(os.environ.get("BOT_B_HARD_STOP_PCT", "-0.05")),
            "soft_stop_pct": float(os.environ.get("BOT_B_SOFT_STOP_PCT", "-0.03")),
            "rsi_ceiling": float(os.environ.get("BOT_B_RSI_CEILING", "65.0")),
            "crypto_universe": os.environ.get("BOT_B_CRYPTO_UNIVERSE", "BTC/USD,ETH/USD,SOL/USD,XRP/USD,ADA/USD,AVAX/USD,DOT/USD,LINK/USD"),
            "stock_universe": os.environ.get("BOT_B_STOCK_UNIVERSE", "QQQ,SPY,AAPL,NVDA,MSFT,TSLA,AMZN,META"),
            "max_position_pct": float(os.environ.get("BOT_B_MAX_POSITION_PCT", "0.05")),
        })

    if not bots:
        log.info("No ALPACA_API_KEY_A/B env vars found — skipping seed")
        return

    with psycopg.connect(db_url, autocommit=False) as conn:
        for bot in bots:
            count = conn.execute(
                "SELECT COUNT(*) FROM bots WHERE bot_id = %s", (bot["bot_id"],)
            ).fetchone()[0]
            if count == 0:
                conn.execute(
                    """
                    INSERT INTO bots (
                        id, bot_id, label, alpaca_api_key, alpaca_secret_key,
                        kelly_fraction, min_confluence, skip_risk_gate,
                        hard_stop_pct, soft_stop_pct, rsi_ceiling,
                        crypto_universe, stock_universe, max_position_pct, enabled, status
                    ) VALUES (
                        %(bot_id)s, %(bot_id)s, %(label)s, %(alpaca_api_key)s, %(alpaca_secret_key)s,
                        %(kelly_fraction)s, %(min_confluence)s, %(skip_risk_gate)s,
                        %(hard_stop_pct)s, %(soft_stop_pct)s, %(rsi_ceiling)s,
                        %(crypto_universe)s, %(stock_universe)s, %(max_position_pct)s, TRUE, 'stopped'
                    )
                    """,
                    bot,
                )
                log.info("Seeded bot %s (%s)", bot["bot_id"], bot["label"])
            else:
                # Always patch keys when they are NULL — handles the case where the
                # row was seeded before env vars were set on the Coolify app.
                conn.execute(
                    """
                    UPDATE bots SET
                        alpaca_api_key   = COALESCE(alpaca_api_key,   %(alpaca_api_key)s),
                        alpaca_secret_key = COALESCE(alpaca_secret_key, %(alpaca_secret_key)s)
                    WHERE bot_id = %(bot_id)s
                      AND (alpaca_api_key IS NULL OR alpaca_api_key = '')
                    """,
                    bot,
                )
                log.info("Bot %s already exists — skipped insert, patched NULL keys if any", bot["bot_id"])
        conn.commit()


if __name__ == "__main__":
    seed_bots()
