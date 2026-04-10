-- 002_multi_bot.sql
-- Expands bots table for multi-bot support and drops bot_id CHECK constraint

-- 1. Drop the CHECK constraint on alpaca_trades.bot_id (if it exists)
ALTER TABLE alpaca_trades DROP CONSTRAINT IF EXISTS alpaca_trades_bot_id_check;

-- 2. Add new columns to bots table (all IF NOT EXISTS to be idempotent)
ALTER TABLE bots
    ADD COLUMN IF NOT EXISTS bot_id            VARCHAR(10),
    ADD COLUMN IF NOT EXISTS alpaca_api_key    VARCHAR(200),
    ADD COLUMN IF NOT EXISTS alpaca_secret_key VARCHAR(200),
    ADD COLUMN IF NOT EXISTS kelly_fraction    FLOAT   DEFAULT 0.25,
    ADD COLUMN IF NOT EXISTS min_confluence    INT     DEFAULT 3,
    ADD COLUMN IF NOT EXISTS hard_stop_pct     FLOAT   DEFAULT -0.08,
    ADD COLUMN IF NOT EXISTS soft_stop_pct     FLOAT   DEFAULT -0.05,
    ADD COLUMN IF NOT EXISTS rsi_ceiling       FLOAT   DEFAULT 65.0,
    ADD COLUMN IF NOT EXISTS crypto_universe   TEXT    DEFAULT 'BTC/USD,ETH/USD,SOL/USD,XRP/USD',
    ADD COLUMN IF NOT EXISTS skip_risk_gate    BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS max_position_pct  FLOAT   DEFAULT 0.05,
    ADD COLUMN IF NOT EXISTS enabled           BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS status            VARCHAR(20) DEFAULT 'stopped',
    ADD COLUMN IF NOT EXISTS status_detail     TEXT,
    ADD COLUMN IF NOT EXISTS updated_at        TIMESTAMPTZ DEFAULT NOW();

-- 3. Backfill bot_id from existing id column for rows that don't have it yet
UPDATE bots SET bot_id = id::text WHERE bot_id IS NULL;

-- 4. Add unique constraint on bot_id (only if not already present)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'bots_bot_id_unique'
    ) THEN
        ALTER TABLE bots ADD CONSTRAINT bots_bot_id_unique UNIQUE (bot_id);
    END IF;
END$$;

-- 5. Enforce NOT NULL on bot_id now that all rows are backfilled
ALTER TABLE bots ALTER COLUMN bot_id SET NOT NULL;
