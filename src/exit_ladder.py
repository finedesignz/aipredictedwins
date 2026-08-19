"""Shared deterministic exit ladder — single source of truth (D-02).

`evaluate_exit` is the pure, side-aware exit-decision function used by BOTH the
live position monitor (src/alpaca_orchestrator.py) and the backtester. Extracting
it once and pinning it with a parity test guarantees the live and backtest ladders
can never silently diverge (Research Pitfall 2).

Only the FOUR deterministic rungs are modelled, in strict live precedence
(first-match wins):

    1. hard_stop     — pnl_pct <= profile.hard_stop_pct
    2. max_hold      — max_hold_hours is not None and hours_held > threshold
    3. trailing_stop — atr > 0 and TrailingStop.update_atr(...) fires
    4. atr_stop      — atr > 0 and side-aware fixed ATR level is crossed

There is NO soft/LLM rung: `ExitAdvisor.should_exit` is unwired in the live monitor
(Research Pitfall 1), so modelling it would inject non-determinism and reduce
fidelity. This module is pure: no broker, no DB, no LLM, no logging side effects.
"""

from __future__ import annotations


def evaluate_exit(
    profile,
    side: str,
    entry_price: float,
    current_price: float,
    hours_held: float,
    atr: float,
    trailing,
    trade_id,
) -> str | None:
    """Return the exit-reason string, or None if no rung fires.

    Args:
        profile: StrategyProfile — reads hard_stop_pct, max_hold_hours,
            atr_mult_trail, atr_mult_stop.
        side: "buy"/"long" for longs; "sell"/"short" for shorts.
        entry_price, current_price: position prices.
        hours_held: hours since entry.
        atr: Average True Range at the profile timeframe (<= 0 disables rungs 3-4).
        trailing: a TrailingStop instance (its update_atr carries per-trade state).
        trade_id: key into the trailing-stop state.

    Returns:
        "hard_stop" | "max_hold" | "trailing_stop" | "atr_stop" | None
    """
    # Side-aware pnl_pct — mirrors alpaca_orchestrator.py:283-290.
    if side in ("sell", "short"):
        pnl_pct = (entry_price - current_price) / entry_price
    else:
        pnl_pct = (current_price - entry_price) / entry_price

    # 1. Hard stop — absolute, side-aware pnl_pct.
    if pnl_pct <= profile.hard_stop_pct:
        return "hard_stop"

    # 2. Max hold — only when configured (None never time-closes).
    if profile.max_hold_hours is not None and hours_held > profile.max_hold_hours:
        return "max_hold"

    # 3. ATR trailing stop (side-aware, only when ATR is valid).
    if atr > 0 and trailing.update_atr(
        trade_id, side, entry_price, current_price, atr, profile.atr_mult_trail
    ):
        return "trailing_stop"

    # 4. ATR fixed stop (side-aware) — only when ATR is valid.
    if atr > 0:
        if side in ("sell", "short"):
            if current_price >= entry_price + profile.atr_mult_stop * atr:
                return "atr_stop"
        else:
            if current_price <= entry_price - profile.atr_mult_stop * atr:
                return "atr_stop"

    return None
