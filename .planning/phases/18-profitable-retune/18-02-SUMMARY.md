---
phase: 18
plan: 02
subsystem: backtest-data
requirements: [TUNE-01]
key-files:
  created: [scripts/fetch_backtest_bars.py]
  modified: [src/backtester/data_loader.py, .gitignore]
commits: [9f2c695]
---

# Phase 18 Plan 02: cached bars Summary

The Wave-0 blocker is cleared. Real Alpaca 1H bars for all 8 symbols, 2025-10-01 → 2026-04-30,
cached once at `data/backtest_bars/<SYM>_1Hour.json` (5.5 MB, gitignored). Every sweep cell, the
baseline and the holdout replay the same bytes.

## Coverage

| symbol | bars | first_ts | last_ts | scans |
|--------|------|----------|---------|-------|
| BTC/USD | 5064 | 2025-10-01 | 2026-04-30 | 167 |
| ETH/USD | 5063 | 2025-10-01 | 2026-04-30 | 167 |
| SOL/USD | 5058 | 2025-10-01 | 2026-04-30 | 166 |
| XRP/USD | 5063 | 2025-10-01 | 2026-04-30 | 167 |
| ADA/USD | 1812 | **2026-02-13** | 2026-04-30 | 58 |
| AVAX/USD | 5064 | 2025-10-01 | 2026-04-30 | 167 |
| DOT/USD | 5056 | 2025-10-01 | 2026-04-30 | 166 |
| LINK/USD | 5059 | 2025-10-01 | 2026-04-30 | 166 |

**ADA/USD has no TRAIN bars** — Alpaca's crypto history for it starts 2026-02-13. It is above
the 80-bar FLAG threshold and contributes to HOLDOUT only. Recorded in 18-BACKTEST.md, not
silently dropped. With BTC+ETH quarantined, 5 symbols still trade on TRAIN, so the quarantine
arm is not vacuous.

Smoke: `BAR_CACHE_DIR=data/backtest_bars python -m src.backtester --phase 0 --train` → 32 trades
(non-zero). TRAIN and HOLDOUT return different bar and trade counts — the date filter applies.

## Deviations from Plan

**[Rule 3 - Blocking] `src/backtester/data_loader.py`: keyless fallback for crypto bars.**
The `.env` Alpaca keys return **401** (stale/rotated), and `load_bars_from_alpaca` raised
outright when keys were absent. Alpaca's crypto market-data endpoint is PUBLIC. The loader now
prefers the account keys and falls back to the keyless `CryptoHistoricalDataClient` when they are
absent or rejected — a rotated *trading* key cannot block a read-only *backtest* fetch. Six lines.
No test regressed (`tests/backtester/test_data_loader.py` green).

## Self-Check: PASSED
