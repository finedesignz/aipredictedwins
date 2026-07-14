# Phase 19: Reliable Runtime & Honest Monitoring — Research

**Researched:** 2026-07-13
**Domain:** In-process supervision (threading watchdog), liveness/heartbeat, alert-path integrity, P&L reconciliation surfacing
**Confidence:** HIGH (every claim below is read at `file:line` in this repo; no library speculation)

## Summary

Phase 19 is **not a build phase — it is a repair phase**. Every mechanism RUN-01 and RUN-02 need
already exists in the tree: a 60s watchdog thread (`bot_manager.py:58-62,85-95`), a revive path
(`:101-119`), a death alerter (`:121-139`), a silence alerter (`:145-212`), an SES notifier
(`src/notifier.py`), and a cent-exact reconciler (`src/reconciliation.py`). None of it is wrong.
All of it is **unreachable in the exact state we are in**. The work is deleting three guards, adding
one table, and making four readers agree on what a resolved trade is.

The single most important line in the phase is `bot_manager.py:189-190`. **CONFIRMED, verbatim:**

```python
        if not any_alive:
            return  # bots are down; death alert handles that separately
```

The trade-silence alert — the only alert that fires on "nothing is happening" — **disables itself
precisely when nothing is happening for the worst possible reason.** It defers to a death alert that
cannot fire, because the death alert only iterates rows the key filter (`:104-107`) already removed.
All-bots-down is the one state guaranteed to be silent. That is the outage, and it is a two-line delete.

Beyond confirming CONTEXT, this research **refutes one CONTEXT claim** (there are *two* status-writer
classes, not one — Bot E's `CopyTraderThread` is the second) and surfaces **five landmines** the
CONTEXT does not mention, of which two will break the phase if the planner does not plan around them:
`reconcile()` has no per-bot exception guard and will abort wholesale on the very keyless bot the B1
fix makes visible (N1); and the watchdog thread is started *inside* `start_all()` **after** the query
that can throw, so a heartbeat written by the watchdog cannot report "the manager never started" (N10)
— absence-of-row must be the signal, and the never-started alert must be fired from `main.py`'s
`except`, not from the manager.

**Primary recommendation:** Delete `bot_manager.py:189-190` and the two key predicates; branch keyless
bots to `status='error'` + a *misconfiguration* alert (not the death alert, which spawns); add
`runtime_heartbeat` (migration `019`, **plus** a `db_schema.sql` block); wrap `reconcile()` per-bot
before scheduling it hourly in the watchdog; define `RESOLVED := pnl IS NOT NULL AND pnl <> 0` once and
apply it at all four reader sites. Touch no trade data.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Thread liveness + revive | In-process watchdog (`BotManager`) | — | Only the process that owns the threads can see `Thread.is_alive()`. A container restart policy cannot: the process is *up*, the threads are dead (N4). |
| All-bots-down detection | In-process watchdog | Heartbeat row (external read) | Watchdog knows `is_alive()`; heartbeat lets the *outside* see it. |
| Manager-never-started detection | **Heartbeat absence** (DB) + `main.py` `except` | — | The watchdog cannot report its own non-existence (N10). Absence-of-row is the signal. |
| Alert delivery | `src/notifier.py` (boto3 SES) | — | Locked. No new provider. |
| Alert-path integrity | `BotManager` startup self-check | `HealthStatus.alerts_configured` | `send_alert` swallows (`notifier.py:59-61`) — a config check is the only way to know it *could* send. |
| Reconciliation compute | `src/reconciliation.py` (pure `reconcile_bot`) | — | Already cent-exact and API-free (`:16-42`). Do not touch. |
| Reconciliation scheduling | Watchdog loop (interval-guarded) | — | The supervisor already ticks. No cron, no new container. |
| Headline P&L / win rate | `portfolio.py` + `settings.py` readers | `reconciliation` table | Read the reconciled number; flag when stale. |
| RESOLVED predicate | `src/db.py` (canonical) | 3 call sites import/mirror it | One definition, four sites (`symbol_stats.py` is the reference impl). |

## Verification of CONTEXT Claims

Every claim in the dispatch brief, checked at `file:line`. **One is refuted.**

| # | CONTEXT claim | Verdict | Evidence |
|---|---|---|---|
| C1 | `bots.status` written **ONLY** by `BotThread._set_status` | **REFUTED (partially)** | See below. |
| C2 | `main.py:65-66` swallows `start_all()`; missing `DATABASE_URL` skips construction | **CONFIRMED** | `main.py:55` `if db_url:` gates the whole block; `:65-66` `except Exception as exc: _log.warning("BotManager unavailable: %s", exc)`. `manager` stays `None`, `:67` sets it on app state, app serves read-only. |
| C3 | `bot_manager.py:67-70` and `:104-107` share the key filter | **CONFIRMED** | Byte-identical predicate at both: `"SELECT * FROM bots WHERE enabled = TRUE " "AND alpaca_api_key IS NOT NULL AND alpaca_api_key != ''"`. A keyless-but-enabled bot is in neither result set → never spawned, never revived, never alerted. |
| C4 | **THE KILLER** — `:187-190` `if not any_alive: return` before the silence alert | **CONFIRMED** | `:186-190`. Exact text quoted in Summary. Guarantees all-bots-down is silent. |
| C5 | `notifier.py` is boto3 SES behind an `alerts@emails4agents.com` sender; `send_alert` swallows ALL failures | **CONFIRMED** | `:17` `SENDER = "alerts@emails4agents.com"`; `:22-39` `_get_ses_client()` → `boto3.client("ses", ...)`; `:47-61` try/except returning `False` on *any* exception. A misconfigured SES = a system that believes it is alerting and is not. |
| C6 | `settings.py:65` hardcodes `100_000.0 * len(bot_ids)` | **CONFIRMED** | `equity = 100_000.0 * len(bot_ids) + total_pnl`, where `total_pnl` (`:63`) is a pure trade-log sum. This feeds the paper-gate readout (`:139-140`). |
| C7 | Post-Phase-18 readers still count `pnl = 0.0` as LOSSES | **CONFIRMED at all 4 sites** | See table below. `db.py:228`'s own comment admits it: *"A genuine 0.00 close is still counted — only NULL is excluded."* |

### C1 — the refutation (planner must act on this)

CONTEXT says `bots.status` is written **only** by `BotThread._set_status`. **There are two writer
classes.** `CopyTraderThread` — which is what **Bot E** runs — has its own identical `_set_status`:

- `src/bot_thread.py:240-244` → `_set_status` → `"running"` `:398`, `"error"` `:404`, `"stopped"` `:407`
- **`src/copytrade_thread.py:140-144`** → `_set_status` → **`"running"` `:429`, `"error"` `:434`, `"stopped"` `:436`**
- Dispatch: `bot_manager._spawn` (`:287-292`) branches on `cfg.strategy == "copytrade"` → `CopyTraderThread`, else `BotThread`. Both are handed `on_status_change=self._on_status_change`.

**What survives:** the *sole SQL writer* of `bots.status` is `BotManager._on_status_change`
(`bot_manager.py:299-309`, `UPDATE` at `:304`) — both thread classes funnel through it. Independently
confirmed there is no other path: `dashboard/api/routes/bots.py:197` builds its `UPDATE` from
`BotUpdate` (`models.py:256-272`), which **has no `status` field**; `seed_bots.py:167-176` patches only
`alpaca_api_key`/`alpaca_secret_key`. So the *DB write* is single-pathed, but the *callers* are two.

**Planning consequence:** any keyless-bot → `status='error'` fix must go through `_on_status_change`
(bot-class-agnostic), and any watchdog change must not assume every enabled bot is a `BotThread`. Bot E
is `enabled: false` today, so it is not a live hazard — but a copytrade bot re-enabled after this phase
would otherwise hit an untested branch.

### C7 — the four reader sites, verbatim

| # | Site | Code | Effect on a `pnl = 0.0` row |
|---|---|---|---|
| 1 | `dashboard/api/routes/portfolio.py:76-80` | `wins = sum(1 for r in closed if (r["pnl"] or 0) > 0)` … `losses = len(closed) - wins` | `0.0 > 0` → False → **booked as a LOSS**; also inflates `resolved` denominator |
| 2 | `dashboard/api/routes/settings.py:62-64` | `wins = sum(... (r["pnl"] or 0) > 0)`; `resolved = len(closed_rows)` | Same — and this **is the paper-gate readout** |
| 3 | `src/db.py:244-246` (`get_alpaca_accuracy`) | `losses = resolved - wins` | Same. Comment at `:228` states the behavior is intentional-for-NULL and blind-to-zero |
| 4 | `dashboard/api/routes/portfolio.py:93-101` (daily P&L) | `sum(r["pnl"] or 0.0 …)`, **no `pnl IS NOT NULL` filter at all** | Harmless to the *sum* (zeros add zero) but it is a 5th site and inconsistent — see N7 |

`src/symbol_stats.py` is the **reference implementation**: it buckets `pnl == 0` into `zero_pnl` and
never counts it as a trade. The dashboard is being brought into line with it, not the reverse.

The Phase-18 `AND pnl IS NOT NULL` filter (`portfolio.py:70`, `settings.py:43`, `db.py:232`) is correct
for the **post-fix NULL channel** and does nothing for the 395 historical `0.0` rows, which pass it.

## Standard Stack

**No new dependencies. Zero installs. This phase adds no packages.**

Everything needed is already imported somewhere in the tree:

| Capability | Existing module | Location | Notes |
|---|---|---|---|
| Supervision | `threading` (stdlib) | `bot_manager.py:6,58-62` | `Thread(daemon=True)` + `Event.wait()` |
| DB pool | `psycopg_pool.ConnectionPool` | `bot_manager.py:8,45-51` | Manager owns its own pool |
| DB (src side) | `psycopg` via `src.db.connection()` | `db.py:70-73` | Reconciler uses this, **not** the manager's pool |
| Alerts | `boto3` SES | `notifier.py:22-39` | Locked. No new provider. |
| Reconciliation | `src.reconciliation` | `reconciliation.py:16-143` | Built Phase 13, scheduled by nobody |
| Migrations | `run_migrations.py` | `dashboard/api/migrations/` | `sorted(glob("*.sql"))`, tracked in `_migrations`, idempotent |

**Package Legitimacy Audit:** N/A — **this phase installs no external packages.** Nothing to slopcheck.

### Migration number — CONFIRMED

Highest existing migration is **`018_universe_quarantine.sql`**. **`019` is the next free number.**
(`009` is duplicated — `009_drop_bot_id_check.sql` and `009_tradingagents.sql` — a pre-existing wart;
`sorted()` handles it and `019` is unambiguous.)

**N3 — the trap:** `src/db_schema.sql:212-215` **mirrors** migration `017_reconciliation.sql` by hand
(*"Mirrors migration 017_reconciliation.sql"*). The schema file is the fresh-DB bootstrap path. A
`runtime_heartbeat` table added **only** as migration `019` will be missing from any DB created from
`db_schema.sql`. **Both files must be written.**

## Architecture Patterns

### System Architecture Diagram

```
                    FastAPI lifespan (dashboard/api/main.py:46-71)
                                    │
                    DATABASE_URL set? ──NO──► manager = None ──► read-only mode, SILENT  ◄── B3
                                    │                                (:55)
                                   YES
                                    │
                       BotManager(db_url) ──throws?──► except: log.warning ──► SILENT   ◄── B3
                                    │                     (:65-66)
                             start_all()  (bot_manager.py:64-83)
                                    │
              SELECT * FROM bots WHERE enabled = TRUE
                AND alpaca_api_key IS NOT NULL AND != ''      ◄── B1: keyless bot vanishes here
                                    │                              (:67-70)
                       ┌────────────┴────────────┐
                    0 rows                    N rows
                       │                         │
              "starting 0 bots"            _spawn each  (:274-297)
                       │                         │  strategy == 'copytrade' ? CopyTraderThread : BotThread
                       └────────────┬────────────┘
                                    │
                    self._watchdog.start()   (:79)  ◄── N10: only reached if the query above didn't throw
                                    │
        ┌───────────────────────────▼───────────────────────────┐
        │  _watchdog_loop  (:85-95)  — while not stopping.wait(60)│
        │                                                         │
        │   _revive_dead_bots (:101-119)                          │
        │      └─ same key filter (:104-107)  ◄── B1 again        │
        │      └─ thread dead? → _maybe_send_death_alert (:121)   │
        │                        → _spawn (revive)                │
        │                                                         │
        │   _check_trade_silence (:145-212)                       │
        │      └─ 1h self-throttle (:149-151)                     │
        │      └─ 24h window guard (:154)                         │
        │      └─ if not any_alive: return   ◄══ B2 — THE KILLER  │
        │                        (:189-190)                       │
        │                                                         │
        │   [PHASE 19 ADDS]                                       │
        │   _check_bots_down()     → alert_all_bots_down          │
        │   _heartbeat()           → UPSERT runtime_heartbeat     │
        │   _maybe_reconcile()     → reconciliation.reconcile()   │
        └─────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
              ┌───────────────────────────────────┐
              │ Postgres                          │
              │  bots.status ◄── _on_status_change│ (:299-309, sole SQL writer)
              │  reconciliation  (UPSERT, 017)    │
              │  runtime_heartbeat (NEW, 019)     │
              │  alpaca_trades ── READ ONLY ✋     │
              └───────────────┬───────────────────┘
                              │
          ┌───────────────────┴────────────────────┐
          ▼                                        ▼
  GET /api/portfolio                       GET /api/settings
   headline P&L, win rate                   paper gate, health
   + pnl_source, stale, unresolved          + manager_alive, alerts_configured
```

### Pattern 1: Interval-guarded steps inside one watchdog tick

The loop ticks every 60s (`:87`). Steps that must run less often self-throttle with a timestamp field —
`_check_trade_silence` already does exactly this (`:149-151`):

```python
# Source: src/bot_manager.py:147-151 (existing, verbatim)
now = time.time()
if now - self._last_silence_check < _SILENCE_CHECK_INTERVAL:
    return
self._last_silence_check = now
```

Reconciliation (hourly) follows this pattern with its own `self._last_reconcile`. **Do not add a second
thread or a scheduler.** Each new step gets its own `try/except` in `_watchdog_loop`, matching `:88-95`
— a step that raises must never kill the loop.

### Pattern 2: Absence-as-signal for the heartbeat (N10 — critical)

`self._watchdog.start()` is at `:79`, **after** the `start_all` query at `:67-70`. If that query throws
(bad `DATABASE_URL`, pool failure), `start_all` raises → caught at `main.py:65-66` → **the watchdog
never starts**. A heartbeat written *by the watchdog* therefore cannot report "the manager never
started."

This is fine **only if absence is the signal**:

```
manager_alive := heartbeat row EXISTS
              AND now() - beat_at < HEARTBEAT_STALE_SECONDS   (default 180)
```

No row ⇒ `manager_alive = false`. Stale row ⇒ `manager_alive = false`. The reader must **never**
default-to-healthy on a missing row. And the "manager never started" *alert* cannot come from the
manager — it must be fired from `main.py`'s `except` branch (`:65-66`) directly, which today only calls
`_log.warning`.

### Pattern 3: Keyless bot is `error`, not `dead`

Once the key predicate is dropped (B1 fix), a keyless enabled bot enters `_revive_dead_bots` with
`thread is None` → falls straight into `_maybe_send_death_alert` (`:114`) and then `_spawn` (`:117`).
That is **wrong twice**: the message says *"thread was found dead and is being restarted"* (it never
lived), and `_spawn` will construct a bot with no credentials every 60s forever.

The revive path must branch **before** the death alert:

```
for row in rows (enabled = TRUE):
    if not row["alpaca_api_key"]:
        _on_status_change(bot_id, "error", "missing alpaca keys")
        alert_bot_misconfigured(bot_id, ...)      # 1h cooldown, reuse _last_death_alert dict
        continue                                   # ← do NOT spawn, do NOT death-alert
    if thread is None or not thread.is_alive():
        ... existing death-alert + revive ...
```

### Anti-Patterns to Avoid

- **Relying on the container restart policy (N4).** It is a **red herring for this outage.** The
  container is *up* — the API is serving `/api/health` and the dashboard renders. Only the bot
  *threads* are dead/never-spawned. `restart: always` restarts a *process that exited*; it cannot
  observe a dead thread inside a live process. Verify and report the policy (CONTEXT decision 1), but
  do not let it appear anywhere in the fix's causal chain.
- **A second supervisor / sidecar / cron.** Locked out by CONTEXT decision 1, and correctly: each is a
  new thing that can silently die.
- **Backfilling the 395 sentinels.** `src/backfill.py` **already exists** (`:142-143`, driving
  `reconciliation._client_for_bot`). It is a loaded gun. Phase 19 does not pull the trigger. Read
  around the rows; never `UPDATE`.
- **Sharing one Alpaca client across bots when scheduling reconcile.** `_client_for_bot` (`:62-93`)
  enforces one account per bot. Keep it.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Restart dead bots | New supervisor/systemd/cron | `_revive_dead_bots` (`bot_manager.py:101-119`) | Already correct once B1's predicate is dropped |
| Send an alert | Any new provider/SDK | `src/notifier.py::send_alert` + a new typed wrapper | Locked. SES creds already resolve in-container |
| Compute reconciled P&L | New math | `reconciliation.reconcile_bot` (`:16-42`) | Pure, cent-exact, already tested (`tests/test_reconciliation.py`) |
| Persist reconciliation | New table/writer | `db.record_reconciliation` (`db.py:334-356`) + table `017` | UPSERT, one row per bot, exists |
| Starting equity | `100_000.0 * len(bots)` | `db.get_starting_equity` (`db.py:322-331`) | Reads `bots.starting_equity`; falls back to 100000 **only** on a missing row |
| Zero-P&L bucketing | New predicate | Mirror `src/symbol_stats.py` | Phase 17 already solved this correctly |
| Periodic work | `schedule`/APScheduler/celery | The existing watchdog tick + a timestamp guard | `_check_trade_silence:149-151` is the pattern |

**Key insight:** the only thing this phase *creates* is one table and three small functions. Everything
else is a **deletion** (two predicates, one `return`, one hardcoded constant). The bug surface is in
what the code refuses to look at, not in what it lacks.

## Runtime State Inventory

Not a rename/refactor phase — but it **does** change live runtime behavior and adds a table, so the
equivalent audit:

| Category | Items Found | Action Required |
|---|---|---|
| Stored data | `bots.status`/`status_detail` (frozen at last write — all four read `stopped`); `reconciliation` table exists but **empty of scheduled writes** (only `scripts/reconcile.py` manual); 395 `pnl=0.0` sentinel rows in `alpaca_trades` | Status: written by the fix via `_on_status_change`. Reconciliation: populated by the new hourly step. **Sentinels: READ-AROUND ONLY — no UPDATE, no DELETE, no backfill.** |
| Schema | `runtime_heartbeat` does not exist | New migration `019_runtime_heartbeat.sql` **and** a mirrored block in `src/db_schema.sql:212+` (N3) |
| Live service config | Coolify app `u7x0xw0y4qvcgeh8vyidsgyi` restart policy — **not declared in the repo**. `docker-compose.dev.yml:35,52,73` (`restart: unless-stopped`) is **dev-only** and does not govern prod. | **Read-only verify via Coolify API; report. Do not change** (CONTEXT fence). Irrelevant to the fix regardless (N4). |
| Secrets/env vars | SES: `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_DEFAULT_REGION` on the **dashboard** service (`notifier.py:37-39`) — presence **unverified in prod**; new: `HEARTBEAT_STALE_SECONDS` (180), `RECONCILE_INTERVAL_HOURS` (1) | The alert-path self-check exists **because** SES presence is unverifiable from here. Defaults must work with the env absent. |
| Build artifacts | None | — |
| Frontend types | `dashboard/web/types/index.ts:1-14` (`Portfolio`), `:106-126` (`BotSettings`) carry no `pnl_source`/`stale`/`unresolved`/`manager_alive`/`alerts_configured` | API additions are runtime-safe (see N8); TS interfaces must be **extended** to *surface* them |

## Common Pitfalls

### N1 — `reconcile()` has no per-bot guard and will abort wholesale (WILL BITE THIS PHASE)

`reconciliation.reconcile()` (`:134-143`):

```python
# Source: src/reconciliation.py:139-143 (verbatim)
    results: list[tuple[str, dict]] = []
    for bot_id in _enabled_bot_ids():
        client = _client_for_bot(bot_id)
        results.append((bot_id, reconcile_bot_live(bot_id, client, tolerance)))
    return results
```

No `try`. And `_client_for_bot` **raises** `ValueError` on a keyless bot (`:86-90`). Worse:
`_enabled_bot_ids` (`:51-59`) selects on **`enabled = TRUE` only — no key predicate**. So *today*, a
single keyless-but-enabled bot makes the manual `scripts/reconcile.py` throw and reconcile **zero**
bots — including the healthy ones.

Scheduling this hourly inside the watchdog without a per-bot `try/except` converts one misconfigured
bot into **total reconciliation failure**, silently (the loop's outer `except` would just log a
warning). **The B1 fix makes keyless bots more likely to be enabled, so this lands exactly when we
touch it.** Wrap per-bot; a failing bot must not starve the others.

**Warning sign:** reconciliation `checked_at` stale for *every* bot at once.

### N10 — the watchdog cannot report its own non-existence

Covered in Pattern 2. `self._watchdog.start()` (`:79`) is downstream of the throwing query (`:67-70`).
**Consequence:** `manager_alive` must be computed from **row absence or staleness**, never
default-healthy; and the never-started alert fires from `main.py:65-66`, not from `BotManager`.

**Warning sign:** a `runtime_heartbeat` row that is simply missing, with the dashboard cheerfully
reporting healthy.

### N2 — B1 may not be the *live* cause; the diagnosis task must actually look

`seed_bots.py:167-176` **back-patches** NULL/empty `alpaca_api_key` from the dashboard's
`ALPACA_API_KEY_{A,B,C,D}` env vars on every run:

```sql
UPDATE bots SET alpaca_api_key = COALESCE(alpaca_api_key, %(alpaca_api_key)s), ...
 WHERE bot_id = %(bot_id)s AND (alpaca_api_key IS NULL OR alpaca_api_key = '')
```

If those env vars are set on the dashboard service (CLAUDE.md says they are, for attribution), the
`bots` rows very likely **do** have keys — which points the live outage at mechanism **(i)** (manager
never started / `start_all` threw), not (ii). **This does not change the plan** — Phase 19 fixes both —
but the task-1 log pull must record which, and must not assume B1.

**B1 remains a real latent bug regardless**, and is worth fixing on its own merits: it is the reason a
keyless bot could *never* be seen.

### N4 — the container restart policy is a red herring

The dashboard container is **running** (it serves the API; the frontend renders `status: stopped`). No
restart policy — `always`, `unless-stopped`, or otherwise — restarts a *thread*. Verify and report it
per the CONTEXT decision, then set it aside. If a plan task frames restart policy as part of the fix,
that task is wrong.

### N5 — the death alert fires *before* the spawn and says the wrong thing

`_revive_dead_bots:113-117` alerts, **then** spawns. For a keyless bot (post-B1-fix) `thread is None`
on the very first tick, so it would alert *"thread was found dead and is being restarted"* about a
thread that never existed, then attempt a credential-less spawn — **every 60 seconds, forever**
(the 1h cooldown suppresses the *email*, not the spawn attempt). Branch keyless **before** `:114`.

### N7 — the fifth P&L reader

`portfolio.py:93-101` (daily P&L) has **no** `pnl IS NOT NULL` filter at all — it relies on
`r["pnl"] or 0.0`. Zeros contribute zero to a sum, so the *number* is right, but it is a fifth site that
disagrees with the other four about what a resolved trade is. Bring it into line for consistency; it is
not a correctness bug today.

### N8 — the frontend will not break, but it also will not show anything

`PortfolioData`/`SettingsData`/`HealthStatus` (`models.py:32-44, 149-171`) are Pydantic models with
**defaults on every field** → adding fields is backward-compatible server-side. TypeScript interfaces
(`types/index.ts:1-14`, `:106-126`) ignore extra JSON properties at runtime → **no crash**. But
`pnl_source`, `stale`, `unresolved`, `manager_alive`, `alerts_configured` will be **invisible** until
the TS interfaces and the components that render them (`app/page.tsx`, `app/settings/page.tsx`,
`components/settings/BotStatus.tsx`) are extended. RUN-02 says the headline *reflects* reconciled
numbers — the flag has to be **visible**, so the frontend is in scope.

### N6 — `get_alpaca_accuracy` consumers (shape change is safe)

Adding an `unresolved` key to the returned dict (`db.py:248-258`) is **additive**; consumers index by
key and will not break:

| Consumer | Site |
|---|---|
| `src/trade_logger.py:52-53` (shim) → `src/alpaca_orchestrator.py:650`, `:1327` | reads `win_rate`, `total_pnl` etc. |
| `scripts/symbol_report.py:271` | read-only report |
| `tests/test_db.py:38,120-130` | asserts the dict |
| **The dashboard does NOT call it** | explicitly noted at `dashboard/api/tests/test_portfolio_win_rate.py:3` |

**But changing `win_rate`/`losses` *values* (by excluding zeros) WILL move numbers the orchestrator
logs and `symbol_report` prints.** That is intended — those numbers are currently wrong — but the
planner should expect `tests/test_db.py` assertions to need updating, and should not mistake that for a
regression.

## Code Examples

### The two-line delete that fixes the outage

```python
# src/bot_manager.py:186-190 — BEFORE (verbatim, current)
        # Check at least one bot is running — silence expected if all bots are down
        with self._lock:
            any_alive = any(t.is_alive() for t in self._threads.values())
        if not any_alive:
            return  # bots are down; death alert handles that separately
```

The `return` goes. All-bots-down becomes its own, louder alert (`_check_bots_down`), and trade silence
is evaluated on its own merits.

### The heartbeat table (migration `019`)

```sql
-- dashboard/api/migrations/019_runtime_heartbeat.sql
-- Additive. Touches no trade data. Mirror this block into src/db_schema.sql (N3).
CREATE TABLE IF NOT EXISTS runtime_heartbeat (
    component     TEXT PRIMARY KEY,
    beat_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    bots_alive    INT NOT NULL DEFAULT 0,
    bots_enabled  INT NOT NULL DEFAULT 0
);
```

Read side (**absence ⇒ dead**, per N10):

```sql
SELECT beat_at, bots_alive, bots_enabled,
       (NOW() - beat_at) < make_interval(secs => %s) AS manager_alive
  FROM runtime_heartbeat WHERE component = 'bot_manager';
-- zero rows  ⇒  manager_alive = false   (do NOT default healthy)
```

### The RESOLVED predicate — one definition, four sites

```sql
-- SQL form (portfolio.py, settings.py, db.py::get_alpaca_accuracy)
AND pnl IS NOT NULL AND pnl <> 0
```

```python
# Python form — mirrors src/symbol_stats.py's zero_pnl bucketing
def is_resolved(pnl) -> bool:
    return pnl is not None and pnl != 0

# and surface the excluded rows rather than hiding them:
unresolved = sum(1 for r in rows if not is_resolved(r["pnl"]))
```

`wins`, `losses`, `resolved`, and the realized-P&L sum are all computed over resolved rows **only**;
`unresolved` is reported **beside** them, never folded into them.

### Alert-path self-check (CONTEXT decision 2)

```python
# Config presence only — no send, no SES call at startup.
def alerts_configured() -> bool:
    from src.notifier import SECRETS_PATH
    if SECRETS_PATH.exists():
        return True
    return bool(os.environ.get("AWS_ACCESS_KEY_ID")
                and os.environ.get("AWS_SECRET_ACCESS_KEY"))
```

Mirrors `notifier._get_ses_client`'s own resolution order (`:27-39`) exactly. Logged at INFO on startup,
exposed as `HealthStatus.alerts_configured`.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|---|---|---|---|
| `losses = resolved - wins` over all non-NULL rows | `RESOLVED := pnl IS NOT NULL AND pnl <> 0`; zeros reported as `unresolved` | Phase 17 (`symbol_stats.py`), generalized here | 395 fabricated losses (60% of closed rows) leave the headline |
| Headline = trade-log sum (`settings.py:65`) | Headline = Alpaca-derived reconciled P&L + `pnl_source`/`stale` | Phase 13 built it; **Phase 19 reads it** | The paper gate is finally evaluated on a reconciled number |
| Liveness = `bots.status` column (frozen on last write) | Liveness = heartbeat freshness (absence ⇒ dead) | Phase 19 | "Manager never started" becomes visible instead of a swallowed `log.warning` |

**Deprecated by this phase:** the `alpaca_api_key != ''` predicate (`bot_manager.py:69-70`, `:106-107`);
the `if not any_alive: return` escape (`:189-190`); `100_000.0 * len(bot_ids)` (`settings.py:65`).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | Coolify's restart policy for app `u7x0xw0y4qvcgeh8vyidsgyi` is Coolify's default (`unless-stopped`-equivalent). **Not declared in the repo** — `docker-compose.dev.yml` is dev-only. | Runtime State Inventory | **Low.** Read-only verify in task 1. Irrelevant to the fix either way (N4). |
| A2 | SES env vars (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`) **are** set on the prod dashboard service. Unverifiable from this repo. | Pitfalls | **Medium** — if absent, *every* alert this phase adds is silently dropped. This is precisely why the self-check is locked in (decision 2). Not a blocker: the self-check *reports* the condition. |
| A3 | The live outage is mechanism **(i)** (manager never started), not (ii) (zero rows matched), because `seed_bots.py:167-176` back-patches keys. | N2 | **None to the plan** — Phase 19 fixes both. Only affects what the diagnosis task records. |
| A4 | The 395 sentinel count and the 60%-of-closed-rows figure are carried from Phase 17 `EVIDENCE.md` (not re-derived here — deriving it requires a prod DB read). | Summary | **Low.** Directionally load-bearing only; the predicate fix is correct at any count. |

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---|---|---|
| Python + pytest | All tests | ✓ | repo baseline **428 passed / 28 skipped** | — |
| `psycopg` / `psycopg_pool` | Manager pool, heartbeat | ✓ | already imported (`bot_manager.py:8`) | — |
| `boto3` | SES alerts | ✓ | already imported (`notifier.py:24`) | — |
| Postgres (prod) | Migration `019` | ✓ (Coolify) | — | Migration is additive + `IF NOT EXISTS` |
| SES credentials (prod dashboard env) | Alerts actually sending | **✗ unverified** | — | **None.** This is the point of the self-check (A2). |
| Coolify API | Read-only restart-policy check | ✓ | app UUID `u7x0xw0y4qvcgeh8vyidsgyi` | Report "unknown" and move on |

**Missing dependencies with no fallback:** none that block execution. SES-unverified is *reported*, not
worked around.

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Framework | pytest |
| Config file | none dedicated — `tests/conftest.py` |
| Quick run command | `pytest tests/test_bot_manager.py tests/test_notifier_selfcheck.py -x -q` |
| Full suite command | `pytest -q` |
| Baseline | **428 passed / 28 skipped** — must not regress |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|---|---|---|---|---|
| RUN-01 | All-bots-down alerts (**killer**) | unit | `pytest tests/test_bot_manager.py -k all_bots_down -x` | ❌ Wave 0 |
| RUN-01 | Keyless enabled bot → `status='error'` + alert, not invisible | unit | `pytest tests/test_bot_manager.py -k keyless -x` | ❌ Wave 0 |
| RUN-01 | Dead thread revived | unit | `pytest tests/test_bot_manager.py -k revive -x` | ❌ Wave 0 |
| RUN-01 | Heartbeat UPSERT + absence ⇒ dead | unit | `pytest tests/test_bot_manager.py -k heartbeat -x` | ❌ Wave 0 |
| RUN-01 | Alert-path self-check when SES unconfigured | unit | `pytest tests/test_notifier_selfcheck.py -x` | ❌ Wave 0 |
| RUN-02 | `RESOLVED := pnl IS NOT NULL AND pnl <> 0` at 4 sites | unit | `pytest tests/test_db.py dashboard/api/tests/test_portfolio_win_rate.py -x` | ⚠️ extend |
| RUN-02 | Headline = reconciled, `pnl_source`/`stale` surfaced | unit | `pytest dashboard/api/tests/test_routes.py -k headline -x` | ⚠️ extend |
| RUN-02 | `settings.py:65` hardcode gone | unit | `pytest dashboard/api/tests/test_routes.py -k starting_equity -x` | ⚠️ extend |
| RUN-02 | Hourly reconcile is per-bot-guarded (N1) | unit | `pytest tests/test_reconciliation.py -k guard -x` | ⚠️ extend |

### Sampling Rate

- **Per task commit:** `pytest tests/test_bot_manager.py -x -q`
- **Per wave merge:** `pytest -q` (428/28 floor)
- **Phase gate:** full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/test_bot_manager.py` — **does not exist.** Covers RUN-01 entirely (all-bots-down, keyless, revive, heartbeat). This is the phase's highest-value missing file.
- [ ] `tests/test_notifier_selfcheck.py` — alert-path config check.
- [ ] Extend `tests/test_db.py` — `get_alpaca_accuracy` RESOLVED predicate + `unresolved` key.
- [ ] Extend `dashboard/api/tests/test_portfolio_win_rate.py` + `test_routes.py` — headline, `pnl_source`, `stale`, starting equity.
- [ ] Extend `tests/test_reconciliation.py` — per-bot exception guard (N1).
- [ ] Fixture: a fake `BotThread` with a controllable `is_alive()` + a capture-only `send_alert` — **no SES, no DB, no Alpaca in unit tests.**

## Security Domain

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | no | No auth change; dashboard `DASHBOARD_TOKEN` untouched (`main.py:101-125`) |
| V3 Session Management | no | — |
| V4 Access Control | yes (weakly) | New health fields ride existing authed routes (`main.py:177-188`). **`alerts_configured` must be a `bool` — never echo key material or SES config values.** |
| V5 Input Validation | yes | New response fields only; Pydantic models. No new user input. |
| V6 Cryptography | no | — |

| Pattern | STRIDE | Mitigation |
|---|---|---|
| Credential leak via new health surface | Information Disclosure | Booleans only; never surface `alpaca_api_key`, AWS keys, or a key prefix in `status_detail` — `"missing alpaca keys"` is the whole message |
| Destructive write to prod trade data | Tampering | **Fence:** `alpaca_trades` is READ-ONLY this phase. `src/backfill.py` exists and must not be invoked. |
| Alert flood / self-DoS | DoS | 1h cooldown per alert class, reusing the existing `_last_death_alert` pattern (`:123-127`) |

## Sources

### Primary (HIGH — read at file:line in this repo, this session)
- `src/bot_manager.py` — `:17-20`, `:45-51`, `:58-62`, `:64-83`, `:85-95`, `:101-119`, `:121-139`, `:145-212` (**`:186-190`**), `:218-268`, `:274-297`, `:299-309`
- `src/bot_thread.py:240-244`, `:398`, `:404`, `:407` — status writer #1
- `src/copytrade_thread.py:140-144`, `:429`, `:434`, `:436` — **status writer #2 (the refutation)**
- `src/notifier.py:17`, `:22-39`, `:42-61`, `:64-143`
- `src/reconciliation.py:16-42`, `:47-59`, `:62-93`, `:96-131`, `:134-143`
- `src/db.py:70-73`, `:224-258`, `:263-276`, `:322-331`, `:334-356`
- `src/db_schema.sql:212-215` — the mirror requirement (N3)
- `dashboard/api/main.py:46-71` (**`:55`, `:65-66`**), `:177-201`
- `dashboard/api/routes/portfolio.py:47-137` (`:66-80`, `:93-101`, `:105-122`)
- `dashboard/api/routes/settings.py:39-65` (**`:65`**), `:68-88`, `:113-144`
- `dashboard/api/routes/bots.py:29-45`, `:185-200`
- `dashboard/api/models.py:32-44`, `:149-171`, `:256-272`, `:285-287`
- `dashboard/api/seed_bots.py:160-178` — the key back-patch (N2)
- `dashboard/api/migrations/` — `017_reconciliation.sql`, `018_universe_quarantine.sql` (**019 free**), `run_migrations.py:10-44`
- `dashboard/web/types/index.ts:1-14`, `:106-126` (N8)
- `docker-compose.dev.yml:35,52,73` — dev-only restart policy

### Secondary (MEDIUM)
- `.planning/phases/17-per-symbol-performance/EVIDENCE.md` — the 395/655 figure (A4, not re-derived)
- `dashboard/api/tests/test_portfolio_win_rate.py:3` — confirms the dashboard does not call `get_alpaca_accuracy`

### Tertiary (LOW / unverified)
- Coolify prod restart policy (A1) — not in repo; read-only API check in task 1
- Prod SES env presence (A2) — not verifiable from repo

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — no new packages; every module already imported and read at `file:line`
- Architecture: **HIGH** — all five CONTEXT defect claims confirmed verbatim; one refuted with evidence
- Pitfalls: **HIGH** for N1/N3/N4/N5/N7/N8/N10 (all read in-tree); **MEDIUM** for N2 (depends on unverifiable prod env)

**Research date:** 2026-07-13
**Valid until:** 30 days (internal codebase; no external dependencies to drift)
</content>
</invoke>
