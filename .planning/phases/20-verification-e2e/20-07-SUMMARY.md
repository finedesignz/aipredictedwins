---
phase: 20-verification-e2e
plan: 07
subsystem: verification
requirements: [VERIFY-01, VERIFY-02]
key-files:
  created:
    - .planning/phases/20-verification-e2e/20-EVIDENCE.md
  modified:
    - .planning/REQUIREMENTS.md
metrics:
  suite: 541 passed / 29 skipped (baseline 29 skipped — zero new skips)
  completed: 2026-07-14
---

# Phase 20 Plan 07: E2E Verification Evidence — Summary

Closed the v1.1 milestone with a real prod measurement: VERIFY-01 validated, VERIFY-02 closed as
PARTIAL (scoped) on the actual state of the window — never on an aspirational one.

## THE BACKFILL WAS NOT RUN. THE HISTORICAL ROWS WERE NOT MODIFIED. NOTHING WAS WRITTEN TO PROD.

Every measurement was SELECT-only under `AIPW_DB_READONLY=1` (libpq
`default_transaction_read_only=on` → Postgres refuses mutations, SQLSTATE 25006). No `--apply`, not
even "just to see". The 395 sentinel rows are byte-identical.

## What was measured (prod, 2026-07-14, git `f1e6e29`)

- **`tolerance_override: false`** — $25 / 0.005 / taker_fee 0.0025, all from `default`. Verified no
  tolerance var is set on the Coolify service. The breach is graded against an unmodified ruler.
- **T0 anchored 07:18:5x UTC for A/B/C** — the window opened today.
- **Windowed verdict: `INSUFFICIENT_SAMPLE` on all three bots** (0 resolved post-T0; need 20).
  Recorded as NOT a pass. Nothing widened, no wait-and-retry to manufacture a sample.
- **All-time reconciliation still BREACHING** (`legacy: true`): A $8,720.31, B $1,610.22, C $9,497.07.
  A fixed level offset — unreachable forever without repairing the rows.
- **Paper gate: 655 total rows → 260 resolved** (delta exactly −395 = the sentinel count), win_rate
  34.6 (below the 40% gate). A real measurement of the live value, not the refuted projection. The
  gate reads worse because it now counts the truth; NOT tuned back.
- **Recovery ceiling: 0 of 395, for every bot** — and no bot carried `positions_unavailable`, so
  these are real zeros, not an Alpaca outage. **But the zero is structural, not incidental:** all 395
  rows are `status='closed'` with `order_id IS NULL`, while the backfill selects only
  `open`/`submitted` rows *with* an `order_id`. **The shipped backfill would repair nothing.**

## Deviations / findings

**[Rule 4 — reported, NOT fixed] `src/backfill.py:153` passes `bot_id` positionally into
`TradeLogger`'s `db_path` slot.** The logger falls back to the `BOT_ID` env var, so under `--apply`
every repaired row would be attributed to whatever `BOT_ID` the environment carries — not the bot
being processed. Harmless on the dry-run path (constructed, never used). Recorded in 20-EVIDENCE §4
as a blocker on the §7 authorization rather than patched: this plan writes `.planning/` only, and
fixing code inside the phase that certifies it is the wrong move. Must be fixed before any `--apply`.

## REQUIREMENTS branch taken: **BRANCH B**, and why

Every bot reports `INSUFFICIENT_SAMPLE`, so Branch A's *"Achieved — within tolerance on the post-T0
window"* line is FORBIDDEN and was not written. VERIFY-02 stays OPEN on the windowed clause until a
dated follow-up run — not before **2026-07-28** — of `python scripts/e2e_verify.py --json` returns
exit 0.

## Suite

`python -m pytest tests/ dashboard/api/tests/ -q` → **541 passed, 29 skipped**. Zero new skips
(VALIDATION case 41, owned here). `test_phase19_fences.py` green, incl. case 38 (backfill stays
UNARMED) and F20-KILLER.

## Self-Check: PASSED
