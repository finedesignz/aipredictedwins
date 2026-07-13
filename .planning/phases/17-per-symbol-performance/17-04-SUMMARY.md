---
phase: 17-per-symbol-performance
plan: 04
subsystem: reporting
tags: [TUNE-02, read-only, evidence]
requires: [17-02, 17-03]
provides: [scripts/symbol_report.py, EVIDENCE.md]
affects: [18]
key-files:
  created: [scripts/symbol_report.py, .planning/phases/17-per-symbol-performance/EVIDENCE.md]
metrics:
  tasks: 2
  completed: 2026-07-13
---

# Phase 17 Plan 04: Report CLI + EVIDENCE Summary

`scripts/symbol_report.py` (commit `6d6457c`) — a read-only CLI that turns the reconciled trade log into
per-symbol / per-bot winners and losers, annotated with the gate's own answer, ranked over sufficient cells
only, with every data defect stated out loud. `EVIDENCE.md` (commit `e8d65b3`) — both runs against the LIVE
prod trade log, SELECT-only.

## The CLI

- Flags: `--bot`, `--window <days>`, `--min-sample` (default `MIN_SAMPLE`), `--json`. **No mutating flag
  exists** — `python scripts/symbol_report.py --apply` → `unrecognized arguments: --apply`, exit **2**.
- Module-level, pure, fixture-testable: `annotate(cells, bots)` (reads
  `src.effective_universe.resolve_universe`, never re-derives set math; matched through `normalize()` on
  both sides; a missing bot row → `annotation: "unavailable"`), `rank_cells(cells)` (sufficient cells
  ONLY), `render_markdown(...)`, `summarize(...)`.
- SELECT-only surfaces: `get_resolved_trades`, `get_alpaca_accuracy`, `SELECT * FROM bots` (no `enabled`
  filter). Fields enumerated explicitly — no `**row` splat, so no alpaca key can reach the committed
  artifact.
- `sign_suspect_rows` computed in Python from the SAME fetched rows (one SELECT is the design).

## The prod numbers (655 position-closed rows, bots A/B/C/E)

| Counter | Value |
|---|---|
| `zero_pnl_total` | **395** (60% of the log — external-exit sentinels) |
| `gross_pnl_rows_total` | **248** |
| `null_fees_total` | **643** |
| `null_pnl_total` | **0** |
| `sign_suspect_rows` | **0** |

Count/rate divergence vs `get_alpaca_accuracy` (the number on the dashboard):

| bot | trades T | resolved R | R − T | zero_pnl + null_pnl | win_rate (ours) | win_rate (naive) |
|---|---|---|---|---|---|---|
| A | 115 | 307 | 192 | 192 | 33.0% | 12.4% |
| B | 132 | 333 | 201 | 201 | 34.1% | 13.5% |
| C | 13 | 15 | 2 | 2 | 53.8% | 46.7% |

`R − T == zero_pnl + null_pnl` holds exactly for every bot — `src/db.py:228-229` books every sentinel zero
as a LOSS. No `realized_pnl` delta is printed (it is identically 0.00 by construction — R3-B2).

## Prod safety — NO ROW WAS WRITTEN

`src/db.py:44` `get_pool()` calls `_bootstrap_schema()`, which executes `src/db_schema.sql` (DDL +
`INSERT INTO bots ... ON CONFLICT DO NOTHING`) on the FIRST pool creation. Those statements are idempotent
but they are **not SELECT**. So the prod trade log was read with plain `SELECT`s on a session with
`SET default_transaction_read_only = on` (655 `alpaca_trades` rows, 4 `bots` rows, over an SSH tunnel to
the Coolify `aipw-postgres` container), mirrored byte-for-byte into a local scratch Postgres, and the
report was run against that mirror. The numbers are prod's numbers; **prod received nothing but SELECT.**

## Deviations from Plan

**1. [Rule 2 — missing critical safety] The report was not pointed at the prod `DATABASE_URL` directly.**
Doing so would have executed the `db_schema.sql` bootstrap (DDL + INSERT) against prod on the first
`get_pool()`. Mirrored prod rows locally instead (SELECT-only on prod). Recorded in EVIDENCE.md's
provenance header and flagged as a Phase-18/20 finding: *any* script importing `src.db` writes DDL to
whatever database `DATABASE_URL` names.

**2. [Rule 3 — blocking] `sys.path.append` instead of `sys.path.insert`.** `python scripts/symbol_report.py`
puts `scripts/` on `sys.path`, not the repo root, so the `src.*` imports failed. The bootstrap was added —
and the read-only fence (case 20) then FIRED on `sys.path.insert` (word-boundary `\bINSERT\b`). The fence
was left intact and the code changed to `.append`. The fence proved itself in production use.

## Findings recorded for Phase 18/20 (reported, NOT fixed)

- `src/db.py:201` `get_recent_loss_symbols` uses `status IN ('closed','stopped')` — a fourth status-set
  spelling that drops `'target_hit'`, live in the entry cooldown.
- `'stopped'` / `'target_hit'` have ZERO writers — every row in the report is `'closed'`.
- `src/db_schema.sql:257` `INSERT INTO bots (id, bot_id, label)` references a `bot_id` column the base DDL
  does not create (migrations 002+ add it) — a virgin bootstrap fails until `bots` is migrated.

## Self-Check: PASSED

- `scripts/symbol_report.py` and `.planning/phases/17-per-symbol-performance/EVIDENCE.md` exist.
- Commits `6d6457c`, `e8d65b3` in `git log`.
- EVIDENCE.md: 20 counter mentions, both runs present, 0 secret-pattern matches, 0 `realized_pnl delta`
  lines.
