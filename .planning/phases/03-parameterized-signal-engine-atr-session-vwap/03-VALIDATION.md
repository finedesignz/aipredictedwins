---
phase: 3
slug: parameterized-signal-engine-atr-session-vwap
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-08
---

# Phase 3 — Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Quick run command** | `python -m pytest tests/test_technical_signals.py -q` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | ~20 seconds |

## Sampling Rate
- After every task commit: `python -m pytest tests/test_technical_signals.py -q`
- Before `/gsd-verify-work`: full suite green (the 6 pre-existing failures fixed)
- Max feedback latency: 30s

## Validation Architecture (from RESEARCH.md)
- **SIGNAL-01:** swing-default parity — `analyze()` with default `profile=SWING` produces identical output to pre-change on a fixed bar fixture; periods sourced from profile.
- **SIGNAL-02:** `_atr` correctness vs hand-computed fixture (`_atr(h,l,c,2)==2.5`); `Signal.atr_value` populated and > 0 for real bars.
- **SIGNAL-03:** session-VWAP resets across a UTC-day boundary (daytrade); swing VWAP semantics unchanged (parity fixture).
- **Remediation:** all 6 stale tests green; full `pytest -q` green. Per-failure: 5 stale-threshold (update expectation), 1 `test_overbought_rsi_returns_none` (assert removed RSI hard-block → update to current behavior).

These are the Nyquist feedback floor — phase cannot pass until all green.
