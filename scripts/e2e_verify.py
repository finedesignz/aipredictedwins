"""End-to-end reconciliation verification (VERIFY-02, Phase 20).

**READ-ONLY. SELECT-ONLY. This script defines NO write flag and issues NO mutating SQL.**

    python scripts/e2e_verify.py                 # every enabled bot, human table
    python scripts/e2e_verify.py --bot A
    python scripts/e2e_verify.py --json
    python -m scripts.e2e_verify

WHAT IT REPORTS, PER BOT
------------------------
  · the WINDOWED verdict — post-T0, the period in which the fixed code was actually
    running, which contains ZERO fabricated rows by construction;
  · the RESOLUTION RATE post-T0;
  · the LEGACY OFFSET — the all-time delta AT T0 — surfaced NEXT TO the check it is
    excluded from, with its authorization note. A number excluded from a check must be
    visible next to the check, or the exclusion is a LIE OF OMISSION;
  · the ALL-TIME row, labelled `legacy: true`. It WILL read within_tolerance: false, and
    that is the correct, honest output of a system that lost the P&L of hundreds of exits.
    It is an EXPECTED BREACH, not a fresh failure, and it does not by itself force a FAIL;
  · the MEASURED paper-gate before/after. RESEARCH R1 refuted the projected magnitude, so
    this script MEASURES it. NO LIVE NUMBER IS HARDCODED ANYWHERE IN THIS FILE.

READ-ONLY IN THREE INDEPENDENT LAYERS (one is a convention; two are not)
-----------------------------------------------------------------------
  1. SELF-ENFORCED ENV — AIPW_DB_READONLY=1 is set below, BEFORE the first `src` import.
  2. SERVER-SIDE — that flag routes into libpq `options=-c default_transaction_read_only=on`
     (src/db.py:38), so POSTGRES ITSELF refuses any mutation with SQLSTATE 25006, and
     _bootstrap_schema()'s DDL is skipped (src/db.py:56).
  3. STATIC FENCE — tests/test_e2e_verify_fences.py greps this source, WITH a self-test
     proving the fence fires.

THERE IS NO --apply, NO --write, NO --fix, AND NO --tolerance.
A CLI tolerance override is a WIDENING LEVER BY ANOTHER NAME: this script exists to report
a breach honestly, and a knob that makes the breach vanish defeats its entire purpose.

IT NEVER WRITES THE ANCHOR. T0 is the MANAGER's to write, on its writable pool. A script
that silently anchored on first run would peg T0 to whenever someone happened to run it.
A missing anchor is reported as NO_ANCHOR and exits non-zero — never created here.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

# ─────────────────────────────────────────────────────────────────────────────
# IMPORT ORDER IS THE GUARANTEE — this line MUST precede the first `src` import.
#
# get_pool() latches the module-level `_pool` on its FIRST CALL, and _create_pool()
# decides BOTH the libpq `options=-c default_transaction_read_only=on` (src/db.py:38) AND
# whether _bootstrap_schema() runs its DDL (src/db.py:56) AT THAT MOMENT. Setting this in
# main(), or in a shell wrapper, is setting it TOO LATE — the pool would already be
# WRITABLE and the schema DDL would already have run against PROD.
#
# This makes read-only a property of THE SCRIPT, not of how someone remembered to invoke
# it. A source-line-order fence asserts it (tests/test_e2e_verify_fences.py case 14).
# ─────────────────────────────────────────────────────────────────────────────
os.environ["AIPW_DB_READONLY"] = "1"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    # `python scripts/e2e_verify.py` puts scripts/ on sys.path, not the repo root.
    sys.path.append(str(REPO_ROOT))

from src import db  # noqa: E402
from src import reconciliation  # noqa: E402
from src.reconciliation import (  # noqa: E402
    DEFAULT_TOLERANCE_PCT,
    DEFAULT_TOLERANCE_USD,
    reconcile_bot,
    reconcile_window,
)

VERDICTS = ("PASS", "FAIL", "INSUFFICIENT_SAMPLE", "NO_ANCHOR")


# ── tolerance provenance — the lever no committed-file grep can see ──────────

def tolerance_provenance() -> dict:
    """The EFFECTIVE tolerances and WHERE THEY CAME FROM.

    `_tolerance()` and `_tolerance_pct()` read os.environ AT CALL TIME. A committed-file
    grep (VALIDATION case 24) is therefore BLIND to `RECONCILIATION_TOLERANCE_USD=100000`
    set in Coolify — which would turn BOTH the all-time row AND the window green, with
    NOTHING in the committed evidence to show it.

    **A tolerance the evidence cannot see is a tolerance that can be widened in secret.**
    So the effective value and its SOURCE are reported, and any override is fatal.
    """
    usd_env = os.environ.get("RECONCILIATION_TOLERANCE_USD")
    pct_env = os.environ.get("RECONCILIATION_TOLERANCE_PCT")
    return {
        "tolerance_usd": float(usd_env) if usd_env is not None else DEFAULT_TOLERANCE_USD,
        "tolerance_usd_source": "env" if usd_env is not None else "default",
        "tolerance_pct": float(pct_env) if pct_env is not None else DEFAULT_TOLERANCE_PCT,
        "tolerance_pct_source": "env" if pct_env is not None else "default",
        "tolerance_override": usd_env is not None or pct_env is not None,
    }


def _taker_fee_provenance() -> dict:
    fee_env = os.environ.get("TAKER_FEE")
    from src.fee_gate import TAKER_FEE

    return {
        "taker_fee": TAKER_FEE,
        "taker_fee_source": "env" if fee_env is not None else "default",
    }


# ── per-bot report ──────────────────────────────────────────────────────────

def _report_for_bot(bot_id: str, prov: dict) -> dict:
    """One bot's row. Every query below is a SELECT."""
    # The anchor is READ, never created. A missing TABLE is the state on landing day.
    try:
        anchor = db.get_reconciliation_anchor(bot_id)
    except Exception as exc:
        # SQLSTATE 42P01 — migration 020 has not been applied to this database yet. This
        # is NOT a generic error: mislabelling it would bury the single most important
        # fact in the report — THE WINDOW HAS NOT OPENED YET.
        if getattr(getattr(exc, "sqlstate", None), "__str__", lambda: "")() == "42P01" \
                or "42P01" in str(getattr(exc, "sqlstate", "")) \
                or exc.__class__.__name__ == "UndefinedTable":
            return {
                "bot_id": bot_id,
                "verdict": "NO_ANCHOR",
                "reason": "table_absent — migration 020 not applied",
            }
        raise

    if anchor is None:
        return {
            "bot_id": bot_id,
            "verdict": "NO_ANCHOR",
            "reason": (
                "no T0 row — the manager's hourly reconcile tick has not run for this bot "
                "since the Phase-20 deploy. T0 is the manager's to write; this script "
                "never creates it."
            ),
        }

    # Per-bot keys. RAISES on a keyless bot — one Alpaca account per bot, hard rule.
    client = reconciliation._client_for_bot(bot_id)

    account = client.get_account()
    equity_now = account["equity"]

    positions = client.get_positions()
    if positions is None:
        # THE CALL FAILED. That is NOT "nothing is held". Never coerce it — same landmine
        # class as the backfill's `or []`.
        return {
            "bot_id": bot_id,
            "error": "positions_unavailable — Alpaca get_positions() returned None",
        }
    unrealized_now = sum(p["unrealized_pnl"] for p in positions)

    trade_log_pnl_now = db.get_realized_pnl(bot_id)
    starting_equity = db.get_starting_equity(bot_id)

    # ALL-TIME — an EXPECTED breach, reported with legacy: true.
    alltime = reconcile_bot(
        trade_log_pnl_now, equity_now, starting_equity, unrealized_now,
        prov["tolerance_usd"],
    )

    # LEGACY OFFSET — the all-time delta AT T0.
    legacy_offset_usd = reconcile_bot(
        anchor["trade_log_pnl"], anchor["equity"], starting_equity,
        anchor["unrealized_pnl"], prov["tolerance_usd"],
    )["delta"]

    counts = db.get_post_anchor_counts(bot_id, anchor["anchored_at"])

    window = reconcile_window(
        anchor=anchor,
        trade_log_pnl_now=trade_log_pnl_now,
        equity_now=equity_now,
        unrealized_now=unrealized_now,
        resolved_post_t0=counts["resolved"],
        unresolved_post_t0=counts["unresolved"],
        legacy_offset_usd=legacy_offset_usd,
    )

    # PAPER GATE — MEASURED, never predicted.
    total_rows = db.get_trade_count(bot_id)
    resolved_rows = db.get_resolved_trade_count(bot_id)

    row = dict(window)
    row["bot_id"] = bot_id
    row["alltime"] = {
        "delta": alltime["delta"],
        "tolerance": alltime["tolerance"],
        "within_tolerance": alltime["within_tolerance"],
        "legacy": True,
    }
    row["paper_gate"] = {
        "total_rows": total_rows,
        "resolved_rows": resolved_rows,
        "excluded": total_rows - resolved_rows,
    }
    return row


def build_report(bot_ids=None) -> dict:
    """The full SELECT-only report. Each bot is guarded independently: a broken bot costs
    exactly ONE bot's row, never the whole report (mirrors reconcile()'s per-bot guard)."""
    prov = tolerance_provenance()

    if bot_ids is None:
        # The `bots` table is THE SOURCE OF TRUTH — never KNOWN_BOTS, never a hardcoded
        # A/B/C. RESEARCH Open Question 2 is genuinely unresolved, so the report STATES
        # which bots it found rather than assuming.
        bot_ids = reconciliation._enabled_bot_ids()

    bots = []
    for bot_id in bot_ids:
        try:
            bots.append(_report_for_bot(bot_id, prov))
        except Exception as exc:
            bots.append({"bot_id": bot_id, "error": f"{type(exc).__name__}: {exc}"})

    report = dict(prov)
    report.update(_taker_fee_provenance())
    report["bots_found"] = list(bot_ids)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["bots"] = bots
    return report


# ── exit code — INSUFFICIENT_SAMPLE IS NOT A PASS. NEITHER IS NO_ANCHOR. ─────

def exit_code(report: dict) -> int:
    """0 ONLY when every enabled bot's verdict is PASS and no tolerance was overridden."""
    if report.get("tolerance_override"):
        return 2
    bots = report.get("bots") or []
    if not bots:
        return 1
    for b in bots:
        if b.get("error"):
            return 1
        if b.get("verdict") != "PASS":
            return 1
    return 0


# ── output ──────────────────────────────────────────────────────────────────

def _db_host() -> str:
    """The DB HOST only — NEVER the credentials, NEVER the DATABASE_URL."""
    url = os.environ.get("DATABASE_URL", "")
    if "@" in url:
        return url.rsplit("@", 1)[-1].split("/")[0]
    return "(DATABASE_URL not set)"


def _print_provenance(prov: dict) -> None:
    print("=" * 78)
    print("E2E RECONCILIATION VERIFICATION (VERIFY-02) — READ-ONLY")
    print("=" * 78)
    print(f"  generated_at : {datetime.now(timezone.utc).isoformat()}")
    print(f"  db_host      : {_db_host()}")
    print("  read_only    : AIPW_DB_READONLY=1 -> libpq "
          "'-c default_transaction_read_only=on' -> Postgres refuses writes (SQLSTATE 25006)")
    print(f"  tolerance_usd: {prov['tolerance_usd']} (source: {prov['tolerance_usd_source']})")
    print(f"  tolerance_pct: {prov['tolerance_pct']} (source: {prov['tolerance_pct_source']})")
    print("  reproduce    : python scripts/e2e_verify.py --json")


def _print_override(prov: dict) -> None:
    print("")
    print("!" * 78)
    print("TOLERANCE_OVERRIDE — REFUSING TO GRADE AGAINST A TAMPERED RULER")
    print("!" * 78)
    print("")
    print("  An environment variable is overriding the reconciliation tolerance:")
    if prov["tolerance_usd_source"] == "env":
        print(f"    RECONCILIATION_TOLERANCE_USD = {prov['tolerance_usd']} "
              f"(committed default: {DEFAULT_TOLERANCE_USD})")
    if prov["tolerance_pct_source"] == "env":
        print(f"    RECONCILIATION_TOLERANCE_PCT = {prov['tolerance_pct']} "
              f"(committed default: {DEFAULT_TOLERANCE_PCT})")
    print("")
    print("  A widened tolerance turns BOTH the all-time row AND the window green, and no")
    print("  grep of any committed file can see it. That is the one move this check exists")
    print("  to prevent. No verdict is emitted and no bot is graded. Exiting non-zero.")
    print("")
    print("  Unset the variable and re-run. THE BREACH IS THE FINDING — it is not to be")
    print("  tuned away.")
    print("")


def _print_table(report: dict) -> None:
    print("")
    print(f"  taker_fee    : {report['taker_fee']} (source: {report['taker_fee_source']})")
    print(f"  bots_found   : {', '.join(report['bots_found']) or '(none)'}"
          "   [from the `bots` table — the source of truth]")
    print("")

    for b in report["bots"]:
        print("-" * 78)
        print(f"BOT {b['bot_id']}")
        if b.get("error"):
            print(f"  ERROR: {b['error']}")
            continue
        if b.get("verdict") == "NO_ANCHOR":
            print("  VERDICT: NO_ANCHOR  (exits non-zero — this is NOT a pass)")
            print(f"  reason : {b.get('reason')}")
            print("  The windowed check has no origin yet, so it has no verdict yet.")
            continue

        print(f"  VERDICT: {b['verdict']}")
        if b["verdict"] == "INSUFFICIENT_SAMPLE":
            print(f"  WHY    : only {b['resolved_post_t0']} resolved trades since T0 "
                  f"(need {reconciliation.MIN_WINDOW_SAMPLE}). The window has NOT EARNED a "
                  f"verdict yet — it did not pass. Exits non-zero.")
        print(f"  anchored_at (T0)       : {b['anchored_at']}")
        print(f"  resolved / unresolved  : {b['resolved_post_t0']} / {b['unresolved_post_t0']}"
              f"   (rate {b['resolution_rate_post_t0']:.3f})")
        print(f"  trade_log_window       : ${b['trade_log_window']:,.2f}")
        print(f"  alpaca_realized_window : ${b['alpaca_realized_window']:,.2f}")
        print(f"  delta_window           : ${b['delta_window']:,.2f}")
        print(f"  tolerance_window       : ${b['tolerance_window']:,.2f}")
        print(f"  within_tolerance       : {b['within_tolerance_window']}")

        at = b["alltime"]
        print(f"  ALL-TIME (legacy=true) : delta ${at['delta']:,.2f} vs tolerance "
              f"${at['tolerance']:,.2f} -> within_tolerance={at['within_tolerance']}")
        print("     ^ an EXPECTED breach. It does not by itself force a FAIL.")
        print(f"  legacy_offset_usd      : ${b['legacy_offset_usd']:,.2f}")
        print(f"     {b['legacy_note']}")

        pg = b["paper_gate"]
        print(f"  PAPER GATE (measured)  : total_rows={pg['total_rows']}  "
              f"resolved_rows={pg['resolved_rows']}  excluded={pg['excluded']}")
        print("     ^ resolved_rows is what the gate reads AFTER Phase 20; total_rows is "
              "what it read BEFORE.")
    print("-" * 78)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="E2E reconciliation verification (VERIFY-02). READ-ONLY: this tool "
                    "defines no write flag and no tolerance flag.",
    )
    ap.add_argument("--bot", help="Limit the report to one bot id. Default: all enabled.")
    ap.add_argument("--json", action="store_true", help="Emit the JSON report alone.")
    args = ap.parse_args(argv)

    prov = tolerance_provenance()

    # FAIL LOUDLY, BEFORE TOUCHING PROD. A widened tolerance cannot be allowed to grade
    # anything: no bot is queried, no verdict is emitted, and the exit is non-zero. The
    # word PASS must not appear anywhere on this path.
    if prov["tolerance_override"]:
        if args.json:
            payload = dict(prov)
            payload["error"] = "TOLERANCE_OVERRIDE"
            payload["bots"] = []
            print(json.dumps(payload, indent=2, default=str))
        else:
            _print_provenance(prov)
            _print_override(prov)
        return 2

    bot_ids = [args.bot] if args.bot else None
    report = build_report(bot_ids)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_provenance(report)
        _print_table(report)

    rc = exit_code(report)
    if not args.json:
        print("")
        print(f"EXIT {rc} — " + (
            "every enabled bot's window reconciles." if rc == 0
            else "not every bot earned a PASS. INSUFFICIENT_SAMPLE and NO_ANCHOR are NOT "
                 "passes."
        ))
    return rc


if __name__ == "__main__":
    sys.exit(main())
