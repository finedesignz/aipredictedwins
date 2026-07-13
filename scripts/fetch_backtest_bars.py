#!/usr/bin/env python
"""Phase 18 (TUNE-01) — one-shot, READ-ONLY Alpaca bar fetch + cache + coverage report.

The Wave-0 blocker. `tests/backtester/fixtures/` holds exactly ONE file (BTC_USD.json,
60 bars) and BTC is the headline quarantine target — a fixture-only sweep with
`--exclude-symbols BTC/USD` has zero tradeable symbols, so every cell returns
trades=0 and the quarantine arm "wins" vacuously. This script puts real bars for all
8 symbols on disk so the sweep measures something.

Market data only. No database import, no connection string, no orders, no write surface.

  python scripts/fetch_backtest_bars.py --start 2025-10-01 --end 2026-04-30

The fetch entry point is load_bars() (data_loader.py:138) — cache -> Alpaca, and
load_bars_from_alpaca calls save_bars_cache for us. load_bars_cached is NOT the fetch
path: it returns None on a miss and caches nothing.
"""
from __future__ import annotations

import argparse
import os
import sys

# Defensive: if any transitive import ever reaches the db module, it must not bootstrap DDL.
os.environ.setdefault("AIPW_DB_READONLY", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from src.backtester.cli import SYMBOLS
from src.backtester.data_loader import load_bars

load_dotenv()   # ALPACA_API_KEY / ALPACA_SECRET_KEY — market-data read only

SIGNAL_WINDOW = 50        # src/backtester/engine.py:22
SCAN_INTERVAL_BARS = 30   # src/backtester/engine.py:23
MIN_BARS = SIGNAL_WINDOW + SCAN_INTERVAL_BARS   # below this a symbol affords <= 1 scan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch + cache 1H Alpaca bars for the Phase-18 sweep (read-only)")
    parser.add_argument("--start", default="2025-10-01")
    parser.add_argument("--end", default="2026-04-30")
    parser.add_argument("--symbols", default=None,
                        help="comma-separated; default = the 8-crypto backtest universe")
    parser.add_argument("--cache-dir", default="data/backtest_bars")
    parser.add_argument("--timeframe", default="1Hour")
    args = parser.parse_args(argv)

    symbols = ([s.strip() for s in args.symbols.split(",") if s.strip()]
               if args.symbols else list(SYMBOLS))

    rows: list[tuple] = []
    empty: list[str] = []
    thin: list[str] = []

    for sym in symbols:
        bars = load_bars(sym, args.start, args.end, timeframe=args.timeframe,
                         fixture_dir=None, cache_dir=args.cache_dir)
        n = len(bars or [])
        if n == 0:
            empty.append(sym)
            rows.append((sym, 0, "-", "-", 0, "EMPTY"))
            continue
        if n < MIN_BARS:
            thin.append(sym)
        rows.append((
            sym, n, bars[0]["timestamp"], bars[-1]["timestamp"],
            max(0, (n - SIGNAL_WINDOW) // SCAN_INTERVAL_BARS),
            "FLAG" if n < MIN_BARS else "",
        ))

    print(f"\nBar coverage — {args.start} -> {args.end} ({args.timeframe}), "
          f"cache={args.cache_dir}\n")
    print("| symbol | bars | first_ts | last_ts | scans_afforded | flag |")
    print("|--------|------|----------|---------|----------------|------|")
    for r in rows:
        print(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} |")

    if empty:
        print(f"\nERROR: zero bars for {', '.join(empty)} — the sweep would go vacuous.")
        return 1
    if thin:
        print(f"\nERROR: FLAGGED (< {MIN_BARS} bars, at most one scan): {', '.join(thin)}")
        return 1
    print("\nOK — every symbol has enough bars for a real sweep.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
