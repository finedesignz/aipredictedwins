"""Per-bot P&L reconciliation (PNL-03).

Compares each bot's trade-log realized P&L against its Alpaca-derived realized
P&L and flags deltas beyond a dollar tolerance. The pure ``reconcile_bot``
helper is cent-exact and API-free; the driver (Plan 03) assembles inputs from
each bot's OWN Alpaca account and persists/alerts on breach.
"""


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
