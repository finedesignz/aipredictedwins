-- 013_bot_c_tradingagents.sql
-- Bot C runs the TauricResearch TradingAgents framework on US equities,
-- routed through our Claude CLI via a local OpenAI-compatible shim.
-- Default symbols: top US equities suitable for the framework's news /
-- fundamentals / insider tools.

UPDATE bots
SET strategy       = 'tradingagents',
    asset_class    = 'stock',
    stock_universe = COALESCE(NULLIF(stock_universe, ''),
                              'SPY,NVDA,AAPL,TSLA,AMZN,GOOGL,MSFT,META'),
    -- Reset to defaults sane for an LLM-driven daily bot.
    kelly_fraction        = 0.25,
    max_position_pct      = 0.05,
    skip_risk_gate        = TRUE,   -- TradingAgents runs its own risk debate
    label                 = 'Agent C — TradingAgents'
WHERE bot_id = 'C';

-- If Bot C row does not yet exist (no env vars set at first deploy),
-- seed_bots.py will create it with strategy='confluence'; this migration
-- only flips an existing row. The seed script will set strategy='tradingagents'
-- on first insert going forward.
