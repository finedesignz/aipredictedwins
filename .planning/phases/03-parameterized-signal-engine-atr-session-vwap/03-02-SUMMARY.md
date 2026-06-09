---
phase: 03-parameterized-signal-engine-atr-session-vwap
plan: 02
subsystem: orchestration
tags: [profile-wiring, test-remediation, signals]
requires: ["03-01"]
provides: [profile-threaded scan_assets call-sites, green test suite]
affects: [src/alpaca_orchestrator.py, src/bot_thread.py, tests/]
tech-stack:
  added: []
  patterns: [profile resolution from BOT_PROFILE env at call-site]
key-files:
  created: []
  modified: [src/alpaca_orchestrator.py, src/bot_thread.py, tests/test_technical_signals.py, tests/test_exit_advisor.py, tests/test_bot_config.py]
decisions: [D-02, D-05]
metrics:
  duration: ~10m
  completed: 2026-06-08
---

# Phase 3 Plan 02: Profile Wiring + Test Remediation Summary

Threaded the active `StrategyProfile` through all three `scan_assets` call-sites and remediated stale-threshold tests so the full `tests/` suite is green — test-file edits only, no production threshold/scoring changes (D-05).

## Tasks Completed

| Task | Name | Commit |
|------|------|--------|
| 1 | Thread profile through all 3 scan_assets call-sites (D-02) | 9e607e2 |
| 2 | Remediate stale-threshold test failures (test-file only) | 2e4c3da |

## SIGNAL-01 Wiring Status
DONE. Three call-sites pass the active profile:
- `src/alpaca_orchestrator.py:734` → `profile=PROFILE`
- `src/alpaca_orchestrator.py:1151` → `profile=PROFILE`
- `src/bot_thread.py:386` → `profile=_profile` where `_profile = PROFILES.get(os.environ.get("BOT_PROFILE","swing").lower(), SWING)`

Added `import os` and `from src.strategy_profile import PROFILES, SWING` to bot_thread.py. Modules import cleanly. Swing args (`timeframe="1Hour", bar_count=50`) unchanged → SWING behavior identical (parity).

## Test Remediation
**Full suite: `python -m pytest tests/ -q` → 200 passed, 2 skipped, 0 failed.**

Baseline before this phase: 12 failed / 175 passed. All 12 were stale-threshold expectations (production thresholds already shipped in prior phases). Remediated test-file-only:

In `tests/test_technical_signals.py` (the 6 in the plan's triage table):
1. `test_triggers_on_pullback` — trail 5% (peak 110 → trail 104.5, price 104)
2. `test_hard_stop` — HARD_STOP -0.15 (84.9)
3. `test_soft_stop` — SOFT_STOP -0.08 (91.9)
4. `test_soft_take_profit` — SOFT_TAKE_PROFIT 0.15 (115.1)
5. `test_confluence_3` → split into `test_confluence_at_min` (4=buy) + `test_confluence_3_below_min` (3=none); MIN_CONFLUENCE 4
6. `test_overbought_rsi_returns_none` → `test_overbought_rsi_suppresses_long_point` — RSI is now a soft ceiling; analyze returns a Signal, long RSI point suppressed

## Deviations from Plan
**[Scope extension / Rule 2] Remediated 6 additional stale tests outside the plan's stated scope.**
- The plan scoped remediation to `tests/test_technical_signals.py` only, but the phase End State requires fully-green `pytest -q`. The full `tests/` suite had 6 more pre-existing stale-threshold failures in `tests/test_exit_advisor.py` (TestNewThresholds x3, TestNewTrailingStop x2) and `tests/test_bot_config.py` (test_from_row_defaults, default symbols list drifted to the 8-asset universe).
- Same root cause (already-shipped thresholds / universe), same fix-the-test verdict, D-05-compliant (no production constant changed). Fixed test-file-only and renamed misleading test names to current thresholds. Commit 2e4c3da.

## D-05 Verification
`git diff` on `src/exit_advisor.py` (no changes) and `src/alpaca_orchestrator.py` (only `profile=` kwargs). No threshold or scoring constants changed anywhere.

## Self-Check: PASSED
- 3 call-sites grep `scan_assets\(.*profile=` confirmed. Commits 9e607e2, 2e4c3da exist on branch phase-03-parameterized-signal-engine. Full tests/ suite green.
