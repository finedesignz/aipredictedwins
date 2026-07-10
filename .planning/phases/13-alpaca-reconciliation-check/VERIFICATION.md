---
phase: 13-alpaca-reconciliation-check
verified: 2026-07-10T00:00:00Z
status: passed
score: 7/7 must-haves verified
overrides_applied: 0
---

# Phase 13: Alpaca Reconciliation Check — Verification Report

**Phase Goal:** Reconcile summed trade-log P&L per bot vs Alpaca account realized P&L; surface delta beyond tolerance (log + persisted flag). Owns PNL-03.
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement — Observable Truths

| # | Must-have | Status | Evidence |
|---|-----------|--------|----------|
| 1 | `reconcile_bot(...)` pure; derivation `(equity−starting)−unrealized`; `abs(delta)<=tol`; 5-key dict | ✓ VERIFIED | `src/reconciliation.py:16-42` — API-free, `alpaca_realized_pnl=(equity-starting_equity)-unrealized_pnl` L33, `within_tolerance=abs(delta)<=tolerance` L35, dict keys trade_log_pnl/alpaca_realized_pnl/delta/within_tolerance/tolerance L36-42 |
| 2 | `get_realized_pnl` three-state sum; `get_starting_equity` bots-row (100000 only if missing); `record_reconciliation` upsert | ✓ VERIFIED | `src/db.py:203-216` `status IN ('closed','stopped','target_hit')` NULL-guarded; `219-228` reads bots.starting_equity, `return 100000.0` only when `row is None`; `231-253` INSERT … `ON CONFLICT (bot_id) DO UPDATE` upsert |
| 3 | Migration 017 (IF NOT EXISTS, bot_id PK, no CHECK, idempotent, not alembic) + schema mirror | ✓ VERIFIED | `dashboard/api/migrations/017_reconciliation.sql:9-17` CREATE TABLE IF NOT EXISTS, `bot_id TEXT PRIMARY KEY`, no CHECK; mirrored `src/db_schema.sql:208-211` |
| 4 | Driver enumerates enabled bots, per-bot own keys, tolerance default 25.0, breach→WARNING+single alert, ok→INFO no alert | ✓ VERIFIED | `src/reconciliation.py:51-59` `SELECT bot_id FROM bots WHERE enabled=TRUE`; `62-93` `_client_for_bot` uses `ALPACA_API_KEY_{id}`/bots-row, raises if absent (never bare/shared); `DEFAULT_TOLERANCE_USD=25.0` L13, env override L47-48; breach `log.warning` + single `notifier.alert_reconciliation_breach` L115-125; else `log.info` no alert L126-130 |
| 5 | `scripts/reconcile.py` prints per-bot delta + PASS/FAIL | ✓ VERIFIED | `scripts/reconcile.py:16-32` prints table, `PASS`/`FAIL` per bot, exit 1 on any breach |
| 6 | 10 VALIDATION cases + DATABASE_URL-gated real-SQL three-state guard; suites green | ✓ VERIFIED | `tests/test_reconciliation.py` all 10 named tests present (L28-295) + `test_realized_pnl_three_states_db` skipif on DATABASE_URL (L164-168). `pytest tests/test_reconciliation.py -q` → 10 passed, 1 skipped. `pytest tests/ -q` → 320 passed, 3 skipped |
| 7 | Scope fence: no Phase-11/12/14/dashboard/universe/retune/risk changes | ✓ VERIFIED | All new code isolated to `src/reconciliation.py`, additive `src/db.py` fns, `notifier.alert_reconciliation_breach` (new fn, reuses `send_alert`), migration 017, mirror schema, `scripts/reconcile.py`, test file. No P&L-compute/order-resolution/backfill/dashboard-render/universe edits |

**Score:** 7/7 truths verified

## Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| PNL-03 | Reconcile trade-log P&L vs Alpaca realized P&L per bot, flag delta beyond tolerance | ✓ SATISFIED | reconcile_bot derivation + persisted reconciliation flag + breach WARNING/alert + runnable script; 10 automated cases green |

## Key Notes

- `unrealized_pnl` correctly treated as signed sum (losing open position increases derived realized) — L27-28 docstring + L110 driver sum.
- Notifier reuses existing `send_alert` channel (no new channel invented) — `notifier.py:127`.
- One-account-per-bot hard rule honored: `_client_for_bot` never reads bare `ALPACA_API_KEY`; raises fail-clear if no per-bot keys.
- Boundary rule inclusive (`<=`) confirmed by `test_reconcile_boundary`.

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Reconciliation tests | `pytest tests/test_reconciliation.py -q` | 10 passed, 1 skipped | ✓ PASS |
| Full suite regression | `pytest tests/ -q` | 320 passed, 3 skipped | ✓ PASS |

## Anti-Patterns Found

None. No TBD/FIXME/XXX/placeholder debt markers in phase files. Missing-row fallback (100000) and NULL-pnl guard (0.0) are documented intentional guards, not stubs.

## Gaps Summary

No gaps. All must-haves and PNL-03 satisfied with codebase evidence and green tests. Ship.

---

_Verified: 2026-07-10 · Verifier: Claude (gsd-verifier)_
