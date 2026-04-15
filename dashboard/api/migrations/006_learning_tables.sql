-- 006_learning_tables.sql
-- Creates trade memory / learning loop tables. Safe to run against a DB that
-- already has these tables from an older schema — uses IF NOT EXISTS and
-- ADD COLUMN IF NOT EXISTS throughout so it is fully idempotent.

-- ─── trade_context ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS trade_context (
    id                  BIGSERIAL PRIMARY KEY,
    bot_id              VARCHAR(10)      NOT NULL DEFAULT '',
    trade_id            BIGINT,
    timestamp           TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    symbol              TEXT             NOT NULL DEFAULT '',
    signal_type         TEXT             NOT NULL DEFAULT '',
    sentiment           DOUBLE PRECISION DEFAULT 0.5,
    confidence          DOUBLE PRECISION,
    price_at_entry      DOUBLE PRECISION DEFAULT 0.0,
    price_change_24h    DOUBLE PRECISION DEFAULT 0.0,
    volume_24h          DOUBLE PRECISION DEFAULT 0.0,
    trajectory          TEXT,
    bull_arguments      JSONB            DEFAULT '[]',
    bear_arguments      JSONB            DEFAULT '[]',
    similar_past_trades JSONB            DEFAULT '[]',
    outcome             TEXT             NOT NULL DEFAULT 'open',
    pnl                 DOUBLE PRECISION,
    lesson_generated    BOOLEAN          NOT NULL DEFAULT FALSE
);

-- Add any columns that may be missing from a pre-existing table
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS bot_id              VARCHAR(10)      NOT NULL DEFAULT '';
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS trade_id            BIGINT;
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS symbol              TEXT             NOT NULL DEFAULT '';
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS signal_type         TEXT             NOT NULL DEFAULT '';
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS sentiment           DOUBLE PRECISION DEFAULT 0.5;
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS confidence          DOUBLE PRECISION;
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS price_at_entry      DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS price_change_24h    DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS volume_24h          DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS trajectory          TEXT;
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS bull_arguments      JSONB            DEFAULT '[]';
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS bear_arguments      JSONB            DEFAULT '[]';
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS similar_past_trades JSONB            DEFAULT '[]';
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS outcome             TEXT             NOT NULL DEFAULT 'open';
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS pnl                 DOUBLE PRECISION;
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS lesson_generated    BOOLEAN          NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_trade_context_bot_symbol  ON trade_context (bot_id, symbol);
CREATE INDEX IF NOT EXISTS idx_trade_context_bot_signal  ON trade_context (bot_id, signal_type);
CREATE INDEX IF NOT EXISTS idx_trade_context_bot_outcome ON trade_context (bot_id, outcome);


-- ─── trade_lessons ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS trade_lessons (
    id           BIGSERIAL PRIMARY KEY,
    bot_id       VARCHAR(10)      NOT NULL DEFAULT '',
    timestamp    TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    lesson_type  TEXT             NOT NULL DEFAULT '',
    symbol       TEXT,
    signal_type  TEXT,
    lesson       TEXT             NOT NULL DEFAULT '',
    confidence   DOUBLE PRECISION DEFAULT 0.5,
    sample_size  INT              DEFAULT 0,
    applies_to   JSONB            DEFAULT '{}',
    active       BOOLEAN          NOT NULL DEFAULT TRUE
);

ALTER TABLE trade_lessons ADD COLUMN IF NOT EXISTS bot_id      VARCHAR(10)      NOT NULL DEFAULT '';
ALTER TABLE trade_lessons ADD COLUMN IF NOT EXISTS lesson_type TEXT             NOT NULL DEFAULT '';
ALTER TABLE trade_lessons ADD COLUMN IF NOT EXISTS symbol      TEXT;
ALTER TABLE trade_lessons ADD COLUMN IF NOT EXISTS signal_type TEXT;
ALTER TABLE trade_lessons ADD COLUMN IF NOT EXISTS lesson      TEXT             NOT NULL DEFAULT '';
ALTER TABLE trade_lessons ADD COLUMN IF NOT EXISTS confidence  DOUBLE PRECISION DEFAULT 0.5;
ALTER TABLE trade_lessons ADD COLUMN IF NOT EXISTS sample_size INT              DEFAULT 0;
ALTER TABLE trade_lessons ADD COLUMN IF NOT EXISTS applies_to  JSONB            DEFAULT '{}';
ALTER TABLE trade_lessons ADD COLUMN IF NOT EXISTS active      BOOLEAN          NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS idx_trade_lessons_bot_active ON trade_lessons (bot_id, active);


-- ─── strategy_scores ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS strategy_scores (
    id                       BIGSERIAL PRIMARY KEY,
    bot_id                   VARCHAR(10)      NOT NULL DEFAULT '',
    updated_at               TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    signal_type              TEXT             NOT NULL DEFAULT '',
    symbol                   TEXT,
    win_rate                 DOUBLE PRECISION DEFAULT 0.0,
    avg_pnl                  DOUBLE PRECISION DEFAULT 0.0,
    total_trades             INT              DEFAULT 0,
    recommended_threshold    DOUBLE PRECISION DEFAULT 0.53,
    recommended_position_pct DOUBLE PRECISION DEFAULT 0.03,
    active                   BOOLEAN          NOT NULL DEFAULT TRUE
);

ALTER TABLE strategy_scores ADD COLUMN IF NOT EXISTS bot_id                   VARCHAR(10)      NOT NULL DEFAULT '';
ALTER TABLE strategy_scores ADD COLUMN IF NOT EXISTS signal_type              TEXT             NOT NULL DEFAULT '';
ALTER TABLE strategy_scores ADD COLUMN IF NOT EXISTS symbol                   TEXT;
ALTER TABLE strategy_scores ADD COLUMN IF NOT EXISTS win_rate                 DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE strategy_scores ADD COLUMN IF NOT EXISTS avg_pnl                  DOUBLE PRECISION DEFAULT 0.0;
ALTER TABLE strategy_scores ADD COLUMN IF NOT EXISTS total_trades             INT              DEFAULT 0;
ALTER TABLE strategy_scores ADD COLUMN IF NOT EXISTS recommended_threshold    DOUBLE PRECISION DEFAULT 0.53;
ALTER TABLE strategy_scores ADD COLUMN IF NOT EXISTS recommended_position_pct DOUBLE PRECISION DEFAULT 0.03;
ALTER TABLE strategy_scores ADD COLUMN IF NOT EXISTS active                   BOOLEAN          NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS idx_strategy_scores_bot_active ON strategy_scores (bot_id, active);
