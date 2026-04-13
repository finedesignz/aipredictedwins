-- 004_stock_universe.sql
-- Add stock_universe column for long/short equity trading.
-- Crypto (long-only) and stocks (long + short) are now separate universes.

ALTER TABLE bots
    ADD COLUMN IF NOT EXISTS stock_universe TEXT DEFAULT 'QQQ,SPY,AAPL,NVDA,MSFT,TSLA,AMZN,META';
