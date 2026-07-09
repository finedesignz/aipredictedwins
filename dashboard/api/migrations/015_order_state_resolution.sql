-- 015_order_state_resolution.sql  (PNL-01, PNL-04)
-- Persist Alpaca order identity + fill data so submitted orders can be resolved
-- to a terminal state. Additive, nullable, idempotent (all statements guarded);
-- NO NOT NULL, NO DEFAULT, NO backfill, NO DROP/non-additive ALTER (global rule 6).
-- Safe to run against Coolify Postgres BEFORE the new code deploys.

ALTER TABLE alpaca_trades ADD COLUMN IF NOT EXISTS order_id         TEXT;
ALTER TABLE alpaca_trades ADD COLUMN IF NOT EXISTS order_type       TEXT;
ALTER TABLE alpaca_trades ADD COLUMN IF NOT EXISTS filled_qty       DOUBLE PRECISION;
ALTER TABLE alpaca_trades ADD COLUMN IF NOT EXISTS filled_avg_price DOUBLE PRECISION;

CREATE INDEX IF NOT EXISTS idx_alpaca_trades_bot_order ON alpaca_trades (bot_id, order_id);
-- pending-resolution lookup (partial index on the hot 'submitted' path)
CREATE INDEX IF NOT EXISTS idx_alpaca_trades_pending
  ON alpaca_trades (bot_id, status) WHERE status = 'submitted';
