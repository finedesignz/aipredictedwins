---
phase: 19-reliable-runtime
plan: 03
subsystem: runtime
tags: [run-01, killer-bug, watchdog]
requires: [19-02]
provides: [BotManager._tick, BotManager._check_bots_down, BotManager._has_keys, BotManager._enabled_rows, BotManager._heartbeat, never-started-alert]
key-files:
  modified:
    - src/bot_manager.py
    - dashboard/api/main.py
metrics:
  commit: 65c84d2
---

# Phase 19 Plan 03: The Killer Bug Dies Summary

## THE DELETE — before / after

**Before** (`src/bot_manager.py:186-190`, inside `_check_trade_silence`, immediately before
the only alert that fires on "nothing is happening"):

```python
        # Check at least one bot is running — silence expected if all bots are down
        with self._lock:
            any_alive = any(t.is_alive() for t in self._threads.values())
        if not any_alive:
            return  # bots are down; death alert handles that separately
```

**After:** gone. Trade silence is evaluated on its own merits. All-bots-down is its own,
louder, independent alert.

That comment was a lie. The death alert it deferred to **could not fire**: `_revive_dead_bots`
only iterated rows the key predicate at `:104-107` had already removed. All-bots-down — the
single most important state in the system — was **guaranteed silent**. Four bots stopped and
nothing said a word.

`grep -c "if not any_alive" src/bot_manager.py` → **0**.
`grep -c "Both bots are currently running" src/bot_manager.py` → **0**.

## THE TICK ORDER — as load-bearing as the delete itself

```python
def _tick(self) -> None:
    with self._lock:
        alive_before = sum(1 for t in self._threads.values() if t.is_alive())   # 1. SNAPSHOT
    enabled = len(self._enabled_rows())
    hours_since_trade = self._hours_since_last_trade()

    for step in (
        lambda: self._check_bots_down(alive_before, enabled, hours_since_trade),  # 2
        self._revive_dead_bots,                                                   # 3
        self._check_trade_silence,                                                # 4
        self._heartbeat,                                                          # 5
        self._maybe_reconcile,                                                    # 6 (19-05)
    ):
        try:
            step()
        except Exception as exc:
            log.warning("BotManager tick step error: %s", exc)
```

`_revive_dead_bots` calls `_spawn` → `thread.start()`. If liveness were read **after** the
revive — or recomputed inside `_check_bots_down` — then in the dominant failure mode (threads
crash-loop every cycle on bad keys, a 401, or an unhandled exception in `_main_loop`)
`alive > 0` on EVERY tick and **the alert would never fire in production**. The same silence,
reintroduced. `alive_before` is a **parameter** for exactly that reason.

`sed -n '/def _check_bots_down/,/    def /p' src/bot_manager.py | grep -c "is_alive()"` → **0**.

The cooldown is reset **only when `alive_before > 0`** — never merely because a revive
succeeded later in the tick, or a crash-looping system would reset it every 60s and "repeats
until one is alive" would be a lie. `_maybe_reconcile` runs LAST so a slow or raising
reconcile cannot delay or suppress the alert.

## THE KEYLESS PREDICATE — BOTH keys

`_has_keys(row)` requires `alpaca_api_key AND alpaca_secret_key`. An api-key-only check lets
an empty-**secret** row through to `_spawn`: `bot_config.py:46-47` coerces the missing secret
to `""` (legal), `bot_thread.py:118-126` passes it straight into `Config` with no env reads,
and `config.py:74-76`'s frozen dataclass **does not raise** → 401 → `status='error'` → thread
exits → revived again in 60s, forever (the 1h cooldown throttles the EMAIL, not the SPAWN).

`sed -n '/def _has_keys/,/^$/p' src/bot_manager.py | grep -c "alpaca_secret_key"` → **1**.

Both key predicates (`:67-70` and `:104-107`) are DELETED — one `_enabled_rows()` query,
`SELECT * FROM bots WHERE enabled = TRUE`, called from both sites. A keyless enabled bot is now
`status='error'` + `status_detail='missing alpaca keys'` + one alert per hour, **before** the
death-alert branch and **never** spawned (research N5). Status writes route through
`_on_status_change` — the sole SQL writer — so the fix is thread-class-agnostic
(CopyTraderThread has its own `_set_status`, refuting the CONTEXT claim).

## The never-started alert (research N10)

`dashboard/api/main.py`'s lifespan now calls `alert_manager_never_started(...)` from the
`except` branch AND from the missing-`DATABASE_URL` branch, which was **completely silent**
before (`:55`'s `if db_url:` skipped the whole block). The import is FUNCTION-LOCAL, after the
`sys.path` insert, inside its own try/except — an alert failure must never take the API down.
This alert cannot live in BotManager: `self._watchdog.start()` (`:79`) sits AFTER the
`start_all` query that can throw (`:67-70`), so the watchdog cannot report its own
non-existence.

`start_all` now also logs `alerts_configured()` / `last_alert_error()` at INFO.

## Verification

- `tests/test_bot_manager.py` — 14/15 GREEN, **including cases 1 AND 1b**. Case 24 remained
  the sole RED (19-05 owns `_maybe_reconcile`) and is now green.
- `dashboard/api/tests/test_lifespan_alert.py` — case 28 GREEN.
- `grep -cE "UPDATE alpaca_trades|DELETE FROM alpaca_trades|backfill" src/bot_manager.py` → 0.

## Deviations from Plan

**1. Extracted `_last_trade_ts()` / `_hours_since_last_trade()`** from `_check_trade_silence`
so `_tick` can pass `hours_since_trade` into `_check_bots_down` without a second copy of the
MAX(timestamp) query and the tz-normalisation. Both return `None` on a DB error or a fresh
deployment — never a fabricated number.

**2. `_maybe_reconcile` was added to `_tick`'s step tuple in 19-05, not here.** Referencing an
attribute that does not exist yet would have raised outside the per-step try/except and broken
the whole tick. 19-03 shipped five steps; 19-05 added the sixth.

## Self-Check: PASSED
