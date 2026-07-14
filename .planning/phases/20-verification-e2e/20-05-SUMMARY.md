---
phase: 20-verification-e2e
plan: 05
subsystem: reconciliation
tags: [anchored-window, migration, schema-mirror]
requires: [20-02]
provides: [reconciliation_anchor, reconcile_window, window_tolerance, ensure_anchor]
affects: [dashboard/api/migrations/020_reconciliation_anchor.sql, src/db_schema.sql, src/db.py, src/reconciliation.py]
key-files:
  created: [dashboard/api/migrations/020_reconciliation_anchor.sql]
  modified: [src/db_schema.sql, src/db.py, src/reconciliation.py]
decisions:
  - "ON CONFLICT (bot_id) DO NOTHING — an UPSERT would re-anchor T0 every run and make the window VACUOUSLY GREEN"
  - "reconcile_window CALLS reconcile_bot twice — two calls, ONE formula. No second copy of the subtraction."
  - "Verdict precedence puts the SAMPLE GATE FIRST so a zero delta on 19 trades cannot reach PASS"
metrics:
  diff: "4 files, ~306 insertions"
completed: 2026-07-13
---

# Phase 20 Plan 05: the anchored reconciliation window

## The formula exists EXACTLY ONCE

```
$ grep -n "equity - starting_equity" src/reconciliation.py
37:        alpaca_realized_pnl = (equity - starting_equity) - unrealized_pnl   <- the DOCSTRING
44:    alpaca_realized_pnl = (equity - starting_equity) - unrealized_pnl       <- the CODE, in reconcile_bot
```

**One code occurrence.** `reconcile_window` **calls** `reconcile_bot` — twice: once with
`tolerance=0.0` to derive the realized figure the tolerance depends on, then again with the
derived tolerance for the authoritative verdict. **Two calls, ONE formula.** A second copy
of that subtraction would be a second place for a sign error — the exact class of defect
this milestone exists to eliminate.

## The anchor writer — `DO NOTHING`, in full

```sql
INSERT INTO reconciliation_anchor
(bot_id, anchored_at, equity, unrealized_pnl, trade_log_pnl)
VALUES (%s, NOW(), %s, %s, %s)
ON CONFLICT (bot_id) DO NOTHING
```
…followed by a `SELECT` that returns the row **now** anchored — the **pre-existing** one if
there was one.

**NEVER `DO UPDATE`.** An UPSERT would silently re-anchor `T0` to "now" on **every run**,
permanently resetting the window to zero samples and making the entire check **VACUOUSLY
GREEN** — the same class of self-defeating move as widening the tolerance. Case 29(b) proves
it behaviorally: a second write with `equity=999_999` leaves `anchored_at`/`equity`/
`unrealized_pnl`/`trade_log_pnl` **all unchanged**.

`grep "DO UPDATE" src/db.py` → only inside `record_reconciliation` (the pre-existing Phase-13
upsert, which legitimately stores the *latest* result, not a fixed origin). **An origin that
moves is not an origin.**

## The schema mirror is NOT optional

`reconciliation_anchor` is in **both** `dashboard/api/migrations/020_reconciliation_anchor.sql`
**and** `src/db_schema.sql`. `_bootstrap_schema()` (src/db.py:61-66) executes db_schema.sql
**wholesale**, so a migration-only table would exist in **PROD AND NOWHERE ELSE** — absent
from every fresh-DB bootstrap and every test DB.

Migration 020, comments stripped, is **`CREATE TABLE IF NOT EXISTS` only** — no DROP, DELETE,
ALTER, UPDATE, INSERT, and no `bot_id` CHECK (migration 009 dropped it for C/D). Idempotent
and safe to apply before the code deploys. **It was NOT applied to prod in this plan.**

## INSUFFICIENT_SAMPLE is not a pass

Verdict precedence — the sample gate is **first**, and that ordering is load-bearing:

```
resolved_post_t0 < 20   -> "INSUFFICIENT_SAMPLE"   <- EVEN AT delta_window == 0.0 EXACTLY
resolution_rate < 0.95  -> "FAIL"
not within_tolerance    -> "FAIL"
otherwise               -> "PASS"
```

Case 22 pins it: 19 resolved trades at a **perfect zero delta** → `INSUFFICIENT_SAMPLE`;
20 resolved trades at the **same** zero delta → `PASS`. The verdict flips **only** on the
sample count.

`window_tolerance = max($25 floor, 0.5% band)`: $25 at a $100 window, $500 at a $100k window,
symmetric under sign. The floor **never drops below $25**.

## The all-time tolerance did not move

`DEFAULT_TOLERANCE_USD = 25.0` — unchanged. The all-time check is a **fixed level offset**
(the sentinel rows contribute exactly zero to `trade_log_pnl` while Alpaca's equity move
already contains their true outcome), invariant under every future correct trade, and
therefore **unsatisfiable forever** absent an authorized write to those rows. It **keeps
breaching**, is relabelled `legacy`, and its offset is **surfaced beside the window** with
its authorization note. **THE BREACH IS THE FINDING.**

The anchor table is a **forced move**, not a preference: the entire `AlpacaClient` surface was
enumerated and there is **no activities call and no portfolio-history call**. There is
literally no way to ask Alpaca "what did you realize since T0". It must be snapshotted.

## Deviations from Plan

**[Rule 1 - Bug]** `ensure_anchor` (called from `reconcile_bot_live`) legitimately added a DB
read, which broke three **pre-existing** driver tests (`KeyError: 'DATABASE_URL'`). The
`driver_env` fixture now stubs `db.get_reconciliation_anchor`. The collaborator set genuinely
changed; **no assertion was weakened** — those tests still assert the all-time reconcile,
which Phase 20 leaves untouched.

**[Rule 1 - Bug]** Two of my own fences fired on my own **prose**: the migration header
explains *why* it must never `DO UPDATE`/carry a `CHECK`, and `write_reconciliation_anchor`'s
docstring says "**NEVER `DO UPDATE`**". Both fences now scan **statements/code, not comments
and docstrings**. A fence that punishes a file for documenting what it forbids pushes that
promise out of the file.

## Self-Check: PASSED
- Migration 020 + db_schema.sql mirror — FOUND in both
- `tests/test_reconciliation.py` + `tests/test_e2e_reconciliation.py` — ALL GREEN
- `tests/test_phase19_fences.py` — ALL GREEN; `_TRADE_WRITER_ALLOWLIST` unchanged
- Suite: skipped count still **29**
