-- 003_rsi_ceiling.sql
-- Raise RSI ceiling from 65 to 72 for existing bot rows.
-- RSI 65 was filtering out BTC/ETH sitting at 64.7–64.9 (overbought threshold is 70).

UPDATE bots SET rsi_ceiling = 72.0 WHERE rsi_ceiling = 65.0;
