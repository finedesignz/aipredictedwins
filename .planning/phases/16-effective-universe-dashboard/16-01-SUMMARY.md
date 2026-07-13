---
phase: 16
plan: 01
subsystem: testing
tags: [UNIV-03, tdd, red]
requires: [src.universe, src.bot_config]
provides: [tests/test_effective_universe.py]
affects: [src/effective_universe.py, dashboard/api/routes/bots.py]
tech-stack:
  added: []
  patterns: [pytest, fastapi-testclient, property-test]
key-files:
  created: [tests/test_effective_universe.py]
  modified: []
decisions:
  - "Shadow deny-lists injected via meme=/untradeable= kwargs — the pure cases never import src.alpaca_orchestrator (Alpaca SDK + env read at import)"
  - "Route cases 14-17 carry their OWN skipif so the 15 pure cases still run with no DB"
metrics:
  duration: ~25m
  completed: 2026-07-12
---

# Phase 16 Plan 01: RED Suite Summary

Executable RED spec for the UNIV-03 effective-universe contract: 19 test functions covering the 18 numbered VALIDATION cases plus case 11b.

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1-3 | RED suite (pure cases 1-13, 18; leak cases 10-12; route cases 14-17) | `1e186a6` |

Committed as one atomic file creation — the three tasks all write the same new file and the suite only collects once complete.

## RED evidence

`python -m pytest tests/test_effective_universe.py -q` before implementation:

```
ERROR tests/test_effective_universe.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.36s
```

Collection error is `ModuleNotFoundError: src.effective_universe` — RED on the missing implementation, not on malformed asserts.

## Load-bearing cases

- **Case 13 (`test_resolver_agrees_with_gate`)** — property test over the cross-product of allowlist ∪ quarantine ∪ off-universe symbols, for all four strategies. Both directions: gate-blocked ⇒ never effective; effective ⇒ `entry_allowed` returns `(True, None)`; reported reason equals the gate's reason verbatim. Non-vacuity guards: `blocked` non-empty per strategy, iterated count > 0, ≥1 gate-blocked symbol per strategy, `total_blocked_by_gate >= 4`.
- **Case 18 (`test_shadow_sets_confluence_only`)** — copytrade effective INCLUDES ETH/USD; `shadow_applied` False for copytrade/trend_btc/tradingagents.
- **Case 3** — DOT/LINK/ETH → `untradeable`, DOGE → `meme`, on a confluence bot (`len(effective) == 5`, not 8).
- **Case 11b** — `exposure_loaded=False` propagates; `leak == []` then means UNKNOWN.

## Deviations from Plan

**1. [Rule 1 - Bug] Route fixture seed had to match the real schema**
- **Found during:** the TEST_DATABASE_URL run (Plan 03 verification)
- **Issue:** `bots.id` is a NOT NULL PK (src/db_schema.sql:12; migration 009 only drops its CHECK) and `alpaca_trades.mirofish_prob` is NOT NULL. The initial fixture inserts omitted both → `NotNullViolation`.
- **Fix:** seed `id = bot_id` (as `seed_bots.py` does) and `mirofish_prob = 0.6`.
- **Commit:** `6384cdb`

## Self-Check: PASSED
- tests/test_effective_universe.py — FOUND
- Commit 1e186a6 — FOUND
