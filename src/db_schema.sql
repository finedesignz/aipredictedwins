-- AI Predicted Wins — Postgres DDL
-- Shared by Bot A and Bot B.
-- Run idempotently: every object uses IF NOT EXISTS / ON CONFLICT DO NOTHING.

-- ─────────────────────────────────────────────
-- 1. bots — registry table
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bots (
    id              TEXT PRIMARY KEY CHECK (id IN ('A', 'B')),
    label           TEXT NOT NULL,
    starting_equity DOUBLE PRECISION NOT NULL DEFAULT 100000.0,
    alpaca_key_prefix TEXT,
    config_flags    JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────
-- 2. alpaca_trades
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alpaca_trades (
    id              BIGSERIAL PRIMARY KEY,
    source_id       BIGINT,
    bot_id          TEXT NOT NULL CHECK (bot_id IN ('A', 'B')),
    timestamp       TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    asset_class     TEXT NOT NULL,
    side            TEXT NOT NULL,
    qty             DOUBLE PRECISION NOT NULL,
    entry_price     DOUBLE PRECISION NOT NULL,
    mirofish_prob   DOUBLE PRECISION NOT NULL,
    market_sentiment TEXT,
    target_price    DOUBLE PRECISION,
    stop_loss       DOUBLE PRECISION,
    status          TEXT DEFAULT 'open',
    exit_price      DOUBLE PRECISION,
    pnl             DOUBLE PRECISION,
    closed_at       TEXT,
    simulation_id   TEXT,
    notes           TEXT
);

-- ─────────────────────────────────────────────
-- 3. validations
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS validations (
    id                   BIGSERIAL PRIMARY KEY,
    source_id            BIGINT,
    bot_id               TEXT NOT NULL CHECK (bot_id IN ('A', 'B')),
    timestamp            TEXT NOT NULL,
    kalshi_ticker        TEXT NOT NULL,
    event_title          TEXT NOT NULL,
    mirofish_prob        DOUBLE PRECISION NOT NULL,
    kalshi_price         DOUBLE PRECISION NOT NULL,
    gap                  DOUBLE PRECISION NOT NULL,
    proposed_side        TEXT NOT NULL,
    decision             TEXT NOT NULL,
    confidence           DOUBLE PRECISION,
    adjusted_probability DOUBLE PRECISION,
    size_multiplier      DOUBLE PRECISION DEFAULT 1.0,
    sentiment_report     TEXT,
    news_report          TEXT,
    contrarian_report    TEXT,
    risk_assessment      TEXT,
    veto_reason          TEXT,
    trade_id             BIGINT
);

-- ─────────────────────────────────────────────
-- 4. screenings
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS screenings (
    id                   BIGSERIAL PRIMARY KEY,
    source_id            BIGINT,
    bot_id               TEXT NOT NULL CHECK (bot_id IN ('A', 'B')),
    timestamp            TEXT NOT NULL,
    kalshi_ticker        TEXT NOT NULL,
    event_title          TEXT NOT NULL,
    quick_probability    DOUBLE PRECISION NOT NULL,
    quick_confidence     TEXT,
    kalshi_price         DOUBLE PRECISION NOT NULL,
    gap                  DOUBLE PRECISION NOT NULL,
    promoted_to_full_sim BOOLEAN DEFAULT FALSE
);

-- ─────────────────────────────────────────────
-- 5. simulations  (id is TEXT/UUID from MiroFish; composite PK)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS simulations (
    id                  TEXT NOT NULL,
    source_id           BIGINT,
    bot_id              TEXT NOT NULL CHECK (bot_id IN ('A', 'B')),
    timestamp           TEXT NOT NULL,
    kalshi_ticker       TEXT NOT NULL,
    event_title         TEXT NOT NULL,
    agent_count         INTEGER,
    rounds              INTEGER,
    mirofish_prob       DOUBLE PRECISION,
    kalshi_price_at_sim DOUBLE PRECISION,
    gap                 DOUBLE PRECISION,
    estimated_cost      DOUBLE PRECISION,
    traded              BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (bot_id, id)
);

-- ─────────────────────────────────────────────
-- 6. daily_stats  (composite PK, no autoincrement)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_stats (
    bot_id          TEXT NOT NULL CHECK (bot_id IN ('A', 'B')),
    date            TEXT NOT NULL,
    trades_placed   INTEGER,
    trades_resolved INTEGER,
    wins            INTEGER,
    losses          INTEGER,
    daily_pnl       DOUBLE PRECISION,
    cumulative_pnl  DOUBLE PRECISION,
    bankroll        DOUBLE PRECISION,
    accuracy        DOUBLE PRECISION,
    PRIMARY KEY (bot_id, date)
);

-- ─────────────────────────────────────────────
-- 7. trades  (legacy Kalshi — historical reads only)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trades (
    id                    BIGSERIAL PRIMARY KEY,
    source_id             BIGINT,
    bot_id                TEXT NOT NULL CHECK (bot_id IN ('A', 'B')),
    timestamp             TEXT NOT NULL,
    kalshi_ticker         TEXT NOT NULL,
    event_title           TEXT NOT NULL,
    side                  TEXT NOT NULL,
    contracts             INTEGER NOT NULL,
    entry_price_cents     INTEGER NOT NULL,
    mirofish_prob         DOUBLE PRECISION NOT NULL,
    kalshi_price_at_entry DOUBLE PRECISION NOT NULL,
    gap                   DOUBLE PRECISION NOT NULL,
    kelly_pct             DOUBLE PRECISION NOT NULL,
    dollar_amount         DOUBLE PRECISION NOT NULL,
    status                TEXT DEFAULT 'open',
    exit_price_cents      INTEGER,
    pnl                   DOUBLE PRECISION,
    resolution_date       TEXT,
    simulation_id         TEXT,
    notes                 TEXT
);

-- ─────────────────────────────────────────────
-- 8. TradeMemory tables
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS trade_lessons (
    id        BIGSERIAL PRIMARY KEY,
    bot_id    TEXT NOT NULL CHECK (bot_id IN ('A', 'B')),
    timestamp TEXT NOT NULL,
    symbol    TEXT,
    lesson    TEXT NOT NULL,
    outcome   TEXT,
    pnl       DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS trade_context (
    id        BIGSERIAL PRIMARY KEY,
    bot_id    TEXT NOT NULL CHECK (bot_id IN ('A', 'B')),
    timestamp TEXT NOT NULL,
    symbol    TEXT NOT NULL,
    context   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_scores (
    bot_id     TEXT NOT NULL CHECK (bot_id IN ('A', 'B')),
    strategy   TEXT NOT NULL,
    score      DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (bot_id, strategy)
);

-- ═════════════════════════════════════════════
-- INDEXES
-- ═════════════════════════════════════════════

-- (bot_id, timestamp) lookup indexes
CREATE INDEX IF NOT EXISTS idx_alpaca_trades_bot_ts   ON alpaca_trades   (bot_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_validations_bot_ts     ON validations     (bot_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_screenings_bot_ts      ON screenings      (bot_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_simulations_bot_ts     ON simulations     (bot_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_bot_ts          ON trades          (bot_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_trade_lessons_bot_ts   ON trade_lessons   (bot_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_trade_context_bot_ts   ON trade_context   (bot_id, timestamp);

-- (bot_id, source_id) unique indexes for migration idempotency
-- (simulations excluded — PK is (bot_id, id); source_id uniqueness handled separately)
CREATE UNIQUE INDEX IF NOT EXISTS ux_alpaca_trades_bot_src ON alpaca_trades (bot_id, source_id) WHERE source_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_validations_bot_src   ON validations   (bot_id, source_id) WHERE source_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_screenings_bot_src    ON screenings    (bot_id, source_id) WHERE source_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_trades_bot_src        ON trades        (bot_id, source_id) WHERE source_id IS NOT NULL;
-- trade_lessons and trade_context have no source_id column — no dedup index needed

-- Additional targeted indexes
CREATE INDEX IF NOT EXISTS idx_alpaca_trades_bot_status  ON alpaca_trades (bot_id, status);
CREATE INDEX IF NOT EXISTS idx_validations_bot_decision  ON validations   (bot_id, decision);

-- ═════════════════════════════════════════════
-- SEED ROWS
-- ═════════════════════════════════════════════
-- id = bot_id (both columns exist after 002_multi_bot migration)
INSERT INTO bots (id, bot_id, label)
VALUES ('A', 'A', 'Bot A — Conservative'), ('B', 'B', 'Bot B — Aggressive')
ON CONFLICT (id) DO NOTHING;
