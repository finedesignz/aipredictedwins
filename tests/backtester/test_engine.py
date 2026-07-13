import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dataclasses
import pathlib
import re

import pytest

from src.backtester.engine import BacktestEngine, SIGNAL_WINDOW, SCAN_INTERVAL_BARS
from src.backtester.config import PHASE_PRESETS
from src.backtester.data_loader import load_bars_fixture

from synth_bars import synth_universe, START_ISO, END_ISO

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_all_fixtures() -> dict[str, list[dict]]:
    bars = {}
    for sym in ["BTC/USD"]:
        try:
            bars[sym] = load_bars_fixture(sym, fixture_dir=FIXTURE_DIR)
        except FileNotFoundError:
            pass
    return bars


class TestBacktestEngine:
    def test_runs_without_error(self):
        engine = BacktestEngine(config=PHASE_PRESETS[0])
        bars_by_symbol = _load_all_fixtures()
        assert bars_by_symbol, "fixture BTC_USD.json must exist for this test to be meaningful"
        result = engine.run(bars_by_symbol, start_iso="2026-03-01", end_iso="2026-03-03")
        assert result is not None
        assert result.equity() > 0

    def test_equity_non_negative(self):
        engine = BacktestEngine(config=PHASE_PRESETS[0])
        result = engine.run(_load_all_fixtures(), "2026-03-01", "2026-03-03")
        assert result.equity() >= 0

    def test_history_has_expected_fields(self):
        engine = BacktestEngine(config=PHASE_PRESETS[0])
        result = engine.run(_load_all_fixtures(), "2026-03-01", "2026-03-03")
        for trade in result.trade_history():
            for field in ("symbol", "entry_price", "exit_price", "qty", "pnl", "reason"):
                assert field in trade

    def test_no_duplicate_positions(self):
        engine = BacktestEngine(config=PHASE_PRESETS[0])
        result = engine.run(_load_all_fixtures(), "2026-03-01", "2026-03-03")
        all_open = [p.symbol for p in result.open_positions()]
        assert len(all_open) == len(set(all_open))

    def test_open_positions_force_closed_at_end(self):
        engine = BacktestEngine(config=PHASE_PRESETS[0])
        result = engine.run(_load_all_fixtures(), "2026-03-01", "2026-03-03")
        # After run, there should be no open positions
        assert result.open_positions() == []
        # All trades should be in trade_history
        from src.backtester.metrics import compute_summary
        summary = compute_summary(
            result.trade_history(), [], PHASE_PRESETS[0].starting_equity
        )
        assert summary["trade_count"] == len(result.trade_history())


# ===========================================================================
# Phase 18 — VALIDATION cases 18-21
# ===========================================================================

_ENGINE_SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "backtester" / "engine.py"
_SIGNALS_SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "technical_signals.py"

_INF = float("inf")


def _run(bars, **overrides):
    cfg = dataclasses.replace(PHASE_PRESETS[0], **overrides)
    engine = BacktestEngine(config=cfg)
    return engine.run(bars, START_ISO, END_ISO)


def _key(t: dict) -> tuple:
    return (t["symbol"], t["entry_timestamp"], t["exit_timestamp"], t["reason"],
            round(t["entry_price"], 9), round(t["exit_price"], 9),
            round(t["qty"], 9), round(t["pnl"], 9))


# --- case 18: the confluence ceiling is 4 — min_confluence=5 is structurally empty

def test_min_confluence_5_is_structurally_empty():
    # (a) STATIC — each scoring branch has exactly FOUR `score += 1`.
    src = _SIGNALS_SRC.read_text(encoding="utf-8")
    start = src.index("score = 0")
    end = src.index("short_score = 0")
    block = src[start:end]
    assert block.strip(), "positive control: the scoring block slice is empty"
    assert "vol_spike" not in block, "positive control: volume spike must stay excluded"
    trending, ranging = block.split("else:", 1)
    assert len(re.findall(r"score \+= 1", trending)) == 4
    assert len(re.findall(r"score \+= 1", ranging)) == 4

    bars = synth_universe()

    # (b) BEHAVIORAL — no trade can ever clear a threshold of 5.
    assert len(_run(bars, min_confluence=5).trade_history()) == 0

    # (c) the score itself never exceeds 4.
    from src.technical_signals import analyze
    top = 0
    for sym, bb in bars.items():
        for i in range(SIGNAL_WINDOW, len(bb), SCAN_INTERVAL_BARS):
            sig = analyze(sym, bb[i - SIGNAL_WINDOW:i])
            if sig:
                top = max(top, sig.confluence_score)
    assert 0 < top <= 4


# --- case 19: the quarantine uses the LIVE gate (src.universe.entry_allowed)

def test_quarantine_uses_the_live_gate():
    bars = synth_universe()
    trades = _run(bars, quarantined=("BTC/USD",), rsi_ceiling=_INF).trade_history()
    syms = [t["symbol"] for t in trades]
    assert "BTC/USD" not in syms
    assert syms.count("ETH/USD") > 0

    src = _ENGINE_SRC.read_text(encoding="utf-8")
    assert "from src.universe import entry_allowed" in src
    assert ".replace(\"/\"" not in src
    assert "in exclude" not in src


# --- case 20: rsi_ceiling is enforced, and it is NON-VACUOUS

def test_rsi_ceiling_is_enforced_and_non_vacuous():
    bars = synth_universe()
    capped = _run(bars, rsi_ceiling=65.0).trade_history()
    uncapped = _run(bars, rsi_ceiling=_INF).trade_history()
    assert len(capped) < len(uncapped)


# --- case 21: the plumbing introduced NO incidental behavior change (the pin)

# Golden: generated from the PRE-Phase-18 engine on these exact bars.
_GOLDEN = [
    ("ETH/USD", "2025-11-03T01:00:00+00:00", "2025-11-16T11:00:00+00:00",
     "hard_take_profit", 53.081812421878, 69.052033432173, 47.097110779315, 752.151268092002),
    ("BTC/USD", "2025-11-11T19:00:00+00:00", "2025-11-25T09:00:00+00:00",
     "hard_take_profit", 121.238938995464, 158.044724543387, 20.725947182269, 762.834767268168),
    ("ETH/USD", "2025-11-25T05:00:00+00:00", "2026-01-31T23:59:59",
     "end_of_backtest", 77.715273938190, 84.511337291015, 32.626422611504, 221.731235043846),
    ("BTC/USD", "2025-11-29T03:00:00+00:00", "2026-01-31T23:59:59",
     "end_of_backtest", 167.095294539942, 169.714354958173, 15.188181105589, 39.778763958574),
]


def test_no_incidental_behavior_change():
    trades = _run(synth_universe(), symbols=(), quarantined=(),
                  rsi_ceiling=_INF).trade_history()
    assert len(trades) == len(_GOLDEN)
    for got, want in zip(trades, _GOLDEN):
        assert got["symbol"] == want[0]
        assert got["entry_timestamp"] == want[1]
        assert got["exit_timestamp"] == want[2]
        assert got["reason"] == want[3]
        assert got["entry_price"] == pytest.approx(want[4])
        assert got["exit_price"] == pytest.approx(want[5])
        assert got["qty"] == pytest.approx(want[6])
        assert got["pnl"] == pytest.approx(want[7])
