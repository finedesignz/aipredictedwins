# tests/test_pnl.py
"""Realized P&L pure-helper suite — Phase 12 Wave 0 (RED), PNL-02.

Pins cent-exact, side-aware realized P&L from actual fills, net of TAKER_FEE on
BOTH legs, never subtracting SLIPPAGE_BUFFER. Golden values hand-computed in
12-RESEARCH.md Q5-A (fee 0.0025, qty 2):
  long  100->110 = +18.95   long  110->100 = -21.05
  short 110->100 = +18.95   short 100->110 = -21.05
  zero-fee long 100->110 = +20.00

RED until Plan 02 creates src/pnl.py — the ImportError is the load-bearing proof.
"""
import pytest

from src.pnl import realized_pnl
from src.fee_gate import TAKER_FEE, SLIPPAGE_BUFFER

FEE = 0.0025
QTY = 2.0


def test_realized_pnl_long():
    # case 1: long gain, fee both legs -> 20 - (100*2+110*2)*0.0025 = 20 - 1.05
    assert realized_pnl("buy", 100.0, 110.0, QTY, FEE) == pytest.approx(18.95, abs=1e-9)
    # long loss
    assert realized_pnl("buy", 110.0, 100.0, QTY, FEE) == pytest.approx(-21.05, abs=1e-9)


def test_realized_pnl_short():
    # case 2: short profits when price falls (side-aware sign)
    assert realized_pnl("short", 110.0, 100.0, QTY, FEE) == pytest.approx(18.95, abs=1e-9)
    assert realized_pnl("short", 100.0, 110.0, QTY, FEE) == pytest.approx(-21.05, abs=1e-9)
    # "sell" and "short" are both short; "buy"/other are long
    assert realized_pnl("sell", 110.0, 100.0, QTY, FEE) == pytest.approx(18.95, abs=1e-9)
    assert realized_pnl("buy", 110.0, 100.0, QTY, FEE) == pytest.approx(-21.05, abs=1e-9)
    assert realized_pnl("long", 100.0, 110.0, QTY, FEE) == pytest.approx(18.95, abs=1e-9)


def test_realized_pnl_fees_both_legs():
    # case 3: fee term = (entry*qty + exit*qty)*fee, not one leg
    gross = (110.0 - 100.0) * QTY
    both_legs_fee = (100.0 * QTY + 110.0 * QTY) * FEE
    one_leg_fee = (110.0 * QTY) * FEE
    result = realized_pnl("buy", 100.0, 110.0, QTY, FEE)
    assert result == pytest.approx(gross - both_legs_fee, abs=1e-9)
    assert result != pytest.approx(gross - one_leg_fee, abs=1e-9)


def test_realized_pnl_no_slippage_double():
    # case 4: with fee=TAKER_FEE only the taker fee is subtracted; SLIPPAGE_BUFFER
    # is never reflected in the realized figure.
    gross = (110.0 - 100.0) * QTY
    taker_only = gross - (100.0 * QTY + 110.0 * QTY) * TAKER_FEE
    with_slippage = gross - (100.0 * QTY + 110.0 * QTY) * (TAKER_FEE + SLIPPAGE_BUFFER)
    result = realized_pnl("buy", 100.0, 110.0, QTY, TAKER_FEE)
    assert result == pytest.approx(taker_only, abs=1e-9)
    assert result != pytest.approx(with_slippage, abs=1e-9)


def test_realized_pnl_guards():
    # case 5: zero-fee isolates the fee term; helper is pure math and must not
    # raise on 0 inputs (fallbacks live in the monitor, not here).
    assert realized_pnl("buy", 100.0, 110.0, QTY, 0.0) == pytest.approx(20.00, abs=1e-9)
    zero = realized_pnl("buy", 0.0, 0.0, 0.0, FEE)
    assert isinstance(zero, float)
    assert zero == pytest.approx(0.0, abs=1e-9)
