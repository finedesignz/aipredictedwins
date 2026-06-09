---
phase: 01-strategyprofile-abstraction-swing-parity
plan: 01
subsystem: trading-config
tags: [refactor, strategy-profile, parity]
requires: []
provides: [StrategyProfile, SWING, PROFILES]
affects: [src/alpaca_orchestrator.py]
key-files:
  created:
    - src/strategy_profile.py
    - tests/test_strategy_profile.py
  modified:
    - src/alpaca_orchestrator.py
decisions:
  - "Module-level resolved PROFILE = SWING; env-override wrapper preserved (D-05/D-06)"
  - "technical_signals.py untouched — profile only carries periods for Phase 3"
  - "kelly_fraction call-sites still read config.kelly_fraction (Pitfall 3)"
metrics:
  duration: ~10m
  completed: 2026-06-08
requirements: [PROFILE-01, PROFILE-02]
---

# Phase 1 Plan 01: StrategyProfile Abstraction + SWING Parity Summary

Frozen `StrategyProfile` value object + `SWING` preset reproducing current swing-bot constants byte-for-byte, with orchestrator style-constant defaults re-sourced from the profile while env overrides still win.

## What Was Built

- **`src/strategy_profile.py`** — `@dataclass(frozen=True) StrategyProfile` with the full D-02 field set (name, timeframe, scan_interval_s, bar_count, htf_filter_timeframe, ema_fast/slow, rsi/adx/atr_period, atr_mult_stop/trail, hard_stop_pct, max_hold_hours, kelly_fraction, max_position_pct, min_confluence, min_short_confluence). `SWING` preset with parity values; `PROFILES = {"swing": SWING}`. Pure constants — no env reads, no orchestrator import.
- **`tests/test_strategy_profile.py`** — 4 tests: values-match-current-constants, frozen, registry, env-override-wins (monkeypatch `MIN_CONFLUENCE=2` + `importlib.reload`).
- **`src/alpaca_orchestrator.py`** — minimal diff: 2 added lines (`from src.strategy_profile import SWING, PROFILES`; `PROFILE = SWING`) + 4 changed default literals (`MAX_POSITION_PCT`, `MIN_CONFLUENCE`, `MIN_SHORT_CONFLUENCE`, `CYCLE_SLEEP_SECONDS`) now source defaults from `PROFILE` via `str(PROFILE.<field>)` inside the existing `_os.environ.get(...)` wrapper.

## Files Changed

| File | Change | Commit |
|------|--------|--------|
| src/strategy_profile.py | created | d0827b2 |
| tests/test_strategy_profile.py | created | d0827b2 |
| src/alpaca_orchestrator.py | 7 ins / 4 del | 1539f14 |

## Test Results

- `pytest tests/test_strategy_profile.py -q` → **4 passed**.
- `pytest tests/test_technical_signals.py -q` → 58 passed, 6 failed.
- `pytest tests/test_exit_advisor.py -q` → 5 passed (subset) / pre-existing failures.

**No regression introduced.** The technical_signals (6) and exit_advisor failures were verified identical on HEAD~1 (before the orchestrator change) by stashing `src/alpaca_orchestrator.py` and re-running — same failure set. They are pre-existing, out of scope for this behavior-preserving refactor, and logged for a future phase. The orchestrator diff is exactly the 2 added lines + 4 changed literals (`git diff --stat`: 7 ins / 4 del).

## Deviations from Plan

None — plan executed as written.

## Deferred / Pre-existing Issues (out of scope)

- `tests/test_technical_signals.py`: `TestKellyTechnical::test_confluence_3`, `TestRSIHardBlock::test_overbought_rsi_returns_none` and 4 others fail on HEAD~1 — pre-existing, unrelated to this refactor.
- `tests/test_exit_advisor.py`: `TestNewThresholds`/`TestNewTrailingStop` failures pre-exist on HEAD~1 — stale threshold expectations, unrelated.

## Requirements

- **PROFILE-01** (frozen StrategyProfile + registry): COMPLETE — `test_profile_is_frozen`, `test_profiles_registry` green.
- **PROFILE-02** (SWING byte-for-byte parity + env-override wins): COMPLETE — `test_swing_values_match_current_constants`, `test_env_override_wins_over_profile_default` green; bots A/B unaffected (env layer preserved).

## Self-Check: PASSED

- FOUND: src/strategy_profile.py
- FOUND: tests/test_strategy_profile.py
- FOUND commit d0827b2, 1539f14
