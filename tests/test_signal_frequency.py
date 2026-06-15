"""VERIFY-02 — regression guard for the DAYTRADE signal-frequency harness.

Imports the pure ``run_frequency`` from scripts/backtest_signal_frequency.py,
loads the committed 5Min fixture, and asserts a SANE candidate-frequency range
(D-05). Deterministic, offline — never invokes --live.

Guards two regressions:
  * a change that SILENCES scanning (0 candidates), and
  * a broken min_confluence gate that FLOODS (nearly every window a candidate).

The exact total is pinned below so any signal-engine math change that shifts
frequency trips this test.
"""
import sys
from pathlib import Path

import pytest

# scripts/ is not a package — add the repo root so the harness imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.backtest_signal_frequency import run_frequency, DEFAULT_FIXTURE_DIR
from src.strategy_profile import DAYTRADE
from src.backtester.data_loader import load_bars_fixture

SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD"]

# Pinned exact totals for the committed fixture.
#   Fixture: tests/fixtures/daytrade_5min/{BTC,ETH,SOL}_USD.json
#   Generated 2026-06-15, 200x 5Min synthetic bars/symbol (single UTC day),
#   mild uptrend + end-dip => trending regime, RSI mid-range, short setups at the dip.
#   Replayed through scan_assets(profile=DAYTRADE, fetch_4h=False), rolling window
#   (bar_count=100) => 101 windows/symbol.
PINNED_LONG = 10
PINNED_SHORT = 59
PINNED_TOTAL = 69
EXPECTED_WINDOWS = 101


@pytest.fixture
def report():
    bars_by_symbol = {s: load_bars_fixture(s, fixture_dir=DEFAULT_FIXTURE_DIR) for s in SYMBOLS}
    return run_frequency(bars_by_symbol, SYMBOLS, profile=DAYTRADE)


def test_frequency_is_nonzero(report):
    """Guards a regression that silences scanning."""
    assert report["total_candidates"] > 0


def test_frequency_not_absurd(report):
    """Guards a broken min_confluence gate that floods candidates."""
    ceiling = 0.8 * report["windows"] * len(SYMBOLS)
    assert report["total_candidates"] <= ceiling


def test_frequency_pinned_exact(report):
    """Pins the exact count so a signal-engine math shift trips the test."""
    assert report["windows"] == EXPECTED_WINDOWS
    assert report["total_long"] == PINNED_LONG
    assert report["total_short"] == PINNED_SHORT
    assert report["total_candidates"] == PINNED_TOTAL
