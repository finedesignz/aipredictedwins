---
phase: 19-reliable-runtime
plan: 05
subsystem: reconciliation
tags: [run-02, landmine-n1, scheduling]
requires: [19-03]
provides: [reconcile-per-bot-guard, BotManager._maybe_reconcile]
key-files:
  modified:
    - src/reconciliation.py
    - src/bot_manager.py
metrics:
  commit: 8fe0007
---

# Phase 19 Plan 05: Defuse, Then Schedule Summary

## The landmine (research N1) — defused first

`reconcile()` (`:139-143`) had **no per-bot try**:

```python
    for bot_id in _enabled_bot_ids():
        client = _client_for_bot(bot_id)        # RAISES on a keyless bot (:86-90)
        results.append((bot_id, reconcile_bot_live(bot_id, client, tolerance)))
```

`_enabled_bot_ids` (`:51-59`) selects `enabled = TRUE` with **no key predicate**, and
`_client_for_bot` **raises** `ValueError` on a keyless bot. So today, one misconfigured bot
already makes the manual `scripts/reconcile.py` throw and reconcile **zero** bots — including
the healthy ones. A live latent bug, not a hypothetical. And 19-03's fix makes keyless-enabled
bots *visible*, so scheduling this unguarded would have turned it into total, silent
reconciliation failure exactly when we touched it.

Now: a per-bot `try/except Exception` wraps BOTH the `_client_for_bot` call and the
`reconcile_bot_live` call. The bad bot is logged (`Reconciliation failed for bot %s: %s`) and
**skipped**; the healthy bots still reconcile and persist; nothing escapes. Diff: 9 lines.

`_client_for_bot` **keeps raising** — it is the one-account-per-bot enforcement point
(CLAUDE.md hard rule, fence F6). The CALLER changed, not the guard. No key predicate was added
to `_enabled_bot_ids`: a keyless enabled bot SHOULD be attempted and SHOULD be logged as
failed — hiding it there would recreate the exact invisibility 19-03 just deleted.

## Then scheduled

`_RECONCILE_INTERVAL_HOURS = float(os.environ.get("RECONCILE_INTERVAL_HOURS", "1"))` and
`BotManager._maybe_reconcile`: the interval guard copied in shape from
`_check_trade_silence:149-151`, then a lazy `from src import reconciliation` (matching
`_maybe_send_death_alert`'s idiom).

It is the **LAST step of `_tick`**, in its own `try/except`. `_check_bots_down` runs FIRST, so
a slow or raising reconcile can never delay or suppress the ALL BOTS DOWN alert — and a
throwing reconcile cannot kill the tick or the heartbeat written earlier in it.

**No second thread. No scheduler. No cron. No new container. No frontend poll loop.** The
supervisor already ticks every 60 seconds; this rides it.

`grep -c "threading.Thread" src/bot_manager.py` → **1** (the pre-existing watchdog).
`grep -cE "AlpacaClient|ALPACA_API_KEY" src/bot_manager.py` → **0** (fence F6).

## Verification

- `tests/test_reconciliation.py` — case **23 GREEN** (was RED: the `ValueError` propagated and
  reconciled ZERO bots), plus a companion case proving a raising `reconcile_bot_live` (an
  Alpaca timeout) costs exactly one bot. Every pre-existing reconciliation test still passes.
- `tests/test_bot_manager.py` — **ALL GREEN**, including case **24** (the last RED in the file)
  and, still, cases **1 and 1b** — the reconcile step did not disturb the tick order.
- `reconcile()`'s only DB write remains the `reconciliation` UPSERT (additive, non-trade). It
  is read-only against Alpaca and against `alpaca_trades`.

## Deviations from Plan

None — plan executed as written.

## Self-Check: PASSED
