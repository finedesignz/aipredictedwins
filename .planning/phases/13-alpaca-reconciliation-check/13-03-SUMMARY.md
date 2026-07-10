# Phase 13 Plan 03: Reconciliation Driver + Entrypoint Summary

Per-bot driver + breach-alert wrapper + runnable entrypoint; turns Plan 01 driver cases (7-9) GREEN — full 10-case suite GREEN.

## Tasks
- Task 1 — `src/notifier.py::alert_reconciliation_breach(bot_id, delta, tolerance, trade_log_pnl, alpaca_realized_pnl)`: formats subject+body, delegates to existing `send_alert`. Commit 0d38dfc.
- Task 2 — `src/reconciliation.py` driver: `reconcile_bot_live(bot_id, alpaca_client, tolerance=None)` assembles the 4 inputs, calls `reconcile_bot`, persists via `db.record_reconciliation`, WARNING+alert on breach / INFO within; `reconcile()` enumerates enabled bots (`_enabled_bot_ids`) and builds ONE client per bot from its own keys (`_client_for_bot`: `ALPACA_API_KEY_{id}` or bots row, never bare/shared). `RECONCILIATION_TOLERANCE_USD` default 25.0. Commit a8fe49f.
- Task 3 — `scripts/reconcile.py`: thin wrapper over `reconcile()`, prints per-bot delta + PASS/FAIL, exits non-zero on breach. Commit 60b8787.

## Verification
- `pytest tests/test_reconciliation.py` → 10 passed, 1 skipped (DB-gated).
- `pytest tests/` → 320 passed, 3 skipped (baseline 310 + 10 new; 2 prior skips + 1 DB-gated). No regressions.
- `scripts/reconcile.py` parses; read-only vs Alpaca, only writes the reconciliation row.

## Deviations
Driver exposes `_enabled_bot_ids()` / `_client_for_bot()` seams (patched by the multi-bot test) for per-bot isolation and zero-network testing. Within Rule-3 scope.

## Scope Fence
No Phase-11/12 change, no Phase-14 backfill, no dashboard rendering, no universe/retune; risk invariants untouched.

## Self-Check: PASSED
- src/notifier.py wrapper, src/reconciliation.py driver, scripts/reconcile.py present; commits 0d38dfc/a8fe49f/60b8787 present.
