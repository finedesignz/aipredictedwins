---
phase: 17-per-symbol-performance
plan: 01
subsystem: testing
tags: [TUNE-02, RED, nyquist, prod-safety]
requires: []
provides: [tests/test_symbol_stats.py]
affects: [17-02, 17-03, 17-04]
key-files:
  created: [tests/test_symbol_stats.py]
metrics:
  tasks: 3
  cases: 23
  completed: 2026-07-13
---

# Phase 17 Plan 01: RED Suite Summary

23 executable specs pinning the TUNE-02 contract — the four-bucket P&L model, the two distinct fee
counters, the count/rate divergence against the dashboard's number, and a prod-safety fence that proves
itself.

## Tasks

| Task | Cases | Commit |
|---|---|---|
| 1 — buckets, fabricated-loss traps, fee split, naive divergence | 1-7, 12-15, 17 | `f74795c` |
| 2 — sample guard, normalization, roll-ups, annotation, ranking | 8-11, 16, 22, 23 | `5d5dc42` |
| 3 — case 18 pool rebind, cases 19/20/21 fence | 18-21 | `366fb9b` |

RED proof at each step: `ModuleNotFoundError: No module named 'src.symbol_stats'` (collection error), never
a malformed assert.

## The load-bearing specs

- **Cases 2/3** — a `closed` row with `pnl == 0.0` (`src/alpaca_orchestrator.py:167-176`) is bucketed
  `zero_pnl`: not a win, not a loss, not in `trades`.
- **Case 7** — `gross_pnl_rows` (counted subset, NULL fees) `<` `null_fees` (all rows, NULL fees) on a mixed
  fixture: two predicates, not one counter twice.
- **Case 12** — `assert aggregate(nonposition_rows) == []`, an explicit empty list.
- **Case 17** — re-derives `src/db.py:227-238` inline: `resolved - trades == zero_pnl + null_pnl` and
  `win_rate != approx(naive_win_rate)`, while `realized_pnl == approx(naive_total)` (the sums agree by
  construction — which is why a delta print would be a lie).
- **Case 18 (prod fence)** — closes `src.db._pool`, sets it to `None`, repoints `DATABASE_URL` from
  `TEST_DATABASE_URL`, then asserts `conn.info.dbname` / `conn.info.host` against the parsed URL **on the
  live connection, before the first INSERT**, and nulls the pool again on teardown. The env-string compare
  is kept but explicitly labelled as necessary-not-sufficient.
- **Cases 20/21** — the fence strips `#` lines AND docstrings (`ast.Expr`/`ast.Constant` by lineno) before
  the mutating-keyword regex, carries a positive control (stripped source non-empty, `SELECT bot_id, symbol`
  present), checks `--apply` on the argparse surface, and self-tests against `update_alpaca_trade` through
  the SAME helpers.

## Deviations from Plan

**1. [Rule 3 — blocking] Case 21 cannot be green while the module-level import is RED.**
The plan asks for both a module-level `from src.symbol_stats import ...` (the RED proof, required by
`must_haves.truths` and `key_links`) and for `test_readonly_fence_actually_fires` to PASS on day one. A
module-level ImportError is a collection error — no test in the file can run. The RED proof was kept (it is
the stated acceptance criterion); case 21 became green as soon as Plan 03 landed, and it verifiably fires
(it asserts `UPDATE` IS found in `update_alpaca_trade` through the same strip+scan helpers case 20 uses).

**2. [Rule 3 — blocking] The fence's word-boundary regex caught `sys.path.insert`** in
`scripts/symbol_report.py` (Plan 04). This is the fence working as designed. Fixed in Plan 04 by using
`sys.path.append`, not by weakening the fence.

## Prod safety

No prod resource was written. Case 18 ran only against a LOCAL Postgres
(`postgresql://…@127.0.0.1:55441/aipw_test17`), and its live-connection positive control passed before its
first INSERT.

## Self-Check: PASSED

- `tests/test_symbol_stats.py` exists (23 test functions).
- Commits `f74795c`, `5d5dc42`, `366fb9b` present in `git log`.
