---
phase: 14-stale-trade-backfill-repair
verified: 2026-07-10T00:00:00Z
status: passed
score: 8/8 must-haves verified
requirement: PNL-05 SATISFIED
ship_verdict: SHIP
---

# Phase 14: Stale-Trade Backfill & Repair — Verification Report

**Phase Goal:** One-shot idempotent backfill resolves existing open/stale `alpaca_trades` rows to their true terminal state from Alpaca history, writing realized P&L via the Phase-12 path; reports resolved/unresolvable/unchanged + residue; NEVER deletes rows. Owns PNL-05.
**Verified:** 2026-07-10
**Status:** PASSED — goal achieved
**Re-verification:** No — initial verification

## Goal Achievement — Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `classify_order()` pure helper; `BotThread._classify` delegates; Phase-11 green; `_TERMINAL_NONPOSITION` resolves at runtime | ✓ PASS | `src/order_resolution.py:11-28` pure (zero I/O). `src/bot_thread.py:17` imports both symbols; `:240` re-exports `_TERMINAL_NONPOSITION`; `:266-268` `_classify` delegates. `import src.bot_thread` → "bot_thread import OK". `test_order_resolution.py` green. |
| 2 | `get_stale_alpaca_candidates(bot_id, older_than_minutes=30)` + `count_unresolvable_alpaca_rows(bot_id)`, read-only | ✓ PASS | `src/db.py:151-172` — `status IN ('open','submitted') AND order_id IS NOT NULL AND timestamp < NOW()-interval`, SELECT-only. `:175-191` NULL order_id COUNT, SELECT-only. |
| 3 | `AlpacaClient.get_closed_orders(symbol, after=...)` CLOSED via GetOrdersRequest (local import), preserves crypto slash | ✓ PASS | `src/alpaca_client.py:419-442` — local import `:428-429`, `QueryOrderStatus.CLOSED` `:432`, `symbols=[symbol]` slash-preserved (docstring `:423`), `after` bounds window. |
| 4 | `resolve_stale_row(...)` reuses pnl+classify; close-match heuristic; writes closed via update_alpaca_trade; idempotent; `backfill(apply=False)` dry-run default; per-bot via `_client_for_bot` never bare | ✓ PASS | `src/backfill.py:51-89` reuses `classify_order`+`realized_pnl`+`TAKER_FEE`. `_match_close:92-128` opposite-side, filled_at>entry, earliest, qty-tolerance→None(ambiguous). `backfill(apply=False):131` default. `:142` `reconciliation._client_for_bot(bot_id)` (never bare keys — `reconciliation.py:62-67`). `:166` `update_alpaca_trade`. Candidate query excludes terminals → idempotent. |
| 5 | `scripts/backfill_trades.py` argparse dry-run DEFAULT + `--apply`; per-bot + overall counts incl residue | ✓ PASS | `scripts/backfill_trades.py:20-24` `--apply store_true` (default dry-run). `:28-41` prints per-bot + ALL totals: Resolved/Unchanged/Unresolvable/Residue + DRY-RUN notice. |
| 6 | NO DELETE/DROP/TRUNCATE in phase diff — UPDATE-only writes | ✓ PASS | `git diff 9139317..HEAD -- src/ scripts/` grep for destructive SQL → only doc-comment prose ("NEVER deletes"). `db.update_alpaca_trade:114-122` is `UPDATE ... WHERE id AND bot_id`, single mutation path. |
| 7 | `tests/test_backfill.py` 14 cases + DATABASE_URL-gated SQL guard; suites green (~336/4) | ✓ PASS | 17 test defs (14 cases + 3 extras). `test_stale_candidates_sql:467` `@pytest.mark.skipif(not DATABASE_URL)`. `test_backfill.py` → 26 passed/1 skipped. Full `tests/` → **336 passed, 4 skipped**. |
| 8 | Scope fence: reuses Phase-11/12 (no re-impl), no Phase-13 change, no schema change, risk untouched | ✓ PASS | Diff touches only new `order_resolution.py`/`backfill.py`/`scripts/backfill_trades.py`, additive `db.py`/`alpaca_client.py`, delegation-only `bot_thread.py`. No `*.sql`/migration in `--name-only`. Reuses `pnl.realized_pnl`, `reconciliation._client_for_bot`. No universe/retune/risk files. |

**Score:** 8/8 truths verified

## Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| PNL-05 | Backfill/repair pass resolves existing open-but-stale trades to true terminal state | ✓ SATISFIED | Full resolution ladder in `src/backfill.py` + entrypoint `scripts/backfill_trades.py`, 14 automated cases green, realized P&L via Phase-12 path, UPDATE-only, idempotent, dry-run default. |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| bot_thread runtime import (`_TERMINAL_NONPOSITION` resolves) | `python -c "import src.bot_thread"` | "bot_thread import OK" | ✓ PASS |
| Phase-11 + backfill suites | `pytest test_order_resolution.py test_backfill.py -q` | 26 passed, 1 skipped | ✓ PASS |
| Full suite regression | `pytest tests/ -q` | 336 passed, 4 skipped | ✓ PASS |

## Anti-Patterns Found

None. No debt markers, no destructive SQL, no bare-key fallback, no stubs. `resolve_stale_row` is a substantive pure decision function; dry-run correctly writes nothing (guarded by `apply` flag at `:163`).

## Human Verification Required

None for goal correctness. Note: `test_stale_candidates_sql` (real-SQL guard) is skipped without `DATABASE_URL` — one of the 4 expected skips. Optional: run against live Postgres (`DATABASE_URL` set) once to exercise the real stale-candidate SQL, and a `--apply` dry-run/apply against the production DB to observe actual residue counts. Not blocking.

## Gaps Summary

No gaps. All 8 must-haves PASS, PNL-05 satisfied, scope fences held, full suite green (336/4), zero destructive SQL, writes are UPDATE-only via the Phase-12 path, resolution reuses Phase-11 classification and Phase-12 P&L without reimplementation.

**Ship verdict: SHIP.**

---
_Verified: 2026-07-10 · Verifier: Claude (gsd-verifier)_
