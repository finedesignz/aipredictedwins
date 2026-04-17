-- 008_asset_class.sql
-- Adds asset_class to bots table so each bot can be crypto or stock-focused

ALTER TABLE bots
    ADD COLUMN IF NOT EXISTS asset_class VARCHAR(20) DEFAULT 'crypto',
    ADD COLUMN IF NOT EXISTS short_enabled BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS dynamic_universe_size INT DEFAULT 20;
