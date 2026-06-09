-- 014_intraday_learning_dims.sql  (LEARN-04)
-- Additive, nullable intraday-learning dimensions on trade_context.
-- Idempotent (ADD COLUMN IF NOT EXISTS); NO NOT NULL, NO DEFAULT, NO backfill —
-- existing rows simply read NULL (respects D-01 + global rule 6: additive only).

ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS time_of_day_bucket TEXT;
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS hold_minutes       DOUBLE PRECISION;
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS volatility_regime  TEXT;

CREATE INDEX IF NOT EXISTS idx_trade_context_bot_volregime ON trade_context (bot_id, volatility_regime);
CREATE INDEX IF NOT EXISTS idx_trade_context_bot_tod       ON trade_context (bot_id, time_of_day_bucket);
