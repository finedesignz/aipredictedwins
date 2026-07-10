---
phase: 14
plan: 02
subsystem: backfill/foundation
tags: [pnl-05, reuse, alpaca-py]
requires: [14-01]
provides: [classify_order, get_stale_alpaca_candidates, count_unresolvable_alpaca_rows, get_closed_orders]
affects: [src/bot_thread.py]
key-files:
  created: [src/order_resolution.py]
  modified: [src/bot_thread.py, src/db.py, src/alpaca_client.py]
decisions:
  - "Extract Phase-11 _classify to pure module-level classify_order; BotThread._classify one-line delegate keeps Phase-11 suite green"
  - "get_closed_orders builds GetOrdersRequest via **kwargs so after= is only passed when provided"
metrics:
  duration: wave-2
  completed: 2026-07-10
commits: [422c6b6, f35e70c, 1012750]
---

# Phase 14 Plan 02: Backfill Foundation Summary

The reusable building blocks the Plan-03 driver wires against — all additive/reuse, no P&L or
resolver re-implementation.

## What shipped
- **`src/order_resolution.py`** — pure `classify_order(order) -> (db_status|None, pnl|None)` +
  canonical `_TERMINAL_NONPOSITION`; zero db/alpaca/BotThread imports. `BotThread._classify` is now
  a one-line delegate (`422c6b6`). Phase-11 suite stays GREEN (10 passed).
- **`src/db.py`** — `get_stale_alpaca_candidates(bot_id, older_than_minutes=30)` (status IN
  ('open','submitted') AND order_id IS NOT NULL AND older than guard window; full column set) and
  `count_unresolvable_alpaca_rows(bot_id)` (NULL-order_id residue). Both read-only, parameterized,
  per-bot (`f35e70c`).
- **`src/alpaca_client.py`** — `get_closed_orders(symbol, after=None)` mirroring `get_open_orders`:
  `QueryOrderStatus.CLOSED`, `symbols=[symbol]`, `limit=500`, `direction='desc'`, `_retry`-wrapped,
  slash preserved, local import of GetOrdersRequest/QueryOrderStatus per repo pattern (`1012750`).

## Deviations from Plan
None — plan executed as written.

## Self-Check: PASSED
- All three artifacts present; commits 422c6b6/f35e70c/1012750 present.
- Phase-11 suite GREEN; classify/db/get_closed_orders import cleanly.
