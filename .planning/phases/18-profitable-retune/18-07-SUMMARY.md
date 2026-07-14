---
phase: 18-profitable-retune
plan: 07
subsystem: risk-config
tags: [kelly, risk-rules, rollout, quarantine, prod-write]
requires: [18-06]
provides: ["quarter-Kelly ceiling enforced on every write AND read path", "Bot B + Bot E risk-rule violations remediated in prod"]
affects: [dashboard/api/models.py, dashboard/api/seed_bots.py, src/bot_config.py]
tech-stack:
  added: []
  patterns: ["read-side clamp at the single choke point (BotConfig.from_row) — a ceiling that only guards writes leaves pre-existing rows out of bounds"]
key-files:
  created: []
  modified:
    - dashboard/api/models.py
    - dashboard/api/seed_bots.py
    - src/bot_config.py
    - tests/test_rollout_config.py
    - tests/test_bot_config.py
    - .planning/phases/18-profitable-retune/18-BACKTEST.md
decisions:
  - "Quarter-Kelly enforced on FOUR paths (PUT, POST, seed raw-SQL INSERT, and read), not three — the read-side clamp is what makes the ceiling total rather than perimeter-only."
  - "Bot E's max_position_pct=1.00 (100% of bankroll per position) brought to 0.05 — found during the mandatory pre-write baseline read, unrelated to the sweep."
  - "The quarantine was NOT applied: the deployed dashboard container predates 986fd69 and its BotUpdate model has no quarantined_symbols field. Blocked on a redeploy, which this plan forbids."
metrics:
  duration: ~25m
  completed: 2026-07-13
---

# Phase 18 Plan 07: Rollout — Kelly Ceiling + Prod Config Write Summary

Closed all four Kelly paths (quarter-Kelly is now a total ceiling, not a perimeter), and remediated
two live risk-rule violations in prod as a `bots` row update — but the quarantine could not be
written, because the deployed container is stale.

## What shipped

### Part 1 — code (commit `a918536`)

Quarter-Kelly (0.25) is a hardcoded CLAUDE.md risk rule, but only the CLI enforced it. Four paths
could still put a bot above the ceiling; all four are now closed:

| Path | Hole | Fix |
|------|------|-----|
| `PUT /api/bots/{id}` | `BotUpdate.kelly_fraction` unbounded | `Field(gt=0, le=0.25)` |
| `POST /api/bots` | `BotCreate` / `BotFull` unbounded — could CREATE a bot at 0.50 | `Field(gt=0, le=0.25)` |
| `seed_bots.build_bots()` | **defaulted `BOT_B_KELLY` to "0.50"**, written by a raw SQL INSERT that bypasses pydantic entirely | default → `"0.25"` AND `min(..., 0.25)` clamp |
| `BotConfig.from_row` | **the READ side had no ceiling** — Bot B's live 0.50 row kept sizing at half-Kelly | `min(..., 0.25)` at the single choke point every bot reads through |

The read-side clamp is the load-bearing one. The three write-side bounds only protect rows written
*after* this phase; Bot B's row was seeded before any bound existed. Without the read clamp the bot
would have kept sizing at 0.50 until the rollout PUT landed.

`dashboard/api/routes/bots.py` is untouched — its dynamic SET + `mgr.update()` hot-swap is exactly
the mechanism TUNE-03 depends on and it needed no change.

### Part 2 — the prod write

Baseline read FIRST (`GET /api/bots`), recorded verbatim in 18-BACKTEST.md. Then one PUT per bot.
No deploy, no restart, no migration, no DDL. Sentinel rows untouched. Bots remain PAPER-gated.

| bot | strategy | field | before | after |
|-----|----------|-------|--------|-------|
| B | confluence | `kelly_fraction` | **0.50** | **0.25** |
| B | confluence | `max_position_pct` | **0.10** | **0.05** |
| E | copytrade | `max_position_pct` | **1.00** | **0.05** |

`min_confluence` unchanged everywhere (criterion 2 never discriminated). `kelly_fraction` unchanged
on every bot already `<= 0.25`. Verified by re-reading `GET /api/bots`: **CEILING HOLDS**
(no bot > 0.25 Kelly), **MAXPOS HOLDS** (no bot > 0.05), nothing else changed.

## Deviations from Plan

**1. [Rule 2 — missing critical functionality] Bot E was at `max_position_pct = 1.00`**
- **Found during:** the mandatory pre-write baseline read.
- **Issue:** Bot E (`copytrade`) was configured to put **100% of bankroll into a single position** —
  a 20x breach of the hardcoded "max 5% bankroll per position" rule. Unrelated to the Phase-18 sweep;
  nobody was looking for it. Bot E is `enabled=false`, so nothing was sized off it, but the row was
  one toggle away from a catastrophic position.
- **Fix:** brought to 0.05 in the same rollout, per the "if any OTHER bot is above the limit, bring it
  down too" instruction. Recorded with a revert curl.

**2. [Rule 1 — bug] Two tests encoded the behavior being removed**
- `tests/test_bot_config.py::test_from_row_custom` asserted `kelly_fraction == 0.5` passes through
  `from_row` as-is. That is precisely the hole the read-side clamp closes, so the test now uses an
  in-bounds `0.20`. Clamp coverage lives in case 28d.
- `tests/test_rollout_config.py` case 28c called `build_bots()` without `ALPACA_API_KEY_B` set, so
  Bot B was never emitted and the test died on `IndexError` rather than on its assertion. Masked while
  the case was `xfail`. Fixed by monkeypatching fake keys (`build_bots` is pure — it writes nothing).

**3. The 4 `xfail(strict)` markers were removed**, as required — a strict xfail that starts passing
fails the suite.

## BLOCKER — the quarantine did not apply

`PUT /api/bots/A` with `{"quarantined_symbols": "..."}` returned **422 `{"detail":"No fields to
update"}`**. Decisive: the **deployed** `BotUpdate` has no `quarantined_symbols` field, so pydantic
dropped the only key in the payload and the SET clause came out empty. The same key was therefore
silently dropped from Bot B's PUT (which returned 200 only because its kelly/max_position keys are
valid on the old model). `GET /api/bots` confirms `quarantined_symbols` is still `null` on all bots.

The column exists (migration 018 ran — the key is present-and-null in the GET), but the running
container predates **986fd69 `feat(15-02): plumb quarantined_symbols through API + seed`**. Coolify
reports `git_branch=main, git_commit_sha=HEAD, status=running:healthy` — the image is just stale.

**Applying the quarantine requires redeploying the dashboard service.** Plan 18-07 explicitly forbids
a deploy/restart, so it was not done. The exact post-redeploy PUT is recorded in 18-BACKTEST.md.
A redeploy also picks up this plan's `le=0.25` bounds.

## Environment notes

- Cloudflare returns **error 1010** to a default `python-urllib`/curl User-Agent — a browser UA is
  required to reach the origin at all. Unauthenticated requests then return 401.
- `curl` in this Git-Bash shell is broken (`libcurl function was given a bad argument`); all HTTP was
  done via Python `urllib`.
- `DASHBOARD_TOKEN` was read from the dashboard service's Coolify env in-memory. It is not written to
  any file in this repo.

## Known Stubs

None.

## Self-Check: PASSED

- `dashboard/api/models.py`, `dashboard/api/seed_bots.py`, `src/bot_config.py` — modified, committed in `a918536`.
- `python -m pytest tests/ dashboard/api/tests/ -q` → **428 passed, 28 skipped, 0 xfailed** (baseline was 424/28/4).
- `POST /api/bots` with `kelly_fraction: 0.50` → **422**. `PUT` with 0.50 → **422**. Both → 200 at 0.25.
- `GET /api/bots` re-read post-write: CEILING HOLDS, MAXPOS HOLDS.
