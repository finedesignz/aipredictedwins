-- 005_signals.sql
-- Creates the signals table for persisting technical scan results from bot threads.
-- The dashboard signals endpoint reads from this table instead of using placeholder data.

CREATE TABLE IF NOT EXISTS signals (
    id              BIGSERIAL PRIMARY KEY,
    scanned_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    bot_id          TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    ema_bullish     BOOLEAN,
    adx_value       DOUBLE PRECISION,
    rsi_value       DOUBLE PRECISION,
    volume_spike    BOOLEAN,
    vwap_bullish    BOOLEAN,
    confluence_score INT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_signals_bot_scanned ON signals (bot_id, scanned_at DESC);
