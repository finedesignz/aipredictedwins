---
phase: 19-reliable-runtime
plan: 02
subsystem: foundation
tags: [run-01, notifier, heartbeat, migration]
requires: [19-01]
provides: [runtime_heartbeat, alerts_configured, last_alert_error, alert_all_bots_down, alert_bot_misconfigured, alert_manager_never_started, get_heartbeat, heartbeat_is_fresh, is_resolved]
key-files:
  created:
    - dashboard/api/migrations/019_runtime_heartbeat.sql
  modified:
    - src/db_schema.sql
    - src/notifier.py
    - dashboard/api/db.py
    - src/db.py
metrics:
  commits: [63afa1c, d141a1d]
---

# Phase 19 Plan 02: Foundation Summary

The things that make both silent failures **visible**: the heartbeat table (in BOTH files),
the alert-path self-check, the swallowed-error recorder, and the absence-is-dead readers.

## What landed

**Migration 019 + the schema mirror (research N3).**
`dashboard/api/migrations/019_runtime_heartbeat.sql` creates
`runtime_heartbeat (component PK, beat_at, bots_alive, bots_enabled)`. The SAME block is
mirrored as **section 11** of `src/db_schema.sql`, immediately after section 10
(reconciliation) and before the INDEXES banner — because `src/db.py:61-66`'s
`_bootstrap_schema()` executes `db_schema.sql` **wholesale**, so a migration-only table is
absent from every fresh-DB bootstrap. Additive and idempotent: no UPDATE/DELETE/DROP/ALTER,
no reference to `alpaca_trades`.

**`src/notifier.py` — five new functions, no new provider.**
- `alerts_configured()` mirrors `_get_ses_client`'s resolution order (`:27-39`) **exactly**:
  secrets file first, else BOTH AWS env vars. No boto3 import, no SES call. A self-check that
  disagrees with the code that actually sends is worse than no check.
- `last_alert_error()` + a module-level `_last_error`. **Config presence != delivery.**
  `send_alert` swallows every exception (`:59-61`), so a valid-looking config still silently
  drops every alert on an unverified SES identity. `send_alert` now records the exception it
  swallows and clears it on success. Its contract is otherwise identical (never raises,
  returns bool).
- `alert_all_bots_down` (subject contains the literal `ALL BOTS DOWN`),
  `alert_bot_misconfigured` (never says died/dead — a keyless bot never lived; the detail is
  the literal `"missing alpaca keys"`), `alert_manager_never_started`.

**`dashboard/api/db.py` — absence is the signal (N10).**
`HEARTBEAT_STALE_SECONDS` (env, default 180 = three missed 60s ticks), `get_heartbeat(conn)`
returning **None** when there is no row (wrapped so a pre-migration dashboard does not 500),
and `heartbeat_is_fresh(beat_at, ...)` returning **False** when `beat_at is None`. Naive
datetimes are treated as UTC. No `src.*` import — no second connection pool.

**`src/db.py::is_resolved(pnl)`** — the one canonical predicate
(`pnl is not None and pnl != 0`), with `src/symbol_stats.py`'s `zero_pnl` bucket named as the
reference implementation. `get_alpaca_accuracy`'s arithmetic is untouched here (19-04 owns it).

## Verification

- Cases **10, 11, 12, 12b, 26, 27** GREEN (all previously RED). Case **29** GREEN.
- `python -c "from src.db import is_resolved; ..."` → `False False True`.
- `grep -nE "^from src|^import src" dashboard/api/db.py` → nothing.
- `git diff --stat` touched zero lines in `src/bot_manager.py`, `dashboard/api/routes/`, and
  `dashboard/web/`.

## Deviations from Plan

None — plan executed as written.

## Self-Check: PASSED
