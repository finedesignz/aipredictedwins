---
phase: 17-per-symbol-performance
plan: 03
subsystem: analytics
tags: [TUNE-02, pure, aggregator]
requires: [17-01]
provides: [src.symbol_stats.aggregate, src.symbol_stats.MIN_SAMPLE]
affects: [17-04]
key-files:
  created: [src/symbol_stats.py]
metrics:
  tasks: 1
  lines: 168
  completed: 2026-07-13
---

# Phase 17 Plan 03: The Pure Aggregator Summary

`src/symbol_stats.py::aggregate(rows, min_sample=MIN_SAMPLE, key=("bot_id","symbol"))` — one pure function
(zero I/O, zero DB import, zero env) holding every rule a reader of the report must be able to trust.
Commit `e6e8870`.

## The four buckets

| Bucket | Condition | Counted? |
|---|---|---|
| win | `pnl > 0` | yes |
| loss | `pnl < 0` | yes |
| `zero_pnl` | `pnl == 0.0` | **no** — indistinguishable from the external-exit sentinel (`src/alpaca_orchestrator.py:167-176`) |
| `null_pnl` | `pnl is None` | **no** — a resolution defect; never coerced |

`trades = wins + losses`. Non-position statuses are dropped BEFORE bucketing (`_POSITION_CLOSED`, the
literal at `src/db.py:215`), so a `rejected` row can never reach the `pnl == 0.0` branch — `aggregate` of
only-nonposition rows is `[]`.

## The two fee counters (distinct predicates)

- `null_fees` — EVERY row in the cell with `fees is None`, including zero/null-pnl rows.
- `gross_pnl_rows` — the COUNTED subset only; their `pnl` is GROSS
  (`src/bot_c/strategy.py:393-395`, `src/trend_strategy.py:172-173` store gross and pass no fees).
- `gross_pnl_rows <= null_fees` always; case 7 asserts strict `<` on a mixed fixture.
- `total_fees` is incomplete drag disclosure and is never fee-subtracted from `realized_pnl`.

Invariant: `expectancy == win_rate*avg_win + (1-win_rate)*avg_loss == realized_pnl / trades`, with
`avg_loss` carried NEGATIVE and both defect buckets excluded from BOTH sides. Every denominator guarded;
`aggregate([]) == []`. Group key is `src.universe.normalize` with the first-seen raw spelling kept as
`display`. `MIN_SAMPLE = 5` marks a cell `insufficient` but never hides it.

## Verification

- `python -m pytest tests/test_symbol_stats.py -q` after this plan: **19 passed, 3 failed, 1 skipped** —
  the three failures were exactly cases 20/22/23, which require Plan 04's `scripts/symbol_report.py`. The
  read-only fence (case 20) was NOT weakened to make it green early.
- `env -u DATABASE_URL python -c "import src.symbol_stats"` → clean import (purity proof).
- No `psycopg` / `src.db` / `DATABASE_URL` import in the module.

## Deviations from Plan

None — plan executed exactly as written. (The acceptance grep
`grep -nE "...|from src.db|..." src/symbol_stats.py` matched a *comment* containing the path
`src/db.py:215` because `.` is a regex wildcard; the comment was reworded so the gate reads clean. No
import exists.)

## Prod safety

No prod resource was written. This module cannot write — it has no I/O at all.

## Self-Check: PASSED

- `src/symbol_stats.py` exists; commit `e6e8870` in `git log`.
