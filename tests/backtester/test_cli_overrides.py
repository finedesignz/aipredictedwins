"""Phase 18 — the sweep knobs are real (VALIDATION cases 14-17, 22).

The knobs the grid varies: --min-confluence, --kelly-fraction, --symbols,
--exclude-symbols. Each is asserted LOAD-BEARING with a strict inequality — "it
runs" would pass on a knob wired to nothing. Kelly above the hardcoded 0.25
quarter-Kelly ceiling must be UNRUNNABLE (parser.error, exit 2).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dataclasses
import pathlib

import pytest

from src.backtester.cli import main
from src.backtester.config import PHASE_PRESETS
from src.backtester.engine import BacktestEngine, _position_dollar_amount

from synth_bars import synth_universe, START_ISO, END_ISO

_BT_DIR = pathlib.Path(__file__).resolve().parents[2] / "src" / "backtester"
_INF = float("inf")


def _run(bars, **overrides):
    cfg = dataclasses.replace(PHASE_PRESETS[0], **overrides)
    return BacktestEngine(config=cfg).run(bars, START_ISO, END_ISO)


# --- case 14: --min-confluence moves the entry gate

def test_min_confluence_is_load_bearing():
    bars = synth_universe()
    at3 = _run(bars, min_confluence=3, rsi_ceiling=_INF).trade_history()
    at4 = _run(bars, min_confluence=4, rsi_ceiling=_INF).trade_history()
    assert len(at3) > len(at4)
    assert len(at4) > 0


# --- case 15: --kelly-fraction moves the notional, and matches the §2.3 grid

def test_kelly_fraction_changes_notional():
    bars = synth_universe()
    t15 = _run(bars, kelly_fraction=0.15, rsi_ceiling=_INF).trade_history()[0]
    t25 = _run(bars, kelly_fraction=0.25, rsi_ceiling=_INF).trade_history()[0]

    n15 = t15["entry_price"] * t15["qty"]
    n25 = t25["entry_price"] * t25["qty"]
    equity = PHASE_PRESETS[0].starting_equity

    assert n25 > n15
    # The first entry is a confluence-3 signal: 1.50% vs 2.50% of equity (RESEARCH §2.3).
    assert n15 / equity == pytest.approx(0.015)
    assert n25 / equity == pytest.approx(0.025)


# --- case 16: THE QUARTER-KELLY CEILING — enforced at the CLI

def test_kelly_ceiling_is_enforced_at_the_cli():
    with pytest.raises(SystemExit) as exc:
        main(["--phase", "0", "--train", "--kelly-fraction", "0.50"])
    assert exc.value.code == 2

    # 0.25 is ACCEPTED by the parser (it fails later only for lack of bar data).
    try:
        main(["--phase", "0", "--train", "--kelly-fraction", "0.25",
              "--fixture-dir", str(pathlib.Path(__file__).parent / "fixtures")])
    except SystemExit as exc:  # pragma: no cover - data-dependent
        assert exc.code != 2, "0.25 must not be rejected by the parser"


# --- case 17: the hardcoded 5% max-position cap is never breached

def test_five_percent_cap_never_breached():
    equity = 100_000.0
    for conf in (3, 4):
        for k in (0.15, 0.20, 0.25):
            amt = _position_dollar_amount(conf, k, 0.05, equity)
            assert amt / equity <= 0.05 + 1e-9


# --- case 22: the sweep is reproducible (no RNG anywhere in the backtester)

def test_sweep_is_reproducible():
    from src.backtester.metrics import compute_summary

    bars = synth_universe()
    e1 = BacktestEngine(config=dataclasses.replace(
        PHASE_PRESETS[0], min_confluence=3, kelly_fraction=0.20))
    p1 = e1.run(bars, START_ISO, END_ISO)
    e2 = BacktestEngine(config=dataclasses.replace(
        PHASE_PRESETS[0], min_confluence=3, kelly_fraction=0.20))
    p2 = e2.run(bars, START_ISO, END_ISO)

    assert p1.trade_history() == p2.trade_history()
    assert (compute_summary(p1.trade_history(), e1.equity_curve())
            == compute_summary(p2.trade_history(), e2.equity_curve()))

    for py in _BT_DIR.glob("*.py"):
        src = py.read_text(encoding="utf-8")
        assert "import random" not in src
        assert "np.random" not in src
