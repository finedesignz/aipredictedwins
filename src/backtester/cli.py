"""
Backtester CLI entry point.

Usage:
  python -m src.backtester --phase 0 --train
  python -m src.backtester --phase 0 --holdout
  python -m src.backtester --phase 0 --start 2026-02-01 --end 2026-04-09
  python -m src.backtester --phase 0 --holdout --disable skip_risk_gate
  python -m src.backtester --phase 0 --start 2026-03-01 --end 2026-03-03 --fixture-dir tests/backtester/fixtures
"""
from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("backtester")

TRAIN_START   = "2025-10-01"
TRAIN_END     = "2026-01-31"
HOLDOUT_START = "2026-02-01"
HOLDOUT_END   = "2026-04-30"

SYMBOLS = [
    "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD",
    "ADA/USD", "AVAX/USD", "DOT/USD", "LINK/USD",
]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Trading bot backtester")
    parser.add_argument("--phase", type=int, default=0, choices=[0, 1, 2, 3, 4])
    parser.add_argument("--train", action="store_true",
                        help=f"Train window ({TRAIN_START} - {TRAIN_END})")
    parser.add_argument("--holdout", action="store_true",
                        help=f"Holdout window ({HOLDOUT_START} - {HOLDOUT_END})")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--disable", nargs="*", default=[],
                        help="Disable PhaseConfig flags (e.g. --disable use_sentiment)")
    parser.add_argument("--fixture-dir", default=None,
                        help="Use fixture JSON files instead of Alpaca API")
    parser.add_argument("--output-dir", default="data/backtest_results")
    # Phase 18 — the three sweep knobs.
    parser.add_argument("--min-confluence", type=int, default=None)
    parser.add_argument("--kelly-fraction", type=float, default=None)
    parser.add_argument("--symbols", default=None,
                        help="comma-separated allowlist (overrides the module SYMBOLS)")
    parser.add_argument("--exclude-symbols", default=None,
                        help="comma-separated quarantine deny-list (slash form: BTC/USD)")
    args = parser.parse_args(argv)

    # Quarter-Kelly is a hardcoded CEILING (CLAUDE.md risk rules); Kelly may only go DOWN.
    if args.kelly_fraction is not None and args.kelly_fraction > 0.25:
        parser.error("--kelly-fraction may not exceed 0.25 (quarter-Kelly is a hardcoded "
                     "CEILING — CLAUDE.md risk rules; Kelly may only go DOWN)")

    # Resolve date range
    if args.train:
        start, end = TRAIN_START, TRAIN_END
    elif args.holdout:
        start, end = HOLDOUT_START, HOLDOUT_END
    elif args.start and args.end:
        start, end = args.start, args.end
    else:
        parser.error("Provide --train, --holdout, or --start/--end")

    # Build config
    from src.backtester.config import PHASE_PRESETS
    config = PHASE_PRESETS[args.phase]
    for flag in (args.disable or []):
        if not hasattr(config, flag):
            log.error("Unknown PhaseConfig flag: %s", flag)
            sys.exit(1)
        config = dataclasses.replace(config, **{flag: False})

    def _csv(value: str) -> tuple[str, ...]:
        return tuple(s.strip() for s in value.split(",") if s.strip())

    overrides: dict = {}
    if args.min_confluence is not None:
        overrides["min_confluence"] = args.min_confluence
    if args.kelly_fraction is not None:
        overrides["kelly_fraction"] = args.kelly_fraction
    # entry_allowed always gets the allowlist — an empty one means "no restriction".
    overrides["symbols"] = _csv(args.symbols) if args.symbols else tuple(SYMBOLS)
    if args.exclude_symbols:
        overrides["quarantined"] = _csv(args.exclude_symbols)
    config = dataclasses.replace(config, **overrides)

    log.info("Phase %d | %s to %s | disabled=%s | mc=%s k=%s quarantined=%s",
             args.phase, start, end, args.disable or "none",
             config.min_confluence, config.kelly_fraction, config.quarantined or "none")

    # Load bars
    from src.backtester.data_loader import load_bars
    bars_by_symbol: dict[str, list[dict]] = {}
    for sym in config.symbols:
        try:
            bars = load_bars(sym, start, end, fixture_dir=args.fixture_dir)
            if bars:
                bars_by_symbol[sym] = bars
                log.info("Loaded %d bars for %s", len(bars), sym)
        except Exception as exc:
            log.warning("Skipping %s: %s", sym, exc)

    if not bars_by_symbol:
        log.error("No bar data available — nothing to backtest")
        sys.exit(1)

    # Run engine
    from src.backtester.engine import BacktestEngine
    engine = BacktestEngine(config=config)
    portfolio = engine.run(bars_by_symbol, start_iso=start, end_iso=end)

    # Compute metrics
    from src.backtester.metrics import compute_summary
    summary = compute_summary(
        portfolio.trade_history(),
        engine.equity_curve(),
        starting_equity=config.starting_equity,
    )

    log.info("Results:")
    for k, v in summary.items():
        log.info("  %-25s %s", k, v)

    # Write HTML report
    from src.backtester.report import generate_report
    report_path = generate_report(
        phase=args.phase,
        config_dict=dataclasses.asdict(config),
        summary=summary,
        equity_curve=engine.equity_curve(),
        trade_history=portfolio.trade_history(),
        output_dir=args.output_dir,
    )
    log.info("Report written: %s", report_path)


if __name__ == "__main__":
    main()
