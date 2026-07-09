---
phase: 12
slug: realized-pnl-from-fills
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-09
---

# Phase 12 — Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Quick run** | `python -m pytest tests/test_pnl.py tests/test_close_pnl.py -q` |
| **Full suite** | `python -m pytest tests/ -q` (baseline 299 passed, 2 skipped) |

## Validation Architecture (PNL-02)

All cases prove realized P&L comes from fills, net of TAKER_FEE, both legs. Pure math in
`tests/test_pnl.py`; monitor wiring in `tests/test_close_pnl.py` (reuse FakeLogger/FakeAlpacaClient).

| # | Case | Test | Proves |
|---|------|------|--------|
| 1 | long: entry_fill/exit_fill/qty/fee → cent-exact net pnl | test_realized_pnl_long | fills+fee math |
| 2 | short: side-aware sign → cent-exact net pnl | test_realized_pnl_short | short sign correct |
| 3 | fee applied to both legs' notional, not one | test_realized_pnl_fees_both_legs | fee model |
| 4 | slippage NOT double-counted (TAKER_FEE only) | test_realized_pnl_no_slippage_double | no double-count |
| 5 | zero/None fill guard → safe fallback, no crash | test_realized_pnl_guards | robustness |
| 6 | close path stores exit_fill as exit_price (not quote) | test_close_stores_exit_fill | exit_price=fill |
| 7 | close path stores net realized pnl (not quote-based) | test_close_stores_net_pnl | pnl=realized |
| 8 | fees column persisted on close | test_close_persists_fees | fees stored |
| 9 | legacy row (entry filled_avg_price NULL) → falls back to entry_price, logged | test_close_legacy_entry_fallback | fallback path |
| 10 | close_position dict missing fill → falls back to current_price, logged | test_close_exit_fallback | exit fallback |

Wave 0 gap: `tests/test_pnl.py` + `tests/test_close_pnl.py` do not exist — created before impl.

## Nyquist Compliance

- PNL-02 maps to ≥1 automated case (all 10 above).
- `nyquist_compliant` flips true when all 10 exist and pass.
