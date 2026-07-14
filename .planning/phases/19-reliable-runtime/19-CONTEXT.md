# Phase 19 — Reliable Runtime & Honest Monitoring — CONTEXT

*Milestone v1.1 · captured 2026-07-13 · mode: --auto (YOLO, decisions auto-selected and LOCKED)*

## Domain

Two failures, both live right now:

1. **The bots are not running, and nothing told anyone.** All four bots (A, B, C, E) report
   `status: "stopped"` / `thread_alive: false` against prod. A/B/C are `enabled: true`. Zero alerts
   were sent. A trading system that silently stops trading is worse than one that crashes loudly.
2. **The dashboard headline is not the reconciled number.** Phase 13 built the reconciliation
   (trade-log P&L vs Alpaca-derived realized P&L, per bot, into the `reconciliation` table). Nothing
   schedules it, nothing reads it, and no dashboard surface shows it. The headline win-rate is still
   computed off the raw trade log — which still contains the 395 historical `pnl=0.0` sentinel rows.

**Requirements owned:** RUN-01 (bots restart / stay running reliably; an unexpected stop is detected
and alerted via the existing notifier path), RUN-02 (the dashboard headline P&L / win-rate reflects
reconciled (PNL-03) numbers, not the overstated trade-log sum).

**Not owned here:** the entry-knob retune (TUNE-01 PARTIAL → Phase 21), tests/E2E (VERIFY-01/02 →
Phase 20).

## Grounding (from code scout)

### The runtime already has a watchdog — it has three blind spots, and the live state sits in all of them

`src/bot_manager.py` already implements most of RUN-01: a `bot-watchdog` daemon thread
(`:58-62`, 60s tick) that revives dead threads (`:101-119`) and emails a death alert with a 1h
per-bot cooldown (`:121-139`), plus a 24h trade-silence alert (`:145-212`). It is started from the
FastAPI lifespan in the dashboard container (`dashboard/api/main.py:46-71`). **The mechanism exists.
It cannot see the current failure.**

- **B1 — the key filter makes a broken bot invisible.** `bot_manager.py:67-70` (`start_all`) and
  `:104-107` (`_revive_dead_bots`) both select
  `WHERE enabled = TRUE AND alpaca_api_key IS NOT NULL AND alpaca_api_key != ''`.
  An enabled bot whose `bots` row has no key is **never spawned, never revived, and never alerted** —
  it simply is not in the result set. Per CLAUDE.md, each bot's *orchestrator* service reads **bare**
  `ALPACA_API_KEY`, and the dashboard's per-bot `_A/_B/_C/_D` env vars are the attribution path — so
  an empty `bots.alpaca_api_key` column is an entirely plausible prod state that this query converts
  into permanent, silent non-trading.
- **B2 — the silence alert is disabled by exactly the condition it should scream about.**
  `bot_manager.py:187-190`: `if not any_alive: return  # bots are down; death alert handles that
  separately`. When zero bots are alive, the trade-silence alert **suppresses itself** and defers to a
  death alert that (per B1, or per B3) never fires. All-bots-down is the single most important alert
  in the system and it is the one state that is guaranteed to be silent.
- **B3 — no liveness signal for the manager itself.** `dashboard/api/main.py:53-66` swallows every
  BotManager failure (`_log.warning("BotManager unavailable: %s")`) and continues in read-only mode;
  a missing `DATABASE_URL` skips construction entirely. There is **no heartbeat**, so nothing outside
  the process can distinguish "manager running, bots healthy" from "manager never started." The
  dashboard's `running` flag (`dashboard/api/routes/settings.py:68-78`) reads `mgr.status()` and
  falls back to the `bots.status` column — both of which say "stopped" without saying *why*.

### Why the bots are stopped (best determination from code; confirm in task 1 with container logs)

`bots.status` is written **only** by `BotThread._set_status` → `BotManager._on_status_change`
(`src/bot_thread.py:240-244, 398-407` → `bot_manager.py:299-309`): `"running"` on loop entry
(`:398`), `"error"` on unhandled exception (`:404`), `"stopped"` in the exit path (`:407`).
`status="stopped"` for **all four** bots, with `thread_alive=false`, means the threads exited (or were
stopped by `stop_all()` on container shutdown) and **were never respawned** — the status column has
been frozen at its last write ever since. There is no crash signature in the state (that would read
`"error"`).

So: **the dashboard container's BotManager is not running any bot threads.** Two mechanisms produce
exactly this state, both alert-silent, and Phase 19 fixes both regardless of which one it is:

- **(i)** BotManager never started this deploy — `DATABASE_URL` absent, or `start_all()` threw and was
  swallowed at `main.py:65-66`; or
- **(ii)** BotManager started but `start_all()`'s key filter (B1) matched **zero rows** — it would
  log `BotManager: starting 0 enabled bots` and then sit there, watchdog ticking over an empty set,
  forever.

Bot E is `enabled: false` — E being down is correct behavior, not a fault.

**First task of the phase is a read-only log pull** from the dashboard container (`BotManager started`
vs `BotManager unavailable: …` vs `BotManager: starting N enabled bots`) to record which mechanism
fired. It is diagnosis for the record, not a fork in the plan.

### The notifier that already exists (do NOT roll a new one)

`src/notifier.py` — `send_alert(subject, body)` (`:42-61`) plus typed wrappers
(`alert_bot_crash :64`, `alert_drawdown_stop :77`, `alert_monitor_error :89`,
`alert_position_closed :99`, `alert_reconciliation_breach :115`, `alert_cycle_summary :130`).
It **never raises** — every failure is logged and swallowed (`:59-61`).

**Two facts to carry into the plan:**
- **Transport is AWS SES via boto3** (`_get_ses_client :22-39`), even though the *sender address* is
  `alerts@emails4agents.com` (`:17`). This is the "existing emails4agents notifier path" RUN-01 means.
- Because `send_alert` swallows everything, **missing SES creds in the dashboard service env produce
  a system that believes it is alerting and is not.** A silent alerter and a silent bot are the same
  outage twice.

### Reconciliation (Phase 13) is built, scheduled by nobody, read by nobody

- `src/reconciliation.py:16-42` — `reconcile_bot(...)` pure, cent-exact:
  `alpaca_realized_pnl = (equity - starting_equity) - unrealized_pnl`; `delta = trade_log_pnl -
  alpaca_realized_pnl`; `within_tolerance = abs(delta) <= tolerance` (default $25,
  `RECONCILIATION_TOLERANCE_USD`).
- `:96-131` `reconcile_bot_live` — persists via `db.record_reconciliation` (`src/db.py:334-338`,
  UPSERT, one row per bot) and fires `notifier.alert_reconciliation_breach` on breach. `:134-143`
  `reconcile()` loops enabled bots, **one Alpaca client per bot** (`_client_for_bot :62-93`, never
  bare/shared keys).
- `dashboard/api/migrations/017_reconciliation.sql` — table exists, and its own header says:
  *"Consumed by the dashboard headline in **Phase 19**."* This phase is what that comment was written
  for.
- **Entry points:** `scripts/reconcile.py` only — a manual CLI. **No cron, no scheduler, no route.**
  `grep -rn reconciliation dashboard/api/routes/` → **zero hits.**

### What the headline actually computes today

- `dashboard/api/routes/portfolio.py:105-122` — `total_pnl = equity - starting_equity` from the live
  **Alpaca account** when keys resolve (honest), but **silently falls back** to the trade-log sum
  (`closed_pnl`, `:119-122`) when Alpaca is unreachable, with no flag on the response.
- `dashboard/api/routes/settings.py:63-65` — `equity = 100_000.0 * len(bot_ids) + total_pnl` where
  `total_pnl` is a **pure trade-log sum**. Hardcoded $100k/bot, ignores `bots.starting_equity`,
  ignores Alpaca, ignores reconciliation. **This is the overstated headline RUN-02 names.** It is also
  the paper-gate readout (`win_rate` vs `win_rate_target=40.0`, `:137-140`) — the gate that guards
  live trading is being evaluated against numbers nobody reconciled.
- **The 395 sentinels still land in the win-rate.** Phase 18 added `AND pnl IS NOT NULL` at
  `portfolio.py:70`, `settings.py:43`, and `src/db.py` `get_alpaca_accuracy` — correct for the
  **post-fix** NULL channel, but the 395 historical rows carry **`pnl = 0.0`, which is NOT NULL**.
  They pass the filter, score `(r["pnl"] or 0) > 0 → False` (`portfolio.py:77`, `settings.py:62`), and
  are booked as **losses**. 60% of the closed-row population is still a fabricated loss in the
  headline. Phase 18 fixed the *writer*, not the *reader*.
- Phase 17's aggregator already got this right: `src/symbol_stats.py` buckets `pnl == 0` rows into
  `zero_pnl` and never counts them as trades. The dashboard is the inconsistent reader.

## Decisions (locked — auto-selected recommended defaults)

### 1. RUN-01 mechanism: harden the EXISTING watchdog. No new supervisor, no new process.

`BotManager`'s watchdog is the right shape (in-process, event-driven off thread liveness, already
wired to the notifier). Phase 19 closes B1/B2/B3 and does not introduce a second supervisor, a
sidecar, systemd, or an external cron — each of which would be a new thing that can silently die.

- **B1 fix — one query, two outcomes.** `start_all` and `_revive_dead_bots` select
  `WHERE enabled = TRUE` (drop the key predicate). A bot with unusable Alpaca keys is then **visible**
  and lands in an explicit `status='error'` + `status_detail='missing alpaca keys'` + **one alert**
  (cooldown-suppressed, same 1h) — never in silence. An enabled bot must always be either running or
  loudly broken; "invisible" is not a state we ship.
- **B2 fix — all-bots-down is its own alert, and it is the loudest one.** Delete the
  `if not any_alive: return` escape (`bot_manager.py:187-190`). Add `_check_bots_down()` to the
  watchdog: if **zero** enabled bots have a live thread, alert (subject: `ALL BOTS DOWN — no bot
  threads alive`), 1h cooldown, and keep alerting each cooldown window until at least one is alive.
  This is the alert whose absence produced the current outage.
- **B3 fix — a heartbeat, so the outside can see the inside.** Each watchdog tick UPSERTs one row into
  a new `runtime_heartbeat` table (`component TEXT PRIMARY KEY, beat_at TIMESTAMPTZ, bots_alive INT,
  bots_enabled INT`) — additive migration, no trade data touched. The dashboard reports
  `manager_alive` = heartbeat age < `HEARTBEAT_STALE_SECONDS` (default 180). A BotManager that never
  started now has a **visible, queryable** signature instead of a swallowed warning line.
- **Restart reliability** = the watchdog revive path (already correct once B1 lands) + the container
  restart policy. The Coolify restart policy is **verified read-only** in this phase and *reported* if
  wrong — changing prod deploy config is outward-facing and is not done silently inside a phase.

### 2. The notifier is `src/notifier.py`. Period. But prove it can actually send.

No new provider, no new transport, no SendGrid/Resend/anything. New alerts are **new wrapper functions
in `src/notifier.py`** (`alert_all_bots_down`, `alert_bot_misconfigured`) reusing `send_alert`.

**Locked addition:** because `send_alert` swallows failures, the manager performs a **startup
alert-path self-check** — confirm SES credentials resolve (secrets file or
`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_DEFAULT_REGION` present) — log it at INFO and expose
`alerts_configured: bool` on the health surface. A trading system whose alerter is unconfigured is not
monitored, and today nothing would tell you.

### 3. RUN-02 — the headline is the RECONCILED number, and it says so when it isn't.

- **Schedule the reconciliation where the supervisor already lives.** The watchdog loop calls
  `reconciliation.reconcile()` every `RECONCILE_INTERVAL_HOURS` (default `1`), guarded by
  try/except like the other watchdog steps. No cron, no new container, no frontend polling (CLAUDE.md:
  reactive over polling). Its only DB write is the `reconciliation` UPSERT — an additive, non-trade
  table (Decision 6).
- **Read it in the headline.** `portfolio.py` and `settings.py` join the `reconciliation` row for each
  bot and return `reconciled: {alpaca_realized_pnl, trade_log_pnl, delta, within_tolerance,
  checked_at}` plus a top-level **`pnl_source`** ∈ `{"reconciled", "alpaca_live", "trade_log"}` and
  **`stale: bool`** (no row, or `checked_at` older than 2× the interval). **The headline P&L is
  `alpaca_realized_pnl` (+ live unrealized), not the trade-log sum.** When reconciliation is stale or
  absent, the number is still shown but is **flagged** — the dashboard never presents an unreconciled
  figure as reconciled.
- **`settings.py:65`'s `100_000.0 * len(bot_ids)` is deleted.** Starting equity comes from
  `bots.starting_equity` (as `db.get_starting_equity` already does, `src/db.py:323`). A hardcoded
  bankroll in the paper-gate readout is exactly how a gate gets passed by a bug.

### 4. The 395 sentinels: the headline stops counting them. Nothing in the DB is touched.

**Locked predicate — one definition, four call sites:** a trade is **RESOLVED** iff
`pnl IS NOT NULL AND pnl <> 0`. Rows with `pnl = 0` are **UNRESOLVED**: excluded from the win-rate
**numerator and denominator**, excluded from the realized-P&L sum, and surfaced as their own
`unresolved` count next to `wins` / `losses`.

- Applied at `dashboard/api/routes/portfolio.py:66-80`, `dashboard/api/routes/settings.py:39-64`,
  `src/db.py` `get_alpaca_accuracy`, keeping them consistent with `src/symbol_stats.py`, which already
  buckets `pnl == 0` as `zero_pnl` and never counts it as a trade. Phase 17's aggregator is the
  reference implementation; the dashboard is being brought into line with it, not the reverse.
- **Cost, stated plainly:** a genuine exactly-break-even trade would be dropped from the win rate.
  With crypto fills and fees this is a measure-zero event, and the alternative — booking 395 fabricated
  zeros as real losses — is the error we are actually suffering from. Post-Phase-18 the writer emits
  `NULL`, never `0.0`, so this predicate's `<> 0` arm is a **historical-row filter with a shrinking
  blast radius**, and it costs nothing going forward.
- **NO backfill. NO UPDATE. NO DELETE.** Repairing the 395 rows from Alpaca activity history is a
  **write to historical prod trade data** and requires **explicit human authorization** — it is
  flagged in this document and in the phase's SUMMARY, and it is **not performed by Phase 19 under any
  circumstance**, including "while we're in there."

### 5. Delivery surface: extend the existing envelopes. No SSE stream this phase.

Runtime health (`manager_alive`, `last_heartbeat`, `bots_alive`/`bots_enabled`, `alerts_configured`)
rides on the existing `GET /api/settings` `HealthStatus` model and `GET /api/bots`
(`thread_alive` already exists at `bots.py:44`). No new WebSocket, no new poll loop in the frontend.
A live push channel for bot state is a real idea and it is **deferred** (see below) — this phase's job
is that the truth *exists and is queryable*, not that it streams.

### 6. What Phase 19 is allowed to write

| Target | Allowed? |
|---|---|
| `reconciliation` table (UPSERT via the Phase-13 driver) | **Yes** — additive, non-trade, that is its purpose |
| `runtime_heartbeat` table (new, additive migration) | **Yes** |
| `bots.status` / `status_detail` (existing `_on_status_change` path) | **Yes** |
| `alpaca_trades` — any UPDATE/DELETE/backfill | **NO. Needs explicit human authorization. Flag, do not do.** |
| `bots` config knobs (`min_confluence`, `kelly_fraction`, `quarantined_symbols`) | **NO — that is Phase 21.** |

## Scope discipline (fences)

- **The hardcoded risk rules are NEVER overridden.** Max 5% bankroll/position, quarter-Kelly ceiling,
  20% drawdown stop, limit orders only, 50 paper trades before live. Phase 19 touches none of them.
- **Live trading stays PAPER-GATED.** Making the paper-gate readout *honest* (Decision 3) may well
  make it read **worse**. That is the point. The gate is not unlocked here.
- **NEVER write to prod trade data.** The 395 sentinel rows are read-around, not repaired. Any
  backfill/repair is a separate, human-authorized task.
- **One Alpaca account per bot** — `reconciliation._client_for_bot` already enforces it; do not
  introduce a shared client while scheduling it.
- **Do not roll a new email provider.** `src/notifier.py` / SES-behind-emails4agents is the path.
- **Do not re-open the retune.** No `min_confluence`, `kelly_fraction`, or `quarantined_symbols`
  change — Phase 21.
- **No new strategies, assets, indicators, or bots.** No changes to entries, exits, risk gate, exit
  advisor, or the learning/shadow gate.
- **No prod deploy-config changes** (Coolify restart policy, env vars) inside the phase — verify and
  report; changing them is an authorized, separate step.
- Reactive over polling; SSE over WebSockets (CLAUDE.md) — and neither is added this phase.

## Canonical refs (MANDATORY reading for research/plan)

- `.planning/REQUIREMENTS.md` — RUN-01, RUN-02 (and the TUNE-01 PARTIAL entry: the retune is Phase 21,
  not this one).
- `.planning/phases/17-per-symbol-performance/EVIDENCE.md` — where the 395/655 (60%) sentinel figure
  and the `zero_pnl` bucket come from.
- `.planning/phases/18-profitable-retune/18-BACKTEST.md` + `VERIFICATION.md` — the writer fix
  (NULL-not-zero), the three win-rate denominator sites, and what was deliberately **not** backfilled.
- `src/bot_manager.py:17-20` (intervals/cooldowns), `:58-62` (watchdog thread), `:64-83` (`start_all`,
  **the key filter**), `:101-119` (`_revive_dead_bots`), `:121-139` (death alert), `:145-212`
  (trade silence, **the `not any_alive` escape at :187-190**), `:259-268` (`status()`),
  `:299-309` (`_on_status_change`).
- `src/bot_thread.py:240-244` (`_set_status`), `:398` (`running`), `:404` (`error`), `:407`
  (`stopped`) — the only writers of `bots.status`.
- `dashboard/api/main.py:46-71` — lifespan; **the swallowed BotManager failure at `:65-66`**.
- `src/notifier.py:17` (sender), `:22-39` (SES client), `:42-61` (`send_alert`, swallows),
  `:115-127` (`alert_reconciliation_breach`).
- `src/reconciliation.py:16-42` (pure `reconcile_bot`), `:62-93` (`_client_for_bot`, one account per
  bot), `:96-143` (driver + `reconcile()`).
- `src/db.py:323` (`get_starting_equity`), `:334-338` (`record_reconciliation`), `get_alpaca_accuracy`
  (win-rate denominator).
- `dashboard/api/routes/portfolio.py:47-137` — headline P&L / win rate; `:70` (Phase-18 NULL filter),
  `:105-122` (Alpaca-vs-trade-log fallback).
- `dashboard/api/routes/settings.py:39-65` (**`equity = 100_000.0 * len(bot_ids) + total_pnl`**),
  `:68-88` (running / uptime), `:113-140` (health + paper gate).
- `dashboard/api/routes/bots.py:29-45` (`_enrich`, `thread_alive`).
- `dashboard/api/migrations/017_reconciliation.sql` — the table, and its "Consumed by the dashboard
  headline in Phase 19" contract.
- `src/symbol_stats.py` — the `zero_pnl` bucketing the dashboard is being aligned to.
- `scripts/reconcile.py` — the existing manual entry point being scheduled.
- CLAUDE.md — hardcoded risk rules, one-account-per-bot, paper gate, never write prod without
  permission, reactive-over-polling.

## Deferred ideas (not this phase)

- **Backfilling / repairing the 395 historical sentinel rows** from Alpaca activity history. A write to
  historical prod trade data — **needs explicit human authorization**, and the source data may no
  longer exist at Alpaca. Read-around, don't repair.
- **SSE / live push of bot + position state** to the dashboard (CLAUDE.md's reactive-over-polling
  end-state). Phase 19 makes the truth queryable; streaming it is a follow-on.
- **External/off-box liveness** (a healthcheck pinged by something that is not the dashboard container
  — the current design still cannot alert if the whole container is gone). Right answer is an uptime
  probe against `/health` + the heartbeat age; infra work, separate authorization.
- **Migrating the notifier transport** from boto3 SES to the emails4agents HTTP API (`/v1/messages/send`)
  — sender address already says emails4agents; the transport doesn't. Cosmetic/consistency, not a RUN
  requirement.
- **Auto-disable a chronically-crashing bot** after N revives in a window (currently it will restart
  forever, alerting hourly). Needs a policy decision; alerting is the Phase-19 bar.
- **Entry-knob retune (TUNE-01 completion)** — Phase 21, on the sentinel-free sample this phase's
  honest headline finally makes measurable.
