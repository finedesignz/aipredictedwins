---
phase: 10-verification-backtest
plans: ["10-01", "10-02"]
subsystem: testing
tags: [verification, backtest, learning, signal-frequency, daytrade]
requires: [bot_thread._run_cycle, technical_signals.scan_assets, strategy_profile.DAYTRADE]
provides: [VERIFY-01, VERIFY-02, real-loop-learning-coverage, signal-frequency-harness]
affects: [tests, scripts]
key-files:
  created:
    - .planning/phases/10-verification-backtest/COVERAGE-MAP.md
    - tests/test_learning_realloop.py
    - tests/test_signal_frequency.py
    - scripts/backtest_signal_frequency.py
    - tests/fixtures/daytrade_5min/BTC_USD.json
    - tests/fixtures/daytrade_5min/ETH_USD.json
    - tests/fixtures/daytrade_5min/SOL_USD.json
  modified: []
metrics:
  test_count_before: 272
  test_count_after: 279
  completed: 2026-06-15
---

# Phase 10 Plans 01+02: Verification + Backtest Summary

Closed the VERIFY-01 coverage audit + Phase-7 mirror-helper gap with real-loop learning
integration tests, and delivered the VERIFY-02 DAYTRADE signal-frequency backtest harness.

## VERIFY-01 — coverage audit + real-loop learning test

**COVERAGE-MAP.md** maps all 12 VERIFY-01 surfaces (profile/SWING parity, ATR exit math, fee gate,
session VWAP, learning sizing math, veto wiring, scale wiring, shadow wiring, signal_type alignment,
shadow gate, learning dimensions, runtime parity) to their existing green tests with a verdict.
Three rows — veto/scale/shadow path tests in `tests/test_learning_wiring.py` — are flagged **MIRROR**:
they assert the `_advice_consume` re-implementation, not the production loop.

**Session-VWAP assertion** (Task 2): CONFIRMED already present in `tests/test_technical_signals.py`
(4 assertions: `test_session_anchor_excludes_prior_day`, `test_session_anchor_below_current_day_vwap`,
`test_session_anchor_false_unchanged`, `test_daytrade_uses_session_anchor`). No new test added — no real gap.

**Real-loop test** (`tests/test_learning_realloop.py`, 4 tests, all green) drives the ACTUAL
`BotThread._run_cycle` with stubbed alpaca/logger + monkeypatched `src.bot_thread._db` and
`scan_assets`, seeded `FakeTradeMemory` (no network, no DB):
- `test_realloop_veto_enforce` — should_trade=False + enforce → `place_market_order` NOT called.
- `test_realloop_veto_shadow` — same advice + `LEARNING_ENFORCE=0` → order IS placed.
- `test_realloop_scale_enforce` — confidence_adjustment=0.5 + enforce → captured qty = 0.5 × adj=1.0 baseline (pre-cap; `_NO_FLOOR` thresholds isolate the ratio from the min_position_pct floor).
- `test_realloop_scale_shadow` — adjustment=0.5 + `LEARNING_ENFORCE=0` → qty unscaled.

**VERIFY-01: COMPLETE.**

## VERIFY-02 — DAYTRADE signal-frequency backtest

**Fixtures** (`tests/fixtures/daytrade_5min/{BTC,ETH,SOL}_USD.json`): 200× deterministic 5Min OHLCV
bars/symbol, single UTC day, mild uptrend + end-dip tuned so DAYTRADE (min_confluence=4) yields
nonzero candidates. normalise_bar-compatible shape.

**Harness** (`scripts/backtest_signal_frequency.py`): pure `run_frequency()` replays fixtures through
the REAL `scan_assets(profile=DAYTRADE, fetch_4h=False)` over a rolling window via `_ReplayClient`
(honors profile-sourced timeframe=5Min/bar_count=100 — scan_assets ignores its own args). Offline
deterministic by default; `--live` Alpaca fetch is flag-gated (never CI). Prints per-symbol + total
report with a STRONG/MARGINAL/NO-EDGE/FLOODED verdict.

**Backtest frequency numbers** (committed fixture, 101 windows × 3 symbols = 303 positions):
| Symbol | long | short |
|--------|------|-------|
| BTC/USD | 2 | 21 |
| ETH/USD | 4 | 20 |
| SOL/USD | 4 | 18 |
| **TOTAL** | **10** | **59** |

Total candidates = **69**, rate 0.23 → VERDICT **STRONG**.

**Regression test** (`tests/test_signal_frequency.py`, 3 tests, green): asserts >0, ≤ 0.8×windows×symbols,
and pins the exact totals (long=10, short=59, total=69, windows=101).

**VERIFY-02: COMPLETE.**

## Test count

`python -m pytest tests/ -q` → **279 passed, 2 skipped** (was 272; +4 real-loop, +3 frequency). ≥272 ✓.

## Deviations from Plan

None — both plans executed as written. Task 2 (session-VWAP) was a confirm-only audit (assertions
already present), so no code change, per the plan's "leave it — do not duplicate" instruction.

## Known Stubs

None. Fixtures are deterministic synthetic data (documented + pinned), not placeholder stubs.

## Self-Check: PASSED
- COVERAGE-MAP.md, test_learning_realloop.py, test_signal_frequency.py, backtest_signal_frequency.py, 3 fixtures — all present.
- Commits b31e294, 72dcf61, 90c5472, fd4a949 (+ harness commit) present on main.
- Full suite 279 passed.
