---
phase: 17-per-symbol-performance
plan: 02
subsystem: data
tags: [TUNE-02, read-only, sql]
requires: [17-01]
provides: [src.db.get_resolved_trades]
affects: [17-04]
key-files:
  modified: [src/db.py]
metrics:
  tasks: 1
  lines_added: 43
  lines_deleted: 0
  completed: 2026-07-13
---

# Phase 17 Plan 02: get_resolved_trades Summary

One read-only parameterized SELECT over `alpaca_trades` — the only query Phase 17 is allowed to run.

## What landed

`src/db.py::get_resolved_trades(bot_id=None, since=None) -> list[dict]` (commit `0fec1e2`):

- `WHERE status IN ('closed', 'stopped', 'target_hit')` — the literal from `src/db.py:215`, so a Phase-15
  gate block (`rejected`, `pnl=0`, `src/bot_thread.py:309`) can never enter the sample.
- `AND "timestamp"::timestamptz >= %s` and `ORDER BY "timestamp"::timestamptz ASC` — the TEXT column
  (`db_schema.sql:28`) is cast in BOTH the filter and the sort; a bare compare/sort would be lexicographic.
- `bot_id` / `since` reach SQL only as `%s` params.
- `pnl` and `fees` returned AS-IS: no `or 0.0`, no COALESCE, no `pnl <> 0` clause. A sentinel `0.0` and a
  NULL both survive intact so Plan 03 can COUNT them instead of absorbing them.
- Returns `conn.execute(...).fetchall()` — `dict_row` (`src/db.py:29`) already yields dicts.

## Byte-identical guarantee

`git diff --numstat src/db.py` → **43 added, 0 deleted**. `get_alpaca_accuracy`, `get_realized_pnl`,
`get_recent_loss_symbols` and `update_alpaca_trade` are untouched; their coercions and the fourth
status-set spelling are REPORTED findings for Phase 18/20, not repaired here.
(`git diff src/db.py | grep -c "^-"` prints `1` — that single match is the `--- a/src/db.py` diff header,
not a removed line. The numstat is the authoritative deletion count: 0.)

## Verification

- Case 18 (real SQL, LOCAL Postgres `aipw_test17` on 127.0.0.1:55441): **1 passed**, key set exactly
  `{bot_id, symbol, asset_class, side, status, pnl, fees, entry_ts, closed_at}`; the seeded `rejected` row
  absent; the 200-day-old row excluded by `--window 90` and the fresh one kept; `bot_id="A"` filtered; the
  NULL-pnl row returned as `None`, not `0.0`.
- Case 19 (`test_window_cast_is_in_the_sql`): both the WHERE and the ORDER BY cast — green.
- `git diff src/db.py | grep -ciE "^\+.*\b(INSERT|UPDATE|DELETE|ALTER|DROP|TRUNCATE)\b"` → `0`.

## Deviations from Plan

None — plan executed exactly as written.

## Prod safety

No prod resource was written. All SQL evidence came from the local `aipw_test17` database.

## Self-Check: PASSED

- `src/db.py::get_resolved_trades` present; commit `0fec1e2` in `git log`.
