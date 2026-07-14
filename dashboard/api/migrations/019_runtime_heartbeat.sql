-- 019_runtime_heartbeat.sql  (RUN-01)
-- The BotManager watchdog's liveness signal, readable from OUTSIDE the process.
--
-- Nothing outside the dashboard process can currently distinguish "manager running,
-- bots healthy" from "manager never started" — main.py:65-66 swallows that failure into
-- a _log.warning. ABSENCE OF A ROW (or a stale beat_at) IS THE SIGNAL: a reader that
-- defaults healthy on a missing row reintroduces the exact silent failure Phase 19 exists
-- to kill. The watchdog cannot report its own non-existence (bot_manager.py:79 starts it
-- AFTER the start_all query that can throw at :67-70).
--
-- Additive, idempotent (CREATE TABLE IF NOT EXISTS). Touches NO trade data — there is no
-- UPDATE/DELETE/DROP/ALTER here and alpaca_trades is not referenced. Safe to apply twice
-- and safe to apply to Coolify Postgres BEFORE the new code deploys.
--
-- N3: src/db_schema.sql carries a MIRRORED block (section 11). src/db.py:61-66
-- `_bootstrap_schema()` executes db_schema.sql WHOLESALE, so a table added ONLY as a
-- migration is absent from every fresh-DB bootstrap. Both files, or the table silently
-- does not exist.

CREATE TABLE IF NOT EXISTS runtime_heartbeat (
    component    TEXT PRIMARY KEY,
    beat_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    bots_alive   INT NOT NULL DEFAULT 0,
    bots_enabled INT NOT NULL DEFAULT 0
);
