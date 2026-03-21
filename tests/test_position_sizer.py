"""Tests for position_sizer — kelly_size()."""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.position_sizer import kelly_size


BANKROLL = 10_000.0


class TestKellySizeSide:
    def test_yes_side_when_win_prob_higher(self):
        result = kelly_size(0.70, 0.50, BANKROLL)
        assert result["side"] == "yes"

    def test_no_side_when_win_prob_lower(self):
        result = kelly_size(0.30, 0.50, BANKROLL)
        assert result["side"] == "no"

    def test_no_edge_returns_zero(self):
        result = kelly_size(0.50, 0.50, BANKROLL)
        assert result["side"] == "none"
        assert result["contracts"] == 0
        assert result["kelly_pct"] == 0.0
        assert result["adjusted_pct"] == 0.0
        assert result["dollar_amount"] == 0.0


class TestKellySizeCap:
    def test_position_capped_at_max_position_pct(self):
        # Very large edge should trigger cap
        result = kelly_size(0.99, 0.10, BANKROLL, kelly_fraction=1.0, max_position_pct=0.05)
        assert result["capped"] is True
        assert result["adjusted_pct"] == 0.05
        assert result["dollar_amount"] == BANKROLL * 0.05

    def test_small_edge_not_capped(self):
        result = kelly_size(0.55, 0.50, BANKROLL, kelly_fraction=0.25, max_position_pct=0.05)
        assert result["capped"] is False
        assert result["adjusted_pct"] <= 0.05


class TestKellySizeQuarterKelly:
    def test_quarter_kelly_is_4x_smaller_than_full(self):
        full = kelly_size(0.70, 0.50, BANKROLL, kelly_fraction=1.0, max_position_pct=1.0)
        quarter = kelly_size(0.70, 0.50, BANKROLL, kelly_fraction=0.25, max_position_pct=1.0)
        # Quarter Kelly adjusted_pct should be 1/4 of full Kelly adjusted_pct
        assert abs(quarter["adjusted_pct"] - full["adjusted_pct"] / 4.0) < 1e-10


class TestKellySizeContracts:
    def test_contracts_calculation_yes_side(self):
        result = kelly_size(0.70, 0.50, BANKROLL, kelly_fraction=0.25, max_position_pct=1.0)
        expected_contracts = int(result["dollar_amount"] / 0.50)
        assert result["contracts"] == expected_contracts

    def test_contracts_calculation_no_side(self):
        result = kelly_size(0.30, 0.50, BANKROLL, kelly_fraction=0.25, max_position_pct=1.0)
        price_per_contract = 1.0 - 0.50  # NO price
        expected_contracts = int(result["dollar_amount"] / price_per_contract)
        assert result["contracts"] == expected_contracts


class TestKellySizePriceCents:
    def test_price_cents_yes_side(self):
        result = kelly_size(0.70, 0.40, BANKROLL)
        assert result["price_cents"] == 40  # kalshi_price * 100

    def test_price_cents_no_side(self):
        result = kelly_size(0.30, 0.60, BANKROLL)
        assert result["price_cents"] == 40  # (1.0 - 0.60) * 100


class TestKellySizeEdgeCases:
    def test_very_small_bankroll(self):
        result = kelly_size(0.80, 0.50, 1.00)
        assert result["contracts"] >= 0
        assert result["dollar_amount"] <= 1.00

    def test_very_large_gap(self):
        result = kelly_size(0.99, 0.01, BANKROLL)
        assert result["side"] == "yes"
        assert result["contracts"] > 0
        assert result["price_cents"] == 1

    def test_output_keys_are_complete(self):
        result = kelly_size(0.60, 0.40, BANKROLL)
        expected_keys = {
            "side", "kelly_pct", "adjusted_pct", "dollar_amount",
            "contracts", "price_cents", "capped",
        }
        assert set(result.keys()) == expected_keys
