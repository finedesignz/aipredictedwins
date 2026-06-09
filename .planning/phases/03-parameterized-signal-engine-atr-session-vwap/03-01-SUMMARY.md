---
phase: 03-parameterized-signal-engine-atr-session-vwap
plan: 01
subsystem: signal-engine
tags: [signals, atr, vwap, profile, tdd]
requires: [strategy_profile.SWING, strategy_profile.DAYTRADE]
provides: [analyze(profile=), scan_assets(profile=), _atr, Signal.atr_value, session-anchored _vwap_bullish]
affects: [src/technical_signals.py]
tech-stack:
  added: []
  patterns: [profile-sourced indicator periods, Wilder ATR reusing _adx TR, UTC-day session VWAP]
key-files:
  created: []
  modified: [src/technical_signals.py, tests/test_technical_signals.py]
decisions: [D-01, D-02, D-03, D-04, D-05]
metrics:
  duration: ~15m
  completed: 2026-06-08
---

# Phase 3 Plan 01: Parameterized Signal Engine + ATR + Session VWAP Summary

Made `src/technical_signals.py` profile-aware (profile-sourced EMA/RSI/ADX/ATR periods), added a Wilder `_atr()` scalar reusing the `_adx` true-range loop with `Signal.atr_value`, and made VWAP UTC-day session-anchored for the daytrade profile — all with swing output byte-for-byte preserved.

## Tasks Completed

| Task | Name | Commit |
|------|------|--------|
| 1 | `_atr()` helper + `atr_value` on Signal (SIGNAL-02) | 93a487e |
| 2 | Parameterize analyze()/scan_assets periods from profile (SIGNAL-01) | 311cf5c |
| 3 | Session-anchored VWAP for daytrade (SIGNAL-03) | 9553d11 |

## SIGNAL Status
- **SIGNAL-01:** DONE — `analyze(symbol, bars, bars_4h=None, profile=SWING)` and `scan_assets(..., profile=SWING)` (profile LAST param). EMA fast/slow, RSI, ADX, ATR periods + 4H-filter EMAs all sourced from profile. No hardcoded 9/21/14 remain in analyze() (verified by grep — no matches). scan_assets fetches via `profile.timeframe`/`bar_count`/`htf_filter_timeframe`.
- **SIGNAL-02:** DONE — `_atr(highs, lows, closes, period=14)` Wilder-smoothed scalar, guard `n < period+1`, reuses `_adx` TR formula. Hand fixture `_atr(...,2) == 2.5` passes. `atr_value: float = 0.0` is the LAST Signal field, populated in analyze() via `profile.atr_period`. NOT wired into exits/scoring (Phase 4).
- **SIGNAL-03:** DONE — `_vwap_bullish(..., timestamps=None, session_anchor=False)`; when daytrade, anchors cumulative VWAP to bars sharing `timestamps[-1][:10]` (UTC day), ISO string slice (no datetime parse). Swing branch (`session_anchor=False`) byte-for-byte unchanged.

## Parity / D-05
- Swing-parity snapshot test (`test_swing_parity_snapshot`) asserts confluence=3, short=0, adx=25.308993, rsi=63.086041, ema_bullish=True, vwap_bullish=False, atr=2.814057, regime=trending — passes.
- No confluence/short-score scoring or threshold constants changed (D-05 honored).

## Test Results
- `python -m pytest tests/test_technical_signals.py -q` → 70 passed, 6 failed.
- The 6 failures are the pre-existing stale-threshold tests (TestTrailingStop, TestThresholdChecks x3, TestKellyTechnical, TestRSIHardBlock) — remediated in Plan 02. No NEW failures introduced.

## Deviations from Plan
None — plan executed as written.

## Self-Check: PASSED
- `_atr` present (`def _atr`), `Signal.atr_value` present, session VWAP wired. Commits 93a487e, 311cf5c, 9553d11 exist on branch phase-03-parameterized-signal-engine.
