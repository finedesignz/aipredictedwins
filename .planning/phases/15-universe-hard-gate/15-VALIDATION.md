---
phase: 15
slug: universe-hard-gate
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-12
updated: 2026-07-12
---

# Phase 15 — Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Quick run** | `python -m pytest tests/test_universe.py -q` |
| **Full suite** | `python -m pytest tests/ -q` (baseline 336 passed, 4 skipped) |

## Validation Architecture (UNIV-01, UNIV-02)

Pure gate + wiring, zero-network fakes (reuse the `FakeAlpacaClient`/`FakeLogger` convention from
`tests/test_order_resolution.py` / `tests/test_backfill.py`).

| # | Case | Test | Proves |
|---|------|------|--------|
| 1 | allowlisted symbol passes the gate | test_allowed_symbol_passes | UNIV-01 happy path |
| 2 | off-universe symbol (TRUMP/USD) blocked, reason='off_universe' | test_off_universe_blocked | UNIV-01 |
| 3 | quarantined symbol (BTC/USD) blocked, reason='quarantined'; quarantine PRECEDES allowlist | test_quarantined_blocked | UNIV-02 |
| 4 | normalize: `BTC/USD` == `BTCUSD` == `btc/usd`; idempotent; total | test_normalize_formats | format skew |
| 5 | empty quarantine string quarantines nothing; empty allowlist allows everything | test_empty_quarantine_noop | safe defaults (Decision 4) |
| 6 | `_submit_order` on a blocked symbol: NO Alpaca call, terminal 'rejected' row (pnl=0), returns (None, None) | test_submit_order_blocks_off_universe | gate of record |
| 7 | `_submit_order` on a blocked symbol logs a WARNING with bot_id/symbol/reason | test_submit_order_logs_rejection | UNIV-01 "rejection is logged" |
| 8 | `_submit_order` on an allowlisted symbol still submits (no regression) | test_submit_order_allows_universe_symbol | no false block |
| 9 | select_long_candidates drops off-universe + quarantined, keeps allowlisted | test_select_long_universe_filter | early filter |
| 10 | select_short_candidates drops off-universe + quarantined (a sell-to-OPEN is an entry) | test_select_short_universe_filter | shorts gated too |
| 11 | EXITS are never gated: close path for a quarantined open position still runs | test_exit_not_gated | can always close |
| 12 | trend strategy: `cfg.trend_symbol` (BITX) passes though not in stock_universe (allowlist = cfg.symbols ∪ {trend_symbol}) | test_trend_symbol_allowed | trend carve-out |
| 13 | copytrade entry on a NOT-held off-universe symbol is blocked; allowlist = `cfg.all_symbols` (crypto ∪ stock) so a legitimate cross-asset-class mirror still passes | test_copytrade_entry_blocked | closes TRUMP/FIL without killing Bot E |
| 14 | bot_c: `_process_ticker` called DIRECTLY with an off-universe ticker is blocked (a higher-level test is vacuous — `_select_tickers` never yields an off-universe ticker) | test_bot_c_entry_blocked | bypass path 2 |
| 15 | BotConfig.quarantined parses the column (missing/None → []); BotConfig.all_symbols is the crypto ∪ stock union | test_bot_config_quarantined / test_bot_config_all_symbols | UNIV-02 config plumbing |
| 16 | DATABASE_URL-gated: migration 018 applied — `bots.quarantined_symbols` EXISTS and its `column_default` STARTS WITH `''` (Postgres renders it `''::text` — do NOT assert equality with `''`) | test_quarantine_column_sql | real-SQL guard |
| 17 | STATIC guard: `"entry_allowed" not in Path("src/alpaca_client.py").read_text()` — automated proof the gate never lands in the exit layer | test_gate_absent_from_alpaca_client | exits never gated (replaces a manual git-diff check) |
| 18 | copytrade leader SELL on an ALREADY-HELD off-universe symbol still submits (the gate is SKIPPED entirely when `normalize(mapped)` is in the live position set) | test_copytrade_sell_held_symbol_not_gated | an open position is never stranded |

Wave 0 gap: `tests/test_universe.py` does not exist — created RED before implementation.
(Case 17 passes trivially from the start and acts as a regression tripwire for Wave 3.)

## Nyquist Compliance

- UNIV-01 → cases 1,2,4,6,7,8,9,10,11,12,13,14,17,18.
- UNIV-02 → cases 3,5,15,16.
- `nyquist_compliant` flips true when the suite exists and passes with zero regressions.
</content>
