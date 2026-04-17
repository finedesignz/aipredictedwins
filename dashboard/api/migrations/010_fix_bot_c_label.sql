-- 010_fix_bot_c_label.sql
-- Normalise Bot C label to match A/B naming convention
UPDATE bots SET label = 'Agent C' WHERE bot_id = 'C' AND label = 'Agent C (Stocks)';
