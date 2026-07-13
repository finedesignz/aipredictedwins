---
phase: 16
plan: 03
subsystem: dashboard-api
tags: [UNIV-03, route, read-only]
requires: [src.effective_universe.resolve_universe, src.bot_config.BotConfig, src.universe.normalize]
provides: ["GET /api/bots/{bot_id}/universe", "models.BotUniverse", "models.BlockedSymbol"]
affects: [dashboard/web/components/bots/UniversePanel.tsx]
tech-stack:
  added: []
  patterns: [envelope-response, function-local-src-import, count-filter-aggregate]
key-files:
  created: []
  modified: [dashboard/api/models.py, dashboard/api/routes/bots.py]
decisions:
  - "src.* imports are FUNCTION-LOCAL (house style, main.py:61) — main.py untouched"
  - "Exposure query runs in its OWN get_db() block so a failed ::timestamptz cast cannot poison the row-fetch transaction (a psycopg tx in error state fails on commit)"
  - "Exposure failure -> exposure_loaded=false on the wire; never a silent empty leak list"
metrics:
  duration: ~20m
  completed: 2026-07-12
---

# Phase 16 Plan 03: Universe Route Summary

`GET /api/bots/{bot_id}/universe` — authenticated (inherited `Depends(verify_token)` from the router mount), documented (`/openapi.json`), read-only. Two SELECTs, no writes, no Alpaca client, no BotManager.

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1-2 | BlockedSymbol/BotUniverse models + handler & exposure query | `6384cdb` | dashboard/api/models.py, dashboard/api/routes/bots.py |

## MANDATORY EVIDENCE (W3) — real TEST_DATABASE_URL run

Local Postgres 17 (portable EDB binaries, `127.0.0.1:5433`, DB `aipw_test`, schema from `src/db_schema.sql` + all 18 migrations). **Not the prod DB.**

```
$ export TEST_DATABASE_URL="postgresql://postgres@127.0.0.1:5433/aipw_test"
$ python -m pytest tests/test_effective_universe.py -q
19 passed, 1 warning in 0.84s
```

**0 skipped.** All 19 test functions = the 18 numbered VALIDATION cases + case 11b. The exposure SQL (including the `"timestamp"::timestamptz` cast) was actually executed.

Live route smoke against the local stack:

```
$ curl -s localhost:8000/api/bots/UNIVLEAK/universe
{'effective': ['BTC/USD', 'SOL/USD', 'XRP/USD'], 'leak': ['TRUMP/USD'],
 'shadow_applied': True, 'shadow_sets_loaded': True, 'exposure_loaded': True}
```

Other gates:
- `grep -c "^from src\|^import src" dashboard/api/routes/bots.py` → **0** (no module-level src import).
- `git diff --stat dashboard/api/main.py` → **empty**.
- Case 16 static source guard: no INSERT/UPDATE/DELETE/AlpacaClient in the handler body; row counts unchanged across the call.
- Case 15: unknown bot_id → 404 naming the bot.
- Case 17: `/api/bots/{bot_id}/universe` present in `/openapi.json` with a `get` operation.

## Deviations from Plan

**1. [Rule 1 - Bug] Exposure query moved to its own connection block**
- **Found during:** Task 2
- **Issue:** the plan placed the exposure query inside the same `with get_db() as conn:` block as the row fetch. If the `::timestamptz` cast fails, the psycopg transaction enters an error state; swallowing the exception then leaves the pooled connection to raise on commit at block exit — turning the degraded-but-honest path into a 500.
- **Fix:** the exposure query gets its own `with get_db()` block inside the `try`, so a failure exits the context manager via the exception path (rollback) and is caught cleanly → `exposure_loaded=False`.
- **Files modified:** dashboard/api/routes/bots.py
- **Commit:** `6384cdb`

**2. [Rule 3 - Blocking] Test fixture seed columns**
- `bots.id` (NOT NULL PK) and `alpaca_trades.mirofish_prob` (NOT NULL) had to be seeded. Test-only change; no schema/migration change.

## Prod safety

Zero writes to the production database. Zero calls to the deployed dashboard. All SQL ran against the local `aipw_test` DB.

## Self-Check: PASSED
- dashboard/api/models.py (BotUniverse, BlockedSymbol) — FOUND
- dashboard/api/routes/bots.py (`/bots/{bot_id}/universe`) — FOUND
- Commit 6384cdb — FOUND
