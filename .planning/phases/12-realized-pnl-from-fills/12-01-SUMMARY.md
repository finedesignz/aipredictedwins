---
phase: 12-realized-pnl-from-fills
plan: 01
subsystem: tests
tags: [pnl-02, tdd-red]
requires: []
provides: [tests/test_pnl.py, tests/test_close_pnl.py]
key-files:
  created:
    - tests/test_pnl.py
    - tests/test_close_pnl.py
metrics:
  commits: b5c8459, 40470ed
reconstructed: true
reconstructed-note: "Written 2026-07-14 during the v1.1 milestone archive. The implementer never wrote a SUMMARY for this plan; this one is reconstructed from the plan, the two commits above, the code on disk, and .planning/phases/12-realized-pnl-from-fills/VERIFICATION.md. Nothing here is asserted beyond that evidence."
---

# Phase 12 Plan 01: RED Contract for Realized P&L Summary

The Wave-0 (RED) test contract for PNL-02: the 10 cases from `12-VALIDATION.md` encoded as named,
deterministic tests across two new files, written before `src/pnl.py` existed and before the monitor
close block was wired.

## Tasks

- **Task 1 — `tests/test_pnl.py` (cases 1-5, pure helper).** 66 lines, commit `b5c8459`
  (`test(12-01): add failing realized_pnl pure-helper suite (cases 1-5)`). Pins the side-aware math
  and the both-legs fee term against the hand-computed goldens (18.95 / -21.05 / 20.00 zero-fee).
  RED by construction: `from src.pnl import realized_pnl` could not resolve — `src/pnl.py` is created
  in Plan 02.
- **Task 2 — `tests/test_close_pnl.py` (cases 6-10, monitor close path).** 188 lines, commit
  `40470ed` (`test(12-01): add failing monitor close-path suite (cases 6-10)`). Drives
  `PositionMonitor._check_positions()` with in-memory `FakeLogger` / `FakeAlpacaClient` doubles
  (pattern borrowed from `tests/test_order_resolution.py`), `current_price` deliberately distinct
  from the scripted exit fill so case 6 genuinely discriminates fill-vs-quote. RED against the
  un-wired monitor, which still stored `exit_price=current_price, pnl=trade_pnl` and passed no fees.

Both commits are test-only — `git show --stat` on each touches nothing under `src/`.

## Verification

- Per-plan RED gate: both suites failed on authoring (import error for `src.pnl`; behavioural failure
  for the un-wired close block). The exact verbatim failure output was **not recorded** at the time
  and is not reconstructed here.
- Downstream (Plans 02/03) turned both suites GREEN. The phase VERIFICATION.md records
  `pytest tests/test_pnl.py tests/test_close_pnl.py -q` → **11 passed** — 10 validation cases plus one
  extra test, `test_total_pnl_uses_realized`, which is not in the 10-case matrix.

## Deviations

- The suite ended up with **11** tests rather than 10 — an extra `test_total_pnl_uses_realized` asserting
  `PositionMonitor.total_pnl` accumulates the realized figure. The plan listed this as optional
  ("Optional: assert monitor.total_pnl/get_stats reflects the realized figure"), so it is an accepted
  addition, not a scope breach. Whether it landed in this plan's commits or Plan 03's was **not
  recorded**; the phase VERIFICATION.md counts it in the 11.
- No other deviation is visible in the commits.

## Self-Check: PASSED (reconstructed)

`tests/test_pnl.py` and `tests/test_close_pnl.py` exist on disk; commits `b5c8459` and `40470ed` are
present in `main`'s history; VERIFICATION.md records the suites GREEN at phase close.
