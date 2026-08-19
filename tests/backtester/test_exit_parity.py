"""Drift-guard parity table pinning evaluate_exit to the live inline ladder.

`_live_inline_ladder` below re-states the exact decision block currently at
src/alpaca_orchestrator.py:316-341 (the four deterministic rungs). Every case in
the table asserts that src.exit_ladder.evaluate_exit returns the identical result.
If the live ladder is tweaked without updating the shared helper, this test fails.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import dataclasses

import pytest

from src.exit_ladder import evaluate_exit
from src.exit_advisor import TrailingStop
from src.strategy_profile import SWING


def _live_inline_ladder(profile, side, entry_price, current_price, hours_held, atr, trailing, trade_id):
    """Verbatim re-statement of alpaca_orchestrator.py:283-341 exit ladder."""
    if side in ("sell", "short"):
        pnl_pct = (entry_price - current_price) / entry_price
    else:
        pnl_pct = (current_price - entry_price) / entry_price

    threshold = None
    if pnl_pct <= profile.hard_stop_pct:
        threshold = "hard_stop"
    elif profile.max_hold_hours is not None and hours_held > profile.max_hold_hours:
        threshold = "max_hold"
    elif atr > 0 and trailing.update_atr(
        trade_id, side, entry_price, current_price, atr, profile.atr_mult_trail
    ):
        threshold = "trailing_stop"
    elif atr > 0:
        if side in ("sell", "short"):
            atr_stop_level = entry_price + profile.atr_mult_stop * atr
            if current_price >= atr_stop_level:
                threshold = "atr_stop"
        else:
            atr_stop_level = entry_price - profile.atr_mult_stop * atr
            if current_price <= atr_stop_level:
                threshold = "atr_stop"
    return threshold


def _p(**overrides):
    return dataclasses.replace(SWING, **overrides)


# (profile, side, entry, current, hours_held, atr, trade_id)
_CASES = [
    # hard stop, long and short
    (_p(), "buy", 100.0, 90.0, 1.0, 0.0, 1),
    (_p(), "short", 100.0, 110.0, 1.0, 0.0, 2),
    # max hold configured
    (_p(max_hold_hours=6.0), "buy", 100.0, 100.0, 7.0, 0.0, 3),
    (_p(max_hold_hours=6.0), "buy", 100.0, 100.0, 5.0, 0.0, 4),
    # max hold None
    (_p(max_hold_hours=None), "buy", 100.0, 100.0, 9999.0, 0.0, 5),
    # atr fixed stop long / short
    (_p(hard_stop_pct=-0.99, max_hold_hours=None), "buy", 100.0, 94.0, 1.0, 3.0, 6),
    (_p(hard_stop_pct=-0.99, max_hold_hours=None), "sell", 100.0, 106.0, 1.0, 3.0, 7),
    # atr stop not reached
    (_p(hard_stop_pct=-0.99, max_hold_hours=None), "buy", 100.0, 99.0, 1.0, 3.0, 8),
    # atr <= 0 => no exit
    (_p(hard_stop_pct=-0.99, max_hold_hours=None), "buy", 100.0, 50.0, 1.0, 0.0, 9),
    # in-profit, nothing fires
    (_p(hard_stop_pct=-0.99, max_hold_hours=None), "buy", 100.0, 105.0, 1.0, 2.0, 10),
    (_p(hard_stop_pct=-0.99, max_hold_hours=None), "short", 100.0, 95.0, 1.0, 2.0, 11),
]


@pytest.mark.parametrize("profile,side,entry,current,hours,atr,tid", _CASES)
def test_parity_matches_live_inline(profile, side, entry, current, hours, atr, tid):
    # Independent TrailingStop instances so the two ladders don't share state.
    expected = _live_inline_ladder(profile, side, entry, current, hours, atr, TrailingStop(), tid)
    actual = evaluate_exit(profile, side, entry, current, hours, atr, TrailingStop(), tid)
    assert actual == expected


def test_parity_trailing_stop_sequence():
    # Two-step trailing scenario must agree across both ladders when fed the same
    # TrailingStop history.
    p = _p(hard_stop_pct=-0.99, max_hold_hours=None, atr_mult_trail=1.5)
    live_ts, shared_ts = TrailingStop(), TrailingStop()
    # arm
    e1 = _live_inline_ladder(p, "buy", 100.0, 120.0, 1.0, 2.0, live_ts, 1)
    a1 = evaluate_exit(p, "buy", 100.0, 120.0, 1.0, 2.0, shared_ts, 1)
    assert a1 == e1
    # pull back
    e2 = _live_inline_ladder(p, "buy", 100.0, 116.0, 1.0, 2.0, live_ts, 1)
    a2 = evaluate_exit(p, "buy", 100.0, 116.0, 1.0, 2.0, shared_ts, 1)
    assert a2 == e2 == "trailing_stop"
