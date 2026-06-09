---
phase: 07-close-self-learning-loop-entry-sizing
plans: ["07-01", "07-02", "07-03"]
subsystem: trading / self-learning loop
requirements: [LEARN-01, LEARN-02, LEARN-03]
tags: [learning, sizing, kelly, shadow-seam]
key-files:
  modified:
    - src/alpaca_orchestrator.py
    - src/bot_thread.py
  created:
    - tests/test_learning_wiring.py
    - tests/conftest.py (FakeTradeMemory fixture)
metrics:
  tests_before: 217 passed / 2 skipped
  tests_after: 230 passed / 2 skipped
  completed: 2026-06-08
---

# Phase 7: Close the Self-Learning Loop + Entry Sizing — Summary

One-liner: closed the trade-memory feedback loop into both runtimes — `_kelly_technical`
now consumes learned confidence/thresholds (LEARN-02/03) and both entry paths veto on
losing patterns (LEARN-01), all behind a `LEARNING_ENFORCE` shadow seam.

## Per-Plan

### 07-01 (Wave 1) — sizing contract + test scaffold — commit `7100f40`
- Extended `_kelly_technical` (src/alpaca_orchestrator.py:384) with `confidence_adjustment=1.0`
  and `min_position_pct=None`.
- Math order (LOCKED): `adjusted_pct *= confidence_adjustment` → floor `max(adjusted, min)` if
  non-zero → hard-cap clamp at `max_position_pct` LAST.
- Default kwargs preserve legacy behaviour → 217 existing tests stayed green.
- `tests/test_learning_wiring.py` math tests (scale, hard-cap-inviolate, dynamic floor+ceiling,
  zero-floor, defaults) + `FakeTradeMemory` fixture in conftest.

### 07-02 (Wave 2) — bot_thread.py (live runtime) — commit `54415b8`
- Added module-level `LEARNING_ENFORCE = os.environ.get("LEARNING_ENFORCE","1")=="1"`.
- Per-cycle `thresholds = memory.get_dynamic_thresholds()` computed ONCE (not per-candidate).
- LONG: EXTENDED the existing veto at the original :522 (wrapped its `continue` in
  `LEARNING_ENFORCE`; no second veto). Captures `adj`, passes `confidence_adjustment` +
  `min_position_pct` + `max_position_pct=min(cfg.max_position_pct, dynamic)`.
- SHORT: ADDED full advisory block (get_advice + veto + scale) AND the missing
  `record_trade_context` with canonical `technical_short_{score}`, sentiment `/4.0`.
- Un-skipped path tests (veto, scaling-in-path, signal_type alignment, shadow no-effect),
  added memory=None no-op + enforce-flag-default tests.

### 07-03 (Wave 2) — alpaca_orchestrator.py (CLI runtime) — commit `2ceeed0`
- Added `LEARNING_ENFORCE` + per-cycle thresholds.
- LONG + SHORT: fresh advisory blocks mirroring bot_thread (both previously had none).
- Added canonical `technical_short_{score}` `record_trade_context` to SHORT (was missing);
  captured `trade_id` on both long/short logs for context linkage.
- Left the alpaca_trades order-log `short_technical_{score}` string untouched (it is in
  alpaca_trades, not trade_context — per guardrail).
- Parity test asserts orchestrator and bot_thread share the same `_kelly_technical` and size
  identically; orchestrator enforce-flag test.

## Wired Paths

| Runtime | Path | get_advice | veto | scale | dynamic min/max | record_context |
|---------|------|-----------|------|-------|-----------------|----------------|
| bot_thread | LONG | pre-existing | extended (wrapped) | added | added | pre-existing |
| bot_thread | SHORT | added | added | added | added | added (canonical) |
| orchestrator | LONG | added | added | added | added | trade_id+signal_type fixed |
| orchestrator | SHORT | added | added | added | added | added (canonical) |

## signal_type Fix
- Canonical: LONG `technical_confluence_{score}`, SHORT `technical_short_{score}` — used in
  BOTH `get_advice` and `record_trade_context` in both runtimes.
- Sentiment standardized on `/4.0` for all advice lookups.
- Orchestrator order-log `short_technical_{score}` (alpaca_trades.market_sentiment) intentionally
  left as-is — not migrated.

## Shadow Seam
`LEARNING_ENFORCE` env (default "1" = enforce). "0" → veto + adjustment are logged as
would-be effect but NOT applied (skip=False, adj=1.0, no dynamic caps). Verified by
`test_shadow_mode_no_effect` and the two enforce-flag-default reload tests.

## Hard-Cap Inviolability (LEARN-03)
Effective max = `min(static MAX_POSITION_PCT/cfg.max_position_pct, dynamic_max)` at every call
site → dynamic max can only tighten, never breach the static cap. `confidence_adjustment` up to
1.5 is clamped LAST. Proven by `test_hard_cap_inviolate`.

## memory=None
All new reads guarded by `if memory is not None`; thresholds=None → default kwargs →
behaviourally identical to pre-phase. `test_memory_none_no_op` confirms `_kelly_technical`
output equals the legacy call.

## LEARN status
- LEARN-01 (veto on losing patterns): DONE both runtimes, both sides.
- LEARN-02 (confidence scaling): DONE.
- LEARN-03 (dynamic floor + cap with static-cap-wins): DONE.

## Test Results
`python -m pytest tests/ -q` → **230 passed, 2 skipped** (the 2 skips are pre-existing,
unrelated to this phase; baseline was 217 passed / 2 skipped). All 13 learning-wiring tests
pass, no skips remaining in test_learning_wiring.py.

Note: `python -m pytest -q` (repo root, no `tests/` arg) errors on vendor/TradingAgents
collection — pre-existing and out of scope; the project's convention is `pytest tests/`.

## Deviations from Plan
- 07-03: captured `trade_id` from `log_alpaca_trade` for both long and short orchestrator
  paths (LONG previously recorded context without trade_id, SHORT had no record at all).
  [Rule 2 — missing critical functionality] required so recorded context links to the trade
  for outcome updates / learning. Minimal diff.

## Self-Check: PASSED
- src/alpaca_orchestrator.py, src/bot_thread.py, tests/test_learning_wiring.py present.
- Commits 7100f40, 54415b8, 2ceeed0 exist in git log.
