---
phase: 20-verification-e2e
plan: 04
subsystem: dashboard
tags: [paper-gate, honesty-fix]
requires: [20-01]
provides: [honest-paper-gate, total_rows-surface]
affects: [dashboard/api/routes/settings.py, dashboard/api/models.py]
key-files:
  modified: [dashboard/api/routes/settings.py, dashboard/api/models.py]
decisions:
  - "paper_trades_completed = len(closed_rows) — the RESOLVED population settings.py ALREADY computes for the win rate. NO new SQL, no sixth spelling of the predicate."
  - "The gate reads WORSE. Intended. NOT to be tuned back."
metrics:
  diff: "2 files, 35 insertions, 5 deletions"
completed: 2026-07-13
---

# Phase 20 Plan 04: the paper gate counts TRADES, not rows

## THE LIVE MAGNITUDE WAS **NOT** PREDICTED

No number in this diff claims the count goes from 655 to ~260. RESEARCH **R1 REFUTED** that
arithmetic: `dashboard/api/db.py:19` `KNOWN_BOTS=("A","B","C","D")` over an **unfiltered**
`COUNT(*)`, versus Phase 17's 655 **position-closed** rows for bots **A/B/C/E** — a
different bot set **and** a different status filter. Two queries returning the same integer
is a coincidence, not an identity.

**`scripts/e2e_verify.py` MEASURES the before/after per bot** (`paper_gate.total_rows`,
`paper_gate.resolved_rows`, `paper_gate.excluded`). The actual prod numbers require
credentials and are **20-07's to measure** — they are not asserted anywhere in this phase.

## What changed

`settings.py:36` was a bare, unfiltered `SELECT COUNT(*) AS n FROM alpaca_trades` fed
straight to `paper_trades_completed` at `:192` — the **50-trade gate that guards LIVE
TRADING**. It counted `submitted` rows, `rejected` gate-blocks and canceled 0-fill entries:
rows that **never became a position at all** (`src/bot_thread.py:362,376,382` writes them).

**A gate satisfied by rows that were never trades is not a gate** — and no test asserted
otherwise, which is precisely why it shipped.

- `paper_trades_completed` now = `len(closed_rows)`, the canonical RESOLVED population
  (`status IN ('closed','stopped','target_hit') AND pnl IS NOT NULL AND pnl <> 0`) that
  settings.py **already computed two lines below** for the win rate. **No new SQL.**
- The raw count survives as `total_rows` on the payload, beside the existing `unresolved`,
  so a user watching the gate figure **fall** can see exactly where the rows went.
  *A number removed from a gate must remain visible next to it.*

## Demonstrated before/after (controlled fixture, case 9)

A 9-row log in which exactly **3** rows are resolved trades:

| | |
|---|---|
| Before (bare `COUNT(*)`) | **9** |
| After (RESOLVED predicate) | **3** |

Six of those nine never became a resolved trade; two (`submitted`, `rejected`) never became
a position at all. Driven through the **real `get_settings` route** against a SQL-honouring
fake — not a source grep.

## THE GATE READS WORSE. THAT IS THE POINT.

Making the gate **honest** is not the same as **opening** it. Byte-unchanged:
`paper_trades_target=50`, `win_rate_target=40.0`, `mode="paper"`, `_LIVE_THRESHOLD`. Live
trading remains paper-gated by every other rule. **This is not to be tuned back.**

## Deviations from Plan

**[Rule 1 - Bug]** My first draft of the case-10 fence asserted the string
`"SELECT COUNT(*) AS n FROM alpaca_trades"` was absent — but that also matches the
**legitimate** filtered `unresolved` count query at `:50-56`. The fence now pins the
**bare, unfiltered gate-shaped** form (`... FROM alpaca_trades WHERE bot_id IN`)
specifically. A filtered `COUNT(*)` is correct and stays.

**[Rule 1 - Bug]** My explanatory comment contained the literal `100_000.0 * len(`, which
tripped Phase 19's existing hardcoded-bankroll fence (`test_settings_equity_is_not_hardcoded`).
The fence was right; the comment was reworded. No assertion was weakened.

## Self-Check: PASSED
- `dashboard/api/tests/` — 28 passed, 16 skipped (pre-existing DB-gated skips)
- `grep paper_trades_completed=total_trades` → **0**
- `grep 655|260` in the diff → **0**
- Suite: skipped count still **29**
