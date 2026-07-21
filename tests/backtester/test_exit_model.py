"""Per-rung precedence + side-awareness unit tests for evaluate_exit.

Pins the shared exit-ladder helper (src/exit_ladder.evaluate_exit) to the four
deterministic rungs in their live precedence:
    hard_stop -> max_hold -> trailing_stop -> atr_stop
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import dataclasses

import pytest

from src.exit_ladder import evaluate_exit
from src.exit_advisor import TrailingStop
from src.strategy_profile import SWING


def _profile(**overrides):
    return dataclasses.replace(SWING, **overrides)


def test_hard_stop_fires_on_loss():
    p = _profile()  # hard_stop_pct = -0.08
    # LONG down 10% -> hard stop
    r = evaluate_exit(p, "buy", 100.0, 90.0, 1.0, 0.0, TrailingStop(), 1)
    assert r == "hard_stop"


def test_hard_stop_precedence_over_atr_stop():
    # A bar that satisfies BOTH hard_stop AND atr_stop must return hard_stop.
    p = _profile(hard_stop_pct=-0.08, atr_mult_stop=2.0)
    # LONG entry 100, current 90 -> pnl -10% (<= -8% hard). atr=1 -> atr_stop
    # level = 100 - 2*1 = 98, current 90 <= 98 also true. hard wins.
    r = evaluate_exit(p, "buy", 100.0, 90.0, 1.0, 1.0, TrailingStop(), 1)
    assert r == "hard_stop"


def test_max_hold_fires_only_when_configured_and_exceeded():
    p = _profile(max_hold_hours=6.0, hard_stop_pct=-0.99)
    # Not exceeded
    assert evaluate_exit(p, "buy", 100.0, 100.0, 5.0, 0.0, TrailingStop(), 1) is None
    # Exceeded
    assert evaluate_exit(p, "buy", 100.0, 100.0, 7.0, 0.0, TrailingStop(), 1) == "max_hold"


def test_max_hold_none_never_time_closes():
    p = _profile(max_hold_hours=None, hard_stop_pct=-0.99)
    assert evaluate_exit(p, "buy", 100.0, 100.0, 10000.0, 0.0, TrailingStop(), 1) is None


def test_swing_max_hold_168_boundary():
    p = _profile()  # SWING max_hold_hours = 168.0
    # Below threshold — never fires
    assert evaluate_exit(p, "buy", 100.0, 100.0, 168.0, 0.0, TrailingStop(), 1) is None
    # Strictly greater fires
    assert evaluate_exit(p, "buy", 100.0, 100.0, 168.1, 0.0, TrailingStop(), 1) == "max_hold"


def test_atr_trail_arms_and_triggers_on_pullback_long():
    p = _profile(hard_stop_pct=-0.99, max_hold_hours=None, atr_mult_trail=1.5)
    ts = TrailingStop()
    # Run up in profit to arm/ratchet peak at 120 (atr=2 -> trail = 120-3 = 117)
    assert evaluate_exit(p, "buy", 100.0, 120.0, 1.0, 2.0, ts, 1) is None
    # Pull back below trail -> trailing_stop
    assert evaluate_exit(p, "buy", 100.0, 116.0, 1.0, 2.0, ts, 1) == "trailing_stop"


def test_atr_fixed_stop_long_level():
    p = _profile(hard_stop_pct=-0.99, max_hold_hours=None, atr_mult_stop=2.0)
    # LONG level = entry - 2*atr = 100 - 2*3 = 94. current 94 <= 94 -> atr_stop
    r = evaluate_exit(p, "buy", 100.0, 94.0, 1.0, 3.0, TrailingStop(), 1)
    assert r == "atr_stop"
    # Just above level -> no exit
    assert evaluate_exit(p, "buy", 100.0, 94.5, 1.0, 3.0, TrailingStop(), 2) is None


def test_atr_fixed_stop_short_level():
    p = _profile(hard_stop_pct=-0.99, max_hold_hours=None, atr_mult_stop=2.0)
    # SHORT level = entry + 2*atr = 100 + 2*3 = 106. current 106 >= 106 -> atr_stop
    r = evaluate_exit(p, "sell", 100.0, 106.0, 1.0, 3.0, TrailingStop(), 1)
    assert r == "atr_stop"
    assert evaluate_exit(p, "sell", 100.0, 105.5, 1.0, 3.0, TrailingStop(), 2) is None


def test_side_aware_short_hard_stop():
    p = _profile(hard_stop_pct=-0.08)
    # SHORT pnl = (entry-current)/entry. Price UP 10% -> loss on short -> hard stop
    r = evaluate_exit(p, "short", 100.0, 110.0, 1.0, 0.0, TrailingStop(), 1)
    assert r == "hard_stop"
    # SHORT with price down (profit) -> no hard stop
    assert evaluate_exit(p, "short", 100.0, 95.0, 1.0, 0.0, TrailingStop(), 2) is None


def test_atr_non_positive_skips_trail_and_fixed():
    p = _profile(hard_stop_pct=-0.99, max_hold_hours=None)
    # atr = 0 -> rungs 3 and 4 skipped, nothing fires
    assert evaluate_exit(p, "buy", 100.0, 50.0, 1.0, 0.0, TrailingStop(), 1) is None
    assert evaluate_exit(p, "sell", 100.0, 101.0, 1.0, 0.0, TrailingStop(), 2) is None
