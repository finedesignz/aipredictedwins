---
phase: 18
plan: 06
subsystem: backtest-sweep
requirements: [TUNE-01, TUNE-03]
key-files:
  created: [scripts/sweep_backtest.py, .planning/phases/18-profitable-retune/18-BACKTEST.md, .planning/phases/18-profitable-retune/18-HOLDOUT.lock]
commits: [5e08834, 180d32d]
---

# Phase 18 Plan 06: the grid sweep Summary

**VERDICT: NEGATIVE. No grid point clears the acceptance bar. SHIP THE QUARANTINE ONLY.**

18 TRAIN cells run (12 live + 6 structurally empty). Best win rate anywhere in the grid:
**4.17%** (bar: 40%). Every live cell loses money on TRAIN. The six `min_confluence=5` cells
return `trades=0` — the confluence score ceiling is 4 — and auto-fail on the `>= 30 trades`
criterion, which `passes_bar()` checks FIRST so they read as EMPTY, not as bad configs.

One HOLDOUT shot, on the thing that will actually ship (baseline + quarantine), against the
baseline: the quarantine improves max drawdown (6.36% vs 7.52%) but on 11 trades — far below the
30-trade floor — and the return is a wash. Recorded as a measurement, not as a pick. The
`18-HOLDOUT.lock` refuses a second holdout run (verified: exit 2).

`scripts/sweep_backtest.py` runs **each cell as a fresh subprocess** with
`BAR_CACHE_DIR=data/backtest_bars` and never a bar-fixture flag — an in-process loop would read
`data_loader.py:20`'s stale import-time cache default and re-fetch from Alpaca mid-sweep. It has
no `--apply/--write/--fix` surface, places no orders, and fences the baseline knob read with
`AIPW_DB_READONLY=1`.

Baseline knobs read READ-ONLY from `GET /api/bots` (no write): A `mc=4 k=0.25`,
B `mc=4 k=0.50` (over the ceiling), C tradingagents, E copytrade (disabled). Recorded verbatim in
18-BACKTEST.md as the revert target.

## Recommendation carried into 18-07 (held)

Quarantine only, on the confluence bots. Leave `min_confluence`/`kelly_fraction` alone. Bot B
0.50 → ≤ 0.25 (hardcoded ceiling, not a tuning result; its `max_position_pct=0.10` also exceeds
the 5% rule — flagged). Do not tune further against this engine: Phase 17 showed the losses are
EXIT-side, the dimension the engine models least faithfully.

## Deviations from Plan

No cell passed TRAIN, so no retune candidate exists. Rather than skip the holdout, the single
authorized shot was spent measuring the quarantine alone (baseline knobs + quarantine ON) against
the baseline on unseen data — the configuration that will actually ship. It is labelled as a
measurement, not a pick, and the holdout was not re-rolled.

## Self-Check: PASSED
