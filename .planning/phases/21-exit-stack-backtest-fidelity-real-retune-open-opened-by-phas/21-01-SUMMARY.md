---
phase: 21-exit-stack-backtest-fidelity-real-retune
plan: 01
subsystem: exit-ladder
tags: [exit, refactor, tdd, single-source-of-truth]
requires: []
provides: [src.exit_ladder.evaluate_exit]
affects: [src/alpaca_orchestrator.py]
tech-stack:
  added: []
  patterns: [pure-function-extraction, parity-drift-guard-test]
key-files:
  created:
    - src/exit_ladder.py
    - tests/backtester/test_exit_model.py
    - tests/backtester/test_exit_parity.py
  modified:
    - src/alpaca_orchestrator.py
decisions:
  - "Model ONLY the 4 deterministic ATR rungs; soft/LLM rung is a dead path (Research Pitfall 1)"
  - "Parity test re-states the live inline ladder verbatim to catch future drift"
metrics:
  duration: ~15m
  completed: 2026-07-20
---

# Phase 21 Plan 01: Shared Exit Ladder (evaluate_exit) Summary

Extracted the live deterministic 4-rung exit ladder into one pure, side-aware
function `src/exit_ladder.evaluate_exit` and re-wired the live position monitor to
delegate to it — establishing the D-02 single source of truth so Plan 02's
backtester consumes the identical decision logic with zero live/backtest drift.

## What Was Built

- **`src/exit_ladder.py`** — `evaluate_exit(profile, side, entry_price, current_price,
  hours_held, atr, trailing, trade_id) -> str | None`. First-match-wins precedence:
  `hard_stop -> max_hold -> trailing_stop -> atr_stop`. Side-aware pnl and ATR levels;
  pure (no broker, DB, LLM, or logging). Reuses `TrailingStop.update_atr` — not
  reimplemented. No soft rung (dead path, would inject LLM non-determinism).
- **`src/alpaca_orchestrator.py`** — inline ladder at :316-341 replaced with a single
  `evaluate_exit(...)` call assigned to `threshold`. Surrounding pnl/atr/hours_held
  setup, the dormant `tightened_stop` rung, logging, and broker close path unchanged.
- **Tests** — `test_exit_model.py` (per-rung precedence + side-awareness, 10 cases),
  `test_exit_parity.py` (drift-guard table + trailing sequence pinning evaluate_exit
  to a verbatim re-statement of the live inline ladder).

## Verification

- `python -m pytest tests/backtester/test_exit_parity.py tests/backtester/test_exit_model.py -q` -> 22 passed
- `python -m pytest tests/ -q` -> 559 passed, 13 skipped, 0 failures (no regression)
- `grep "evaluate_exit(" src/alpaca_orchestrator.py` -> hit; old inline `if pnl_pct <= self.profile.hard_stop_pct` block gone.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected `test_atr_non_positive_skips_trail_and_fixed` short case**
- **Found during:** Task 2 (GREEN)
- **Issue:** The short assertion used `current=200` (entry 100) with `hard_stop_pct=-0.99`,
  giving a -100% short loss that legitimately trips `hard_stop` — so the case could
  never return None regardless of the atr<=0 skip it meant to test.
- **Fix:** Changed short current price to `101.0` (small loss, no hard-stop trip), so the
  case correctly asserts rungs 3-4 are skipped when `atr == 0`.
- **Files modified:** tests/backtester/test_exit_model.py
- **Commit:** d3d789c

## Commits

- 1d5ac28 test(21-01): failing parity + per-rung tests (RED)
- d3d789c feat(21-01): extract shared pure evaluate_exit exit ladder (GREEN)
- 4c9f382 refactor(21-01): route live monitor through shared evaluate_exit

## Self-Check: PASSED
- src/exit_ladder.py — FOUND
- tests/backtester/test_exit_model.py — FOUND
- tests/backtester/test_exit_parity.py — FOUND
- Commits 1d5ac28, d3d789c, 4c9f382 — FOUND
