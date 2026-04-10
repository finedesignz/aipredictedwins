import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.backtester.engine import BacktestEngine
from src.backtester.config import PHASE_PRESETS
from src.backtester.data_loader import load_bars_fixture

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
