-- Add trend-follower strategy fields to bots table.
-- Enables a non-confluence mode where the bot rides a leveraged BTC ETF (BITX)
-- when BTC > 50DMA and sits in cash otherwise.

ALTER TABLE bots
    ADD COLUMN IF NOT EXISTS strategy         TEXT    DEFAULT 'confluence',
    ADD COLUMN IF NOT EXISTS trend_ma_window  INT     DEFAULT 50,
    ADD COLUMN IF NOT EXISTS trend_symbol     TEXT    DEFAULT 'BITX',
    ADD COLUMN IF NOT EXISTS trend_benchmark  TEXT    DEFAULT 'BTC/USD';
