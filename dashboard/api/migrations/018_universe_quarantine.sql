-- 018_universe_quarantine.sql
-- Phase 15 (UNIV-02): per-bot symbol quarantine — drop a chronically unprofitable
-- symbol with one config write, zero code change.
--
-- Additive + idempotent (ADD COLUMN IF NOT EXISTS). No constraint change, no data
-- migration, no DELETE/DROP/TRUNCATE. Safe to apply BEFORE the new orchestrator
-- code deploys: default '' = nothing quarantined = current behavior.
--
-- FORMAT: entries must match the crypto_universe format (slash included, e.g.
-- 'BTC/USD'). A bare 'BTC' will NOT match — normalize() only uppercases and
-- strips the slash; it does not resolve a base ticker to a pair.

ALTER TABLE bots
    ADD COLUMN IF NOT EXISTS quarantined_symbols TEXT DEFAULT '';
