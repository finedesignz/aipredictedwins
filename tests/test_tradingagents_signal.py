"""Tests for the TradingAgents-style signal adapter.

Stubs out the OpenAI-compatible client so the test suite never makes real
LLM calls. Verifies vote parsing, decision parsing, score aggregation,
caching, fault tolerance, and the merge_with_confluence policy.
"""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from src.tradingagents_signal import (
    TradingAgentsSignal,
    TradingAgentsScore,
    merge_with_confluence,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@dataclass
class _FakeConfig:
    llm_api_key: str = "test"
    llm_base_url: str = "http://localhost:9999"
    llm_model_name: str = "test-model"


def _make_signal_instance(monkeypatch, scripted_replies):
    """Build a TradingAgentsSignal with `_call` returning scripted_replies in order."""
    sig = TradingAgentsSignal.__new__(TradingAgentsSignal)
    sig.config = _FakeConfig()
    sig._llm = MagicMock()
    sig._model = "test-model"

    replies = list(scripted_replies)
    def fake_call(prompt, role):
        return replies.pop(0) if replies else "VOTE: HOLD"
    sig._call = fake_call
    # Use a fresh cache for each test — class-level cache must not leak
    sig._cache = {}
    TradingAgentsSignal._cache = {}
    return sig


_BARS = [
    {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000, "vwap": 100.5}
    for _ in range(12)
]
_INDICATORS = {
    "ema_state": "bullish", "adx": 28.0, "plus_di": 25.0, "minus_di": 12.0,
    "rsi": 58.0, "vwap_state": "above", "trend_4h": "bullish", "vol_ratio": 1.3,
}


# ---------------------------------------------------------------------------
# Vote / decision parsing
# ---------------------------------------------------------------------------

def test_parse_vote_extracts_buy():
    vote, reason = TradingAgentsSignal._parse_vote(
        "Strong uptrend with momentum.\nVOTE: BUY"
    )
    assert vote == "BUY"
    assert "Strong uptrend" in reason


def test_parse_vote_defaults_to_hold_when_missing():
    vote, _ = TradingAgentsSignal._parse_vote("No clear bias here.")
    assert vote == "HOLD"


def test_parse_vote_case_insensitive():
    vote, _ = TradingAgentsSignal._parse_vote("vote: sell")
    assert vote == "SELL"


def test_parse_decision_reads_json():
    raw = '{"decision": "BUY", "confidence": 0.7, "reasoning": "x"}'
    assert TradingAgentsSignal._parse_decision(raw) == "BUY"


def test_parse_decision_invalid_json_falls_back_to_hold():
    assert TradingAgentsSignal._parse_decision("not json at all") == "HOLD"


def test_parse_decision_unknown_value_falls_back_to_hold():
    raw = '{"decision": "MOON", "confidence": 1.0}'
    assert TradingAgentsSignal._parse_decision(raw) == "HOLD"


# ---------------------------------------------------------------------------
# Aggregation: 4 analyst votes + synthesizer -> TradingAgentsScore
# ---------------------------------------------------------------------------

def test_evaluate_aggregates_buy_consensus(monkeypatch):
    replies = [
        "Bullish momentum.\nVOTE: BUY",        # technical
        "Sector hot.\nVOTE: BUY",              # sentiment
        "Solid fundamentals.\nVOTE: BUY",      # fundamental
        "Risks contained.\nVOTE: BUY",         # risk
        '{"decision": "BUY", "confidence": 0.8, "reasoning": "all green"}',
    ]
    sig = _make_signal_instance(monkeypatch, replies)
    result = sig.evaluate("BTC/USD", 100.0, _BARS, _INDICATORS, change_24h_pct=2.5)

    assert isinstance(result, TradingAgentsScore)
    assert result.side == "buy"
    assert result.score == 4
    assert result.raw_decision == "BUY"
    assert set(result.votes) == {"technical", "sentiment", "fundamental", "risk"}
    assert all(v == "BUY" for v in result.votes.values())


def test_evaluate_sell_consensus_uses_sell_count(monkeypatch):
    replies = [
        "Breakdown.\nVOTE: SELL",
        "Fading interest.\nVOTE: SELL",
        "Weak fundamentals.\nVOTE: HOLD",
        "Ugly tape.\nVOTE: SELL",
        '{"decision": "SELL", "confidence": 0.6, "reasoning": "downside"}',
    ]
    sig = _make_signal_instance(monkeypatch, replies)
    result = sig.evaluate("ETH/USD", 50.0, _BARS, _INDICATORS, change_24h_pct=-3.0)

    assert result.side == "sell"
    assert result.score == 3  # SELL votes only
    assert result.raw_decision == "SELL"


def test_evaluate_hold_returns_none_side(monkeypatch):
    replies = [
        "Mixed.\nVOTE: HOLD",
        "Neutral.\nVOTE: HOLD",
        "Wait.\nVOTE: HOLD",
        "No edge.\nVOTE: HOLD",
        '{"decision": "HOLD", "confidence": 0.4, "reasoning": "wait"}',
    ]
    sig = _make_signal_instance(monkeypatch, replies)
    result = sig.evaluate("SOL/USD", 25.0, _BARS, _INDICATORS)

    assert result.side == "none"
    assert result.raw_decision == "HOLD"


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def test_evaluate_caches_within_hour_bucket(monkeypatch):
    replies = [
        "ok\nVOTE: BUY", "ok\nVOTE: BUY", "ok\nVOTE: BUY", "ok\nVOTE: BUY",
        '{"decision": "BUY"}',
    ]
    sig = _make_signal_instance(monkeypatch, replies)

    first = sig.evaluate("BTC/USD", 100.0, _BARS, _INDICATORS)
    # Second call should hit the cache — no replies left, but no exception either
    second = sig.evaluate("BTC/USD", 100.0, _BARS, _INDICATORS)

    assert first is second
    assert second.raw_decision == "BUY"


# ---------------------------------------------------------------------------
# Bar summary helper
# ---------------------------------------------------------------------------

def test_summarize_bars_handles_empty():
    assert TradingAgentsSignal._summarize_bars([]) == "  (no bars)"


def test_summarize_bars_renders_ohlcv():
    out = TradingAgentsSignal._summarize_bars(_BARS[:2])
    assert "O=100.00" in out
    assert "C=101.00" in out
    assert out.count("\n") == 1  # two lines = one newline


# ---------------------------------------------------------------------------
# merge_with_confluence policy
# ---------------------------------------------------------------------------

def test_merge_unavailable_returns_unchanged():
    score, reason = merge_with_confluence(3, None, "buy")
    assert score == 3
    assert reason == "ta_unavailable"


def test_merge_agreement_boosts_score():
    ta = TradingAgentsScore(
        symbol="BTC/USD", score=4, side="buy",
        votes={}, rationales={}, raw_decision="BUY",
    )
    score, reason = merge_with_confluence(3, ta, "buy")
    assert score == 5  # 3 + min(2, 4//2) = 3 + 2
    assert reason.startswith("ta_agree")


def test_merge_disagreement_blocks_by_default():
    ta = TradingAgentsScore(
        symbol="BTC/USD", score=3, side="sell",
        votes={}, rationales={}, raw_decision="SELL",
    )
    score, reason = merge_with_confluence(4, ta, "buy")
    assert score == 0
    assert "veto" in reason


def test_merge_disagreement_soft_penalty_when_block_disabled():
    ta = TradingAgentsScore(
        symbol="BTC/USD", score=3, side="sell",
        votes={}, rationales={}, raw_decision="SELL",
    )
    score, reason = merge_with_confluence(4, ta, "buy", block_on_disagreement=False)
    assert score == 3  # 4 - 1
    assert "disagree" in reason


def test_merge_neutral_returns_unchanged():
    ta = TradingAgentsScore(
        symbol="BTC/USD", score=2, side="none",
        votes={}, rationales={}, raw_decision="HOLD",
    )
    score, reason = merge_with_confluence(3, ta, "buy")
    assert score == 3
    assert reason == "ta_neutral"


# ---------------------------------------------------------------------------
# Fault tolerance: an internal exception inside evaluate returns None
# ---------------------------------------------------------------------------

def test_evaluate_returns_none_on_internal_exception(monkeypatch):
    sig = _make_signal_instance(monkeypatch, [])

    def boom(*_args, **_kwargs):
        raise RuntimeError("forced failure")
    sig._call = boom

    result = sig.evaluate("BTC/USD", 100.0, _BARS, _INDICATORS)
    assert result is None
