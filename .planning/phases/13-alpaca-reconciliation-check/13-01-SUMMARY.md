# Phase 13 Plan 01: Reconciliation RED Contract Summary

RED test contract for PNL-03: 10 VALIDATION cases + a DATABASE_URL-gated three-state guard in `tests/test_reconciliation.py`, all failing until Plans 02/03 land.

## Tasks
- Task 1 — pure `reconcile_bot` math cases (1-5, 10): within/over/boundary/negative/derivation(long+short)/guards+result-shape. Commit e5c7a9d.
- Task 2 — three-state realized-P&L sum (case 6): fake-conn mimics `status IN ('closed','stopped','target_hit')` filter + a `DATABASE_URL`-gated real-SQL integration guard (baseline-delta on bot A, cleans up its rows). Commit e5c7a9d.
- Task 3 — driver cases (7-9): persist/alert/multi-bot via `_FakeAlpaca` + `send_alert` counter + caplog WARNING/INFO. Commit e5c7a9d.

(All three tasks landed in one `test(13-01)` RED commit — single file, TDD RED gate.)

## Verification
- `pytest tests/test_reconciliation.py --collect-only` → 11 tests collected.
- RED at authoring: 7 failed, 3 errored (missing modules), 1 skipped (DB-gated).

## Deviations
Plan-checker warning addressed: added `test_realized_pnl_three_states_db` (DATABASE_URL-gated) alongside the fake case-6, catching a 'closed'-only SQL regression when a DB is present.

## Self-Check: PASSED
- tests/test_reconciliation.py exists; commit e5c7a9d present.
