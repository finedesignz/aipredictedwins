---
phase: 19-reliable-runtime
plan: 01
subsystem: tests
tags: [tdd, red, run-01, run-02]
requires: []
provides: [tests/test_bot_manager.py, tests/test_notifier_selfcheck.py, tests/test_phase19_fences.py, dashboard/api/tests/test_heartbeat.py, dashboard/api/tests/test_lifespan_alert.py]
affects: [tests/test_db.py, tests/test_reconciliation.py, dashboard/api/tests/test_portfolio_win_rate.py, dashboard/api/tests/test_routes.py]
key-files:
  created:
    - tests/test_bot_manager.py
    - tests/test_notifier_selfcheck.py
    - tests/test_phase19_fences.py
    - dashboard/api/tests/test_heartbeat.py
    - dashboard/api/tests/test_lifespan_alert.py
  modified:
    - tests/test_db.py
    - tests/test_reconciliation.py
    - dashboard/api/tests/test_portfolio_win_rate.py
    - dashboard/api/tests/test_routes.py
metrics:
  commit: fc806c0
---

# Phase 19 Plan 01: The RED Suite Summary

`tests/test_bot_manager.py` did not exist. RUN-01 was entirely untested — which is exactly
how `src/bot_manager.py:186-190`'s `if not any_alive: return` survived long enough for four
bots to stop in silence. It exists now, and all 29 VALIDATION cases + the three plan-check
additions (1b, 5b, 12b) + the 8 fences have a named test.

## The eleven must-fail cases — VERBATIM pre-fix failure lines

| Case | Test | Verbatim pre-fix failure |
|------|------|--------------------------|
| 1 | `test_all_bots_down_alerts` | `E AttributeError: 'BotManager' object has no attribute '_check_bots_down'` |
| **1b** | `test_all_bots_down_alerts_through_a_whole_tick` | `E AttributeError: 'BotManager' object has no attribute '_tick'. Did you mean: '_lock'?` |
| 5 | `test_keyless_enabled_bot_is_error_and_alerts` | `E AssertionError: assert ('X', 'error', 'missing alpaca keys') in []` |
| **5b** | `test_api_key_without_secret_is_also_keyless` | `E AssertionError: assert ('Y', 'error', 'missing alpaca keys') in []` |
| 6 | `test_keyless_bot_is_not_spawned_and_gets_no_death_alert` | `E AssertionError: assert ['Y'] == []` / `E Left contains one more item: 'Y'` |
| 13 | `test_zero_pnl_is_not_a_loss` | `E assert 2 == 1` (losses; the 0.0 sentinel booked as a loss) |
| 15 | `test_portfolio_win_rate_excludes_sentinels` | `E AssertionError: the headline win rate still books ~395 pnl=0.0 sentinels as LOSSES` / `E assert 'pnl <> 0' in '"""\nPortfolio summary endpoint...'` |
| 17 | `test_paper_gate_win_rate_excludes_sentinels` | `E AssertionError: the PAPER GATE win rate still books pnl=0.0 sentinels as LOSSES` / `E assert 'pnl <> 0' in '"""\nSettings endpoint...'` |
| 22 | `test_settings_equity_is_not_hardcoded` | `E AssertionError: the paper gate is still evaluated against a HARDCODED $100k bankroll` / `E '100_000.0 * len(' is contained here: equity = 100_000.0 * len(bot_ids) + total_pnl` |
| 23 | `test_reconcile_is_guarded_per_bot` | `E ValueError: No Alpaca keys for bot X` (propagated out of `reconcile()` — ZERO bots reconciled) |
| 26 | `test_absence_of_row_means_dead` | `E ImportError: cannot import name 'HEARTBEAT_STALE_SECONDS' from 'db'` |

Bonus RED (case 14): `E AssertionError: unresolved` / `assert 'unresolved' in {'avg_pnl': 1.67, 'crypto_pnl': 5.0, 'losses': 2, 'resolved': 3, ...}`.
Bonus RED (case 12b/10-12): `E ImportError: cannot import name 'alert_all_bots_down' from 'src.notifier'`.

**No case passed pre-fix that should have failed.** Cases 8, 9 and 9b passed pre-fix by
design — they pin behaviour that must NOT change.

## The two traps the tests are built to catch

**Case 1b (T-19-32).** Case 1 drives `_check_bots_down` directly with an empty thread dict —
a shape that never occurs in production. `_revive_dead_bots` respawns via `_spawn` →
`thread.start()`, so a bot revived earlier in the same tick is `is_alive() == True` by the
time a later check runs. In the dominant failure mode (crash-loop on bad keys / a 401 / an
unhandled exception) that means `alive > 0` on EVERY tick and the alert never fires. Case 1b
drives the whole integrated `_tick()` with a **succeeding** revive (the FakeThread's
`start()` really does flip `is_alive()` to True) and asserts the alert fires anyway, then
ticks a second time with the threads crash-dead again to prove the cooldown was not reset by
the transient revive.

**Case 5b (T-19-34).** An api-key-only keyless check spawns an empty-**secret** row. Traced:
`bot_config.py:46-47` (`or ""` — empty is legal) → `bot_thread.py:118-126` (no env reads) →
`config.py:74-76` (frozen dataclass, **does not raise**). Case 6 confirmed it: pre-fix, bot
`Y` (api key, no secret) WAS spawned (`assert ['Y'] == []`).

## Safety

- `BotManager._spawn` is monkeypatched to a FakeThread installer for **every** case by
  default (plan-check W1), not just 1b. The real `_spawn` constructs a live
  `BotThread`/`CopyTraderThread` and starts a live trading loop. **No test constructed a real
  BotThread. No test touched live Alpaca, SES, or the prod DB.**
- The `FakeConn` HONOURS `alpaca_api_key IS NOT NULL`, so cases 5/6's RED reason is real and
  case 8 is non-vacuous.
- `src.bot_manager.ConnectionPool` is monkeypatched before any BotManager is constructed. The
  watchdog thread is never started. Time is frozen, never slept.
- Every static/grep case asserts a POSITIVE CONTROL first.

## Deviations from Plan

**1. [Rule 3 — Blocking] `dashboard/api/tests/test_routes.py`'s module-level `pytestmark`
made an UNGATED test impossible.** The plan requires the `100_000.0 * len(` grep fence to run
with no database, but the module skipped wholesale without `TEST_DATABASE_URL`. Moved the
gate into the `client` fixture (`pytest.skip(...)` inside it). Every DB-backed test still
skips visibly; the skip count is unchanged; the two new static fences now run everywhere.

**2. [Rule 2 — Correctness] `tests/test_phase19_fences.py` F1 excludes test modules from the
trade-writer scan.** As first written it flagged `dashboard/api/tests/test_portfolio_win_rate.py`
(a pre-existing `DELETE FROM alpaca_trades` against a TEST database only). F1 is about SOURCE
writers; test modules are permitted to seed/clean `TEST_DATABASE_URL`. The self-test still
proves the detector fires on `src/db.py::update_alpaca_trade`.

**3. `tests/test_db.py::test_null_pnl_excluded_from_denominator` was updated in place**
(`losses == 4` → `losses == 3`, `resolved == 6` → `5`), as the plan instructs. That assertion
was documenting the bug.

## Self-Check: PASSED
All five new files exist; commit `fc806c0` is in `git log`.
