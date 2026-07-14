"""Per-bot P&L reconciliation (PNL-03).

Compares each bot's trade-log realized P&L against its Alpaca-derived realized
P&L and flags deltas beyond a dollar tolerance. The pure ``reconcile_bot``
helper is cent-exact and API-free; the driver assembles inputs from each bot's
OWN Alpaca account and persists/alerts on breach.
"""
import logging
import os

log = logging.getLogger(__name__)

DEFAULT_TOLERANCE_USD = 25.0

# ── The anchored window (VERIFY-02, Phase 20) ─────────────────────────────────
# DEFAULT_TOLERANCE_USD STAYS 25.0 AND DOES NOT MOVE. The all-time check is a FIXED LEVEL
# OFFSET (the historical pnl=0.0 sentinels contribute exactly zero to trade_log_pnl while
# Alpaca's equity move already contains their true outcome), so it is UNSATISFIABLE
# forever, absent an authorized write to those rows. It KEEPS BREACHING, is relabelled
# `legacy`, and its offset is SURFACED. WIDENING THE TOLERANCE TO GO GREEN IS BANNED.
# THE BREACH IS THE FINDING.
DEFAULT_TOLERANCE_PCT = 0.005      # 0.5% relative band
MIN_WINDOW_SAMPLE = 20             # below this -> INSUFFICIENT_SAMPLE, which is NOT a pass
RESOLUTION_RATE_BAR = 0.95


def reconcile_bot(
    trade_log_pnl: float,
    equity: float,
    starting_equity: float,
    unrealized_pnl: float,
    tolerance: float,
) -> dict:
    """Compare trade-log realized P&L against Alpaca-derived realized P&L.

    Alpaca has no direct realized-P&L field, so derive it:
        alpaca_realized_pnl = (equity - starting_equity) - unrealized_pnl
    ``unrealized_pnl`` is the signed SUM of open-position unrealized P&L — a
    losing open position (negative unrealized) INCREASES derived realized.

    Returns a 5-key result dict; ``within_tolerance`` uses an inclusive
    ``abs(delta) <= tolerance`` boundary.
    """
    alpaca_realized_pnl = (equity - starting_equity) - unrealized_pnl
    delta = trade_log_pnl - alpaca_realized_pnl
    within_tolerance = abs(delta) <= tolerance
    return {
        "trade_log_pnl": trade_log_pnl,
        "alpaca_realized_pnl": alpaca_realized_pnl,
        "delta": delta,
        "within_tolerance": within_tolerance,
        "tolerance": tolerance,
    }


# ── Driver ─────────────────────────────────────────────────────────────────────

def _tolerance() -> float:
    return float(os.environ.get("RECONCILIATION_TOLERANCE_USD", str(DEFAULT_TOLERANCE_USD)))


def _tolerance_pct() -> float:
    """Relative band, env-reversible (TUNE-03's standard). Mirrors ``_tolerance``."""
    return float(os.environ.get("RECONCILIATION_TOLERANCE_PCT", str(DEFAULT_TOLERANCE_PCT)))


def window_tolerance(
    alpaca_realized_window: float,
    tolerance_usd: float | None = None,
    tolerance_pct: float | None = None,
) -> float:
    """``max($25 floor, 0.5% band)`` on the ABSOLUTE realized figure.

    The floor binds on small windows; the band binds on large ones. The band exists
    because a FLAT $25 on a growing cumulative sum is a tolerance that TIGHTENS as the
    sample grows — the wrong direction.

    It is NOT a licence to widen: the floor NEVER drops below ``DEFAULT_TOLERANCE_USD``.
    """
    usd = _tolerance() if tolerance_usd is None else tolerance_usd
    pct = _tolerance_pct() if tolerance_pct is None else tolerance_pct
    return max(usd, pct * abs(alpaca_realized_window))


LEGACY_NOTE = (
    "legacy_offset_usd is the all-time reconciliation delta AT T0 — the unrecoverable "
    "P&L of the pre-fix external exits, whose rows carry pnl = 0.0 and contribute exactly "
    "zero to trade_log_pnl while Alpaca's equity move already contains their true outcome. "
    "It is a FIXED LEVEL OFFSET, invariant under every future correct trade, and it is "
    "EXCLUDED from the windowed verdict by construction. Clearing it requires an "
    "AUTHORIZED BACKFILL of the historical rows. It is reported here, beside the check it "
    "is excluded from, because a number excluded from a check must be visible next to it."
)


def reconcile_window(
    anchor: dict,
    trade_log_pnl_now: float,
    equity_now: float,
    unrealized_now: float,
    resolved_post_t0: int,
    unresolved_post_t0: int,
    legacy_offset_usd: float,
    tolerance_usd: float | None = None,
    tolerance_pct: float | None = None,
) -> dict:
    """The ANCHORED-WINDOW verdict: how well has the trade log reconciled SINCE T0?

    IMPLEMENTED BY CALLING ``reconcile_bot`` — never by re-writing the subtraction. The
    windowed formula IS ``reconcile_bot`` with ``starting_equity := equity_T0`` and the
    other two terms DIFFERENCED:

        alpaca_realized_window = (equity_now - equity_T0) - (unrealized_now - unrealized_T0)
        trade_log_window       = trade_log_pnl_now - trade_log_pnl_T0
        delta_window           = trade_log_window - alpaca_realized_window

    The tolerance depends on the realized figure, so ``reconcile_bot`` is called TWICE:
    once with ``tolerance=0.0`` to obtain the figure, then again with the derived
    tolerance. **Two calls, ONE formula.** A second copy of that subtraction would be a
    second place for a sign error — the exact class of defect this milestone exists to
    eliminate.

    Note the SIGN TRAP ``reconcile_bot``'s own docstring documents: ``unrealized_pnl`` is
    SIGNED, so a LOSING open position (negative unrealized) INCREASES derived realized —
    and the window differences BOTH unrealized terms, so a slip here is SILENT.

    Verdict precedence — the sample gate is FIRST, and that ordering is load-bearing:

        resolved_post_t0 < MIN_WINDOW_SAMPLE   -> "INSUFFICIENT_SAMPLE"  (EVEN IF delta == 0)
        resolution_rate  < RESOLUTION_RATE_BAR -> "FAIL"
        not within_tolerance_window            -> "FAIL"
        otherwise                              -> "PASS"

    **INSUFFICIENT_SAMPLE IS NOT A PASS.** A perfect delta on a thin sample has not earned
    a verdict, and evaluating the sample gate first is what stops a vacuously-clean thin
    window from being reported as green.
    """
    kwargs = dict(
        trade_log_pnl=trade_log_pnl_now - anchor["trade_log_pnl"],
        equity=equity_now,
        starting_equity=anchor["equity"],
        unrealized_pnl=unrealized_now - anchor["unrealized_pnl"],
    )

    # Call 1 — derive the realized figure the tolerance depends on.
    probe = reconcile_bot(tolerance=0.0, **kwargs)
    tol = window_tolerance(probe["alpaca_realized_pnl"], tolerance_usd, tolerance_pct)

    # Call 2 — the authoritative verdict, SAME formula.
    result = reconcile_bot(tolerance=tol, **kwargs)

    denom = resolved_post_t0 + unresolved_post_t0
    resolution_rate = (resolved_post_t0 / denom) if denom > 0 else 0.0

    if resolved_post_t0 < MIN_WINDOW_SAMPLE:
        verdict = "INSUFFICIENT_SAMPLE"
    elif resolution_rate < RESOLUTION_RATE_BAR:
        verdict = "FAIL"
    elif not result["within_tolerance"]:
        verdict = "FAIL"
    else:
        verdict = "PASS"

    return {
        "trade_log_window": result["trade_log_pnl"],
        "alpaca_realized_window": result["alpaca_realized_pnl"],
        "delta_window": result["delta"],
        "tolerance_window": result["tolerance"],
        "within_tolerance_window": result["within_tolerance"],
        "resolution_rate_post_t0": resolution_rate,
        "resolved_post_t0": resolved_post_t0,
        "unresolved_post_t0": unresolved_post_t0,
        "verdict": verdict,
        "legacy_offset_usd": legacy_offset_usd,
        "legacy_note": LEGACY_NOTE,
        "anchored_at": anchor.get("anchored_at"),
    }


def ensure_anchor(bot_id: str, alpaca_client) -> dict | None:
    """Read-or-create T0. An EXISTING anchor is NEVER MOVED.

    Called from ``reconcile_bot_live``, which runs on the manager's WRITABLE pool. It is
    NEVER called from ``scripts/e2e_verify.py`` — a read-only script that self-anchored
    would peg T0 to whenever someone happened to run it.

    Under ``db._readonly()`` the INSERT is not attempted (Postgres would refuse it with
    SQLSTATE 25006): it reads, and returns ``None`` if absent, so a read-only caller can
    report ``NO_ANCHOR`` honestly rather than crash.
    """
    from src import db

    existing = db.get_reconciliation_anchor(bot_id)
    if existing is not None:
        return existing

    if db._readonly():
        log.warning(
            "Bot %s has no reconciliation anchor and the pool is READ-ONLY — "
            "T0 is the manager's to write. Reporting NO_ANCHOR.", bot_id,
        )
        return None

    equity = alpaca_client.get_account()["equity"]
    positions = alpaca_client.get_positions() or []
    unrealized = sum(p["unrealized_pnl"] for p in positions)
    trade_log_pnl = db.get_realized_pnl(bot_id)

    anchor = db.write_reconciliation_anchor(bot_id, equity, unrealized, trade_log_pnl)
    log.info(
        "Reconciliation anchor T0 captured for bot %s: equity=$%.2f unrealized=$%.2f "
        "trade_log_pnl=$%.2f", bot_id, equity, unrealized, trade_log_pnl,
    )
    return anchor


def _enabled_bot_ids() -> list[str]:
    """Enumerate enabled bots from the bots table (source of truth, not A/B hardcode)."""
    from src import db

    with db.connection() as conn:
        rows = conn.execute(
            "SELECT bot_id FROM bots WHERE enabled = TRUE ORDER BY bot_id"
        ).fetchall()
    return [r["bot_id"] for r in rows]


def _client_for_bot(bot_id: str):
    """Build one AlpacaClient from THIS bot's own keys — never bare/shared keys.

    Sources per-bot keys from ALPACA_API_KEY_{id}/ALPACA_SECRET_KEY_{id} (the
    dashboard env-suffix pattern), falling back to the bots-row keys. One account
    per bot (hard rule) — a standalone script must not read bare ALPACA_API_KEY.
    """
    from src import db
    from src.alpaca_client import AlpacaClient
    from src.config import Config

    api_key = os.environ.get(f"ALPACA_API_KEY_{bot_id}", "")
    secret_key = os.environ.get(f"ALPACA_SECRET_KEY_{bot_id}", "")

    if not api_key or not secret_key:
        with db.connection() as conn:
            row = conn.execute(
                "SELECT alpaca_api_key, alpaca_secret_key FROM bots WHERE bot_id = %s",
                (bot_id,),
            ).fetchone()
        if row:
            api_key = api_key or (row["alpaca_api_key"] or "")
            secret_key = secret_key or (row["alpaca_secret_key"] or "")

    if not api_key or not secret_key:
        raise ValueError(
            f"No Alpaca keys for bot {bot_id} — set ALPACA_API_KEY_{bot_id}/"
            f"ALPACA_SECRET_KEY_{bot_id} or seed the bots row (one account per bot)."
        )

    return AlpacaClient(Config(alpaca_api_key=api_key, alpaca_secret_key=secret_key,
                              alpaca_env="paper"))


def reconcile_bot_live(bot_id: str, alpaca_client, tolerance: float | None = None) -> dict:
    """Assemble the four inputs for one bot, reconcile, persist, log/alert on breach.

    Read-only against Alpaca; the only write is the reconciliation row.
    """
    from src import db, notifier

    if tolerance is None:
        tolerance = _tolerance()

    # Capture T0 on the first post-deploy tick, under the manager's WRITABLE pool. Once
    # written it is NEVER moved (ON CONFLICT DO NOTHING). The all-time reconcile below is
    # UNCHANGED — it keeps breaching, and keeps being reported.
    ensure_anchor(bot_id, alpaca_client)

    trade_log_pnl = db.get_realized_pnl(bot_id)
    starting_equity = db.get_starting_equity(bot_id)
    equity = alpaca_client.get_account()["equity"]
    positions = alpaca_client.get_positions() or []
    unrealized_pnl = sum(p["unrealized_pnl"] for p in positions)

    result = reconcile_bot(trade_log_pnl, equity, starting_equity, unrealized_pnl, tolerance)
    db.record_reconciliation(bot_id, result)

    if not result["within_tolerance"]:
        log.warning(
            "Reconciliation breach: bot %s delta $%.2f exceeds tolerance $%.2f "
            "(trade_log=$%.2f, alpaca_realized=$%.2f)",
            bot_id, result["delta"], tolerance,
            result["trade_log_pnl"], result["alpaca_realized_pnl"],
        )
        notifier.alert_reconciliation_breach(
            bot_id, result["delta"], tolerance,
            result["trade_log_pnl"], result["alpaca_realized_pnl"],
        )
    else:
        log.info(
            "Reconciliation OK: bot %s delta $%.2f within tolerance $%.2f",
            bot_id, result["delta"], tolerance,
        )
    return result


def reconcile(tolerance: float | None = None) -> list[tuple[str, dict]]:
    """Reconcile every enabled bot against its OWN Alpaca account.

    Returns a list of (bot_id, result). One client per bot — never shared.

    PER-BOT GUARD (research N1). `_enabled_bot_ids` has NO key predicate and
    `_client_for_bot` RAISES on a keyless bot (:86-90) — correctly, since that raise is
    what enforces one-account-per-bot. Without this try, ONE misconfigured bot propagates
    out and reconciles ZERO bots, including the healthy ones. A bad bot must cost exactly
    one bot's reconciliation, not all of it. Nothing escapes this function.
    """
    results: list[tuple[str, dict]] = []
    for bot_id in _enabled_bot_ids():
        try:
            client = _client_for_bot(bot_id)
            results.append((bot_id, reconcile_bot_live(bot_id, client, tolerance)))
        except Exception as exc:
            log.error("Reconciliation failed for bot %s: %s", bot_id, exc)
            continue
    return results
