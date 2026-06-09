"""Tests for recalibrated exit thresholds and trailing stop logic."""
import pytest


class TestNewThresholds:
    def test_soft_stop_at_minus_8_pct(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 97.5) is None   # -2.5% NORMAL
        assert check_position_thresholds(100.0, 91.9) == "soft_stop"  # -8.1% (SOFT_STOP_PCT -0.08)

    def test_soft_take_profit_at_plus_15_pct(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 106.0) is None  # +6% NORMAL
        assert check_position_thresholds(100.0, 115.1) == "soft_take_profit"  # +15.1% (0.15)

    def test_hard_stop_at_minus_15_pct(self):
        from src.exit_advisor import check_position_thresholds
        result = check_position_thresholds(100.0, 90.0)
        assert result == "soft_stop", f"Expected soft_stop at -10%, got {result}"
        assert check_position_thresholds(100.0, 84.9) == "hard_stop"  # -15.1% (HARD_STOP_PCT -0.15)

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

    def test_triggers_with_5_pct_trail(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        ts.update(1, 100.0, 108.0)   # peak at 108
        ts.update(1, 100.0, 110.0)   # new peak at 110
        # Trail stop = 110 * 0.95 = 104.5 (TRAIL_DISTANCE_PCT 0.05); price 104 < 104.5 → trigger
        result = ts.update(1, 100.0, 104.0)
        assert result == "trailing_stop"

    def test_no_trigger_above_trail(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        ts.update(1, 100.0, 108.0)  # peak 108; trail = 104.76
        assert ts.update(1, 100.0, 105.5) is None  # above trail

    def test_tightens_above_20pct(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        ts.update(1, 100.0, 122.0)   # peak +22%, above 20% tighten threshold
        ts.update(1, 100.0, 125.0)   # new peak +25%
        # Tightened trail = 125 * (1-0.03) = 121.25; normal trail = 125 * (1-0.05) = 118.75
        # Price 121.0 below tightened trail (121.25) but above normal trail (118.75)
        result = ts.update(1, 100.0, 121.0)
        assert result == "trailing_stop"
