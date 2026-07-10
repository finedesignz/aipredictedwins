---
phase: 14
plan: 01
subsystem: backfill/tests
tags: [pnl-05, tdd-red, alpaca-py]
requires: []
provides: [tests/test_backfill.py, A1-A3-confirmed]
affects: []
key-files:
  created: [tests/test_backfill.py]
  modified: []
decisions:
  - "Lazy per-test imports of not-yet-built surfaces so collection succeeds and the Wave-0 smoke passes while resolver/driver cases fail RED on missing impl"
metrics:
  duration: wave-1
  completed: 2026-07-10
commit: 69a094e
---

# Phase 14 Plan 01: RED Backfill Suite + A1-A3 Smoke Summary

RED test suite pinning the PNL-05 backfill contract (14 VALIDATION cases) plus a Wave-0
alpaca-py smoke confirming the CLOSED-query mechanism before it is built.

## What shipped
- `tests/test_backfill.py` — zero-network fakes (`FakeLogger`, `FakeAlpacaClient` with scripted
  `get_order`/`get_positions`/`get_closed_orders`), all 14 cases as executable specs, P&L asserted
  against `src.pnl.realized_pnl` + `src.fee_gate.TAKER_FEE` (no inline math).
- Lazy imports: smoke passes today; 15 non-smoke cases RED on `ModuleNotFoundError`/`ImportError`
  (missing impl), 1 Postgres-gated case skips cleanly.

## A1-A3 outcome — ALL CONFIRMED
- **A1**: `QueryOrderStatus.CLOSED` imports and is a real enum member. ✓
- **A2**: `GetOrdersRequest(status=CLOSED, symbols=[...], limit=500, direction='desc')` builds;
  `after=` accepted. ✓
- **A3**: crypto symbol keeps the slash (`"BTC/USD"`), not stripped — matches `alpaca_trades.symbol`. ✓

No deviations.

## Self-Check: PASSED
- tests/test_backfill.py exists; commit 69a094e present.
- RED state verified: 15 failed (missing impl), 1 passed (smoke), 1 skipped (Postgres).
