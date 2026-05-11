"""One-shot seeder for Bot E (ai4trade.ai copy-trader).

Run this once after deploying migration 012:
  1. Inserts a `bots` row for Bot E (strategy='copytrade')
  2. Self-registers an agent on ai4trade.ai
  3. Inserts the matching `copytrade_state` row with the bearer token

Re-running is safe — both inserts are idempotent (ON CONFLICT DO NOTHING)
and selfRegister is skipped if a token already exists.

Required env vars:
  DATABASE_URL              -- Postgres connection string
  ALPACA_API_KEY_E          -- Bot E's own paper account key
  ALPACA_SECRET_KEY_E       -- Bot E's own paper account secret

Optional env vars:
  AI4TRADE_BASE_URL         -- defaults to https://ai4trade.ai
  AI4TRADE_AGENT_NAME       -- defaults to 'aipredictedwins-bot-e'
  AI4TRADE_AGENT_PASSWORD   -- generated if not provided
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sys

import psycopg

from src.ai4trade_client import AI4TradeClient, AI4TradeError

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("seed_bot_e")

BOT_ID = "E"


def _env(name: str, *, required: bool = False, default: str | None = None) -> str | None:
    val = os.environ.get(name, default)
    if required and not val:
        log.error("Missing required env var: %s", name)
        sys.exit(2)
    return val


def main() -> int:
    db_url = _env("DATABASE_URL", required=True)
    alpaca_key = _env("ALPACA_API_KEY_E", required=True)
    alpaca_secret = _env("ALPACA_SECRET_KEY_E", required=True)
    base_url = _env("AI4TRADE_BASE_URL", default="https://ai4trade.ai")
    agent_name = _env("AI4TRADE_AGENT_NAME", default="aipredictedwins-bot-e")
    agent_password = _env("AI4TRADE_AGENT_PASSWORD") or secrets.token_urlsafe(16)

    with psycopg.connect(db_url, autocommit=True) as conn:
        # 1. Upsert bots row.
        conn.execute(
            """
            INSERT INTO bots (
                bot_id, id, label, strategy, asset_class, enabled,
                alpaca_api_key, alpaca_secret_key,
                skip_risk_gate, max_position_pct
            ) VALUES (
                %s, %s, %s, 'copytrade', 'crypto', TRUE,
                %s, %s,
                TRUE, 1.0
            )
            ON CONFLICT (id) DO UPDATE SET
                strategy = EXCLUDED.strategy,
                alpaca_api_key = EXCLUDED.alpaca_api_key,
                alpaca_secret_key = EXCLUDED.alpaca_secret_key,
                enabled = TRUE
            """,
            (BOT_ID, BOT_ID, "Bot E — ai4trade Copy", alpaca_key, alpaca_secret),
        )
        log.info("Upserted bots row for %s", BOT_ID)

        # 2. Check if copytrade_state already exists with a token.
        row = conn.execute(
            "SELECT claw_token, agent_id FROM copytrade_state WHERE bot_id = %s",
            (BOT_ID,),
        ).fetchone()

        if row and row[0]:
            log.info("copytrade_state already populated (agent_id=%s) — skipping selfRegister", row[1])
            return 0

        # 3. Self-register on ai4trade.
        client = AI4TradeClient(base_url=base_url)
        try:
            data = client.self_register(name=agent_name, password=agent_password)
        except AI4TradeError as exc:
            log.error("ai4trade selfRegister failed: %s", exc)
            return 1
        log.info(
            "Registered agent on %s: id=%s name=%s initial_balance=%s",
            base_url, data.get("agent_id"), data.get("name"), data.get("initial_balance"),
        )

        # 4. Insert copytrade_state.
        conn.execute(
            """
            INSERT INTO copytrade_state (
                bot_id, base_url, agent_id, claw_token, agent_name,
                agent_password, followed_leaders, last_signal_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, 0)
            ON CONFLICT (bot_id) DO UPDATE SET
                base_url = EXCLUDED.base_url,
                agent_id = EXCLUDED.agent_id,
                claw_token = EXCLUDED.claw_token,
                agent_name = EXCLUDED.agent_name,
                agent_password = EXCLUDED.agent_password,
                updated_at = NOW()
            """,
            (
                BOT_ID,
                base_url,
                data.get("agent_id"),
                data["token"],
                data.get("name") or agent_name,
                agent_password,
                json.dumps([]),
            ),
        )
        log.info("Seeded copytrade_state for bot %s", BOT_ID)
    log.info("Done. Restart the dashboard container so BotManager picks up Bot E.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
