---
phase: 19-reliable-runtime
plan: 06
subsystem: dashboard
tags: [run-01, run-02, visibility]
requires: [19-04, 19-05]
provides: [pnl_source, stale, reconciled, manager_alive, alerts_configured, alerts_last_error]
key-files:
  modified:
    - dashboard/api/models.py
    - dashboard/api/routes/portfolio.py
    - dashboard/api/routes/settings.py
    - dashboard/web/types/index.ts
    - dashboard/web/app/page.tsx
    - dashboard/web/app/settings/page.tsx
    - dashboard/web/components/settings/BotStatus.tsx
metrics:
  commit: 84b2557
---

# Phase 19 Plan 06: Make It Visible Summary

## The headline is the reconciled number, and says so when it isn't

`017_reconciliation.sql`'s header said *"Consumed by the dashboard headline in Phase 19."*
Nothing consumed it. Worse, `portfolio.py:111-122` fell back from the live Alpaca figure to
the raw trade-log sum **silently, with no flag on the response** — nobody could tell which
number they were looking at.

Three branches, `pnl_source` set on **every** one:

| Branch | `pnl_source` | `total_pnl` |
|--------|--------------|-------------|
| reconciliation row present | `"reconciled"` | `row.alpaca_realized_pnl + live unrealized` |
| no row, Alpaca reachable | `"alpaca_live"` | `equity - starting_equity` |
| no row, Alpaca unreachable | `"trade_log"` | `closed_pnl` (RESOLVED-only, from 19-04) |

`stale = (no row) OR (now - checked_at) > 2 * RECONCILE_INTERVAL_HOURS` — the same env var the
watchdog uses. The number is still SHOWN when stale, but FLAGGED. The `reconciled` dict
(`alpaca_realized_pnl`, `trade_log_pnl`, `delta`, `within_tolerance`, `checked_at`) rides along
so the frontend can render the out-of-tolerance breach.

The P&L math is not re-derived — it reuses the reconciler's stored `alpaca_realized_pnl`.
`_fetch_alpaca_account`'s 8s timeout and `{}`-on-failure contract are unchanged.

## Every new default is PESSIMISTIC

```
$ python -c "... p=PortfolioData(); h=HealthStatus(); print(...)"
trade_log True 0 None False False None
```

`pnl_source="trade_log"`, `stale=True`, `unresolved=0`, `reconciled=None`,
`manager_alive=False`, `alerts_configured=False`, `alerts_last_error=None`. **A missing signal
never reads as "reconciled and fresh".**

## The health surface — absence is the signal

`manager_alive = heartbeat_is_fresh(hb["beat_at"]) if hb else False`. The `else False` is
load-bearing (research N10): `self._watchdog.start()` (bot_manager.py:79) sits AFTER the
`start_all` query that can throw (`:67-70`), so the watchdog cannot report its own
non-existence. `grep -n "manager_alive = True" dashboard/api/routes/settings.py` → nothing.
There is no unconditional healthy path.

`alerts_configured` / `alerts_last_error` come from a **FUNCTION-LOCAL**
`from src.notifier import ...` inside a `try/except` that falls back to `(False, None)` — the
pessimistic value. No dashboard route imports `src.*` today, so a module-level import that
failed would take the whole route module down at startup. This does **not** violate 19-04's
fence, which is specifically **no `src.db` import** (no second connection pool):
`grep -nE "^from src\.db|from src import db" dashboard/api/routes/settings.py` → nothing.

The existing `running` flag is left alone — it answers a different question ("does the manager
think a thread is alive"); `manager_alive` answers "is the manager alive AT ALL".

## Rendered, not just returned (research N8)

TS silently drops unknown JSON keys, so these fields were **invisible** until the interfaces
AND the components were extended.

- `types/index.ts` — `Portfolio += unresolved / pnl_source / stale / reconciled`;
  `BotSettings += unresolved` and six `health.*` fields; new `Reconciliation` interface.
- `app/page.tsx` — a `PnlSourceBadge` beside the headline: **Reconciled** (green only when
  reconciled AND not stale) / **Alpaca live** / **Trade log**, plus a red **STALE** badge and a
  red **RECONCILIATION BREACH** badge when `within_tolerance === false` (ROADMAP criterion 3).
  `unresolved` is shown beside W/L and is **never labelled a loss**.
- `app/settings/page.tsx` — hard-red alarms: **BotManager NOT RUNNING**, **Alerts are NOT
  configured** ("this system cannot tell you when it breaks"), **The last alert FAILED to
  send** (with the swallowed exception string).
- `components/settings/BotStatus.tsx` — `BotManager` health indicator with
  `bots_alive/bots_enabled`, an `Alerts` indicator, and an unresolved-trades note under the
  paper-gate progress bars.

`npx tsc --noEmit` → clean. `npm run build` → succeeds. `git diff --stat dashboard/web/package.json`
→ **EMPTY** (no new dependency). No `EventSource`, no `WebSocket`, no new poll loop.

## Deviations from Plan

**1. Per-bot `status_detail` is NOT rendered in `BotStatus.tsx`.** `SettingsData` carries no
per-bot status/status_detail, and the plan's own model spec added only `unresolved` to it.
Inventing a payload field the plan did not specify is scope the phase did not authorize
(Karpathy: smallest diff). A misconfigured bot is still loudly visible three ways: the
`alert_bot_misconfigured` email, the `bots_alive/bots_enabled` mismatch on the health panel,
and `bots.status='error'` + `status_detail='missing alpaca keys'` on the existing `/api/bots`
surface. **Flagged for the verifier** as the one acceptance criterion not literally met.

**2. Browser screenshot evidence NOT captured.** The three states (reconciled badge / stale
warning / `manager_alive=false`) require a live Postgres. `TEST_DATABASE_URL` is unset and the
**prod DB is off-limits for this phase** (no writes, hard constraint). Standing up a throwaway
Postgres and seeding it was judged out of scope against that constraint. Evidence captured
instead: `npx tsc --noEmit` clean, `npm run build` succeeds, and the full API contract is
proven by the green behavioral+static tests. **This is a known gap for the verifier** — the
render paths are type-checked and build-verified but not visually confirmed.

## Self-Check: PASSED
