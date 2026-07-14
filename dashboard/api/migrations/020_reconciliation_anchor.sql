-- 020_reconciliation_anchor.sql  (VERIFY-02, Phase 20)
-- T0 — the per-bot reconciliation ANCHOR: a one-time snapshot of {equity,
-- unrealized_pnl, trade_log_pnl} taken on the manager's first post-deploy reconcile
-- tick. It exists because the all-time reconciliation CANNOT be satisfied: the
-- historical pnl = 0.0 sentinel rows contribute exactly ZERO to trade_log_pnl while
-- Alpaca's (equity - starting_equity) already contains their true outcome, so the delta
-- is a FIXED LEVEL OFFSET, invariant under every future correct trade. The honest close
-- is an ANCHORED WINDOW, and Alpaca exposes NO activities call and NO portfolio-history
-- call — so "what did you realize since T0" MUST come from a stored snapshot. This table
-- is a forced move, not a preference.
--
-- T0 IS WRITTEN ONCE PER BOT, VIA `ON CONFLICT (bot_id) DO NOTHING`.
-- **NEVER `DO UPDATE`.** An UPSERT would silently re-anchor T0 to "now" on EVERY run,
-- permanently resetting the window to zero samples and making the entire check
-- VACUOUSLY GREEN — the same class of self-defeating move as widening the tolerance.
-- Re-anchoring must require an explicit, separate, human-authorized action.
--
-- Additive, idempotent (CREATE TABLE IF NOT EXISTS). NO DROP/DELETE/ALTER, NO backfill,
-- NO bot_id CHECK (live bots dropped it for C/D, migration 009). Safe to run twice and
-- safe to run against Coolify Postgres BEFORE the new code deploys.
-- Mirrored in src/db_schema.sql — _bootstrap_schema() executes that file WHOLESALE, so a
-- migration-only table would exist in PROD AND NOWHERE ELSE.

CREATE TABLE IF NOT EXISTS reconciliation_anchor (
    bot_id         TEXT PRIMARY KEY,
    anchored_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    equity         DOUBLE PRECISION NOT NULL,
    unrealized_pnl DOUBLE PRECISION NOT NULL,
    trade_log_pnl  DOUBLE PRECISION NOT NULL
);
