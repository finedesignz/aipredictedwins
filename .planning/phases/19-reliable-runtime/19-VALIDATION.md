# Phase 19 — Reliable Runtime & Honest Monitoring — VALIDATION

**Requirements:** RUN-01 (bots stay running; an unexpected stop is detected and alerted),
RUN-02 (headline P&L / win-rate reflects reconciled numbers, not the overstated trade-log sum)
**Baseline:** `pytest -q` → **428 passed / 28 skipped**. No case below may regress it.
**Framework:** pytest. Unit-only — **no SES send, no Alpaca call, no prod DB** in any case here.

## Wave-0 gap (RED before GREEN)

**`tests/test_bot_manager.py` DOES NOT EXIST.** It is the single highest-value missing file in this
phase: cases 1–9 all live in it. Cases 1, 3, 5 and 6 **MUST FAIL before the fix** — a case that passes
against current `main` is not testing the bug.

| File | Status | Covers |
|---|---|---|
| `tests/test_bot_manager.py` | ❌ **CREATE** | Cases 1–9 (all of RUN-01) |
| `tests/test_notifier_selfcheck.py` | ❌ **CREATE** | Cases 10–12 |
| `tests/test_db.py` | ⚠️ extend | Cases 13, 14 |
| `dashboard/api/tests/test_portfolio_win_rate.py` | ⚠️ extend | Cases 15, 16 |
| `dashboard/api/tests/test_routes.py` | ⚠️ extend | Cases 17–21 |
| `tests/test_reconciliation.py` | ⚠️ extend | Cases 22, 23 |
| `dashboard/api/migrations/019_runtime_heartbeat.sql` + `src/db_schema.sql` | ❌ **CREATE/EDIT** | Case 24 |

**Shared fixtures required:** a `FakeThread` with a settable `is_alive()`; a capture-only `send_alert`
(records `(subject, body)` to a list, never touches boto3); an in-memory `bots` row set. **No network,
no DB, in cases 1–14.**

---

## RUN-01 — The runtime tells the truth

### Group A — The killer: all-bots-down must actually alert

| # | Case | Test | Proves |
|---|---|---|---|
| **1** | **All bots down → ALERT FIRES.** Zero enabled bots have a live thread; last trade is older than `TRADE_SILENCE_ALERT_HOURS`. | Drive `_check_trade_silence` / `_check_bots_down` with `self._threads = {}` (or all `is_alive()==False`). Assert **≥1** `send_alert` captured, subject matches `ALL BOTS DOWN`. | **THE KILLER BUG.** `bot_manager.py:189-190` (`if not any_alive: return`) is deleted. **MUST FAIL on current `main`** — today this asserts 0 alerts. If it passes pre-fix, the test is wrong. |
| 2 | All bots down, alert **repeats** each cooldown window until one is alive. | Tick; assert 1 alert. Tick again immediately; assert **still 1** (cooldown). Advance clock > 1h; tick; assert **2**. | The alert does not fire once and give up — an outage that persists keeps screaming. Reuses the `:123-127` cooldown pattern. |
| 3 | **≥1 bot alive → NO all-bots-down alert.** | One `FakeThread` with `is_alive()==True`. Assert **zero** `ALL BOTS DOWN` alerts. | No false positives. The loudest alert must not cry wolf. |
| 4 | Trade silence is evaluated **on its own merits** once the `any_alive` escape is gone. | Bots alive, last trade 30h ago (> 24h threshold). Assert a *trade-silence* alert fires (not an all-bots-down one). | Deleting `:189-190` did not break the pre-existing silence alert — the two alerts are now independent, not mutually suppressing. |

### Group B — A keyless-but-enabled bot is loudly broken, never invisible

| # | Case | Test | Proves |
|---|---|---|---|
| **5** | **Keyless + enabled bot → `status='error'` + `status_detail='missing alpaca keys'` + ONE alert.** | `bots` row set contains `{bot_id:'X', enabled:True, alpaca_api_key:''}`. Run `_revive_dead_bots`. Assert `_on_status_change` called with `('X','error','missing alpaca keys')` **and** one `alert_bot_misconfigured` captured. | B1 fixed. **MUST FAIL on current `main`** — the key predicate (`bot_manager.py:106-107`) removes the row from the result set entirely, so *nothing* is called. "Invisible" is not a state we ship. |
| **6** | **Keyless bot is NOT spawned and does NOT get a death alert.** | Same fixture. Assert `_spawn` **not called** for `X`, and **no** `"thread died"`-subject alert. | Research N5. Post-B1-fix, a keyless bot has `thread is None` and would otherwise fall into `_maybe_send_death_alert` (`:114`) → wrong message → credential-less `_spawn` (`:117`) **every 60s forever**. The branch must precede the death alert. |
| 7 | Keyless-bot alert respects the 1h cooldown. | Tick twice inside an hour. Assert exactly **1** alert (but `status='error'` re-asserted each tick). | No hourly spam; status stays authoritative. |
| 8 | A keyed, enabled bot is **unaffected** by the B1 fix. | Row with a key, thread alive. Assert no status change, no alert, no respawn. | Dropping the key predicate did not change behavior for healthy bots. |

### Group C — Dead threads are revived; both thread classes work

| # | Case | Test | Proves |
|---|---|---|---|
| 9 | **A dead thread is revived.** | Keyed enabled bot whose `FakeThread.is_alive()` flips to `False`. Run `_revive_dead_bots`. Assert `_spawn` called for that `bot_id` **and** a death alert fired. | RUN-01 core: the revive path (`:101-119`) works once B1's predicate is gone. |
| 9b | Revive dispatches on `strategy` — a `copytrade` bot respawns as `CopyTraderThread`, not `BotThread`. | Row with `strategy='copytrade'`, dead thread. Assert the spawned class is `CopyTraderThread`. | **Research refutation C1:** there are TWO thread classes (`copytrade_thread.py:140-144` is a second `bots.status` writer, contra CONTEXT). Bot E is `enabled:false` today, so this guards a latent break, not a live one. |

### Group D — The alert path proves it can actually send

| # | Case | Test | Proves |
|---|---|---|---|
| **10** | **SES unconfigured → self-check reports `False` and logs at INFO.** | `monkeypatch` `SECRETS_PATH.exists()→False`, unset `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`. Assert `alerts_configured() is False`. | **The "believes it's alerting and is not" failure.** `send_alert` swallows every exception (`notifier.py:59-61`), so an unconfigured SES is invisible today. Config presence is the only detectable signal. |
| 11 | SES configured (either channel) → `True`. | (a) secrets file exists → `True`. (b) file absent but both AWS env vars present → `True`. | The check mirrors `_get_ses_client`'s own resolution order (`notifier.py:27-39`) **exactly** — it must not disagree with the code that actually sends. |
| 12 | `alerts_configured` is a **bool** on the health surface and leaks nothing. | Assert `HealthStatus.alerts_configured` is `bool`; assert no AWS key material / key prefix appears in any response body or in `status_detail`. | Security fence: booleans only. `"missing alpaca keys"` is the entire detail string. |

---

## RUN-02 — The headline is honest

### Group E — `RESOLVED := pnl IS NOT NULL AND pnl <> 0` at all four reader sites

A `pnl = 0.0` sentinel is **NOT a loss**. It is excluded from the win-rate **numerator AND denominator**
and from the realized-P&L sum, and reported as its own `unresolved` count.
**Reference implementation:** `src/symbol_stats.py` (Phase 17) already buckets `pnl == 0` as `zero_pnl`.

| # | Case | Test | Proves |
|---|---|---|---|
| **13** | **Site 3 — `src/db.py::get_alpaca_accuracy`: a `pnl=0.0` row is NOT a loss.** | Row set: 1 win (`+10`), 1 loss (`-5`), 1 sentinel (`0.0`), 1 NULL. Assert `wins==1`, `losses==1`, `resolved==2`, `win_rate==0.5`, `unresolved==2`. | **MUST FAIL on current `main`:** `db.py:244-246` gives `resolved=3, losses=2, win_rate=0.333`. `db.py:228`'s comment even states the zero is counted on purpose. |
| 14 | `get_alpaca_accuracy` gains `unresolved` **additively** — existing keys keep their names. | Assert the returned dict still has `total_trades, resolved, wins, losses, win_rate, total_pnl, avg_pnl, crypto_pnl, stock_pnl` **plus** `unresolved`. | Research N6: consumers (`trade_logger.py:52-53` → `alpaca_orchestrator.py:650,:1327`; `scripts/symbol_report.py:271`) index by key and must not break. Values *will* move — that is the fix, not a regression. |
| **15** | **Site 1 — `portfolio.py`: sentinels leave the headline win rate.** | Same 4-row set via the route's DB. Assert `wins==1`, `losses==1`, `trades_resolved==2`, `unresolved==2`. | **MUST FAIL on current `main`:** `portfolio.py:77-80` books the `0.0` as a loss (`losses = len(closed) - wins`). |
| 16 | `portfolio.py` realized-P&L sum **excludes** sentinels. | Assert the closed-P&L sum is `+10 + -5 = +5`, computed over resolved rows only. | Zeros contribute 0 to a sum, so the number is unchanged — but the *population* it is computed over is now consistent with the win rate. No silent disagreement between the two figures. |
| **17** | **Site 2 — `settings.py`: the PAPER-GATE win rate excludes sentinels.** | Same row set via `GET /api/settings`. Assert `win_rate` is computed over resolved-only. | **MUST FAIL on current `main`** (`settings.py:62-64`). This is the gate that guards live trading. Making it honest may make it read **worse** — that is the point; the gate is not unlocked here. |
| 18 | Site 5 (`portfolio.py:93-101`, daily P&L) is brought into line. | Daily rows incl. a sentinel + a NULL. Assert the same RESOLVED predicate governs. | Research N7: today this site has **no** `pnl IS NOT NULL` filter at all. Not a correctness bug (zeros sum to zero) but a fifth reader disagreeing about what a trade is. |

### Group F — The headline is the reconciled number, and says so when it isn't

| # | Case | Test | Proves |
|---|---|---|---|
| **19** | **Headline P&L is Alpaca-derived/reconciled, not the trade-log sum.** | Seed a `reconciliation` row with `alpaca_realized_pnl=+500`, `trade_log_pnl=+900` (a $400 delta). Assert the headline reports **+500** (+ live unrealized), **not** +900. | RUN-02 core. The overstated trade-log sum stops being the headline. |
| 20 | `pnl_source` ∈ `{reconciled, alpaca_live, trade_log}` is surfaced and correct. | (a) fresh `reconciliation` row → `"reconciled"`. (b) no row, Alpaca reachable → `"alpaca_live"`. (c) no row, Alpaca unreachable → `"trade_log"`. | `portfolio.py:111-122` **silently** falls back from Alpaca to the trade-log sum today with **no flag on the response**. The consumer can no longer be misled about which number it is looking at. |
| 21 | `stale: bool` is surfaced — no row, **or** `checked_at` older than 2× `RECONCILE_INTERVAL_HOURS`. | (a) no row → `stale=True`. (b) `checked_at` 3h old (interval=1h) → `stale=True`. (c) 30min old → `stale=False`. | The number is still shown when stale, but **flagged**. The dashboard never presents an unreconciled figure as reconciled. |
| **22** | **`settings.py:65`'s hardcoded `100_000.0 * len(bot_ids)` is GONE.** | Seed `bots.starting_equity` to a **non-100000** value (e.g. `50_000`). Assert `GET /api/settings` `equity` derives from `bots.starting_equity` (via `db.get_starting_equity`, `db.py:322-331`), **not** from `100_000 * len(bot_ids)`. Grep-assert the literal `100_000.0 * len(` is absent from `settings.py`. | **MUST FAIL on current `main`.** A hardcoded bankroll in the paper-gate readout is exactly how a gate gets passed by a bug. |
| **23** | **Hourly `reconcile()` is guarded PER BOT — one keyless bot cannot starve the others.** | Two enabled bots; `_client_for_bot('X')` raises `ValueError` (keyless), `'A'` succeeds. Call the watchdog's reconcile step. Assert **A still reconciled and persisted**, X logged as failed, no exception escapes. | **Research N1 — the phase's own landmine.** `reconciliation.py:139-143` has **no `try`**, and `_client_for_bot` raises (`:86-90`); `_enabled_bot_ids` (`:51-59`) already selects `enabled = TRUE` with **no key predicate**. The B1 fix makes keyless-enabled bots *more* likely — so scheduling this unguarded converts one misconfigured bot into **total, silent reconciliation failure**. |
| 24 | The hourly reconcile step self-throttles and never kills the watchdog. | Tick 3× inside an hour → `reconcile()` called **once**. Make `reconcile()` raise → assert the watchdog loop survives and later steps still run. | Mirrors the existing interval-guard pattern (`bot_manager.py:149-151`) and the per-step `try/except` (`:88-95`). No new thread, no cron. |

### Group G — The heartbeat is queryable from outside the process

| # | Case | Test | Proves |
|---|---|---|---|
| **25** | **Heartbeat is queryable from OUTSIDE the process.** | Run a watchdog tick. Assert a `runtime_heartbeat` row exists for `component='bot_manager'` with fresh `beat_at`, correct `bots_alive` / `bots_enabled`. Read it back via a **plain SQL SELECT**, not via the manager object. | B3 fixed. Nothing outside the process can distinguish "manager running, bots healthy" from "manager never started" today — `main.py:65-66` swallows the failure into a `log.warning`. |
| **26** | **Absence-of-row ⇒ `manager_alive == False` (never default-healthy).** | Empty `runtime_heartbeat`. Assert `GET /api/settings` reports `manager_alive=False`. | **Research N10 — the subtle one.** `self._watchdog.start()` (`:79`) sits **after** the `start_all` query that can throw (`:67-70`), so a heartbeat written *by the watchdog* **cannot** report its own non-existence. Absence must be the signal. A reader that defaults healthy on a missing row reintroduces the exact silent failure this phase exists to kill. |
| 27 | A stale heartbeat ⇒ `manager_alive == False`. | `beat_at` = now − 300s, `HEARTBEAT_STALE_SECONDS=180`. Assert `manager_alive=False`. Then `beat_at` = now − 30s → `True`. | Freshness, not mere existence, is liveness. |
| 28 | `main.py`'s `except` branch (`:65-66`) alerts on a never-started manager. | Force `BotManager(db_url)` / `start_all()` to raise. Assert an alert is fired **from `main.py`**, not from the manager. | The manager cannot alert about its own non-existence (N10). Today `:65-66` only calls `_log.warning` — into the void. |
| 29 | Migration `019` is additive and idempotent; `db_schema.sql` mirrors it. | Apply `019_runtime_heartbeat.sql` twice (`CREATE TABLE IF NOT EXISTS`) → no error. Assert `runtime_heartbeat` also appears in `src/db_schema.sql`. | **Research N3:** `db_schema.sql:212-215` hand-mirrors migration `017`. A table added *only* as a migration is **missing from every fresh-DB bootstrap**. Both files, or the table silently does not exist. `019` confirmed as the next free number (highest is `018_universe_quarantine.sql`). |

---

## Fences — assertions that must hold at phase exit

| # | Case | Test | Proves |
|---|---|---|---|
| **F1** | **NO write to `alpaca_trades`.** The 395 `pnl=0.0` sentinels are **read around, not repaired**. | Grep-assert **zero** `UPDATE alpaca_trades` / `DELETE FROM alpaca_trades` / backfill invocation in the phase diff. Assert `src/backfill.py` is **not called** from `bot_manager` or any route. | HARD fence. `src/backfill.py:142-143` already exists and is a loaded gun. Repairing historical prod trade data needs **explicit human authorization** — flag in SUMMARY, do not do, including "while we're in there." |
| **F2** | **Hardcoded risk rules untouched.** | Grep-assert no diff to: max 5% bankroll/position, quarter-Kelly ceiling, 20% drawdown stop, limit-orders-only, 50-paper-trade gate. `BotUpdate.kelly_fraction` keeps `le=0.25` (`models.py:260-262`). | CLAUDE.md risk rules are never overridden. |
| **F3** | **Paper gate stays closed.** | Assert `mode == "paper"` and the gate logic is unchanged — only its *inputs* got honest. | Making the readout honest may make it read **worse**. The gate is not unlocked here. |
| **F4** | **No new email provider.** | Grep-assert no `sendgrid`/`resend`/`postmark`/`mailgun`; new alerts are new wrappers in `src/notifier.py` reusing `send_alert`. | CONTEXT decision 2. |
| **F5** | **No retune.** | Grep-assert no diff to `min_confluence`, `kelly_fraction`, `quarantined_symbols` values. | Phase 21 owns the retune. |
| **F6** | **One Alpaca account per bot.** | Assert the scheduled reconcile still routes through `reconciliation._client_for_bot` (`:62-93`) — never a shared or bare-key client. | CLAUDE.md hard rule; `_client_for_bot` already enforces it. Do not regress while scheduling. |
| **F7** | **No prod deploy-config change.** | Coolify restart policy is **verified read-only and reported**. Assert no Coolify env/config mutation in the phase. | CONTEXT fence. Also **N4**: restart policy is a *red herring* — the container is up; only the threads are dead. No restart policy restarts a thread. If a task frames it as part of the fix, that task is wrong. |
| **F8** | **Full suite does not regress.** | `pytest -q` → **≥ 428 passed / 28 skipped**. | Baseline floor. Note: `tests/test_db.py` assertions **will need updating** for the new RESOLVED predicate (case 14) — that is the fix landing, not a regression. |

---

## Definition of Done

1. Cases **1, 5, 6, 13, 15, 17, 22, 23, 26** demonstrably **FAIL on current `main`** and **PASS** after the fix. (A test that passes pre-fix is not testing the bug.)
2. All 29 cases + 8 fences green.
3. `pytest -q` ≥ 428 passed / 28 skipped.
4. `alpaca_trades` byte-identical — verified by diff.
5. The 395 sentinels are **flagged in SUMMARY as requiring explicit human authorization to repair**, and untouched.
</content>
</invoke>
