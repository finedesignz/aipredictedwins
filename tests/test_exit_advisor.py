"""Tests for recalibrated exit thresholds and trailing stop logic."""
import pytest


class TestNewThresholds:
    def test_soft_stop_at_minus_3_pct(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 97.5) is None   # -2.5% NORMAL
        assert check_position_thresholds(100.0, 96.9) == "soft_stop"  # -3.1%

    def test_soft_take_profit_at_plus_8_pct(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 106.0) is None  # +6% NORMAL
        assert check_position_thresholds(100.0, 108.1) == "soft_take_profit"  # +8.1%

    def test_hard_stop_at_minus_5_pct(self):
        from src.exit_advisor import check_position_thresholds
        result = check_position_thresholds(100.0, 95.5)
        assert result == "soft_stop", f"Expected soft_stop at -4.5%, got {result}"
        assert check_position_thresholds(100.0, 94.9) == "hard_stop"  # -5.1%

    def test_no_hard_take_profit(self):
        from src.exit_advisor import check_position_thresholds
        result = check_position_thresholds(100.0, 115.0)
        assert result == "soft_take_profit"
        result = check_position_thresholds(100.0, 150.0)
        assert result == "soft_take_profit"

    def test_normal_range(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 100.5) is None
        assert check_position_thresholds(100.0, 97.5) is None
        assert check_position_thresholds(100.0, 107.9) is None


class TestNewTrailingStop:
    def test_no_trigger_below_new_activation(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        assert ts.update(1, 100.0, 104.0) is None  # +4%, below 5% activation

    def test_activates_at_5_pct(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        assert ts.update(1, 100.0, 105.1) is None  # above activation, not trailing yet

    def test_triggers_with_3_pct_trail(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        ts.update(1, 100.0, 108.0)   # peak at 108
        ts.update(1, 100.0, 110.0)   # new peak at 110
        # Trail stop = 110 * 0.97 = 106.7; price 106 < 106.7 → trigger
        result = ts.update(1, 100.0, 106.0)
        assert result == "trailing_stop"

    def test_no_trigger_above_trail(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        ts.update(1, 100.0, 108.0)  # peak 108; trail = 104.76
        assert ts.update(1, 100.0, 105.5) is None  # above trail

    def test_tightens_above_12pct(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        ts.update(1, 100.0, 113.0)   # peak 113 (+13%), above 12% tighten threshold
        ts.update(1, 100.0, 115.0)   # new peak 115
        # Tightened trail = 115 * 0.98 = 112.7; normal trail = 115 * 0.97 = 111.55
        # Price 112.5 is below tightened trail (112.7) but above normal trail (111.55)
        result = ts.update(1, 100.0, 112.5)
        assert result == "trailing_stop"
