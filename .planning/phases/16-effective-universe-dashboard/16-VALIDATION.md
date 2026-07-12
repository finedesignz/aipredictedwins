---
phase: 16
slug: effective-universe-dashboard
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-12
updated: 2026-07-12   # revised after plan-check: +case 18 (shadow sets are confluence-only), +case 11b (exposure_loaded)
---

# Phase 16 — Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (+ FastAPI `TestClient`) |
| **Quick run** | `python -m pytest tests/test_effective_universe.py -q` |
| **API run** | `TEST_DATABASE_URL=<local pg> python -m pytest tests/test_effective_universe.py -q` (cases 14-17; MUST be run for real — the exposure SQL has no other execution path) |
| **Full suite** | `python -m pytest tests/ -q` (baseline 358 passed, 5 skipped) |
| **Frontend** | no test framework exists — verify with `npm run build` + screenshots (LOCAL stack only) |

## Validation Architecture (UNIV-03)

Pure resolver in `src/effective_universe.py` (zero I/O, unit-tested), thin route on top.

| # | Case | Test | Proves |
|---|------|------|--------|
| 1 | confluence bot: effective = cfg.symbols − quarantine − meme − untradeable | test_effective_confluence | core resolver |
| 2 | quarantined symbol appears in blocked with reason='quarantined' | test_blocked_reason_quarantined | UNIV-02 surfaced |
| 3 | on a CONFLUENCE bot: meme symbol → reason='meme'; untradeable → reason='untradeable' | test_blocked_reason_shadow_sets | Decision 3b (the DOT/LINK/ETH lie) |
| 4 | reason precedence is deterministic + documented (quarantined > off_universe > meme > untradeable) | test_reason_precedence | no ambiguous label |
| 5 | trend bot allowlist includes cfg.trend_symbol (BITX) | test_effective_trend_carveout | matches gate |
| 6 | copytrade bot allowlist = cfg.all_symbols (crypto ∪ stock) | test_effective_copytrade_union | matches gate |
| 7 | bot_c allowlist = cfg.symbols (stock_universe) | test_effective_bot_c | matches gate |
| 8 | strategy dispatch comes from the bots.strategy column, not a thread | test_allowlist_by_strategy_column | API needs no thread |
| 9 | effective set empty → starvation flag True | test_starvation_flag | over-quarantine visible |
| 10 | a blocked/off_universe symbol WITH an open position or recent trade → leak flag True | test_leak_flag | the TRUMP/FIL case |
| 11 | no exposure on a blocked symbol → leak False; a QUARANTINED symbol holding an open position is NOT a leak | test_no_false_leak | no crying wolf |
| 11b | exposure query failed → `exposure_loaded: false` AND `leak: []` means UNKNOWN, not "no leak" | test_exposure_unloaded_is_unknown_not_no_leak | the leak signal never fails silent |
| 12 | symbol normalization on BOTH sides (alpaca_trades.symbol is mixed BTCUSD / BTC/USD) | test_leak_normalization | format skew |
| 13 | **the panel cannot drift from the gate**: for every symbol the resolver calls `universe.entry_allowed` — a symbol the gate BLOCKS is never reported effective. Non-vacuity-guarded (blocked non-empty, iterated count > 0, ≥1 gate-blocked symbol per strategy). | test_resolver_agrees_with_gate | anti-lie invariant |
| 14 | `GET /api/bots/{bot_id}/universe` → 200, Envelope shape, all keys incl. `shadow_applied` + `exposure_loaded`, and NO key/secret field | test_universe_route_200 | route contract |
| 15 | unknown bot_id → 404 | test_universe_route_404 | error path |
| 16 | route is read-only: no writes (row counts unchanged), no Alpaca client (static source guard) | test_universe_route_readonly | scope fence |
| 17 | the route appears in `/openapi.json` | test_openapi_contains_universe_route | docs contract |
| 18 | **the shadow sets are CONFLUENCE-ONLY**: copytrade effective INCLUDES ETH/USD (not struck through); `shadow_applied` is False for copytrade / trend_btc / tradingagents | test_shadow_sets_confluence_only | Decision 3b, corrected — no false strike-through |

Wave 0 gap: `tests/test_effective_universe.py` does not exist — created RED before implementation.

### Why case 18 exists (the B1 correction)

`MEME_CRYPTO` (`src/alpaca_evaluator.py:42`) and `_ALPACA_UNTRADEABLE`
(`src/alpaca_orchestrator.py:79-84`) are enforced at exactly two places: the confluence selectors
`select_long_candidates` / `select_short_candidates` (`src/bot_thread.py:144-145`, `163-164`) and the
CLI orchestrator. They appear **nowhere** in `src/copytrade_thread.py`, `src/trend_strategy.py` or
`src/bot_c/strategy.py` — `bot_thread` dispatches `trend_btc` → `run_trend_cycle` (`:551`) and
`tradingagents` → `run_tradingagents_cycle` (`:560`), both of which bypass the selectors entirely.

So subtracting them for every strategy would invent a **new** lie: Bot E (copytrade) really does trade
ETH/USD when its leader does, but the panel would strike it through as `untradeable`. The subtraction is
therefore strategy-conditional (`shadow_applies_to`), and case 18 pins it.

## Known over-report (carry into VERIFICATION.md — W2)

For `trend_btc` the panel reports `allowlist = cfg.symbols + [BITX]` because that is exactly what the
**gate** permits (`src/trend_strategy.py:103`) — but the trend cycle in practice only ever *enters*
`cfg.trend_symbol` (BITX). The panel therefore over-reports the trend bot's real trading surface. This is
consistent with CONTEXT Decision 2 (mirror the gate, not the strategy's internal appetite) and is
deliberately not special-cased — but it must be recorded as a known over-report.

## Frontend verification (no test framework — evidence-based)

- `npm run build` succeeds (the drifted `types/index.ts` `BotFull` is realigned as part of this phase —
  note it does not currently *break* `tsc`; it is fixed because a silently drifted client contract is the
  very failure mode this phase exists to kill).
- Screenshots of a bot card showing: effective chips, blocked chips struck-through with a **visible**
  reason (no hover-only `title` — `Badge` has no `title` prop), the `N of M tradeable` count, and both
  warning states (leak, starvation).
- **All evidence is captured against a LOCAL stack + LOCAL/TEST Postgres.** Never the deployed dashboard,
  never the prod DB — forcing STARVATION on a live bot would starve a real trader, and seeding a phantom
  open TRUMP/USD row would be ingested by the Phase-13/14 reconciliation + backfill jobs.

## Nyquist Compliance

- UNIV-03 → cases 1–18 + the build/screenshot evidence.
- `nyquist_compliant` flips true when the suite passes (18/18 with a real `TEST_DATABASE_URL`, 0 skipped)
  and the three screenshots exist.
</content>
