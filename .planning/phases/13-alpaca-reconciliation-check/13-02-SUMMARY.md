# Phase 13 Plan 02: Reconciliation Foundation Summary

Pure `reconcile_bot` helper + three per-bot db accessors + additive migration 017; turns Plan 01 pure cases (1-6, 10) GREEN.

## Tasks
- Task 1 — `src/reconciliation.py::reconcile_bot(trade_log_pnl, equity, starting_equity, unrealized_pnl, tolerance)`: `alpaca_realized_pnl = (equity - starting_equity) - unrealized_pnl`, `delta = trade_log_pnl - alpaca_realized_pnl`, `within_tolerance = abs(delta) <= tolerance`; 5-key dict, no I/O. Commit a1f8dc1.
- Task 2 — `src/db.py`: `get_realized_pnl` (SUM pnl over `status IN ('closed','stopped','target_hit')`, NULL-guarded), `get_starting_equity` (bots row, 100000 only as missing-row fallback), `record_reconciliation` (UPSERT on bot_id). Commit c8e8fa1.
- Task 3 — `dashboard/api/migrations/017_reconciliation.sql` (CREATE TABLE IF NOT EXISTS, bot_id PK, 7 cols, no CHECK, no DROP) + `src/db_schema.sql` mirror (section 10). Commit 66e6d77.

## Verification
- `pytest tests/test_reconciliation.py -k "reconcile or three_states"` → GREEN.
- Migration 017 additive/idempotent; verify grep gate passed (`CREATE TABLE IF NOT EXISTS reconciliation`, PK present, no bot_id CHECK).

## Deviations
`get_starting_equity`/driver read `get_account()["equity"]` (dict) — real `AlpacaClient.get_account` returns a dict, not an attribute object as the plan interface loosely stated. No behavior impact.

## Self-Check: PASSED
- src/reconciliation.py, src/db.py accessors, migration 017, schema mirror all present; commits a1f8dc1/c8e8fa1/66e6d77 present.
