---
phase: 11-order-state-resolution-engine
plan: 02
subsystem: bot-thread / order-lifecycle
tags: [order-resolution, pnl, alpaca, tdd, wave-2]
requires: [11-01]
provides:
  - "BotThread._resolve_pending_orders (DB-driven, idempotent, crash-safe)"
  - "BotThread._submit_order / _classify helpers"
  - "TradeLogger.get_pending_alpaca_orders shim"
affects: [src/bot_thread.py, src/trade_logger.py, tests/test_order_resolution.py]
tech-stack:
  added: []
  patterns: [tdd-wave-0, db-driven-resolver, classify-on-fresh-status]
key-files:
  created: [tests/test_order_resolution.py]
  modified: [src/bot_thread.py, src/trade_logger.py]
decisions:
  - "Resolver reads pending rows from DB each cycle + at startup (crash-safe)"
  - "Limit-timeout cancels then re-fetches; fill beats cancel on fresh status"
  - "Submit exception → terminal 'rejected' row (no silent drop)"
requirements: [PNL-01, PNL-04]
metrics:
  tasks: 3
  files: 3
  tests_added: 10
  suite: "299 passed, 2 skipped"
completed: 2026-07-09
---

# Phase 11 Plan 02: Order-State Resolution Engine Summary

DB-driven, idempotent order-state resolver wired into BotThread: every submission
now persists `order_id`/`order_type`/`status='submitted'`/fills, submit exceptions
record a terminal `rejected` row, and each cycle (plus once at startup) pending
orders are polled and terminalized — `open` on fill/partial, `canceled`/`expired`/
`rejected` (pnl=0) otherwise, cancel-then-recheck for resting limits past timeout.

## Tasks

1. **Wave 0 RED suite** (`9d3cc62`) — `tests/test_order_resolution.py`: 10 cases
   (9 state-machine + happy-path submit) with in-memory `FakeAlpacaClient` +
   `FakeLogger` doubles (no network, no Postgres). Confirmed RED (10 failed:
   missing `_resolve_pending_orders`/`_submit_order`).
2. **Resolver + wiring** (`3669e22`) — `_resolve_pending_orders`, `_classify`,
   `_submit_order`, `_limit_order_timeout_s`, `_order_age_s` on BotThread;
   `TradeLogger.get_pending_alpaca_orders` shim; resolve call after
   `monitor.start()` and at top of each `_scan_loop` cycle. → 9/9 subset green.
3. **Submission wiring** (`b8e8006`) — long + short entry sites route through
   `_submit_order` (persist order_id/type/status/fills; exception→rejected);
   pre-submit dedup/exposure unions `submitted` rows. → all 10 green.

## RED → GREEN

- After Task 1: `10 failed` (AttributeError — resolver/wiring absent).
- After Task 2: `9 passed, 1 deselected` (resolver subset).
- After Task 3: `10 passed` (full order-resolution suite).

## Verification

- `python -m pytest tests/test_order_resolution.py -q` → **10 passed**.
- `python -m pytest tests/ -q` → **299 passed, 2 skipped** (289 prior + 10 new;
  the 2 skips are the `DATABASE_URL`-gated Postgres smoke tests).
- `ast.parse(src/bot_thread.py)` → OK.

## Deviations from Plan

**1. [Rule 3 - Blocking] Added `TradeLogger.get_pending_alpaca_orders` shim**
- **Found during:** Task 2
- **Issue:** The resolver's key-link is `logger.get_pending_alpaca_orders`, but
  `TradeLogger` only had `get_open_alpaca_positions` (11-01 added the function to
  `src/db.py`, not the shim). Without the shim the DB-driven, mockable seam the
  tests assert against does not exist.
- **Fix:** Added a one-line shim delegating to `_db.get_pending_alpaca_orders`.
- **Files modified:** `src/trade_logger.py`
- **Commit:** `3669e22`

Notes: the test doubles use an in-memory `FakeLogger` (isolated `alpaca_trades`
store) rather than a Postgres/sqlite fixture — the project's test suite is
all-mock (`tests/test_db.py` skips without `DATABASE_URL`), so this reuses the
established no-DB pattern rather than inventing a live-DB fixture.

## Scope Fence (honored)

No historical P&L recompute (Phase 12), no backfill of stale rows (Phase 14), no
universe gate (Phase 15). PositionMonitor boundary untouched — it still owns
position exits.

## Self-Check: PASSED

- `tests/test_order_resolution.py` — FOUND
- `src/bot_thread.py::_resolve_pending_orders` — FOUND
- Commits `9d3cc62`, `3669e22`, `b8e8006` — FOUND
