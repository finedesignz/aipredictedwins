---
phase: 20-verification-e2e
plan: 02
subsystem: verification
tags: [tdd-red, anchored-window, e2e-chain, fences]
requires: []
provides: [G4-red-suite, G1-chain-suite, e2e-verify-fences, gross-writer-red]
affects: [tests/test_reconciliation.py, tests/test_e2e_reconciliation.py, tests/test_e2e_verify_fences.py, tests/test_gross_pnl_writers.py, tests/test_phase19_fences.py]
key-files:
  created: [tests/test_e2e_reconciliation.py, tests/test_e2e_verify_fences.py, tests/test_gross_pnl_writers.py]
  modified: [tests/test_reconciliation.py, tests/test_phase19_fences.py]
decisions:
  - "FINDING: scripts/backfill_trades.py is an ARMED --apply entrypoint predating Phase 20. Fence 38 rewritten to freeze the trigger set honestly rather than assert a falsehood."
  - "The chain's existing JOINS are SOUND — 31/32/33/35/36 all pass on main. Only case 34 (G3's slash bug) fails."
metrics:
  suite-after: "504 passed, 29 skipped, 37 failed (intended RED)"
completed: 2026-07-13
---

# Phase 20 Plan 02: RED — the anchored window, the E2E chain, the fences

## Are the existing chain's joins sound? YES.

**Cases 31, 32, 33, 35, 36 all PASS on current `main`.** The links were already correct;
the chain merely proves the joins. Specifically: long and short both reconcile to the
cent, fees carry through the backfill join with the right sign, and NULL/0.0 rows are
excluded from both the numerator and the win-rate denominator. Nothing was papered over.

**Case 34 FAILS** — G3's slash bug, caught at chain level:

```
AssertionError: the trade log realized P&L for a position that is STILL OPEN AT ALPACA —
                the slash mismatch fabricated it
assert -9417.5 == 957.5 ± 1.0e-09
```

The held BTC/USD position was force-closed at a fabricated loss, dragging the trade log's
realized P&L from **+$957.50** to **−$9,417.50**. The reconciliation then breaches.

## Per-case status

| Case | File | Status on `main` | Failure |
|------|------|------------------|---------|
| 17-26 | test_reconciliation | **RED** | `ImportError: cannot import name 'reconcile_window'` etc. |
| 27 | test_reconciliation | **RED** | migration 020 does not exist |
| 28 | test_reconciliation | **RED** | `reconciliation_anchor` absent from src/db_schema.sql |
| 29, 30* | test_reconciliation | **RED** | `module 'src.db' has no attribute 'write_reconciliation_anchor'` |
| 31,32,33,35,36 | test_e2e_reconciliation | **GREEN** | — the joins are sound |
| 34 | test_e2e_reconciliation | **RED** | `assert -9417.5 == 957.5` (above) |
| 12,14,16,42 | test_e2e_verify_fences | **RED** | `scripts/e2e_verify.py` does not exist |
| 13 | test_e2e_verify_fences | **GREEN** | the fence FIRES on a mutating fixture — proven before the thing it fences exists |
| 15 | test_e2e_verify_fences | **GREEN** | src/db.py:56's `if not _readonly():` guard intact |
| 37-40, F20-KILLER | test_phase19_fences | **GREEN** | all pass |
| W1-W6 | test_gross_pnl_writers | **RED** | see below |

\* case 30 (`test_the_anchor_uses_per_bot_alpaca_keys`) PASSES — it pins existing correct
behavior (`_client_for_bot` raises on a keyless bot).

## The gross-P&L writers — RED for the right reason

```
W1/W4  AssertionError: the trend/bot_c exit writer records NO fees
       assert None is not None
W2/W5  AssertionError: gross P&L recorded (10000.0) instead of net (9725.0)
W3/W6  AssertionError: a PROFITABLE short was recorded as a LOSS (-10000.0) — sign inverted
       assert -10000.0 > 0
```

Fixture sized so gross-vs-net is **$275** — 11x the $25 tolerance floor. Not vacuous.

## Deviations from Plan

### [Rule 1 - Bug] The plan's premise about the backfill entrypoint was FALSE

Plan 20-02 case 38 instructed: *"assert no committed file under src/, dashboard/, scripts/
or .github/ invokes `backfill(apply=True)` / `--apply`."* Written literally, **that fence
fails on `main`** — because `scripts/backfill_trades.py` has been an armed `--apply` CLI
since **Phase 14 (PNL-05)**:

```python
ap.add_argument("--apply", action="store_true",
                help="Actually write resolved rows. Default: dry-run (no writes).")
results = backfill(apply=args.apply)
```

**The gun has always had a trigger.** Until Plan 20-03 landed, that trigger fired a
backfill that closes every genuinely-held position with a fabricated P&L.

I did **not** delete the file (out of scope; the backfill authorization is 20-07's) and I
did **not** write a fence asserting a falsehood. Instead fence 38 now:
1. **Freezes the trigger set** at exactly `{"scripts/backfill_trades.py"}` — Phase 20 adds
   no second one;
2. asserts `src/backfill.py` itself grows no `argparse`/`__main__`/`--apply`;
3. asserts **nothing automated can pull it** — verified no CI workflow, Dockerfile,
   compose file or cron references the backfill. **The trigger is human-only.**

**This is a live risk that 20-07 must weigh:** the recovery-ceiling authorization is not
merely procedural — a human at a terminal can fire this today.

### [Rule 1 - Bug] Fence detectors were too blunt

The first `--tolerance`/`--apply` and `_ARMS_BACKFILL` detectors matched **bare mentions**,
so a docstring *promising* "this tool has NO `--tolerance` flag" tripped its own fence.
Detectors now target the **mechanism** (`add_argument("--tolerance")`; import-of-backfill
AND an apply mechanism), which is strictly *more* precise, not weaker — and case 13's
self-test still proves they fire. A fence that forbids documenting what it forbids pushes
the promise out of the file.

## Self-Check: PASSED
All four files FOUND. Suite: 504 passed, **29 skipped** (unchanged). Zero new skips.
