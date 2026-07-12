---
phase: 15-universe-hard-gate
plan: 02
subsystem: config
tags: [universe, quarantine, migration, bot-config]
requires: [15-01]
provides: [src/universe.py, bots.quarantined_symbols, BotConfig.quarantined, BotConfig.all_symbols]
affects: [15-03]
tech-stack:
  added: []
  patterns: [pure predicate module, additive idempotent migration]
key-files:
  created: [src/universe.py, dashboard/api/migrations/018_universe_quarantine.sql]
  modified: [src/db_schema.sql, src/bot_config.py, dashboard/api/routes/bots.py, dashboard/api/models.py, dashboard/api/seed_bots.py]
decisions:
  - "entry_allowed checks quarantine BEFORE the allowlist; an EMPTY allowlist means no allowlist restriction (dynamic-universe safety net)"
  - "BotConfig.all_symbols = crypto UNION stock — the copytrade allowlist, so Bot E's cross-asset-class mirrors are not wrongly blocked"
  - "db_schema.sql bots block gains only the one column + a scope note; the stale CHECK (id IN ('A','B')) is left alone (out of scope, risks C/D/E)"
metrics:
  duration: ~12m
  completed: 2026-07-12
---

# Phase 15 Plan 02: Pure Gate + Quarantine Column Summary

Pure `src/universe.py` predicate plus the `bots.quarantined_symbols` column landed end-to-end
(DB → BotConfig → API), inert by default (`''` = nothing quarantined = zero behavior change).

## What Was Built

- **`src/universe.py`** — stdlib-only, zero-I/O, total: `normalize()` (uppercase, strip whitespace +
  slash; idempotent; `None`/`""` → `""`) and `entry_allowed(symbol, allowlist, quarantined)` →
  `(bool, reason)` with `reason ∈ {None, "off_universe", "quarantined"}`. Quarantine precedes the
  allowlist; an empty allowlist imposes no restriction.
- **`dashboard/api/migrations/018_universe_quarantine.sql`** — bare
  `ALTER TABLE bots ADD COLUMN IF NOT EXISTS quarantined_symbols TEXT DEFAULT '';`. Additive,
  idempotent, no constraint touched, no DROP/DELETE/TRUNCATE. Header documents the required
  `BTC/USD` format (a bare `BTC` will not match).
- **`src/db_schema.sql`** — mirrors the column + a note that this block is not a full mirror.
- **`src/bot_config.py`** — `quarantined_symbols: str = ""` field, `from_row` reader (missing key →
  `""` → `[]`, so a pre-migration DB fails safe), plus `quarantined` (flat, asset-class-agnostic
  deny-list) and `all_symbols` (crypto ∪ stock, deduped, order-stable) properties.
- **Column plumbing** — `_BOT_COLS` projection + POST INSERT (`routes/bots.py`), `BotFull`/`BotCreate`
  (`str = ""`) and `BotUpdate` (`Optional[str] = None`, so `""` clears and `None` leaves alone)
  in `models.py`, and `BOT_<X>_QUARANTINED` env + INSERT in `seed_bots.py`. The seed's existing-bot
  UPDATE branch is unchanged (key-patch only — widening would clobber live operator edits).

PUT needs no SQL change: `set_clauses` is built from non-None `BotUpdate` fields, so column names stay
Pydantic-derived and values stay bound params (no injection surface added).

## Deviations from Plan

None — plan executed as written.

## Commits

- `d8e28fb` feat(15-02): src/universe.py pure normalize + entry_allowed gate
- `01bf8bd` feat(15-02): migration 018 quarantine column + BotConfig quarantined/all_symbols
- `986fd69` feat(15-02): plumb quarantined_symbols through API + seed

## Verification

At the end of this plan the pure + bot_config cases were GREEN; only the Plan-03 wiring cases
remained RED. Full suite: 349 passed / 9 failed (all 9 in `tests/test_universe.py` wiring cases) /
5 skipped — zero regressions outside the new suite.

## Self-Check: PASSED
- `src/universe.py`, `dashboard/api/migrations/018_universe_quarantine.sql` exist
- commits `d8e28fb`, `01bf8bd`, `986fd69` present in `git log`
