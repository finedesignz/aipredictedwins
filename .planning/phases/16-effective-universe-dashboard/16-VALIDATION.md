---
phase: 16
slug: effective-universe-dashboard
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-12
---

# Phase 16 — Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (+ FastAPI `TestClient`) |
| **Quick run** | `python -m pytest tests/test_effective_universe.py -q` |
| **API run** | `python -m pytest dashboard/api/tests/test_routes.py -q` (TEST_DATABASE_URL-gated) |
| **Full suite** | `python -m pytest tests/ -q` (baseline 358 passed, 5 skipped) |
| **Frontend** | no test framework exists — verify with `npm run build` + a screenshot |

## Validation Architecture (UNIV-03)

Pure resolver in `src/effective_universe.py` (zero I/O, unit-tested), thin route on top.

| # | Case | Test | Proves |
|---|------|------|--------|
| 1 | confluence bot: effective = cfg.symbols − quarantine − meme − untradeable | test_effective_confluence | core resolver |
| 2 | quarantined symbol appears in blocked with reason='quarantined' | test_blocked_reason_quarantined | UNIV-02 surfaced |
| 3 | meme symbol → reason='meme'; untradeable → reason='untradeable' | test_blocked_reason_shadow_sets | Decision 3b (the DOT/LINK/ETH lie) |
| 4 | reason precedence is deterministic + documented (quarantined > off_universe > meme > untradeable) | test_reason_precedence | no ambiguous label |
| 5 | trend bot allowlist includes cfg.trend_symbol (BITX) | test_effective_trend_carveout | matches gate |
| 6 | copytrade bot allowlist = cfg.all_symbols (crypto ∪ stock) | test_effective_copytrade_union | matches gate |
| 7 | bot_c allowlist = cfg.symbols (stock_universe) | test_effective_bot_c | matches gate |
| 8 | strategy dispatch comes from the bots.strategy column, not a thread | test_allowlist_by_strategy_column | API needs no thread |
| 9 | effective set empty → starvation flag True | test_starvation_flag | over-quarantine visible |
| 10 | a blocked/off_universe symbol WITH an open position or recent trade → leak flag True | test_leak_flag | the TRUMP/FIL case |
| 11 | no exposure on a blocked symbol → leak flag False | test_no_false_leak | no crying wolf |
| 12 | symbol normalization on BOTH sides (alpaca_trades.symbol is mixed BTCUSD / BTC/USD) | test_leak_normalization | format skew |
| 13 | **the panel cannot drift from the gate**: for every symbol the resolver calls `universe.entry_allowed` — a symbol the gate BLOCKS is never reported effective | test_resolver_agrees_with_gate | anti-lie invariant |
| 14 | `GET /api/bots/{bot_id}/universe` → 200, Envelope shape, all keys | test_universe_route_200 | route contract |
| 15 | unknown bot_id → 404 | test_universe_route_404 | error path |
| 16 | route is read-only: no writes, no Alpaca client constructed | test_universe_route_readonly | scope fence |
| 17 | the route appears in `/openapi.json` | test_openapi_contains_universe_route | docs contract |

Wave 0 gap: `tests/test_effective_universe.py` does not exist — created RED before implementation.

## Frontend verification (no test framework — evidence-based)

- `npm run build` succeeds (fixing the drifted `types/index.ts` `BotFull` is a prerequisite).
- Screenshot of a bot card showing: effective chips, quarantined struck-through with reason, the
  `N of M tradeable` count, and both warning states (leak, starvation) rendered.

## Nyquist Compliance

- UNIV-03 → cases 1–17 + the build/screenshot evidence.
- `nyquist_compliant` flips true when the suite passes and the screenshot exists.
