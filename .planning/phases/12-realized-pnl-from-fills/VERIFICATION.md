---
phase: 12-realized-pnl-from-fills
verified: 2026-07-10T00:00:00Z
status: passed
score: 5/5 must-haves verified (PNL-02 SATISFIED)
re_verification: No — initial verification
---

# Phase 12: Realized P&L From Fills — Verification Report

**Phase Goal:** Each closed trade records realized P&L from actual fill prices/quantities net of fees — never quote/target prices. Owns PNL-02.
**Status:** PASSED
**Ship verdict:** SHIP.

## Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `src/pnl.py::realized_pnl(side, entry_fill, exit_fill, qty, taker_fee)` pure, side-aware, TAKER_FEE both legs, no SLIPPAGE | ✓ VERIFIED | `src/pnl.py:10-28` — side branch L23-26; fees both notionals L27; no I/O; docstring states SLIPPAGE never subtracted |
| 2 | Migration 016 idempotent (not alembic) + schema mirror + `fees` kwarg on both `update_alpaca_trade` | ✓ VERIFIED | `016_realized_pnl_fees.sql` `ADD COLUMN IF NOT EXISTS fees DOUBLE PRECISION`; `db_schema.sql:45-46`; `db.py:107,118,121`; `trade_logger.py:42-44` |
| 3 | Monitor close block: exit_price=real close fill, pnl=realized net fees, fees persisted, total_pnl uses new figure, entry uses row filled_avg_price w/ logged fallback, exit fill logged fallback, ladder unchanged | ✓ VERIFIED | `alpaca_orchestrator.py:296-319`; ladder L238-267 intact (still quote-driven triggers) |
| 4 | Tests test_pnl.py + test_close_pnl.py map to 10 VALIDATION cases and pass | ✓ VERIFIED | 10 cases + `test_total_pnl_uses_realized`; `pytest tests/test_pnl.py tests/test_close_pnl.py -q` → 11 passed |
| 5 | Scope fence: no order-resolution/reconciliation/backfill/universe/retune, risk invariants untouched | ✓ VERIFIED | Only close-block P&L number + exit_price changed; ladder, Kelly, DD stop, fee-hurdle gate untouched |

**Score:** 5/5 truths verified.

## Key Links

| From | To | Via | Status |
|------|-----|-----|--------|
| alpaca_orchestrator | src.pnl.realized_pnl | import L36, call L306 | WIRED |
| alpaca_orchestrator | TAKER_FEE | fee_gate import L35, fees L305 | WIRED |
| close block | DB fees column | logger.update_alpaca_trade(fees=) L308-314 → db.py L118/121 | WIRED |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase suites | `pytest tests/test_pnl.py tests/test_close_pnl.py -q` | 11 passed in 6.22s | ✓ PASS |
| Full suite | `pytest tests/ -q` | 310 passed, 2 skipped | ✓ PASS (matches expected ~310/2) |

## Requirements Coverage

| Req | Description | Status | Evidence |
|-----|-------------|--------|----------|
| PNL-02 | Closed trade records realized P&L from actual fills net fees, not quote/target | ✓ SATISFIED | pnl.py helper + monitor close wiring + fees persistence + 11 green tests |

## Anti-Patterns

None. No TODO/FIXME/stub in phase files. Fallbacks are logged (L298, L302), not silent.

## Gaps Summary

None. All must-haves and PNL-02 satisfied with code + test evidence. No scope-fence violations.

---
_Verified: 2026-07-10 · Verifier: Claude (gsd-verifier)_
