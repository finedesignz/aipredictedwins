---
phase: 20-verification-e2e
plan: 01
subsystem: verification
tags: [tdd-red, backfill, paper-gate]
requires: []
provides: [G3-red-suite, G2-red-suite]
affects: [tests/test_backfill.py, dashboard/api/tests/test_paper_gate.py]
key-files:
  created: [dashboard/api/tests/test_paper_gate.py]
  modified: [tests/test_backfill.py]
decisions:
  - "tests/test_backfill.py:199 CORRECTED IN PLACE, not supplemented — a green test that certified the bug is worse than no test"
metrics:
  suite-before: "488 passed, 29 skipped"
  suite-after: "490 passed, 29 skipped, 10 failed (intended RED)"
completed: 2026-07-13
---

# Phase 20 Plan 01: RED — the backfill slash bug and the paper gate

The two defects that guard live money got their first failing tests: `src/backfill.py`
would close live positions with fabricated P&L, and the 50-trade paper gate counted rows
that were never trades.

## THE LOADED GUN, PHOTOGRAPHED

Executed against current `main`, a genuinely-HELD `BTC/USD` position in Alpaca's **real
slashless** payload shape:

```
>>> resolve_stale_row(row(symbol="BTC/USD"), entry, live_symbols={'BTCUSD'}, close_order=close)
('resolved', {'status': 'closed', 'exit_price': 80.0, 'pnl': -20.45, 'fees': 0.45})
```

**A live, open position, closed with a fabricated $20.45 loss.** This matches RESEARCH's
prediction exactly. The `unchanged` arm was UNREACHABLE in production: `:148` builds
`live_symbols` slash-STRIPPED (Alpaca returns `pos.symbol` raw) while `:72`/`:155` compare
a slashed `row["symbol"]`. `'BTC/USD' in {'BTCUSD'}` is False for **every** held position,
**always**.

## The must-fail cases — verbatim

| Case | Test | Verbatim failure on `main` |
|------|------|----------------------------|
| 3 (corrected) | `test_backfill_still_open_unchanged` | `AssertionError: assert 'unresolvable' == 'unchanged'` |
| 1 | `test_held_position_real_alpaca_shape_is_unchanged` | `AssertionError: assert 'resolved' == 'unchanged'` — kwargs `{'status':'closed','exit_price':80.0,'pnl':-20.45,'fees':0.45}` |
| 2 | `test_held_position_no_close_order_is_unchanged_not_unresolvable` | `assert 'unresolvable' == 'unchanged'` |
| 3 | `test_symbol_shape_matrix` | `AssertionError: row='BTC/USD' live={'BTCUSD'} -> 'resolved'` (2 of 4 combinations fail) |
| 5 | `test_driver_issues_no_close_hunt_for_a_held_symbol` | a close hunt IS issued for a symbol still held |
| 6 | `test_get_positions_none_aborts_the_bot` | resolves the row against an empty set; no `positions_unavailable` marker |
| 6b | `test_resolve_stale_row_treats_None_live_symbols_as_the_SAFE_arm` | `TypeError` / wrong arm |
| 9 | `test_non_trade_rows_are_excluded_from_the_paper_gate` | **`assert 9 == 3`** — from the REAL `get_settings` route driven against a SQL-honouring fake |
| 10 | `test_the_bare_count_star_never_returns` | the literal `SELECT COUNT(*) AS n FROM alpaca_trades` found in settings.py |

Case 11 PASSES today (the canonical predicate already exists at settings.py:43-49 for the
win rate, and the targets are pinned). That is honest: only the *gate figure* was wrong.

## What was corrected, not merely added

`tests/test_backfill.py:199` fed `live_symbols={"BTC/USD"}` — a **slashed** set Alpaca
never emits. The test did not miss the bug; **it encoded it**, passing green by mirroring
the defect. It is now `{"BTCUSD"}`. The W3 sweep converted the remaining slashed
`get_positions()` fixtures (`:378`, `:433-436`) to the real shape, so the only slashed
`live_symbols` left is case 3's four-way matrix, where it is deliberately under test.

## Deviations from Plan

None. Case 11's predicate-half passing (rather than failing) is a fact about the code, not
a deviation — settings.py already ran the canonical query; only its *use* as the gate was
broken.

## Self-Check: PASSED
- `dashboard/api/tests/test_paper_gate.py` — FOUND
- Suite: 490 passed, **29 skipped** (unchanged), 10 intended failures
- Zero new skips. No test touches prod DB, live Alpaca, or the network.
