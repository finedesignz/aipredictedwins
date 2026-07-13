---
phase: 18
plan: 03
subsystem: position-monitor
requirements: [TUNE-01]
key-files:
  modified: [src/alpaca_orchestrator.py, src/backfill.py]
commits: [9164358]
---

# Phase 18 Plan 03: the sentinel writer Summary

`src/alpaca_orchestrator._resolve_external_exit(alpaca, row, live_symbols) -> dict`. A position
that vanishes from Alpaca now resolves to its REAL fee-net exit from order history, or to
`status='closed', exit_price=NULL, pnl=NULL`. The `pnl=0.0` /
`exit_price=trade.get("entry_price")` fabrication literals are GONE.

Zero new resolver logic: it wires `backfill.resolve_stale_row` / `backfill._match_close` /
`pnl.realized_pnl` / `order_resolution.classify_order` / `universe.normalize`. `git diff` on
`src/pnl.py`, `src/order_resolution.py`, `src/alpaca_client.py` is EMPTY.

## The three doors, all closed

1. **The slash trap** — the monitor builds `live_symbols` slash-STRIPPED (`"BTCUSD"`) while
   `row["symbol"]` is slashed. BOTH sides now go through `src.universe.normalize`. Without it the
   fix would have mass-closed every held position on cycle 1.
2. **THE THIRD DOOR** — `if live_symbols is None: return {}` is the FIRST line, before any Alpaca
   call. `None` means `get_positions()` FAILED; it does not mean "nothing is held". The literal
   `(live_symbols or ())` appears nowhere. The monitor's `if live_symbols is not None:` guard at
   the call site is RETAINED verbatim.
3. **The transient error** — every Alpaca call is try/except'd and returns `{}` (leave the row
   open, retry next cycle). "unresolvable" means *Alpaca answered and there is no matching close*
   — never *Alpaca did not answer*. `get_order` and `get_closed_orders` are tested raising
   independently.

A terminal 0-fill entry keeps its honest `pnl=0`. The 395 historical sentinel rows were NOT
touched: no backfill, no UPDATE, no DELETE.

## Deviations from Plan

None. The only diff to `src/backfill.py` is the permitted one-line W1 comment at `:71`.

**Phase-20 item (W1):** `src/backfill.py` has the SAME slash mismatch (`:147` builds
`live_symbols` slash-stripped; `:71` compares a slashed `row["symbol"]`). It is saved today only
by `close_order is None -> unresolvable -> no write`. Prod now has one resolver that normalizes
and one that does not. Out of scope here (shared surface, ~20 tests).

## Self-Check: PASSED — `tests/test_external_exit_resolution.py` 10 passed; `tests/test_backfill.py` green.
