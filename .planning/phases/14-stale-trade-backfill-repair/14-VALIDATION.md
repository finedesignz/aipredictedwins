---
phase: 14
slug: stale-trade-backfill-repair
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-10
---

# Phase 14 — Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Quick run** | `python -m pytest tests/test_backfill.py -q` |
| **Full suite** | `python -m pytest tests/ -q` (baseline 320 passed, 3 skipped) |

## Validation Architecture (PNL-05)

Zero-network fakes (extend test_order_resolution.py / test_reconciliation.py conventions).

| # | Case | Test | Proves |
|---|------|------|--------|
| 1 | entry order canceled/rejected/expired, 0 filled → terminal non-position, pnl=0 | test_backfill_entry_canceled | unfilled resolves |
| 2 | entry filled + position gone + closing order found → status='closed', exit_price=exit_fill, pnl=realized, fees set | test_backfill_filled_closed | realized backfill via Phase-12 path |
| 3 | entry filled + position still open → unchanged (genuinely held) | test_backfill_still_open_unchanged | no false close |
| 4 | row with NULL order_id → unresolvable residue, untouched | test_backfill_no_order_id_residue | no guessing |
| 5 | closing order not findable in Alpaca history → unresolvable, unchanged | test_backfill_close_not_found | best-effort honesty |
| 6 | idempotent: re-run over already-terminal rows is a no-op | test_backfill_idempotent | crash/re-run safe |
| 7 | dry-run (default) writes nothing; --apply writes | test_backfill_dry_run_no_write | safe default |
| 8 | realized_pnl reused with entry_fill/exit_fill/filled_qty/TAKER_FEE (long) | test_backfill_pnl_long | Phase-12 reuse long |
| 9 | short side realized_pnl sign correct | test_backfill_pnl_short | short sign |
| 10 | guard window excludes too-recent rows (avoid racing live) | test_backfill_guard_window | no live race |
| 11 | counts reported: resolved / unresolvable / unchanged per bot + overall | test_backfill_counts | reporting |
| 12 | partial/ambiguous close (multiple closes) → matching heuristic (earliest opposite-side after entry) or unresolvable | test_backfill_ambiguous_close | heuristic |
| 13 | per-bot isolation: each bot uses its OWN account keys | test_backfill_per_bot_keys | one-account-per-bot |
| 14 | DATABASE_URL-gated: get_stale_alpaca_candidates real SQL returns only stale open/submitted+order_id rows | test_stale_candidates_sql | real-SQL guard |

Wave 0 gap: `tests/test_backfill.py` does not exist — created before impl.

## Nyquist Compliance

- PNL-05 maps to ≥1 automated case (all above).
- `nyquist_compliant` flips true when the suite exists and passes.
