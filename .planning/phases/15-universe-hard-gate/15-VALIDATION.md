---
phase: 15
slug: universe-hard-gate
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-12
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
| 3 | quarantined symbol (BTC/USD) blocked, reason='quarantined' | test_quarantined_blocked | UNIV-02 |
| 4 | normalize: `BTC/USD` == `BTCUSD` == `btc/usd` | test_normalize_formats | format skew |
| 5 | empty quarantine string quarantines nothing | test_empty_quarantine_noop | safe default |
| 6 | `_submit_order` on a blocked symbol: NO Alpaca call, terminal 'rejected' row (pnl=0), returns (None, None) | test_submit_order_blocks_off_universe | gate of record |
| 7 | `_submit_order` on a blocked symbol logs a WARNING with bot_id/symbol/reason | test_submit_order_logs_rejection | UNIV-01 "rejection is logged" |
| 8 | `_submit_order` on an allowlisted symbol still submits (no regression) | test_submit_order_allows_universe_symbol | no false block |
| 9 | select_long_candidates drops off-universe + quarantined, keeps allowlisted | test_select_long_universe_filter | early filter |
| 10 | select_short_candidates drops off-universe + quarantined | test_select_short_universe_filter | shorts gated too |
| 11 | EXITS are never gated: close path for a quarantined open position still runs | test_exit_not_gated | can always close |
| 12 | trend strategy: `cfg.trend_symbol` (BITX) passes even though not in stock_universe | test_trend_symbol_allowed | trend carve-out |
| 13 | copytrade entry with an off-universe symbol is blocked (the leak) | test_copytrade_entry_blocked | closes TRUMP/FIL |
| 14 | bot_c entry with an off-universe symbol is blocked | test_bot_c_entry_blocked | bypass path 2 |
| 15 | BotConfig.quarantined parses the column; missing column/None → empty | test_bot_config_quarantined | UNIV-02 config plumbing |
| 16 | DATABASE_URL-gated: migration 018 applied — `bots.quarantined_symbols` exists, default '' | test_quarantine_column_sql | real-SQL guard |

Wave 0 gap: `tests/test_universe.py` does not exist — created RED before implementation.

## Nyquist Compliance

- UNIV-01 → cases 1,2,4,6,7,8,9,10,11,12,13,14.
- UNIV-02 → cases 3,5,15,16.
- `nyquist_compliant` flips true when the suite exists and passes with zero regressions.
