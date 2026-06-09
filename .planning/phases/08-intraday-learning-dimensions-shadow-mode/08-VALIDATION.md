---
phase: 8
slug: intraday-learning-dimensions-shadow-mode
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-08
---

# Phase 8 — Validation Strategy

## Test Infrastructure
| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Quick run command** | `python -m pytest tests/test_learning_dimensions.py tests/test_shadow_gate.py -q` |
| **Full suite command** | `python -m pytest tests/ -q` |
| **Estimated runtime** | ~20s |

## Sampling Rate
- After each task commit: quick run
- Before `/gsd-verify-work`: full suite green (230+ baseline)
- Max latency: 30s

## Validation Architecture (from RESEARCH.md)
- **LEARN-04:** migration `014_intraday_learning_dims.sql` adds time_of_day_bucket/hold_minutes/volatility_regime via `ADD COLUMN IF NOT EXISTS` (nullable, no backfill); mirrored in db_schema.sql. record_trade_context persists time_of_day_bucket + volatility_regime at entry (4 sites); hold_minutes filled at close via update_trade_outcome kwarg from learning_loop (timestamp + closed_at). volatility_regime = atr/price bands (low<1%/med/high≥2.5%, "unknown" if atr≤0); time_of_day_bucket = UTC session label.
- **LEARN-05:** generate_lessons/update_strategy_scores condition on dimensions additively (respect min_sample); existing per-signal/per-symbol lessons unchanged. Live advice key stays (symbol, signal_type) — dimensions inform lessons/scores only.
- **LEARN-06:** `should_enforce_learning(memory, bot_id)` — closed-trade count vs LEARNING_SHADOW_UNTIL_TRADES (default 30); < → shadow (log `learn_shadow: WOULD ...`, no action); ≥ → enforce. Explicit LEARNING_ENFORCE=0 forces shadow (precedence). Replaces the 8 static seam checks (single source of truth, computed once/cycle).
- **Back-compat:** existing rows NULL-tolerant; migration idempotent; memory=None no-op; FakeTradeMemory gains count_closed_trades().

Nyquist floor — phase cannot pass until dimension-persist, hold_minutes-at-close, shadow-below/enforce-above, explicit-override, and migration-idempotency tests green + full suite green.
