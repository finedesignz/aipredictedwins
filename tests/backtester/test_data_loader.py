import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.backtester.data_loader import load_bars_fixture, normalise_bar

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class TestNormaliseBar:
    def test_required_keys_present(self):
        bar = normalise_bar({
            "timestamp": "2026-03-01T00:00:00+00:00",
            "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.5, "volume": 500.0, "vwap": 100.3,
        })
        for key in ("timestamp", "open", "high", "low", "close", "volume", "vwap"):
            assert key in bar

    def test_missing_vwap_defaults_to_close(self):
        bar = normalise_bar({"timestamp": "t", "open": 1.0, "high": 1.0,
                              "low": 1.0, "close": 1.0, "volume": 1.0})
        assert bar["vwap"] == 1.0


class TestLoadBarsFixture:
    def test_loads_btc_fixture(self):
        bars = load_bars_fixture("BTC/USD", fixture_dir=FIXTURE_DIR)
        assert len(bars) == 60
        assert bars[0]["close"] > 0

    def test_unknown_symbol_raises(self):
        try:
            load_bars_fixture("FAKE/USD", fixture_dir=FIXTURE_DIR)
            assert False, "should have raised FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_bars_sorted_by_timestamp(self):
        bars = load_bars_fixture("BTC/USD", fixture_dir=FIXTURE_DIR)
        timestamps = [b["timestamp"] for b in bars]
        assert timestamps == sorted(timestamps)
