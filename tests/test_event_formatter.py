"""Tests for event_formatter — format_event() and get_event_question()."""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.event_formatter import format_event, get_event_question


SAMPLE_MARKET = {
    "title": "Will BTC exceed $100k?",
    "subtitle": "Bitcoin price above $100,000 by end of March",
    "category": "Crypto",
    "close_time": "2026-03-31T23:59:59Z",
    "ticker": "BTC-100K-MAR26",
    "event_ticker": "BTC-PRICES",
    "yes_price": 65,
    "volume": 250_000,
}


# ── format_event ──────────────────────────────────────────────────────────────


class TestFormatEvent:
    def test_output_contains_title(self):
        output = format_event(SAMPLE_MARKET)
        assert SAMPLE_MARKET["title"] in output

    def test_output_contains_ticker(self):
        output = format_event(SAMPLE_MARKET)
        assert SAMPLE_MARKET["ticker"] in output

    def test_output_contains_prediction_question(self):
        output = format_event(SAMPLE_MARKET)
        assert "PREDICTION QUESTION" in output

    def test_output_contains_close_time(self):
        output = format_event(SAMPLE_MARKET)
        assert SAMPLE_MARKET["close_time"] in output

    def test_output_contains_subtitle_as_question(self):
        output = format_event(SAMPLE_MARKET)
        assert f"PREDICTION QUESTION: {SAMPLE_MARKET['subtitle']}" in output

    def test_output_contains_category(self):
        output = format_event(SAMPLE_MARKET)
        assert SAMPLE_MARKET["category"] in output


class TestFormatEventMissingFields:
    def test_missing_title_uses_default(self):
        output = format_event({})
        assert "Unknown Event" in output

    def test_missing_close_time_uses_default(self):
        output = format_event({})
        assert "Unknown" in output

    def test_missing_subtitle_uses_empty(self):
        market = {"title": "Some Title"}
        output = format_event(market)
        # With empty subtitle, question falls back to title
        assert "PREDICTION QUESTION: Some Title" in output

    def test_empty_dict_does_not_raise(self):
        output = format_event({})
        assert isinstance(output, str)
        assert len(output) > 0

    def test_missing_volume_defaults_to_zero(self):
        output = format_event({"title": "Test"})
        assert "$0" in output


# ── get_event_question ────────────────────────────────────────────────────────


class TestGetEventQuestion:
    def test_returns_subtitle_when_present(self):
        result = get_event_question(SAMPLE_MARKET)
        assert result == SAMPLE_MARKET["subtitle"]

    def test_falls_back_to_title_when_subtitle_empty(self):
        market = {"title": "Fallback Title", "subtitle": ""}
        result = get_event_question(market)
        assert result == "Fallback Title"

    def test_falls_back_to_title_when_subtitle_missing(self):
        market = {"title": "Only Title"}
        result = get_event_question(market)
        assert result == "Only Title"

    def test_empty_dict_returns_empty_string(self):
        result = get_event_question({})
        assert result == ""
