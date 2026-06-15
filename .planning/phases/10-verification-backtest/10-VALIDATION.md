---
phase: 10
slug: verification-backtest
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-09
---

# Phase 10 — Validation Strategy

## Test Infrastructure
| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Quick run command** | `python -m pytest tests/test_learning_realloop.py tests/test_signal_frequency.py -q` |
| **Full suite command** | `python -m pytest tests/ -q` |
| **Estimated runtime** | ~25s |

## Sampling Rate
- After each task commit: quick run
- Before `/gsd-verify-work`: full suite green (272+ baseline)

## Validation Architecture (from RESEARCH.md)
- **VERIFY-01 coverage map:** audit doc maps existing tests → SWING parity / ATR exit math / fee gate / learning veto-scale / session VWAP. Confirm session-VWAP assertion exists (add if missing).
- **VERIFY-01 real-loop gap:** new `tests/test_learning_realloop.py` drives the REAL `BotThread._run_cycle` (DI: stub alpaca get_bars/get_latest_price/place_market_order, seeded FakeTradeMemory) and asserts a should_trade=False seed vetoes (no order placed) and adjustment<1 scales the real order qty — in BOTH enforce and shadow modes. Replaces reliance on the `_advice_consume` mirror helper.
- **VERIFY-02 backtest:** new ≥100×5Min fixture; `scripts/backtest_signal_frequency.py` replays it through `scan_assets(profile=DAYTRADE, fetch_4h=False)` via a stub/replay client (scan_assets sources timeframe/bar_count from profile → client must honor 5Min/100). Reuse src/backtester/data_loader. `tests/test_signal_frequency.py` asserts a sane candidate-frequency RANGE (>0, not absurd) on the fixture → doubles as regression guard. Deterministic (no network); optional live-fetch mode documented.
- Full suite green (272+).

Nyquist floor — real-loop veto+scale tests, backtest frequency-range test, suite green.
