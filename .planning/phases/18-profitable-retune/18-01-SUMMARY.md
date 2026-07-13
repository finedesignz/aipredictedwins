---
phase: 18
plan: 01
subsystem: tests
requirements: [TUNE-01, TUNE-03]
key-files:
  created: [tests/test_external_exit_resolution.py, tests/test_db_readonly.py, tests/test_rollout_config.py, tests/backtester/test_cli_overrides.py, tests/backtester/synth_bars.py, dashboard/api/tests/test_portfolio_win_rate.py]
  modified: [tests/test_db.py, tests/backtester/test_engine.py]
commits: [c142cbe, 19aed6f, 0bb7f24]
---

# Phase 18 Plan 01: RED suite Summary

All 29 VALIDATION cases (+4b, +5b, +28b/c/d) have a named test, written before any `src/` or
`dashboard/` change. RED confirmed: 11 intended failures + 1 intended ImportError
(`_resolve_external_exit` did not exist).

## Notable

- **Cases 9-12** could not use `tests/test_db.py`'s existing style (the whole module was
  `DATABASE_URL`-gated and would have SKIPPED, and a skip is not a RED). The module gate was
  moved onto the two existing Postgres smoke tests individually, and cases 9-12 drive
  `get_alpaca_accuracy` through a fake connection that **honours the SQL it is handed** — it
  applies the NULL filter only if the query asks for it, so the fix cannot pass vacuously.
- **Cases 28 / 28b / 28c / 28d** are closed by Plan **18-07**, which is HELD for human
  authorization (its later tasks write the prod `bots` row). They are marked
  `xfail(strict=True)`: recorded, failing, and they flip green the moment 18-07 lands (a strict
  xfail that starts passing is itself a failure, so this cannot rot).
- **Case 21's golden** was generated from the PRE-Phase-18 engine on deterministic synthetic
  bars (`tests/backtester/synth_bars.py` — a closed-form price path, no RNG, no I/O). The 60-bar
  BTC fixture affords at most one scan and yields no usable trade history to pin.
- Case 18 (the confluence ceiling really is 4) and case 22 (determinism) passed on day one, as
  the plan predicted.
- Case 29's fence targets tests that **point the pool at a non-test database**; read-only gating
  on `DATABASE_URL` (pre-existing, e.g. `tests/test_universe.py:425`) is allowed. The self-test
  on `src/db.py::update_alpaca_trade` fires, so the detector is not vacuous.

## Self-Check: PASSED
