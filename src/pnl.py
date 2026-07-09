"""Realized P&L from actual fills (PNL-02).

Single source of truth for the closed-trade P&L number. Pure math on the values
handed in — no I/O, no logging, no fallback logic (fallbacks live in the monitor
close block). Side-aware, net of the taker fee on BOTH legs. SLIPPAGE_BUFFER is
never subtracted here: real fills already embed slippage.
"""


def realized_pnl(
    side: str,
    entry_fill: float,
    exit_fill: float,
    qty: float,
    taker_fee: float,
) -> float:
    """Cent-exact realized P&L net of taker fees on both legs.

    long  (side not in {"sell","short"}): (exit_fill - entry_fill) * qty - fees
    short (side in {"sell","short"}):     (entry_fill - exit_fill) * qty - fees
    fees = (entry_fill*qty + exit_fill*qty) * taker_fee
    """
    if side in ("sell", "short"):
        gross = (entry_fill - exit_fill) * qty
    else:
        gross = (exit_fill - entry_fill) * qty
    fees = (entry_fill * qty + exit_fill * qty) * taker_fee
    return gross - fees
