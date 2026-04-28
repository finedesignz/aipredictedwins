-- 009_tradingagents.sql
ALTER TABLE bots
    ADD COLUMN IF NOT EXISTS min_short_confluence  INT     DEFAULT 3,
    ADD COLUMN IF NOT EXISTS tradingagents_enabled BOOLEAN DEFAULT FALSE;
