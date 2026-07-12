---
phase: 15-universe-hard-gate
plan: 01
subsystem: testing
tags: [universe, gate, quarantine, red-suite]
requires: []
provides: [tests/test_universe.py]
affects: [15-02, 15-03]
tech-stack:
  added: []
  patterns: [zero-network fakes, static source guard, signed-qty position fake]
key-files:
  created: [tests/test_universe.py]
  modified: []
decisions:
  - "FakeAlpacaClient.get_positions() returns the REAL row shape (slashless symbol, SIGNED float qty) so the copytrade reduce-vs-add branch is drivable"
  - "Case 14 drives src.bot_c.strategy._process_ticker DIRECTLY (a higher-level test would be vacuous — _select_tickers never yields an off-universe ticker)"
metrics:
  duration: ~10m
  completed: 2026-07-12
---

# Phase 15 Plan 01: RED Universe Hard-Gate Suite Summary

RED test suite pinning the UNIV-01/UNIV-02 contract before any implementation: 22 collected cases
covering the 19 VALIDATION rows, with exits-never-gated enforced by a static source guard.

## What Was Built

`tests/test_universe.py` — pure-module cases (normalize, entry_allowed precedence, empty-allowlist
safety net, BITX trend carve-out, BotConfig.quarantined/all_symbols), wiring cases (`_submit_order`
block/allow, selector filters, copytrade, bot_c), and the three exit-safety cases:

- **Case 17** (`test_gate_absent_from_alpaca_client`) — static guard: reads `src/alpaca_client.py`
  from disk (pathlib, repo-root-relative) and asserts `"entry_allowed"` is absent. GREEN from the
  start; the regression tripwire for Plan 03.
- **Case 18** — a copytrade SELL that REDUCES a held off-universe long still submits.
- **Case 19** — a copytrade BUY that ADDS to that same held long is BLOCKED (the audited TRUMP case),
  plus the short mirror (BUY on a held short = reduce = submits), a SELL on a not-held symbol
  (short-to-open = gated), and the fail-CLOSED path when `get_positions()` raises.

At the end of this plan the suite failed RED with `ModuleNotFoundError: No module named 'src.universe'`
— the right reason (missing impl, not malformed tests).

## Deviations from Plan

None — plan executed as written.

## Commits

- `8c1557e` test(15-01): RED universe hard-gate suite (UNIV-01, UNIV-02)

## Self-Check: PASSED
- `tests/test_universe.py` exists
- commit `8c1557e` present in `git log`
