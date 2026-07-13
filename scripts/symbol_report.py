"""Per-symbol / per-bot performance report (TUNE-02, Phase 17).

Read-only: this script defines no write flag and issues no mutating SQL. It ranks
and annotates; Phase 18 decides.

    python scripts/symbol_report.py                       # all bots, FULL HISTORY (default)
    python scripts/symbol_report.py --bot A --window 90
    python scripts/symbol_report.py --min-sample 10
    python scripts/symbol_report.py --json
    python -m scripts.symbol_report

Every data defect the trade log still carries is stated out loud rather than
absorbed: sentinel zeros (src/alpaca_orchestrator.py:167-176), gross P&L with no fee
data (src/bot_c/strategy.py:393-395, src/trend_strategy.py:172-173), sign-inverted
shorts on those same rows, resolution defects (NULL pnl), and the count/rate
divergence against the number the dashboard shows (src/db.py:228-229).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    # `python scripts/symbol_report.py` puts scripts/ on sys.path, not the repo root.
    sys.path.append(str(REPO_ROOT))

from src.bot_config import BotConfig            # noqa: E402
from src.db import connection, get_alpaca_accuracy, get_resolved_trades  # noqa: E402
from src.effective_universe import resolve_universe  # noqa: E402
from src.symbol_stats import MIN_SAMPLE, aggregate   # noqa: E402
from src.universe import normalize                    # noqa: E402

EVIDENCE_PATH = (
    REPO_ROOT / ".planning" / "phases" / "17-per-symbol-performance" / "EVIDENCE.md"
)

SIGN_SUSPECT_SQL = (
    "SELECT count(*) FROM alpaca_trades WHERE fees IS NULL AND side <> 'buy' "
    "AND status IN ('closed','stopped','target_hit')"
)


# ── pure helpers (the tests call these with fixtures, no DB) ──────────────────

def annotate(cells: list[dict], bots) -> list[dict]:
    """Stamp already_quarantined / off_universe by READING the gate's own resolver.

    The verdict comes from src.effective_universe.resolve_universe — never from
    re-derived set math. Matched through normalize() on BOTH sides. A cell whose bot
    row is missing is stamped annotation="unavailable", never a silent blank.
    """
    cfgs: dict[str, BotConfig] = {}
    for b in bots or []:
        cfg = b if isinstance(b, BotConfig) else BotConfig.from_row(b)
        cfgs[cfg.bot_id] = cfg

    # exposure keyed by NORMALIZED symbol, built from the cells themselves, so a
    # symbol that was traded but is off-allowlist still reaches the resolver.
    exposure: dict[str, dict[str, dict]] = {}
    for c in cells:
        if c.get("bot_id") is None or c.get("symbol") is None:
            continue
        seen = c["trades"] + c["zero_pnl"] + c["null_pnl"]
        exposure.setdefault(c["bot_id"], {})[c["symbol"]] = {
            "open": 0,
            "recent": seen,
            "display": c.get("display") or c["symbol"],
        }

    blocked_by_bot: dict[str, dict[str, str]] = {}
    for bot_id, cfg in cfgs.items():
        resolved = resolve_universe(cfg, exposure=exposure.get(bot_id, {}))
        blocked_by_bot[bot_id] = {
            normalize(b["symbol"]): b["reason"] for b in resolved["blocked"]
        }

    for c in cells:
        bot_id = c.get("bot_id")
        if bot_id not in blocked_by_bot:
            c["annotation"] = "unavailable"
            c["already_quarantined"] = False
            c["off_universe"] = False
            continue
        reason = blocked_by_bot[bot_id].get(normalize(c.get("symbol")))
        c["annotation"] = reason or "effective"
        c["already_quarantined"] = reason == "quarantined"
        c["off_universe"] = reason in ("off_universe", "meme", "untradeable")
    return cells


def rank_cells(cells: list[dict]) -> list[dict]:
    """Rank by expectancy — over `sufficient` cells ONLY.

    Thin cells stay visible in the full table; they are merely ineligible for the
    ranking. Ranking a 2-trade cell is how a phantom "worst symbol" gets born.
    """
    return sorted(
        [c for c in cells if c.get("sample") == "sufficient"],
        key=lambda c: c["expectancy"],
        reverse=True,
    )


def summarize(rows: list[dict], cells: list[dict]) -> dict:
    """The five loud counters. sign_suspect_rows is computed from the SAME rows."""
    return {
        "rows": len(rows),
        "cells": len(cells),
        "null_pnl_total": sum(c["null_pnl"] for c in cells),
        "zero_pnl_total": sum(c["zero_pnl"] for c in cells),
        "gross_pnl_rows_total": sum(c["gross_pnl_rows"] for c in cells),
        "null_fees_total": sum(c["null_fees"] for c in cells),
        "sign_suspect_rows": sum(
            1 for r in rows
            if r.get("fees") is None and (r.get("side") or "").lower() != "buy"
        ),
    }


def _f(x, nd=2):
    return "-" if x is None else f"{x:,.{nd}f}"


def _cell_table(cells: list[dict]) -> list[str]:
    head = (
        "| bot | symbol | trades | wins | losses | win_rate | realized_pnl | total_fees "
        "| avg_win | avg_loss | expectancy | best | worst | zero_pnl | null_pnl "
        "| gross_pnl_rows | sample | quarantined | off_universe |"
    )
    out = [head, "|" + "---|" * 19]
    for c in sorted(cells, key=lambda c: c["expectancy"]):
        star = "" if c["sample"] == "sufficient" else " *"
        out.append(
            f"| {c.get('bot_id') or 'ALL'} | {c.get('display') or c.get('symbol') or 'ALL'}{star} "
            f"| {c['trades']} | {c['wins']} | {c['losses']} | {c['win_rate'] * 100:.1f}% "
            f"| {_f(c['realized_pnl'])} | {_f(c['total_fees'])} | {_f(c['avg_win'])} "
            f"| {_f(c['avg_loss'])} | {_f(c['expectancy'])} | {_f(c['best'])} | {_f(c['worst'])} "
            f"| {c['zero_pnl']} | {c['null_pnl']} | {c['gross_pnl_rows']} | {c['sample']} "
            f"| {c.get('already_quarantined', False)} | {c.get('off_universe', False)} |"
        )
    return out


def render_markdown(cells: list[dict], rollups: dict, summary: dict) -> str:
    """The whole report. Data in, string out — pure."""
    L: list[str] = []
    L.append("# Phase 17 — Per-Symbol Performance (TUNE-02)")
    L.append("")
    L.append(f"- Database: {summary.get('db_label', 'unknown')} (**SELECT-only** — no rows written)")
    L.append(f"- Generated: {summary.get('generated_at', '')}")
    L.append(f"- Window: {summary.get('window', 'full history')}")
    L.append(f"- min-sample: {summary.get('min_sample', MIN_SAMPLE)} "
             f"(cells below it are marked `insufficient` and asterisked — shown, never hidden)")
    L.append(f"- Rows: {summary['rows']} position-closed | Cells: {summary['cells']}")
    L.append("")
    L.append("This report ranks and annotates; Phase 18 decides.")
    L.append("")
    L.append(f"`sign_suspect_rows` audit SQL (re-runnable by hand):\n\n    {SIGN_SUSPECT_SQL}")
    L.append("")

    L.append("## Per-(bot, symbol)")
    L.append("")
    L.extend(_cell_table(cells))
    L.append("")

    L.append("## Roll-up — all bots, per symbol")
    L.append("")
    L.extend(_cell_table(rollups.get("by_symbol", [])))
    L.append("")

    L.append("## Roll-up — per bot")
    L.append("")
    L.extend(_cell_table(rollups.get("by_bot", [])))
    L.append("")

    ranked = rank_cells(cells)
    L.append("## Ranking (sufficient cells ONLY)")
    L.append("")
    if not ranked:
        L.append("_No cell has enough trades to rank._")
    else:
        L.append("Best by expectancy:")
        L.append("")
        for c in ranked[:5]:
            L.append(f"- {c.get('bot_id')} {c.get('display')}: expectancy {_f(c['expectancy'])} "
                     f"over {c['trades']} trades (realized {_f(c['realized_pnl'])})")
        L.append("")
        L.append("Worst by expectancy:")
        L.append("")
        for c in list(reversed(ranked))[:5]:
            L.append(f"- {c.get('bot_id')} {c.get('display')}: expectancy {_f(c['expectancy'])} "
                     f"over {c['trades']} trades (realized {_f(c['realized_pnl'])})")
    L.append("")

    L.append("## Summary — the five loud counters (printed even at zero)")
    L.append("")
    L.append(f"- `null_pnl_total`: {summary['null_pnl_total']} — resolution defects "
             "(pnl IS NULL on a position-closed row). Excluded from every statistic, never coerced to zero.")
    L.append(f"- `zero_pnl_total`: {summary['zero_pnl_total']} — pnl == 0.0 on a position-closed row: the "
             "external-exit sentinel (src/alpaca_orchestrator.py:167-176). NOT losses, NOT trades.")
    L.append(f"- `gross_pnl_rows_total`: {summary['gross_pnl_rows_total']} — COUNTED rows with NULL fees; "
             "their pnl is probably GROSS (src/bot_c/strategy.py:393-395, src/trend_strategy.py:172-173).")
    L.append(f"- `null_fees_total`: {summary['null_fees_total']} — ALL rows with NULL fees (the wider set, "
             "including zero/null-pnl rows).")
    L.append(f"- `sign_suspect_rows`: {summary['sign_suspect_rows']} — of the NULL-fee rows, those with "
             "`side <> 'buy'`.")
    L.append("")
    L.append("A non-zero value in ANY of these is a FINDING for Phase 18/20. Phase 17 does not fix it.")
    L.append("")
    L.append("*The realized_pnl of cells with gross_pnl_rows > 0 is NOT fee-adjusted (those rows were "
             "written with a gross pnl and no fee data); total_fees under-reports drag for those bots.*")
    L.append("")
    L.append("*sign_suspect_rows are NULL-fee rows with side <> 'buy': the gross writers compute "
             "(current_price - entry) * q with no side handling, so a short's P&L sign is INVERTED while "
             "the row is still counted as a win or a loss. A losing short reads as a winner. Non-zero here "
             "is a finding of a WORSE class than \"gross\" and Phase 18 must not rank on those cells.*")
    L.append("")

    L.append("## Known limitations")
    L.append("")
    L.append("### (a) The count/rate divergence vs get_alpaca_accuracy — the number the dashboard shows")
    L.append("")
    L.append("| bot | trades T (symbol_stats) | resolved R (get_alpaca_accuracy) | R - T | "
             "zero_pnl + null_pnl | win_rate (ours) | win_rate (naive) |")
    L.append("|---|---|---|---|---|---|---|")
    for d in summary.get("divergence", []):
        L.append(
            f"| {d['bot_id']} | {d['trades']} | {d['resolved']} | {d['delta']} | "
            f"{d['defects']} | {d['win_rate'] * 100:.1f}% | {d['naive_win_rate'] * 100:.1f}% |"
        )
    L.append("")
    L.append("Y books every sentinel zero and every NULL as a LOSS (src/db.py:228-229 "
             "`losses = resolved - wins`); avg_pnl divides by `resolved`. realized_pnl AGREES with "
             "db.get_realized_pnl BY CONSTRUCTION — the defect is in the DENOMINATOR, not the sum. "
             "Phase 18 DOES change get_alpaca_accuracy: it excludes `pnl IS NULL` from the "
             "denominator, so the R-T divergence this table measures SHRINKS — that gap IS the "
             "sentinel + NULL defect.")
    L.append("")
    L.append("### (b) 'stopped' and 'target_hit' are EMPTY populations")
    L.append("")
    L.append("No writer emits them — every update_alpaca_trade call site writes 'closed' or 'rejected'. "
             "Every row in this report is `'closed'`. Do not read \"no stop-outs\" as a performance fact.")
    L.append("")
    L.append("### (c) get_recent_loss_symbols uses a FOURTH status-set spelling")
    L.append("")
    L.append("`src/db.py:201` `get_recent_loss_symbols` filters `status IN ('closed','stopped')` — dropping "
             "`'target_hit'` — and it is LIVE in the entry cooldown. Reported as a Phase-18/20 finding; "
             "Phase 17 changes no bot behavior.")
    L.append("")
    return "\n".join(L)


# ── I/O edges (SELECT-only) ───────────────────────────────────────────────────

def _load_bots() -> list[dict]:
    """Every bot row — WITHOUT the enabled filter (a disabled bot still has history)."""
    with connection() as conn:
        return conn.execute("SELECT * FROM bots").fetchall()


def _divergence(cells: list[dict], by_bot: list[dict]) -> list[dict]:
    out = []
    for cell in by_bot:
        bot_id = cell.get("bot_id")
        if not bot_id:
            continue
        acc = get_alpaca_accuracy(bot_id)
        out.append({
            "bot_id": bot_id,
            "trades": cell["trades"],
            "resolved": acc["resolved"],
            "delta": acc["resolved"] - cell["trades"],
            "defects": cell["zero_pnl"] + cell["null_pnl"],
            "win_rate": cell["win_rate"],
            "naive_win_rate": acc["win_rate"],
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Per-symbol / per-bot performance report (TUNE-02).")
    ap.add_argument("--bot", type=str, default=None, help="Restrict to one bot_id.")
    ap.add_argument("--window", type=int, default=None, help="Only trades entered in the last N days.")
    ap.add_argument("--min-sample", type=int, default=MIN_SAMPLE,
                    help=f"Trades required for a cell to be rankable (default {MIN_SAMPLE}).")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of the markdown table.")
    args = ap.parse_args()

    since = None
    if args.window:
        since = datetime.now(timezone.utc) - timedelta(days=args.window)

    rows = get_resolved_trades(bot_id=args.bot, since=since)
    cells = aggregate(rows, min_sample=args.min_sample)
    by_symbol = aggregate(rows, min_sample=args.min_sample, key=("symbol",))
    by_bot = aggregate(rows, min_sample=args.min_sample, key=("bot_id",))

    try:
        bots_rows = _load_bots()
    except Exception as exc:                                  # reported, never silently blank
        print(f"warning: bots table unreadable ({exc}) — cells stamped 'unavailable'", file=sys.stderr)
        bots_rows = []
    annotate(cells, bots_rows)

    summary = summarize(rows, cells)
    summary["min_sample"] = args.min_sample
    summary["window"] = f"last {args.window} days" if args.window else "full history"
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    summary["db_label"] = "prod-readonly" if not args.bot else f"prod-readonly (bot {args.bot})"
    summary["divergence"] = _divergence(cells, by_bot)

    rollups = {"by_symbol": by_symbol, "by_bot": by_bot}

    if args.json:
        print(json.dumps({"cells": cells, "rollups": rollups, "summary": summary}, default=str, indent=2))
        return 0

    text = render_markdown(cells, rollups, summary)
    print(text)
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(text, encoding="utf-8")
    print(f"\nwrote {EVIDENCE_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
