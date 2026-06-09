"""Tests for the fee/slippage pre-trade gate (FEE-01)."""

import importlib

import src.fee_gate as fee_gate
from src.fee_gate import clears_fee_hurdle


# --- Boundary cases (hurdle = 2*0.0025 + 0.0010 = 0.0060) -------------------

def test_boundary_exact_clears():
    assert clears_fee_hurdle(0.0060, 0.0025, 0.0010) is True


def test_just_below_skips():
    assert clears_fee_hurdle(0.00599, 0.0025, 0.0010) is False


def test_just_above_clears():
    assert clears_fee_hurdle(0.0061, 0.0025, 0.0010) is True


def test_swing_target_clears():
    assert clears_fee_hurdle(0.08, 0.0025, 0.0010) is True


# --- Default knob values ----------------------------------------------------

def test_default_knobs():
    assert fee_gate.TAKER_FEE == 0.0025
    assert fee_gate.SLIPPAGE_BUFFER == 0.0010


# --- Env override via reload ------------------------------------------------

def test_env_override_taker_fee(monkeypatch):
    monkeypatch.setenv("TAKER_FEE", "0.005")
    reloaded = importlib.reload(fee_gate)
    try:
        assert reloaded.TAKER_FEE == 0.005
    finally:
        monkeypatch.delenv("TAKER_FEE", raising=False)
        importlib.reload(fee_gate)


def test_env_override_slippage_buffer(monkeypatch):
    monkeypatch.setenv("SLIPPAGE_BUFFER", "0.002")
    reloaded = importlib.reload(fee_gate)
    try:
        assert reloaded.SLIPPAGE_BUFFER == 0.002
    finally:
        monkeypatch.delenv("SLIPPAGE_BUFFER", raising=False)
        importlib.reload(fee_gate)


# --- Entry-flow allow/skip decision (D-02/D-04) -----------------------------

def test_swing_move_allowed_default_knobs():
    # Soft TP 0.08/0.15 swing moves clear the default 0.0060 hurdle.
    assert clears_fee_hurdle(0.08, fee_gate.TAKER_FEE, fee_gate.SLIPPAGE_BUFFER) is True
    assert clears_fee_hurdle(0.15, fee_gate.TAKER_FEE, fee_gate.SLIPPAGE_BUFFER) is True


def test_swing_move_skipped_with_high_fees():
    # Forced-high taker fee (0.05 -> hurdle 0.101) skips a 0.08 move.
    assert clears_fee_hurdle(0.08, 0.05, 0.0010) is False
