---
phase: 11-order-state-resolution-engine
plan: 01
subsystem: order-state / persistence
tags: [alpaca, postgres, migration, order-resolution]
requires: []
provides:
  - alpaca_trades.order_id/order_type/filled_qty/filled_avg_price columns
  - log_alpaca_trade(status/order_id/order_type/fills)
  - update_alpaca_trade terminal closed_at (canceled/expired/rejected)
  - get_pending_alpaca_orders(bot_id)
  - AlpacaClient.get_order(order_id)
affects: [Wave 2 resolver (11-02)]
tech-stack:
  added: []
  patterns: [additive-idempotent-migration, parameterized-sql, _retry+_parse_order wrapper]
key-files:
  created:
    - dashboard/api/migrations/015_order_state_resolution.sql
  modified:
    - src/db_schema.sql
    - src/db.py
    - src/alpaca_client.py
decisions:
  - order_type persisted alongside order_id (plan extends research's 3-col set to 4) for the limit-timeout branch
  - status default 'submitted' (pre-terminal), NOT 'open'
metrics:
  duration: ~15m
  completed: 2026-07-09
---

# Phase 11 Plan 01: Order-State Resolution Foundation Summary

Persist Alpaca order identity (`order_id`, `order_type`, `filled_qty`, `filled_avg_price`) on `alpaca_trades`, write rows in a pre-terminal `submitted` status, stamp `closed_at` on the new terminal order states, expose a DB read of pending orders, and add a single-order fetch wrapper — the contracts the Wave 2 resolver consumes.

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 | Migration 015 + db_schema.sql mirror | 142d2dd |
| 2 | db.py persistence + AlpacaClient.get_order | 9b53fb6 |

## What Was Built

- **Migration 015** (`dashboard/api/migrations/015_order_state_resolution.sql`): 4 `ADD COLUMN IF NOT EXISTS` (order_id, order_type, filled_qty, filled_avg_price) + 2 `CREATE INDEX IF NOT EXISTS` (bot_order, pending partial on `status='submitted'`). Fully additive/idempotent — no DROP/DELETE/non-additive ALTER (rule 6). Safe to run against Coolify Postgres before code deploy.
- **src/db_schema.sql**: mirrored the four columns into the `alpaca_trades` CREATE TABLE and the two indexes into the index block. `status`/`closed_at` left as-is; free-text `TEXT`, no CHECK/enum added.
- **src/db.py**:
  - `log_alpaca_trade` INSERT extended with `status` (default `'submitted'`), `order_id`, `order_type`, `filled_qty`, `filled_avg_price` — all read via `trade_data.get(...)`, so existing callers omitting them still work.
  - `update_alpaca_trade` `closed_at` set broadened to include `canceled`/`expired`/`rejected`.
  - New `get_pending_alpaca_orders(bot_id)` returning exactly `id, order_id, symbol, qty, side, order_type, timestamp, status` for `status='submitted'` rows. `get_open_alpaca_positions` unchanged.
- **src/alpaca_client.py**: `get_order(order_id)` wrapping `TradingClient.get_order_by_id` via `_retry` + `_parse_order`.

## Deviations from Plan

None — plan executed exactly as written. (Plan intentionally adds `order_type` beyond the 3 columns in RESEARCH's SQL block; followed the plan.)

## Verification

- Task 1 automated verify: 6 `IF NOT EXISTS` in migration; schema contains order_type/order_id/idx_alpaca_trades_pending — OK.
- Task 2 automated verify: both modules `ast.parse` clean; `get_pending_alpaca_orders`, `def get_order(`, `get_order_by_id` present — OK.
- Full project suite: `python -m pytest tests/ -q` → **289 passed, 2 skipped** (exceeds 279 baseline, no regression).
- Note: `vendor/TradingAgents/tests/*` fail collection (`ModuleNotFoundError: cli.utils`) — pre-existing, unrelated to this phase, out of scope.

## Scope Fence Honored

No historical P&L recompute, no backfill of stale rows, no universe gate. Forward mechanism only.

## Self-Check: PASSED
- FOUND: dashboard/api/migrations/015_order_state_resolution.sql
- FOUND: src/db.py get_pending_alpaca_orders
- FOUND: src/alpaca_client.py get_order
- FOUND commit: 142d2dd
- FOUND commit: 9b53fb6
