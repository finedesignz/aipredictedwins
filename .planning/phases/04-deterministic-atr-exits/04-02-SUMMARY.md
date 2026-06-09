---
phase: 04-deterministic-atr-exits
plan: 02
subsystem: exits
tags: [atr, exit-ladder, profile, deterministic]
requires: [TrailingStop.update_atr, technical_signals._atr, strategy_profile]
provides: [PositionMonitor.profile, ATR-exit-ladder]
affects: [src/alpaca_orchestrator.py, src/bot_thread.py]
key-files:
  modified: [src/alpaca_orchestrator.py, src/bot_thread.py]
decisions:
  - "First-match ladder: hard_stop_pct -> max_hold -> ATR trail -> ATR stop."
  - "ATR computed live at self.profile.timeframe (not literal 1Hour)."
  - "ExitAdvisor import/attr retained but never called for the exit decision (Phase 5 removes)."
metrics:
  completed: 2026-06-08
---

# Phase 4 Plan 02: Deterministic ATR Exit Ladder Summary

Replaced the MiroFish LLM soft-exit branch with a deterministic, side-aware ATR ladder + absolute overrides; threaded the active profile into both monitor sites.

## Built
- `PositionMonitor.__init__` gains `profile=SWING`; stored `self.profile`.
- Per-position: `hours_held` computed unconditionally; ATR fetched live at `self.profile.timeframe`, `limit=atr_period+5`, via `_atr`.
- First-match ladder: 1) `pnl_pct <= hard_stop_pct` -> `hard_stop`; 2) `max_hold_hours is not None and hours_held > max_hold_hours` -> `max_hold`; 3) `atr>0` and `update_atr(...)` -> `trailing_stop`; 4) `atr>0` and side-aware ATR-stop breached -> `atr_stop`. `atr<=0` -> only rungs 1+2.
- Deleted the `elif threshold in ("soft_stop","soft_take_profit")` branch and its `should_exit()` call. Close path / side-aware pnl preserved.
- Profile threaded: orchestrator `main()` passes `PROFILE`; `bot_thread` resolves `PROFILES.get(BOT_PROFILE, SWING)`.

## Test Results
- `tests/test_atr_exits.py`: 8 passed.
- Full suite `python -m pytest tests/ -q`: **208 passed, 2 skipped** (200 baseline + 8 new).
- No-LLM assertion (`test_no_llm_call`): PASS — `mock_advisor.should_exit.assert_not_called()` across atr_stop (long/short) and hard_stop.
- Exactly 2 `PositionMonitor(` sites, both passing a profile; no `should_exit` in monitor decision path; monitor ATR uses `self.profile.timeframe`.

## Deviations
- None.

## Self-Check: PASSED
- src/alpaca_orchestrator.py, src/bot_thread.py modified.
- Commits 73dedfa, eb76c42 in log.
