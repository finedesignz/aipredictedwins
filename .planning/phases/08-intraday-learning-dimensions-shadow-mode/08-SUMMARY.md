---
phase: 08-intraday-learning-dimensions-shadow-mode
plans: ["08-01", "08-02", "08-03"]
subsystem: trade-memory / learning-loop
tags: [learning, shadow-mode, intraday-dimensions, migration]
requires: [Phase 7 learning loop, trade_context schema]
provides:
  - time_of_day_bucket / volatility_regime / hold_minutes dimensions on trade_context
  - dimension-conditioned lessons + strategy scores
  - count-based should_enforce_learning shadow gate (replaces static LEARNING_ENFORCE)
affects: [src/trade_memory.py, src/learning_loop.py, src/bot_thread.py, src/alpaca_orchestrator.py, src/db_schema.sql, dashboard/api/migrations]
tech-stack:
  added: []
  patterns: [additive nullable migration, pure dimension helpers, per-cycle shadow gate]
key-files:
  created:
    - dashboard/api/migrations/014_intraday_learning_dims.sql
    - tests/test_learning_dimensions.py
    - tests/test_shadow_gate.py
  modified:
    - src/trade_memory.py
    - src/learning_loop.py
    - src/bot_thread.py
    - src/alpaca_orchestrator.py
    - src/db_schema.sql
    - tests/conftest.py
    - tests/test_learning_wiring.py
decisions:
  - "Vol thresholds: low <1%, med 1-2.5%, high >=2.5% ATR/price; unknown if atr<=0 or price<=0"
  - "Time buckets: asia/eu/us_am/us_pm/off UTC session labels"
  - "strategy_scores dimension scores encoded into signal_type ('<sig>@<value>') — no schema change (A3)"
  - "get_advice / runtime veto-scale key (symbol, signal_type) left UNCHANGED — dimensions inform lessons only"
metrics:
  tests: "261 passed, 2 skipped"
  completed: 2026-06-08
---

# Phase 8 Plans 01-03: Intraday Learning Dimensions + Shadow Mode Summary

Adds three nullable intraday dimensions (`time_of_day_bucket`, `volatility_regime`, `hold_minutes`)
to `trade_context`, wires them through both runtimes' entry/close paths and the learning loop's
dimension-conditioned lessons/scores, and replaces the static Phase-7 `LEARNING_ENFORCE` boolean
with a count-based `should_enforce_learning` shadow gate (auto-enforce at 30 closed trades/bot;
explicit `LEARNING_ENFORCE=0` forces shadow).

## What shipped

### 08-01 — Schema + pure-function foundation
- `time_of_day_bucket(entry_iso)` and `volatility_regime(atr, price)` pure helpers in `src/trade_memory.py`.
- `dashboard/api/migrations/014_intraday_learning_dims.sql`: 3 additive nullable columns
  (`ADD COLUMN IF NOT EXISTS`, no NOT NULL/DEFAULT/backfill) + 2 indexes. Idempotent.
- Mirrored the 3 `ADD COLUMN IF NOT EXISTS` into `src/db_schema.sql` trade_context block (Pitfall 1).
- `FakeTradeMemory.count_closed_trades()` injectable via `closed_count=` kwarg (conftest).
- New `tests/test_learning_dimensions.py` + `tests/test_shadow_gate.py` scaffold.

### 08-02 — Recording + dimension lessons
- `record_trade_context` INSERT persists `time_of_day_bucket` (from entry ts) + `volatility_regime`
  (from `atr_value`/`price_at_entry`); `"atr_value": signal.atr_value` threaded through all 4 record
  dicts (bot_thread long+short, orchestrator long+short).
- `update_trade_outcome(..., hold_minutes=None)` back-compat kwarg; `learning_loop._sync_trade_outcomes`
  SELECTs entry/exit ts and computes `_hold_minutes` in Python (TEXT ISO, Pitfall 4).
- `generate_lessons` SELECTs the 3 new columns and adds additive `(signal_type, dimension)` passes,
  skipping NULL/"unknown" and respecting `min_sample`. `update_strategy_scores` gains dimension
  passes (encoded into signal_type, `HAVING COUNT(*) >= 2`). Existing lessons/scores unchanged.

### 08-03 — Shadow gate
- `TradeMemory.count_closed_trades()` (parameterized COUNT).
- Module-level `should_enforce_learning(memory, bot_id, shadow_until=None)`: explicit
  `LEARNING_ENFORCE=0` wins (D-06), else count vs `LEARNING_SHADOW_UNTIL_TRADES` (default 30);
  `memory is None` -> False.
- Replaced all 8 static `LEARNING_ENFORCE` seam checks (bot_thread long+short, orchestrator
  long+short — veto + scale + threshold-clamp) with a single per-cycle `enforce` local. Removed the
  static module bool from both runtimes. Shadow mode logs `learn_shadow: WOULD veto/scale` and
  no-ops; enforce path identical to Phase 7. The two `enforce={...}` log f-strings now interpolate
  the per-cycle value.

## Deviations from Plan

### Auto-fixed Issues
**1. [Rule 1 - Test bug] Migration text-contract test over-matched the comment line**
- Found during: 08-01 Task 2.
- Issue: `assert "NOT NULL" not in text` tripped on the descriptive comment ("NO NOT NULL");
  the ADD COLUMN line filter also matched the comment containing "ADD COLUMN IF NOT EXISTS".
- Fix: restrict the NOT NULL check to lines starting with `ALTER TABLE`.
- Commit: 76a6856.

**2. [Rule 3 - Blocking] Phase-7 enforce-flag tests asserted the removed module bool**
- Found during: 08-03 Task 2.
- Issue: `test_orchestrator_learning_enforce_flag` / `test_learning_enforce_flag_default` reloaded the
  module and asserted `LEARNING_ENFORCE is False`; removing the static bool (per guardrail) broke them.
- Fix: rewrote both as gate-semantics tests (no static bool present; helper importable;
  explicit-0 forces shadow in both runtimes).
- Commit: 771dac7.

## Guardrail Compliance
- Migration is additive-only (ADD COLUMN IF NOT EXISTS, nullable, no backfill) — global rule 6 honored.
  Migration NOT run against any DB (string/double-apply idempotency only).
- `get_advice` / runtime advice key (symbol, signal_type) unchanged (test_get_advice_key_unchanged).
- All 8 seams use one per-cycle gate; no stray static `LEARNING_ENFORCE` seam (grep-verified).
- `memory=None` no-op; NULL-tolerant lessons.

## Verification
`python -m pytest tests/ -q` -> **261 passed, 2 skipped** (baseline was 244; +17 new tests).

## New environment variable
- `LEARNING_SHADOW_UNTIL_TRADES` (default 30, code default — no Coolify change required).
  `LEARNING_ENFORCE` semantics changed: `=0` forces shadow; otherwise count-based.

## Self-Check: PASSED
- dashboard/api/migrations/014_intraday_learning_dims.sql — FOUND
- tests/test_learning_dimensions.py — FOUND
- tests/test_shadow_gate.py — FOUND
- Commits 1a11688, 76a6856, 07dc4c3, a710d8e, e28d0b7, 0b22c80, 77d5ac9, 771dac7 — all present
