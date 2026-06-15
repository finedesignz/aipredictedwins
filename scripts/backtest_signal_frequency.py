#!/usr/bin/env python3
"""VERIFY-02 — DAYTRADE signal-FREQUENCY backtest harness (NOT P&L).

Replays committed 5-minute OHLCV fixtures through the REAL
``scan_assets(profile=DAYTRADE, fetch_4h=False)`` over a rolling window and
reports how often the DAYTRADE profile produces candidates per symbol. Guards
against a regression that silences scanning (0 candidates) or floods it.

Default path is fully offline/deterministic (fixture replay, no clock, no
network). ``--live`` fetches real 5Min bars from Alpaca (gated, never in CI).

CRITICAL (Pitfall 1): ``scan_assets`` IGNORES its own timeframe/bar_count args
and sources them from ``profile`` — for DAYTRADE it calls
``get_bars(symbol, timeframe="5Min", limit=100)``. The _ReplayClient therefore
serves a ``profile.bar_count``-sized slice regardless of the passed args.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the repo root importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.strategy_profile import DAYTRADE
from src.technical_signals import scan_assets
from src.backtester.data_loader import load_bars_fixture, load_bars_from_alpaca

DEFAULT_SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD"]
DEFAULT_FIXTURE_DIR = "tests/fixtures/daytrade_5min"


class _ReplayClient:
    """Serves a rolling profile-sized window of bars per symbol.

    ``scan_assets`` calls ``get_bars(symbol, timeframe="5Min", limit=100)`` — we
    ignore those args and return ``bars[end - bar_count : end]`` for the active
    window end index, so the slice always matches DAYTRADE.bar_count.
    """

    def __init__(self, bars_by_symbol: dict[str, list[dict]], end_idx: int, bar_count: int):
        self._bars = bars_by_symbol
        self._end = end_idx
        self._bar_count = bar_count

    def get_bars(self, symbol, timeframe="5Min", limit=100):
        bars = self._bars.get(symbol, [])
        start = max(0, self._end - self._bar_count)
        return bars[start:self._end]


def run_frequency(bars_by_symbol, symbols, window=None, profile=DAYTRADE):
    """Pure frequency function — no I/O. Returns a report dict.

    Slides the window end index across each fixture (step 1) from
    ``profile.bar_count`` to the fixture length, runs the real
    ``scan_assets(profile=DAYTRADE, fetch_4h=False)`` per position, and counts
    long candidates (confluence_score >= profile.min_confluence) and short
    candidates (short_score >= profile.min_short_confluence).

    ``window`` optionally caps the number of rolling positions evaluated
    (latest-N) for speed/determinism; default = all positions.
    """
    bc = profile.bar_count
    n = min((len(bars_by_symbol.get(s, [])) for s in symbols), default=0)
    if n < bc:
        # Not enough bars to form even one full window.
        ends = []
    else:
        ends = list(range(bc, n + 1))
        if window is not None and window < len(ends):
            ends = ends[-window:]

    per_symbol = {s: {"long": 0, "short": 0} for s in symbols}
    for end_idx in ends:
        client = _ReplayClient(bars_by_symbol, end_idx, bc)
        signals = scan_assets(client, symbols, fetch_4h=False, profile=profile)
        for sig in signals:
            if sig.symbol not in per_symbol:
                continue
            if sig.confluence_score >= profile.min_confluence:
                per_symbol[sig.symbol]["long"] += 1
            if getattr(sig, "short_score", 0) >= profile.min_short_confluence:
                per_symbol[sig.symbol]["short"] += 1

    total_long = sum(v["long"] for v in per_symbol.values())
    total_short = sum(v["short"] for v in per_symbol.values())
    total_candidates = total_long + total_short
    return {
        "windows": len(ends),
        "symbols": list(symbols),
        "per_symbol": per_symbol,
        "total_long": total_long,
        "total_short": total_short,
        "total_candidates": total_candidates,
    }


def _verdict(report) -> str:
    windows, syms = report["windows"], len(report["symbols"])
    total = report["total_candidates"]
    if windows == 0 or syms == 0:
        return "NO-DATA"
    rate = total / (windows * syms)
    if total == 0:
        return "NO-EDGE (0 candidates — scanning may be silenced)"
    if rate > 0.8:
        return "FLOODED (gate likely broken — almost every window a candidate)"
    if rate >= 0.05:
        return "STRONG"
    return "MARGINAL"


def _load_fixtures(fixture_dir, symbols):
    return {s: load_bars_fixture(s, fixture_dir=fixture_dir) for s in symbols}


def _load_live(symbols, start_iso, end_iso):
    return {s: load_bars_from_alpaca(s, start_iso, end_iso, timeframe="5Min") for s in symbols}


def print_report(report):
    print("=== DAYTRADE signal-frequency report ===")
    print(f"windows={report['windows']}  symbols={len(report['symbols'])}")
    for sym, c in report["per_symbol"].items():
        print(f"  {sym:10s} long_candidates={c['long']:4d}  short_candidates={c['short']:4d}")
    print(f"TOTAL long={report['total_long']}  short={report['total_short']}  "
          f"candidates={report['total_candidates']}")
    print(f"VERDICT: {_verdict(report)}")


def main(argv=None):
    p = argparse.ArgumentParser(description="DAYTRADE signal-frequency backtest")
    p.add_argument("--fixture-dir", default=DEFAULT_FIXTURE_DIR)
    p.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    p.add_argument("--window", type=int, default=None, help="cap rolling positions (latest-N)")
    p.add_argument("--live", action="store_true", help="fetch real 5Min bars from Alpaca (NOT for CI)")
    p.add_argument("--start", default=None, help="--live start ISO")
    p.add_argument("--end", default=None, help="--live end ISO")
    args = p.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if args.live:
        if not (args.start and args.end):
            p.error("--live requires --start and --end")
        bars_by_symbol = _load_live(symbols, args.start, args.end)
    else:
        bars_by_symbol = _load_fixtures(args.fixture_dir, symbols)

    report = run_frequency(bars_by_symbol, symbols, window=args.window, profile=DAYTRADE)
    print_report(report)
    return report


if __name__ == "__main__":
    main()
