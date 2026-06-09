# Phase 3: Parameterized Signal Engine + ATR + Session VWAP — Phase Summary

**Branch:** `phase-03-parameterized-signal-engine`
**Completed:** 2026-06-08
**Plans:** 03-01 (Wave 1), 03-02 (Wave 2)

## What Was Built
Made `src/technical_signals.py` profile-aware and intraday-correct, then wired the active
`StrategyProfile` through every live `scan_assets` call-site — with swing output preserved
byte-for-byte. Brought the full project test suite green.

## SIGNAL Requirement Status
- **SIGNAL-01 (profile-sourced periods): DONE.** `analyze(symbol, bars, bars_4h=None, profile=SWING)`
  and `scan_assets(..., profile=SWING)` — profile is the LAST param. EMA fast/slow, RSI, ADX, ATR
  periods and the 4H-filter EMAs all source from the profile; no hardcoded 9/21/14 remain in
  `analyze()` (grep-verified). All 3 call-sites thread the active profile:
  - `alpaca_orchestrator.py:734` & `:1151` → `profile=PROFILE` (module-level)
  - `bot_thread.py:386` → `profile=PROFILES.get(BOT_PROFILE, SWING)`
- **SIGNAL-02 (ATR on Signal): DONE.** `_atr(highs, lows, closes, period=14)` Wilder-smoothed scalar
  reusing the `_adx` true-range formula, guard `n < period+1`. Hand fixture `_atr(...,2) == 2.5`.
  `atr_value: float = 0.0` is the LAST `Signal` field, populated via `profile.atr_period`.
  NOT wired into exits/scoring (deferred to Phase 4 per D-03).
- **SIGNAL-03 (session VWAP): DONE.** `_vwap_bullish(..., timestamps=None, session_anchor=False)`;
  daytrade anchors cumulative VWAP to bars sharing `timestamps[-1][:10]` (UTC day, ISO slice, no
  datetime parse). Swing branch byte-for-byte unchanged.

## Files Modified
- `src/technical_signals.py` — `_atr`, parameterized `analyze`/`scan_assets`, session VWAP, `Signal.atr_value`
- `src/alpaca_orchestrator.py` — `profile=PROFILE` on 2 scan_assets calls
- `src/bot_thread.py` — `import os`, profile import, `profile=_profile` on scan_assets call
- `tests/test_technical_signals.py` — TestATR, TestProfilePeriods (incl. swing-parity snapshot), TestSessionVWAP; 6 stale tests remediated
- `tests/test_exit_advisor.py`, `tests/test_bot_config.py` — 6 stale-threshold tests remediated

## Test Results (ACTUAL)
- `python -m pytest tests/ -q` → **200 passed, 2 skipped, 0 failed.**
- Baseline before phase: 12 failed / 175 passed / 2 skipped.
- Note: `python -m pytest -q` (repo root) cannot collect because the vendored
  `vendor/TradingAgents/tests/` has unrelated import errors (`No module named 'cli.utils'`) —
  pre-existing, outside this phase. The project suite is `tests/` and is fully green.

## Swing Parity / D-05
- Parity snapshot test asserts SWING analyze() output: confluence=3, short=0, adx=25.308993,
  rsi=63.086041, ema_bullish=True, vwap_bullish=False, atr=2.814057, regime=trending.
- No confluence/short-score scoring logic or threshold constants changed (git-diff verified;
  exit_advisor.py untouched, alpaca_orchestrator.py only gained `profile=` kwargs).

## Remediation Outcome
All 12 pre-existing failures were stale test expectations (production thresholds/universe already
shipped in prior phases) — all fix-the-test, zero genuine code bugs, all test-file-only edits.
The plan named only the 6 in `test_technical_signals.py`; the other 6 (test_exit_advisor,
test_bot_config) were remediated as a documented scope extension to satisfy the phase end-state
(fully-green suite).

## Commits
- 93a487e feat(03-01): _atr() + atr_value (SIGNAL-02)
- 311cf5c feat(03-01): parameterize analyze()/scan_assets (SIGNAL-01)
- 9553d11 feat(03-01): session-anchored VWAP (SIGNAL-03)
- 9e607e2 feat(03-02): thread profile through 3 scan_assets call-sites
- 2e4c3da test(03-02): remediate stale-threshold tests
