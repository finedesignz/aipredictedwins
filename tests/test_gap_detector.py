"""Tests for gap_detector — detect_gap() and filter_opportunities()."""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.gap_detector import detect_gap, filter_opportunities


# ── detect_gap ────────────────────────────────────────────────────────────────


class TestDetectGapDirection:
    def test_mirofish_higher_than_kalshi_returns_yes(self):
        result = detect_gap(0.70, 0.40)
        assert result["direction"] == "yes"
        assert result["gap"] > 0

    def test_mirofish_lower_than_kalshi_returns_no(self):
        result = detect_gap(0.30, 0.60)
        assert result["direction"] == "no"
        assert result["gap"] < 0

    def test_equal_probabilities_direction_is_no(self):
        # gap == 0.0, which is not > 0, so direction falls to "no"
        result = detect_gap(0.50, 0.50)
        assert result["direction"] == "no"
        assert result["gap"] == 0.0


class TestDetectGapTradeable:
    def test_gap_above_threshold_is_tradeable(self):
        result = detect_gap(0.80, 0.50, min_gap=0.15)
        assert result["tradeable"] is True

    def test_gap_below_threshold_is_not_tradeable(self):
        result = detect_gap(0.55, 0.50, min_gap=0.15)
        assert result["tradeable"] is False

    def test_gap_exactly_at_threshold_is_tradeable(self):
        result = detect_gap(0.65, 0.50, min_gap=0.15)
        assert result["tradeable"] is True

    def test_negative_gap_above_threshold_is_tradeable(self):
        result = detect_gap(0.20, 0.50, min_gap=0.15)
        assert result["tradeable"] is True


class TestDetectGapConfidence:
    def test_low_confidence_below_020(self):
        result = detect_gap(0.55, 0.50)
        assert result["confidence"] == "low"

    def test_medium_confidence_at_020(self):
        result = detect_gap(0.70, 0.50)
        assert result["confidence"] == "medium"

    def test_medium_confidence_at_030(self):
        result = detect_gap(0.80, 0.50)
        assert result["confidence"] == "medium"

    def test_high_confidence_above_030(self):
        result = detect_gap(0.90, 0.50)
        assert result["confidence"] == "high"


class TestDetectGapEdgeCases:
    def test_extreme_low_mirofish(self):
        result = detect_gap(0.01, 0.99)
        assert result["direction"] == "no"
        assert result["abs_gap"] == 0.98
        assert result["confidence"] == "high"
        assert result["tradeable"] is True

    def test_extreme_high_mirofish(self):
        result = detect_gap(0.99, 0.01)
        assert result["direction"] == "yes"
        assert result["abs_gap"] == 0.98
        assert result["confidence"] == "high"
        assert result["tradeable"] is True

    def test_output_keys_are_complete(self):
        result = detect_gap(0.60, 0.40)
        expected_keys = {
            "mirofish_prob", "kalshi_price", "gap", "abs_gap",
            "direction", "tradeable", "confidence",
        }
        assert set(result.keys()) == expected_keys

    def test_values_are_rounded_to_four_decimals(self):
        result = detect_gap(0.333333, 0.111111)
        assert result["mirofish_prob"] == 0.3333
        assert result["kalshi_price"] == 0.1111
        assert result["gap"] == 0.2222
        assert result["abs_gap"] == 0.2222


# ── filter_opportunities ─────────────────────────────────────────────────────


def _make_entry(abs_gap: float, tradeable: bool, event_ticker: str = "EVT-A"):
    """Helper to build a market+signal entry for filter tests."""
    return {
        "market": {
            "ticker": f"MKT-{abs_gap}",
            "event_ticker": event_ticker,
            "volume": 50_000,
        },
        "signal": {
            "abs_gap": abs_gap,
            "tradeable": tradeable,
        },
    }


class TestFilterOpportunities:
    def test_sorts_by_score_descending(self):
        entries = [
            _make_entry(0.20, True),
            _make_entry(0.40, True),
            _make_entry(0.30, True),
        ]
        result = filter_opportunities(entries)
        gaps = [r["signal"]["abs_gap"] for r in result]
        assert gaps == [0.40, 0.30, 0.20]

    def test_filters_out_non_tradeable(self):
        entries = [
            _make_entry(0.40, True),
            _make_entry(0.35, False),
            _make_entry(0.20, True),
        ]
        result = filter_opportunities(entries)
        assert len(result) == 2
        for r in result:
            assert r["signal"]["tradeable"] is True

    def test_respects_max_correlated_positions(self):
        entries = [
            _make_entry(0.25, True, event_ticker="EVT-X"),
            _make_entry(0.30, True, event_ticker="EVT-X"),
        ]
        # Already have 3 positions for EVT-X — both should be skipped
        open_positions = [
            {"event_ticker": "EVT-X"},
            {"event_ticker": "EVT-X"},
            {"event_ticker": "EVT-X"},
        ]
        result = filter_opportunities(entries, open_positions, max_correlated=3)
        assert len(result) == 0

    def test_allows_different_event_tickers(self):
        entries = [
            _make_entry(0.25, True, event_ticker="EVT-A"),
            _make_entry(0.30, True, event_ticker="EVT-B"),
        ]
        open_positions = [
            {"event_ticker": "EVT-A"},
            {"event_ticker": "EVT-A"},
            {"event_ticker": "EVT-A"},
        ]
        result = filter_opportunities(entries, open_positions, max_correlated=3)
        # EVT-A blocked (3 existing), EVT-B allowed
        assert len(result) == 1
        assert result[0]["market"]["event_ticker"] == "EVT-B"

    def test_empty_input_returns_empty(self):
        assert filter_opportunities([]) == []

    def test_all_non_tradeable_returns_empty(self):
        entries = [
            _make_entry(0.05, False),
            _make_entry(0.10, False),
        ]
        assert filter_opportunities(entries) == []
