---
phase: 20-verification-e2e
plan: 06
subsystem: verification
tags: [cli, select-only, tolerance-provenance]
requires: [20-02, 20-04, 20-05]
provides: [scripts/e2e_verify.py]
affects: [scripts/e2e_verify.py]
key-files:
  created: [scripts/e2e_verify.py]
decisions:
  - "On ANY tolerance override the script SHORT-CIRCUITS BEFORE querying prod — it grades nothing and emits no PASS"
  - "NO --tolerance, NO --apply. A CLI tolerance override is a widening lever by another name."
metrics:
  diff: "1 file, 393 lines"
completed: 2026-07-14
---

# Phase 20 Plan 06: `scripts/e2e_verify.py` — nothing can manufacture a PASS

## `--help` output

```
usage: e2e_verify.py [-h] [--bot BOT] [--json]

E2E reconciliation verification (VERIFY-02). READ-ONLY: this tool defines no
write flag and no tolerance flag.

options:
  -h, --help  show this help message and exit
  --bot BOT   Limit the report to one bot id. Default: all enabled.
  --json      Emit the JSON report alone.
```

**Only `--bot` and `--json`.** No `--apply`, no `--write`, no `--fix`, **no `--tolerance`**.

## Import order IS the guarantee

```
AIPW_DB_READONLY set at line : 62
first `src` import at line   : 69
```

**62 < 69.** `get_pool()` latches `_pool` on its **first call**, and `_create_pool()` decides
**both** the libpq `options=-c default_transaction_read_only=on` (src/db.py:38) **and**
whether `_bootstrap_schema()` runs its DDL (src/db.py:56) **at that moment**. Setting the env
in `main()`, or in a shell wrapper, is setting it **too late** — the pool would already be
writable and the schema DDL would already have run against prod.

This makes read-only a property of **the script**, not of how someone remembered to invoke it.

## THE TOLERANCE OVERRIDE — PROVEN

```
$ RECONCILIATION_TOLERANCE_USD=100000 python scripts/e2e_verify.py

  tolerance_usd: 100000.0 (source: env)
  tolerance_pct: 0.005 (source: default)

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
TOLERANCE_OVERRIDE — REFUSING TO GRADE AGAINST A TAMPERED RULER
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

  An environment variable is overriding the reconciliation tolerance:
    RECONCILIATION_TOLERANCE_USD = 100000.0 (committed default: 25.0)

  A widened tolerance turns BOTH the all-time row AND the window green, and no
  grep of any committed file can see it. That is the one move this check exists
  to prevent. No verdict is emitted and no bot is graded. Exiting non-zero.

  Unset the variable and re-run. THE BREACH IS THE FINDING — it is not to be
  tuned away.

EXIT CODE = 2
```

`TOLERANCE_OVERRIDE` emitted · **no PASS anywhere in the output** · **exit 2** · and it
**short-circuits before it ever queries prod** — it refuses to grade rather than grading with
a bad ruler. The effective `TAKER_FEE` + source is printed in the provenance header too.

`_tolerance()` reads `os.environ` **at call time**, so a Coolify env var is a lever **no
committed-file grep can see**. That is the door this closes.

## Verdicts and exit codes

| Verdict | Exit | Note |
|---------|------|------|
| PASS (all bots) | **0** | the only zero-exit path |
| FAIL | non-zero | |
| **INSUFFICIENT_SAMPLE** | **non-zero** | **NOT a pass.** <20 resolved trades since T0 means the window has not *earned* a verdict |
| **NO_ANCHOR** | **non-zero** | **NOT a pass** |
| per-bot ERROR | non-zero | one broken bot costs one bot's row, not the report |
| tolerance_override | **2** | grades nothing |

`NO_ANCHOR` covers **two** states, and the second is the one that occurs first: a missing
`reconciliation_anchor` **TABLE** (`UndefinedTable`, SQLSTATE **42P01** — migration 020 not yet
applied) is caught **specifically** and reported as `NO_ANCHOR` + `reason: "table_absent"`,
**not** flattened into a generic error. **This is the expected state on landing day**, and
mislabelling it would bury the single most important fact in the report: *the window has not
opened yet.*

## Fences

| Grep | Result |
|------|--------|
| `UPDATE/DELETE/INSERT/DROP/ALTER` | **0** — SELECT-only |
| `--apply\|--write\|--fix\|--tolerance` declared | **0** — only `--bot`, `--json` |
| `ensure_anchor` | **0** — the script NEVER creates T0 |
| `KNOWN_BOTS` | **0** — the bot set comes from `_enabled_bot_ids()`, the `bots` table |
| `655\|260\|395\|8720` | **0** — no live magnitude hardcoded; it **measures** |

It never writes the anchor: **T0 is the manager's to write.** A script that self-anchored on
first run would peg T0 to *whenever someone happened to run it*.

## Deviations from Plan

**[Rule 1 - Bug]** My docstring promising *"THERE IS NO `--apply`, NO `--write`, NO `--fix`,
AND NO `--tolerance`"* tripped the very fences it was promising to satisfy — they matched bare
mentions. Detectors retargeted to the **mechanism** (`add_argument("--flag")`; import-of-backfill
**and** an apply mechanism). Strictly **more** precise, not weaker; case 13's self-test still
proves they fire. Same reasoning as 20-05's docstring fix.

## THE SCRIPT WAS NOT RUN AGAINST PROD

No `DATABASE_URL` is configured in this environment. The prod run — read-only, under
`AIPW_DB_READONLY=1` — is **20-07's**, behind its credentials gate.

## Self-Check: PASSED
- `scripts/e2e_verify.py` — FOUND, `--help` exits 0
- `tests/test_e2e_verify_fences.py` + `tests/test_phase19_fences.py` — **ALL GREEN (20/20)**
- Full suite: **541 passed, 29 skipped, 0 failed**
