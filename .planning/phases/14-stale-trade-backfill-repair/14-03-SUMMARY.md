---
phase: 14
plan: 03
subsystem: backfill/driver
tags: [pnl-05, tdd-green, one-shot]
requires: [14-02]
provides: [resolve_stale_row, backfill, scripts/backfill_trades.py]
affects: []
key-files:
  created: [src/backfill.py, scripts/backfill_trades.py]
  modified: []
decisions:
  - "Closing-order match heuristic (opposite side, filled_at strictly after entry, earliest, qty tolerance 2%) lives in the driver; resolve_stale_row stays pure and I/O-free"
  - "Entrypoint mirrors scripts/reconcile.py convention (run via python -m scripts.backfill_trades)"
metrics:
  duration: wave-3
  completed: 2026-07-10
commits: [54db75e, 4577f7a]
---

# Phase 14 Plan 03: Resolver + Driver + Entrypoint Summary

Completes PNL-05: genuinely-stale `alpaca_trades` rows resolve to true terminal state via the reused
Phase-11/12 paths, idempotently, per-bot, dry-run by default, never deleting a row.

## What shipped
- **`src/backfill.py`** (`54db75e`):
  - pure `resolve_stale_row(row, entry_order, live_symbols, close_order)` → terminal non-position
    (pnl=0) / unchanged / closed (realized_pnl + fees) / unresolvable; entry_fill falls back to
    entry_price, qty uses filled_qty; P&L via `src.pnl.realized_pnl` + `src.fee_gate.TAKER_FEE`.
  - `backfill(apply=False)` driver: enumerates via `reconciliation._enabled_bot_ids`, one
    `_client_for_bot` per bot (never bare keys), `_match_close` heuristic (opposite side, filled,
    filled_at strictly after entry, earliest; qty within 2% else unresolvable), dry-run default
    writes nothing, `--apply` writes via `TradeLogger.update_alpaca_trade` (UPDATE-only). Idempotent
    structurally (candidates fresh each run, terminal rows drop out).
- **`scripts/backfill_trades.py`** (`4577f7a`) — thin argparse entrypoint, `--apply` flag, per-bot +
  ALL counts table (resolved/unchanged/unresolvable/residue), DRY RUN banner.

## RED → GREEN
Wave 1 left 15 cases RED on missing impl. After Plan 02 + 03: `tests/test_backfill.py` = 16 passed,
1 skipped (Postgres-gated). Full suite: **336 passed, 4 skipped** (baseline 320 + 16 new; zero
regressions).

## Deviations from Plan
- `scripts/backfill_trades.py` run directly (`python scripts/backfill_trades.py`) hits
  `ModuleNotFoundError: src` — identical pre-existing behavior to `scripts/reconcile.py`; documented
  invocation is `python -m scripts.backfill_trades`. Not a Phase-14 regression.

## Known Stubs
None.

## Self-Check: PASSED
- src/backfill.py + scripts/backfill_trades.py present; commits 54db75e/4577f7a present.
- Full suite 336 passed, 4 skipped — GREEN.
