#!/usr/bin/env python
"""Phase 18 (TUNE-01) — the reproducible grid sweep + the acceptance-bar evaluator.

TRAIN: 18 cells = min_confluence {3,4,5} x kelly_fraction {0.15,0.20,0.25} x quarantine
{ON,OFF}. The six mc=5 cells are STRUCTURALLY EMPTY (the confluence score ceiling is 4 —
src/technical_signals.py:371-406, the volume spike is deliberately excluded). They are RUN
and RECORDED as trades=0, auto-failing on the >= 30-trade criterion, which is checked FIRST
so they read as EMPTY rather than as merely bad configs.

HOLDOUT: exactly TWO cells — the named candidate and the baseline. Picking on the holdout is
forbidden (CONTEXT Decision 6) and it is enforced in code: `--holdout` without `--candidate`
is a parser.error, and a second holdout run is refused via 18-HOLDOUT.lock.

EACH CELL IS A FRESH SUBPROCESS with BAR_CACHE_DIR in its env. This is NOT a style choice:
data_loader.py:20 reads BAR_CACHE_DIR at IMPORT and bakes it into default args (:59, :144),
and cli.py never passes cache_dir — so an in-process loop would read the stale, empty default
cache and re-fetch live bars mid-sweep, destroying the reproducibility this driver exists to
hold. No bar-fixture flag is ever passed (the cache namespace is <SYM>_1Hour.json; the fixture
namespace is <SYM>.json — the flag would kill every cell).

Read-only: no database import for a write path, no orders, no mutation surface at all. The
baseline knob read is fenced with AIPW_DB_READONLY=1.
"""
from __future__ import annotations

import argparse
import datetime
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PHASE_DIR = ROOT / ".planning" / "phases" / "18-profitable-retune"
HOLDOUT_LOCK = PHASE_DIR / "18-HOLDOUT.lock"

CACHE_DIR = "data/backtest_bars"
UNIVERSE = "BTC/USD,ETH/USD,SOL/USD,XRP/USD,ADA/USD,AVAX/USD,DOT/USD,LINK/USD"
QUARANTINE = "BTC/USD,ETH/USD,TRUMP/USD,FIL/USD,ARB/USD"

MIN_CONFLUENCES = (3, 4, 5)
KELLYS = (0.15, 0.20, 0.25)
QUARANTINES = (False, True)

MIN_TRADES = 30
MIN_WIN_RATE = 0.40
MAX_DRAWDOWN_LIMIT = 0.20

_METRIC = re.compile(r"^\s*(?:INFO\s+backtester:)?\s{2,}([a-z_]+)\s+(-?[\d.]+)\s*$")


def run_cell(window: str, min_confluence: int, kelly: float, quarantine: bool) -> dict:
    """One cell = one FRESH backtester process against the SAME cached bars."""
    cmd = [sys.executable, "-m", "src.backtester", "--phase", "0", f"--{window}",
           "--min-confluence", str(min_confluence),
           "--kelly-fraction", str(kelly),
           "--symbols", UNIVERSE]
    if quarantine:
        cmd += ["--exclude-symbols", QUARANTINE]

    env = {**os.environ, "BAR_CACHE_DIR": CACHE_DIR, "AIPW_DB_READONLY": "1"}
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True)

    summary: dict = {}
    for line in (proc.stdout + proc.stderr).splitlines():
        m = _METRIC.match(line)
        if m:
            summary[m.group(1)] = float(m.group(2))
    if "trade_count" not in summary:
        summary = {"trade_count": 0.0, "win_rate": 0.0, "max_drawdown": 0.0,
                   "total_return_pct": 0.0, "monitor_pnl": 0.0, "sharpe_ratio": 0.0}
    summary["trade_count"] = int(summary["trade_count"])
    summary["exit_code"] = proc.returncode
    return summary


def expectancy(summary: dict) -> float:
    n = summary.get("trade_count") or 0
    return (summary.get("monitor_pnl", 0.0) / n) if n else 0.0


def passes_bar(summary: dict, baseline: dict) -> tuple[bool, str]:
    """The four-way conjunction, evaluated in code. trades >= 30 is checked FIRST so a
    structurally-empty cell reads as EMPTY, not as a bad config."""
    n = summary.get("trade_count", 0)
    if n < MIN_TRADES:
        return False, f"trade count {n} < {MIN_TRADES}"
    if summary.get("win_rate", 0.0) < MIN_WIN_RATE:
        return False, f"win_rate {summary['win_rate']:.2%} < 40%"
    dd = summary.get("max_drawdown", 1.0)
    if dd >= baseline.get("max_drawdown", 1.0):
        return False, f"max_drawdown {dd:.2%} not improved vs baseline {baseline['max_drawdown']:.2%}"
    if dd >= MAX_DRAWDOWN_LIMIT:
        return False, f"max_drawdown {dd:.2%} >= 20%"
    if summary.get("total_return_pct", 0.0) < baseline.get("total_return_pct", 0.0):
        return False, (f"return {summary['total_return_pct']:.2f}% < "
                       f"baseline {baseline['total_return_pct']:.2f}%")
    return True, "PASS"


def row(mc, k, q, s, verdict) -> str:
    return (f"| {mc} | {k:.2f} | {'ON' if q else 'OFF'} | {s['trade_count']} | "
            f"{s.get('win_rate', 0.0):.2%} | {s.get('max_drawdown', 0.0):.2%} | "
            f"{expectancy(s):.2f} | {s.get('total_return_pct', 0.0):.2f}% | {verdict} |")


def read_baseline_knobs() -> None:
    """Read the live bots row READ-ONLY. AIPW_DB_READONLY=1 skips the schema bootstrap and
    makes every connection read-only server-side."""
    os.environ["AIPW_DB_READONLY"] = "1"
    if not os.environ.get("DATABASE_URL"):
        print("baseline knobs: no connection string in env — read them from GET /api/bots "
              "and record them in 18-BACKTEST.md")
        return
    from src.db import connection
    with connection() as conn:
        for r in conn.execute(
            "SELECT bot_id, strategy, min_confluence, kelly_fraction, quarantined_symbols "
            "FROM bots ORDER BY bot_id"
        ).fetchall():
            print(r)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase-18 backtest grid sweep (read-only)")
    parser.add_argument("--holdout", action="store_true",
                        help="run the named candidate + the baseline on the HOLDOUT window")
    parser.add_argument("--candidate", default=None,
                        help="mc,kelly,quarantine — e.g. '4,0.20,on' (required with --holdout)")
    parser.add_argument("--baseline", default="4,0.25,off",
                        help="the live config: mc,kelly,quarantine")
    parser.add_argument("--baseline-knobs", action="store_true",
                        help="print the live bots row (READ-ONLY) and exit")
    args = parser.parse_args(argv)

    if args.baseline_knobs:
        read_baseline_knobs()
        return 0

    def parse_cell(text: str) -> tuple[int, float, bool]:
        mc, k, q = [p.strip() for p in text.split(",")]
        return int(mc), float(k), q.lower() in ("on", "true", "1", "yes")

    base_mc, base_k, base_q = parse_cell(args.baseline)

    if args.holdout:
        if not args.candidate:
            parser.error("picking on the holdout is forbidden — CONTEXT Decision 6. "
                         "--holdout requires an explicit --candidate mc,kelly,quarantine "
                         "chosen on TRAIN.")
        if HOLDOUT_LOCK.exists():
            parser.error("the holdout has already been run (see 18-HOLDOUT.lock) — running "
                         "it again with a different --candidate IS picking on the holdout, "
                         "and CONTEXT Decision 6 forbids it")
        rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                             capture_output=True, text=True).stdout.strip()
        HOLDOUT_LOCK.parent.mkdir(parents=True, exist_ok=True)
        HOLDOUT_LOCK.write_text(
            f"candidate={args.candidate}\nbaseline={args.baseline}\n"
            f"timestamp={datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
            f"git_rev={rev}\n", encoding="utf-8")

        cand_mc, cand_k, cand_q = parse_cell(args.candidate)
        base = run_cell("holdout", base_mc, base_k, base_q)
        cand = run_cell("holdout", cand_mc, cand_k, cand_q)

        print("| mc | kelly | quarantine | trades | win_rate | max_dd | expectancy | return | verdict |")
        print("|----|-------|------------|--------|----------|--------|------------|--------|---------|")
        print(row(base_mc, base_k, base_q, base, "BASELINE"))
        ok, reason = passes_bar(cand, base)
        print(row(cand_mc, cand_k, cand_q, cand, ("PASS" if ok else f"FAIL — {reason}")))
        return 0

    # TRAIN — all 18 cells, plus the baseline cell on the same bars and the same engine.
    baseline = run_cell("train", base_mc, base_k, base_q)
    print("| mc | kelly | quarantine | trades | win_rate | max_dd | expectancy | return | verdict |")
    print("|----|-------|------------|--------|----------|--------|------------|--------|---------|")
    print(row(base_mc, base_k, base_q, baseline, "BASELINE"))

    for mc in MIN_CONFLUENCES:
        for k in KELLYS:
            for q in QUARANTINES:
                s = run_cell("train", mc, k, q)
                ok, reason = passes_bar(s, baseline)
                print(row(mc, k, q, s, ("PASS" if ok else f"FAIL — {reason}")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
