---
phase: 04-deterministic-atr-exits
plan: 01
subsystem: exits
tags: [tdd, atr, trailing-stop]
requires: [strategy_profile.SWING, technical_signals._atr]
provides: [TrailingStop.update_atr, tests/conftest.py, tests/test_atr_exits.py]
affects: [src/exit_advisor.py]
key-files:
  created: [tests/conftest.py, tests/test_atr_exits.py]
  modified: [src/exit_advisor.py]
decisions:
  - "Deterministic ATR bars: flat closes + constant high-low => Wilder ATR == high-low exactly."
  - "Generator exposed via atr_bars fixture (tests/ is not a package, no by-name import)."
metrics:
  completed: 2026-06-08
---

# Phase 4 Plan 01: Test Foundation + ATR TrailingStop Summary

RED spec + side-aware ATR-distance trailing-stop tracker, unblocking the 04-02 monitor rewrite.

## Built
- `tests/conftest.py` — `fake_bars`, `make_bars_for_atr` (verified against `_atr`), `mock_alpaca`/`mock_logger`/`mock_advisor` fixtures, `atr_bars` generator fixture, ATR sanity test.
- `tests/test_atr_exits.py` — 8 tests: long/short ATR stop, trail ratchet (long+short), zero-ATR safe, max-hold fires (DAYTRADE), swing-None skip, precedence (hard_stop wins), no-LLM assertion.
- `src/exit_advisor.py` — `TrailingStop.update_atr(trade_id, side, entry_price, current_price, atr, mult_trail)`: high-water longs / low-water shorts, arms only in profit, `atr<=0 -> None`; `_troughs` dict added; `remove()` clears both; pct `update()` unchanged.

## Test Results
- 8 tests RED at Task 2 (TypeError on missing 4th constructor arg — confirms RED, not import error).
- `update_atr` unit-verified (long, short, ratchet, atr<=0, not-armed) + `update()` back-compat.
- `tests/test_exit_advisor.py`: 10 passed (no regression).

## Deviations
- Plan Task 3 verify expected `test_atr_trail_ratchet` GREEN after Task 3, but that test drives the 4-arg `PositionMonitor` constructor which only lands in 04-02 — it goes green in 04-02. `update_atr` itself was unit-verified at Task 3 instead. (Plan-internal sequencing inconsistency, no behavior change.)

## Self-Check: PASSED
- tests/conftest.py, tests/test_atr_exits.py, src/exit_advisor.py present.
- Commits 8a03a09, 2b66939, c2e094c in log.
