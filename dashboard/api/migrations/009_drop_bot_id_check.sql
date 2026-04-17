-- 009_drop_bot_id_check.sql
-- Remove the hard-coded check constraint on bots.id so new bots (C, D, ...) can be seeded

ALTER TABLE bots DROP CONSTRAINT IF EXISTS bots_id_check;
ALTER TABLE alpaca_trades DROP CONSTRAINT IF EXISTS alpaca_trades_bot_id_check;
