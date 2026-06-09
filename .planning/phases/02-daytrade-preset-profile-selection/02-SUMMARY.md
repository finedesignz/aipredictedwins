---
phase: 02-daytrade-preset-profile-selection
plan: 01
subsystem: strategy-profiles
tags: [daytrade, profile-selection, bot_profile]
requires: [src/strategy_profile.py SWING/PROFILES, alpaca_orchestrator env-default chain]
provides: [DAYTRADE preset, PROFILES['daytrade'], BOT_PROFILE-driven PROFILE resolution]
affects: [src/alpaca_orchestrator.py startup, banner]
tech-stack:
  patterns: [frozen-dataclass preset, env-var fail-fast selection]
key-files:
  modified:
    - src/strategy_profile.py
    - src/alpaca_orchestrator.py
    - tests/test_strategy_profile.py
decisions:
  - "BOT_PROFILE resolved at module-load PROFILE line (not main()) to keep Phase-1 env-default chain intact"
  - "Unknown BOT_PROFILE raises ValueError (fail fast, no silent fallback)"
metrics:
  duration: ~10m
  completed: 2026-06-08
  tasks: 3
  files: 3
---

# Phase 2 Plan 01: DAYTRADE Preset + Profile Selection Summary

Added the DAYTRADE 5-min preset and wired the orchestrator to select its active profile from `BOT_PROFILE` (default swing, unknown fails fast), with swing behavior byte-for-byte unchanged.

## What Was Built

- **DAYTRADE preset** (`src/strategy_profile.py`): `name=daytrade, timeframe=5Min, scan_interval_s=120, bar_count=100, htf_filter_timeframe=1Hour, ema 9/21, rsi/adx/atr 14, atr_mult_stop=1.5, atr_mult_trail=2.0, hard_stop_pct=-0.04, max_hold_hours=6.0, kelly=0.25, max_position=0.05, min_confluence=4, min_short_confluence=3`. Registered `PROFILES={"swing":SWING,"daytrade":DAYTRADE}`. Module docstring updated.
- **Profile selection** (`src/alpaca_orchestrator.py`): replaced `PROFILE = SWING` with `_PROFILE_NAME = os.environ.get("BOT_PROFILE","swing").lower()` → `PROFILE = PROFILES[_PROFILE_NAME]`; unknown name raises `ValueError(f"Unknown BOT_PROFILE=...; valid: {sorted(PROFILES)}")`. Resolution stays on the same line position so downstream `MAX_POSITION_PCT/MIN_CONFLUENCE/MIN_SHORT_CONFLUENCE/CYCLE_SLEEP_SECONDS` still read the selected profile's defaults and per-field env overrides still win. Banner gains a `Profile : {PROFILE.name}` line.
- **Tests** (`tests/test_strategy_profile.py`): DAYTRADE spec values, registry keys, BOT_PROFILE selection (daytrade/swing/unset), case-insensitive, unknown→ValueError, daytrade import smoke. SWING parity tests retained.

Did NOT touch technical_signals periods or consume ATR/max_hold (deferred to Phase 3/4).

## Test Results

`python -m pytest tests/test_strategy_profile.py -q` → **11 passed in 0.16s** (was 4; +7 new, all SWING parity retained).

CLI verification (actual output):
- no `BOT_PROFILE`: `swing-default OK`, `PROFILE.name=='swing'`
- `BOT_PROFILE=daytrade`: `daytrade -> daytrade` (no crash)
- `BOT_PROFILE=bogus`: `ValueError: Unknown BOT_PROFILE='bogus'; valid: ['daytrade', 'swing']`, python exit=1

## Requirements

- **PROFILE-03** (DAYTRADE preset): COMPLETE — registered with spec values, parity intact.
- **PROFILE-04** (BOT_PROFILE selection): COMPLETE — default swing, unknown fails fast, env overrides intact, banner shows profile.

## Deviations from Plan

None — plan executed as written. TDD followed for Task 1 (RED `ImportError: cannot import name 'DAYTRADE'` → GREEN 6 passed).

## Commits

- `4503320` feat(02-01): add DAYTRADE preset + register in PROFILES
- `d56fc1b` feat(02-01): select PROFILE from BOT_PROFILE env at module load + banner line
- `0d2a11d` test(02-01): BOT_PROFILE selection, fail-fast, case-insensitive, daytrade smoke

## Self-Check: PASSED
- src/strategy_profile.py DAYTRADE: FOUND
- src/alpaca_orchestrator.py BOT_PROFILE: FOUND
- commits 4503320 / d56fc1b / 0d2a11d: FOUND
