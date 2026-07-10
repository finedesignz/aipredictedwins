---
phase: 13
slug: alpaca-reconciliation-check
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-10
---

# Phase 13 — Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Quick run** | `python -m pytest tests/test_reconciliation.py -q` |
| **Full suite** | `python -m pytest tests/ -q` (baseline 310 passed, 2 skipped) |

## Validation Architecture (PNL-03)

Pure math + driver/persist wiring in `tests/test_reconciliation.py`, zero-network fakes
(reuse `test_close_pnl.py`/`test_reconciliation` fake-double convention, `pytest.approx`).

| # | Case | Test | Proves |
|---|------|------|--------|
| 1 | within tolerance → within_tolerance=True, no breach | test_reconcile_within_tolerance | pass path |
| 2 | over tolerance → within_tolerance=False | test_reconcile_over_tolerance | breach detect |
| 3 | delta exactly at tolerance boundary → within (<=) | test_reconcile_boundary | boundary rule |
| 4 | negative delta over tolerance (abs compare) → breach | test_reconcile_negative_delta | abs delta |
| 5 | alpaca realized = (equity − starting) − unrealized (long+short unrealized) | test_reconcile_alpaca_derivation | derivation math |
| 6 | trade_log_pnl sums closed+stopped+target_hit, excludes canceled/rejected/expired | test_realized_pnl_three_states | correct sum set |
| 7 | breach persists reconciliation row (bot_id, delta, within_tolerance, tolerance) via upsert | test_persist_reconciliation | flag written |
| 8 | breach calls notifier.send_alert once; within-tolerance does not | test_breach_alerts | alert reuse |
| 9 | multi-bot: each bot reconciled independently against its own account/starting_equity | test_multi_bot_independent | per-bot isolation |
| 10 | None/zero guards (no positions, zero unrealized) → no crash | test_reconcile_guards | robustness |

Wave 0 gap: `tests/test_reconciliation.py` does not exist — created before impl.

## Nyquist Compliance

- PNL-03 maps to ≥1 automated case (all 10 above).
- `nyquist_compliant` flips true when all 10 exist and pass.
