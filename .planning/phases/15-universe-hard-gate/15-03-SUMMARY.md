---
phase: 15-universe-hard-gate
plan: 03
subsystem: trading
tags: [universe, gate, entry, copytrade, exits-ungated]
requires: [15-02]
provides: [hard gate on all 5 entry paths]
affects: []
tech-stack:
  added: []
  patterns: [reduce-only gate skip via signed position qty, fail-closed gate]
key-files:
  created: []
  modified: [src/bot_thread.py, src/trend_strategy.py, src/bot_c/strategy.py, src/copytrade_thread.py, src/alpaca_orchestrator.py]
decisions:
  - "Gate reads self.config inside _submit_order — NO new parameter (tests/test_order_resolution.py:156/246 call it positionally)"
  - "Blocked entry reuses the existing terminal 'rejected' status (pnl=0) — no sixth status value, Phase-12/13 accounting intact"
  - "Copytrade gate-skip is REDUCE-ONLY: (held>0 and sell) or (held<0 and buy). A BUY that ADDS to a held off-universe long is BLOCKED (the audited TRUMP case). Fails CLOSED if get_positions() raises."
  - "src/alpaca_client.py has a ZERO diff — the gate never touched the exit layer"
metrics:
  duration: ~15m
  completed: 2026-07-12
---

# Phase 15 Plan 03: Wire the Hard Gate into All Five Entry Sites Summary

All five live entry paths now fail closed on an off-universe or quarantined symbol, while every exit
path remains completely ungated. Closes the TRUMP/FIL leak.

## What Was Built

| # | Site | Gate |
|---|------|------|
| E1 | `src/bot_thread.py` `_submit_order` | `entry_allowed(symbol, cfg.symbols, cfg.quarantined)` at the top, before the try-block, reading `self.config`. Blocked → WARNING (bot_id/symbol/side/reason) + exactly ONE terminal `rejected` row (pnl=0) + `return None, None` (no double-write). Both selectors gained the same predicate as belt-and-braces. `update_config` now logs the effective NORMALIZED allowlist/quarantine sets (Pitfall 4 visibility). |
| E2 | `src/trend_strategy.py` | Entry BUY gated against `cfg.symbols + [cfg.trend_symbol]` (BITX carve-out). The SELL exit is untouched. |
| E3 | `src/bot_c/strategy.py` | Gate at the top of `_process_ticker`'s entry path — the last chokepoint before the order. `_exit_position` untouched. |
| E4 | `src/copytrade_thread.py` | Builds a SIGNED held map from `get_positions()` (slashless symbol, negative qty for shorts — normalized both sides). Skips the gate IFF the order REDUCES: `(held>0 and sell)` or `(held<0 and buy)`. Everything else — including a BUY that ADDS to a held off-universe long, and a SELL on a not-held symbol (short-to-open) — goes through `entry_allowed(mapped, cfg.all_symbols, cfg.quarantined)`. Blocked → `action="blocked"`, `error_detail=reason`, no Alpaca call. A raising/unparseable `get_positions()` yields `held={}` → gate EVALUATED (fails CLOSED). |
| E5 | `src/alpaca_orchestrator.py` | New module-level `QUARANTINED_SYMBOLS` read via `_os.environ.get` (the module has no bare `os` name — a bare `os.` would NameError at import). Both the long and the short entry are gated against the resolved `universe` list; PositionMonitor's `close_position` untouched. |

Copytrade uses `cfg.all_symbols` (crypto ∪ stock), not `cfg.symbols`, so Bot E's legitimate
cross-asset-class mirrors still execute while TRUMP/FIL (in neither universe) is blocked.

## Exits Are Never Gated (proven)

- **Case 17** (static): `"entry_allowed"` is absent from `src/alpaca_client.py`. `git diff --stat`
  against the phase-start commit (`5eb7f9c`) for that file is **EMPTY**.
- **Case 18**: a copytrade SELL that reduces a held off-universe long still submits.
- **Case 11**: a quarantined symbol's open position still closes.

## Deviations from Plan

None — plan executed as written.

## Commits

- `a5ef19e` feat(15-03): hard gate at _submit_order + selector filters (UNIV-01)
- `31a522c` feat(15-03): gate trend + bot_c entries (E2, E3)
- `c86de71` feat(15-03): gate copytrade (REDUCE-only skip) + CLI orchestrator entries

## Verification (Definition of Done)

```
python -c "import src.alpaca_orchestrator"   → import ok (no NameError)
python -m pytest tests/test_universe.py -q   → 22 passed, 1 skipped
python -m pytest tests/ -q                   → 358 passed, 5 skipped, 1 warning
git diff --stat 5eb7f9c -- src/alpaca_client.py → (empty)
grep -c entry_allowed src/alpaca_orchestrator.py → 3 (import + long + short)
```

Baseline was 336 passed / 4 skipped; +22 new tests and +1 skip (the DATABASE_URL-gated case 16).
Zero regressions.

## Self-Check: PASSED
- All five modified files exist with the gate present
- commits `a5ef19e`, `31a522c`, `c86de71` present in `git log`
