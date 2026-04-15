-- 007_rsi_ceiling_65.sql
-- Align rsi_ceiling to 65 for all bots.
-- Migration 003 raised it to 72, but the signal engine hard-blocks at RSI_ENTRY_CEILING=65
-- by default (env var). Setting the DB column to match eliminates the confusing mismatch
-- where the DB says 72 but the effective ceiling is 65.

UPDATE bots SET rsi_ceiling = 65.0 WHERE rsi_ceiling > 65.0;
