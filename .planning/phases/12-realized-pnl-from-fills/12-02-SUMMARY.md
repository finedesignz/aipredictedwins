---
phase: 12-realized-pnl-from-fills
plan: 02
subsystem: pnl
tags: [pnl-02, migration-016, fees]
requires: [12-01]
provides: [src/pnl.py, alpaca_trades.fees, update_alpaca_trade(fees=)]
key-files:
  created:
    - src/pnl.py
    - dashboard/api/migrations/016_realized_pnl_fees.sql
  modified:
    - src/db_schema.sql
    - src/db.py
    - src/trade_logger.py
metrics:
  commits: 080bf4b, 72098ef, 26c2f05
reconstructed: true
reconstructed-note: "Written 2026-07-14 during the v1.1 milestone archive. The implementer never wrote a SUMMARY for this plan; this one is reconstructed from the plan, the three commits above, the code on disk, and VERIFICATION.md. Nothing here is asserted beyond that evidence."
---

# Phase 12 Plan 02: The P&L Helper, the Fees Column, the Fees Kwarg Summary

The foundation Plan 03 wires against: one pure function that owns the closed-trade number, one
additive nullable column to hold the fee total, and the kwarg that carries it from caller to Postgres.

## Tasks

- **Task 1 — `src/pnl.py` (commit `080bf4b`).** 28 lines, one function:
  `realized_pnl(side, entry_fill, exit_fill, qty, taker_fee) -> float`. Short branch on
  `side in ("sell", "short")` → `(entry_fill - exit_fill) * qty`, long otherwise; fees =
  `(entry_fill*qty + exit_fill*qty) * taker_fee`, i.e. **both legs**. Pure — no I/O, no logging, no
  fallback logic (fallbacks belong to the monitor). The docstring states outright that
  `SLIPPAGE_BUFFER` is never subtracted here, because real fills already embed slippage; the module
  never imports it. Turned Plan 01's cases 1-5 GREEN.
- **Task 2 — migration 016 + schema mirror (commit `72098ef`).**
  `dashboard/api/migrations/016_realized_pnl_fees.sql` (8 lines): a single
  `ALTER TABLE alpaca_trades ADD COLUMN IF NOT EXISTS fees DOUBLE PRECISION;` — additive, idempotent,
  no NOT NULL, no DEFAULT, **no backfill** (historical repair is deliberately not this phase's
  business). Mirrored into `src/db_schema.sql` so `_bootstrap_schema()` on a fresh DB agrees with the
  migrated one.
- **Task 3 — the `fees` kwarg through both layers (commit `26c2f05`).** `src/db.py::update_alpaca_trade`
  gains `fees: float | None = None`, the UPDATE gains `fees = %s` (parameterized), and `fees` is
  threaded into the params tuple. `src/trade_logger.py::update_alpaca_trade` gains the same default
  and forwards it positionally. Purely additive: every pre-existing caller that omits `fees` writes
  NULL and is otherwise unchanged.

## Verification

- `pytest tests/test_pnl.py` — cases 1-5 GREEN against the new helper (per plan + VERIFICATION.md).
- `pytest tests/ -q` — no regressions from the additive kwarg (`test_close_pnl.py` still RED at this
  point, as designed, pending Plan 03).
- VERIFICATION.md truths 1 and 2 cite this plan's artifacts directly: `src/pnl.py:10-28`,
  `016_realized_pnl_fees.sql`, `db_schema.sql:45-46`, `db.py:107,118,121`, `trade_logger.py:42-44`.

## Deviations

None visible in the commits. All three tasks landed as planned, one commit each, additively.
Migration 016 was applied to prod Postgres at some point before Phase 19's migration 019 —
**exactly when is not recorded** in this phase's artifacts.

## Self-Check: PASSED (reconstructed)

`src/pnl.py`, `016_realized_pnl_fees.sql` exist; the `fees` column is in `db_schema.sql`; `fees = %s`
is in `db.py`'s UPDATE; commits `080bf4b`, `72098ef`, `26c2f05` are present in `main`.
