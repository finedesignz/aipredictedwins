-- 017_reconciliation.sql  (PNL-03)
-- Latest per-bot reconciliation result: trade-log realized P&L vs Alpaca-derived
-- realized P&L, with a dollar-tolerance breach flag. Consumed by the dashboard
-- headline in Phase 19. Additive, idempotent (CREATE TABLE IF NOT EXISTS); NO
-- DROP/DELETE/backfill, NO bot_id CHECK (live bots dropped it for C/D, mig 009).
-- Safe to run against Coolify Postgres BEFORE the new code deploys.
-- bot_id PRIMARY KEY gives latest-per-bot for free via UPSERT.

CREATE TABLE IF NOT EXISTS reconciliation (
    bot_id              TEXT PRIMARY KEY,
    checked_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trade_log_pnl       DOUBLE PRECISION NOT NULL,
    alpaca_realized_pnl DOUBLE PRECISION NOT NULL,
    delta               DOUBLE PRECISION NOT NULL,
    within_tolerance    BOOLEAN NOT NULL,
    tolerance           DOUBLE PRECISION NOT NULL
);
