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
    """
    results: list[tuple[str, dict]] = []
    for bot_id in _enabled_bot_ids():
        client = _client_for_bot(bot_id)
        results.append((bot_id, reconcile_bot_live(bot_id, client, tolerance)))
    return results
