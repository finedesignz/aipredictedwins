-- 006_learning_tables.sql
-- Creates trade memory / learning loop tables used by TradeMemory and LearningLoop.

CREATE TABLE IF NOT EXISTS trade_context (
    id               BIGSERIAL PRIMARY KEY,
    bot_id           VARCHAR(10)   NOT NULL,
    trade_id         BIGINT,                   -- FK → alpaca_trades.id (nullable: pre-trade advice)
    timestamp        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    symbol           TEXT          NOT NULL,
    signal_type      TEXT          NOT NULL,
    sentiment        DOUBLE PRECISION DEFAULT 0.5,
    confidence       DOUBLE PRECISION,
    price_at_entry   DOUBLE PRECISION DEFAULT 0.0,
    price_change_24h DOUBLE PRECISION DEFAULT 0.0,
    volume_24h       DOUBLE PRECISION DEFAULT 0.0,
    trajectory       TEXT,
    bull_arguments   JSONB         DEFAULT '[]',
    bear_arguments   JSONB         DEFAULT '[]',
    similar_past_trades JSONB      DEFAULT '[]',
    outcome          TEXT          NOT NULL DEFAULT 'open',  -- 'open', 'win', 'loss'
    pnl              DOUBLE PRECISION,
    lesson_generated BOOLEAN       NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_trade_context_bot_symbol
    ON trade_context (bot_id, symbol);

CREATE INDEX IF NOT EXISTS idx_trade_context_bot_signal
    ON trade_context (bot_id, signal_type);

CREATE INDEX IF NOT EXISTS idx_trade_context_bot_outcome
    ON trade_context (bot_id, outcome);


CREATE TABLE IF NOT EXISTS trade_lessons (
    id           BIGSERIAL PRIMARY KEY,
    bot_id       VARCHAR(10)   NOT NULL,
    timestamp    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    lesson_type  TEXT          NOT NULL,  -- 'asset', 'pattern', 'threshold'
    symbol       TEXT,
    signal_type  TEXT,
    lesson       TEXT          NOT NULL,
    confidence   DOUBLE PRECISION DEFAULT 0.5,
    sample_size  INT           DEFAULT 0,
    applies_to   JSONB         DEFAULT '{}',
    active       BOOLEAN       NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_trade_lessons_bot_active
    ON trade_lessons (bot_id, active);


CREATE TABLE IF NOT EXISTS strategy_scores (
    id                      BIGSERIAL PRIMARY KEY,
    bot_id                  VARCHAR(10)   NOT NULL,
    updated_at              TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    signal_type             TEXT          NOT NULL,
    symbol                  TEXT,
    win_rate                DOUBLE PRECISION DEFAULT 0.0,
    avg_pnl                 DOUBLE PRECISION DEFAULT 0.0,
    total_trades            INT           DEFAULT 0,
    recommended_threshold   DOUBLE PRECISION DEFAULT 0.53,
    recommended_position_pct DOUBLE PRECISION DEFAULT 0.03,
    active                  BOOLEAN       NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_strategy_scores_bot_active
    ON strategy_scores (bot_id, active);
