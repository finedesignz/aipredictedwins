"""
Fee/Slippage Pre-Trade Gate (FEE-01).

Deterministic guard: skip an approved candidate when the expected move to its
soft take-profit target does not clear round-trip cost
``2 * taker_fee + slippage_buffer``. Prevents intraday churn where the 5-min
cadence produces trades too small to overcome fees.

Pure helper — no logging, no side effects. Fee params are env-overridable knobs
following the established env-with-default pattern.
"""

import os

# Config knobs (env-overridable). Alpaca crypto taker ballpark 0.25%; 0.10% slippage.
TAKER_FEE = float(os.environ.get("TAKER_FEE", "0.0025"))
SLIPPAGE_BUFFER = float(os.environ.get("SLIPPAGE_BUFFER", "0.0010"))


def clears_fee_hurdle(expected_move_pct: float, taker_fee: float, slippage_buffer: float) -> bool:
    """Return True when the expected move clears round-trip cost.

    Hurdle = ``2 * taker_fee + slippage_buffer`` (entry + exit taker fees plus a
    slippage buffer). Boundary-exact: a move equal to the hurdle clears it.
    """
    return expected_move_pct >= 2 * taker_fee + slippage_buffer
