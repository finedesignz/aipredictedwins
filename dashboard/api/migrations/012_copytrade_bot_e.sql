-- 012_copytrade_bot_e.sql
-- Adds tables for Bot E (ai4trade.ai copy-trader) state and signal ledger.
-- Schema already permits arbitrary bot_id (migration 009 dropped CHECK
-- constraints) and already has `strategy` column (migration 011). The only
-- new persistent state is the bearer token, the followed-leader list, and
-- a per-signal ledger used for client-side dedupe across restarts.

-- Per-bot copy-trade runtime state. One row per copy-trade bot (currently E).
CREATE TABLE IF NOT EXISTS copytrade_state (
    bot_id            TEXT PRIMARY KEY,
    base_url          TEXT NOT NULL DEFAULT 'https://ai4trade.ai',
    agent_id          BIGINT,
    claw_token        TEXT,                         -- bearer token from selfRegister
    agent_name        TEXT,
    agent_password    TEXT,                         -- stored so we can rebuild a session if token is rotated
    followed_leaders  JSONB DEFAULT '[]'::jsonb,    -- list of upstream agent_ids
    last_signal_id    BIGINT DEFAULT 0,             -- highest feed signal id seen (dedupe cursor)
    last_leader_pick_at TIMESTAMPTZ,                -- when Claude last chose leaders
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One row per platform signal we've seen, even if we couldn't act on it.
-- Lets us audit copy-trade decisions and avoid double-execution.
CREATE TABLE IF NOT EXISTS copytrade_signals (
    id              BIGSERIAL PRIMARY KEY,
    bot_id          TEXT NOT NULL,
    platform_signal_id BIGINT NOT NULL,             -- ai4trade `id` column
    leader_agent_id BIGINT,
    leader_name     TEXT,
    market          TEXT,                           -- "stock" | "crypto" | other
    symbol          TEXT,                           -- bare symbol as published
    mapped_symbol   TEXT,                           -- Alpaca-format symbol or NULL if unsupported
    signal_type     TEXT,                           -- "realtime" | "position" | "trade"
    side            TEXT,                           -- "buy" | "sell"
    entry_price     DOUBLE PRECISION,
    quantity        DOUBLE PRECISION,
    executed_at     TIMESTAMPTZ,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Action outcome
    action          TEXT NOT NULL DEFAULT 'pending',-- "executed" | "skipped_unsupported" | "skipped_dup" | "error"
    alpaca_order_id TEXT,
    alpaca_qty      DOUBLE PRECISION,
    error_detail    TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_copytrade_signals_bot_platform
    ON copytrade_signals (bot_id, platform_signal_id);
CREATE INDEX IF NOT EXISTS idx_copytrade_signals_bot_received
    ON copytrade_signals (bot_id, received_at DESC);
