-- 004_stock_universe.sql
-- Adds stock_universe column to bots table for long/short stock trading

ALTER TABLE bots
    ADD COLUMN IF NOT EXISTS stock_universe TEXT DEFAULT 'QQQ,SPY,AAPL,NVDA,MSFT,TSLA,AMZN,META';
