-- 016_realized_pnl_fees.sql  (PNL-02)
-- Persist the round-trip taker-fee total for a closed trade so realized P&L
-- (from actual fills, net of fees) can be stored and audited. Additive,
-- nullable, idempotent; NO NOT NULL, NO DEFAULT, NO backfill, NO DROP/non-additive
-- ALTER (global rule 6; Phase 14 backfills historicals).
-- Safe to run against Coolify Postgres BEFORE the new code deploys.

ALTER TABLE alpaca_trades ADD COLUMN IF NOT EXISTS fees DOUBLE PRECISION;
