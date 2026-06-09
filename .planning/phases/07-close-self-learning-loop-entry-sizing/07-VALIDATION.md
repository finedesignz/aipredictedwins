---
phase: 7
slug: close-self-learning-loop-entry-sizing
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-08
---

# Phase 7 — Validation Strategy

## Test Infrastructure
| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Quick run command** | `python -m pytest tests/test_learning_wiring.py -q` |
| **Full suite command** | `python -m pytest tests/ -q` |
| **Estimated runtime** | ~20s |

## Sampling Rate
- After every task commit: quick run
- Before `/gsd-verify-work`: full suite green (217+ baseline)
- Max latency: 30s

## Validation Architecture (from RESEARCH.md)
- **LEARN-01 (veto):** get_advice should_trade=False → candidate skipped (logged `learn_veto`), not sized/ordered. bot_thread LONG already vetoes — extend, don't double-veto. Add veto to the other 3 paths.
- **LEARN-02 (scale):** confidence_adjustment (0.0–1.5) scales the Kelly result BEFORE the cap clamp.
- **LEARN-03 (thresholds):** get_dynamic_thresholds min/max_position_pct feed sizing; effective max = `min(MAX_POSITION_PCT, dynamic_max)` so the static hard cap always wins.
- **Loop integrity:** signal_type canonicalized to `technical_confluence_{score}` (long) / `technical_short_{score}` (short) in BOTH record_trade_context and get_advice; short paths now CALL record_trade_context; sentiment normalized `/4.0`.
- **Shadow seam:** `LEARNING_ENFORCE` env flag (default enforce) wraps veto/scale so Phase 8 can flip to log-only.
- **Caps inviolate:** test adjustment>1 never breaches MAX_POSITION_PCT / exposure cap.
- **memory=None path:** learning disabled → no veto/scale, behaves as today.

Nyquist floor — phase cannot pass until veto/scale/threshold + caps-inviolate tests green and full suite green.
