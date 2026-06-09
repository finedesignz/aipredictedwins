---
phase: 06-fee-slippage-pre-trade-gate
plan: 01
subsystem: trading-entry-guard
tags: [fee-gate, slippage, risk]
requires: []
provides: [clears_fee_hurdle, fee_gate_skip]
affects: [src/alpaca_orchestrator.py, src/bot_thread.py]
tech-stack:
  added: []
  patterns: [env-var-with-default knobs, deterministic pre-trade guard]
key-files:
  created: [src/fee_gate.py, tests/test_fee_gate.py]
  modified: [src/alpaca_orchestrator.py, src/bot_thread.py]
decisions:
  - "Hurdle = 2*taker_fee + slippage_buffer; boundary-exact (>=)."
  - "expected_move_pct = soft-target fraction the trade is managed against (orchestrator 0.08, bot_thread abs(SOFT_TAKE_PROFIT_PCT))."
  - "Env knobs TAKER_FEE=0.0025, SLIPPAGE_BUFFER=0.0010."
metrics:
  completed: 2026-06-08
  tasks: 2
  files: 4
requirements: [FEE-01]
---

# Phase 6 Plan 01: Fee/Slippage Pre-Trade Gate Summary

Deterministic pre-trade fee/slippage gate (FEE-01): a pure `clears_fee_hurdle` helper skips approved candidates whose move to soft take-profit cannot clear `2*taker_fee + slippage_buffer`, wired into all four entry blocks (orchestrator long/short, bot_thread long/short) after risk-gate approval and before sizing.

## What Was Built

- **`src/fee_gate.py`** — pure `clears_fee_hurdle(expected_move_pct, taker_fee, slippage_buffer) -> bool` returning `expected_move_pct >= 2*taker_fee + slippage_buffer`; module-level env knobs `TAKER_FEE` (0.0025) and `SLIPPAGE_BUFFER` (0.0010).
- **4 entry-block gates** — inserted after risk-gate approval, before `_kelly_technical`:
  - orchestrator long (~line 855, move=0.08), orchestrator short (~959, 0.08)
  - bot_thread long (~534), bot_thread short (~681) using `abs(SOFT_TAKE_PROFIT_PCT)`
  - On skip: log `fee_gate_skip` (symbol + move + hurdle) then `continue` — no order placed.
- **`tests/test_fee_gate.py`** — boundary (0.0060 True, 0.00599 False, 0.0061 True), swing-clears, default knobs, env-override via `importlib.reload`, allow/skip flow decision.

## Verification (actual output)

- `pytest tests/test_fee_gate.py -q` → `9 passed`
- `pytest tests/ -q` → `217 passed, 2 skipped`
- `grep -c clears_fee_hurdle` → orchestrator 3 (1 import + 2 sites), bot_thread 3 (1 import + 2 sites)
- `fee_gate_skip` present in both files.

Swing candidates (0.08/0.15) clear the default 0.0060 hurdle and are unaffected.

## Deviations from Plan

None — plan executed exactly as written.

## Commits

- `5baddce` feat(06-01): add fee/slippage pre-trade gate helper + tests
- `1f2e853` feat(06-01): wire fee/slippage gate into all 4 entry blocks

## Self-Check: PASSED
- FOUND: src/fee_gate.py
- FOUND: tests/test_fee_gate.py
- FOUND commit 5baddce, 1f2e853
