---
phase: 20-verification-e2e
plan: 03
subsystem: backfill
tags: [bugfix, symbol-normalization, outage-safety]
requires: [20-01]
provides: [backfill-fixed-but-unarmed]
affects: [src/backfill.py]
key-files:
  modified: [src/backfill.py]
decisions:
  - "src.universe.normalize used at BOTH compare sites — never a local .replace('/','')"
  - "counts['error'] = 'positions_unavailable' makes an Alpaca outage DISTINGUISHABLE from 'nothing to recover' in the recovery ceiling a human authorizes a prod write against"
metrics:
  diff: "1 file, 29 insertions, 4 deletions"
completed: 2026-07-13
---

# Phase 20 Plan 03: the backfill is disarmed — and it was NOT run

## THE BACKFILL WAS NOT RUN. NO PROD ROW WAS TOUCHED.

Neither `apply=True` nor `apply=False`. No entrypoint was added. The 395 historical
sentinel rows are byte-identical.

## Before / after, executed

```
                                          BEFORE (main)                                    AFTER
HELD, real slashless Alpaca shape   ('resolved', {'status':'closed',            ('unchanged', None)
                                     'exit_price':80.0,'pnl':-20.45,
                                     'fees':0.45})   <- FABRICATED LOSS
                                     on a LIVE position
get_positions() FAILED (None)       resolves against an empty set              ('unchanged', None)
genuinely VANISHED                  ('resolved', {...})                        ('resolved', {...})  <- still works
```

The fix did **not** make the backfill inert — a genuinely-vanished position still resolves
correctly (positive control, case 4).

## The diff

```diff
+from src.universe import normalize

     if status == "open":
-        # NOTE (Phase 18 W1): live_symbols here is slash-STRIPPED by backfill.py:147 ...
-        if row["symbol"] in live_symbols:
+        if live_symbols is None:          # the get_positions() call FAILED
+            return "unchanged", None
+        norm_live = {normalize(s) for s in live_symbols}
+        if normalize(row.get("symbol")) in norm_live:
             return "unchanged", None

-        live_symbols = {p["symbol"] for p in (client.get_positions() or [])}
+        positions = client.get_positions()
+        if positions is None:
+            log.warning("Backfill SKIPPED for bot %s: get_positions() returned None ...")
+            counts["error"] = "positions_unavailable"
+            counts["residue"] = db.count_unresolvable_alpaca_rows(bot_id)
+            results.append((bot_id, counts))
+            continue
+        live_symbols = {normalize(p["symbol"]) for p in positions}

-            if status == "open" and row["symbol"] not in live_symbols:
+            if status == "open" and normalize(row["symbol"]) not in live_symbols:
```

Three edits, `git diff --stat`: **1 file, 29 insertions, 4 deletions.** `_match_close`, the
write gate at `:164`, and every other arm are untouched.

## Why the `error` marker is load-bearing, not decoration

Without it, an Alpaca outage yields `{"resolved": 0, "unchanged": 0, ...}` —
**byte-identical to a clean bot with nothing to repair.** An operator reading the recovery
ceiling in `20-EVIDENCE.md` would see "Bot A: 0 recoverable" and conclude "nothing to fix"
when it actually means **"Alpaca never answered."** That dict is what a human authorizes a
**write to production trade data** against. **Plan 20-07 must REFUSE to print a ceiling for
any bot carrying `counts["error"]`.**

## Acceptance greps

| Grep | Result |
|------|--------|
| `replace("/"` in src/backfill.py | **0** — no hand-rolled second normalizer |
| `from src.universe import normalize` | **hit** (line 25) |
| `or []` | **0** — the coercion landmine is gone |
| `apply=True\|--apply\|argparse\|__main__` | **0** — no entrypoint added |
| `positions_unavailable` | **hit** (line 168) |
| `Phase-20 item` | **0** — the stale NOTE is gone |

## ⚠ CARRY-FORWARD TO 20-07: THE GUN HAS A TRIGGER

`scripts/backfill_trades.py` (Phase 14, PNL-05) is an **armed `--apply` CLI** and always
has been. This plan fixed the **ammunition**; it did not remove the trigger. The trigger is
**human-only** (verified: no CI workflow, Dockerfile, compose file or cron references it).
Repairing the 395 rows remains a blocking human authorization.

## Deviations from Plan

None to the code. The plan's assumption that no `--apply` entrypoint existed was wrong;
that finding is recorded in 20-02-SUMMARY.md and carried forward above.

## Self-Check: PASSED
- `tests/test_backfill.py` — ALL GREEN (45 passed incl. the 8 former REDs)
- `tests/test_e2e_reconciliation.py` case 34 — **now GREEN**
- `tests/test_phase19_fences.py` — ALL GREEN
- Suite: skipped count still **29**
