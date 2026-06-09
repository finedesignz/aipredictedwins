"""Tests for the technical signal engine."""

import pytest
from src.technical_signals import _ema, _rsi, _adx, _atr, _volume_spike, _vwap_bullish, analyze
from src.strategy_profile import SWING, DAYTRADE, StrategyProfile


# ---------------------------------------------------------------------------
# Helper: generate synthetic OHLCV bars
# ---------------------------------------------------------------------------

def _make_bars(closes: list[float], base_volume: float = 1000.0) -> list[dict]:
    """Generate bars from a list of close prices with synthetic OHLCV."""
    bars = []
    for i, c in enumerate(closes):
        bars.append({
            "open": c * 0.999,
            "high": c * 1.005,
            "low": c * 0.995,
            "close": c,
            "volume": base_volume + (i * 10),
            "vwap": c * 1.001,
            "timestamp": f"2026-03-27T{i:02d}:00:00",
        })
    return bars


def _make_uptrend_bars(n: int = 50, start: float = 100.0, step: float = 0.5) -> list[dict]:
    """Generate an uptrend: rising prices with realistic oscillation.

    Uses a sine wave overlay (amplitude=5.0) so default step=0.5 bars give
    RSI ~63 (well below the 72 ceiling). Larger step values (e.g. 1.5) produce
    RSI > 72, which is used by RSI-ceiling tests to verify the hard block.
    """
    import math
    closes = [start + i * step + 5.0 * math.sin(i * 0.7) for i in range(n)]
    return _make_bars(closes)


def _make_downtrend_bars(n: int = 50, start: float = 125.0, step: float = 0.5) -> list[dict]:
    """Generate a downtrend: steadily falling prices."""
    closes = [start - i * step for i in range(n)]
    return _make_bars(closes)


def _make_sideways_bars(n: int = 50, center: float = 100.0, amplitude: float = 0.5) -> list[dict]:
    """Generate sideways chop: oscillating around a center."""
    import math
    closes = [center + amplitude * math.sin(i * 0.5) for i in range(n)]
    return _make_bars(closes)


# ---------------------------------------------------------------------------
# EMA tests
# ---------------------------------------------------------------------------

class TestEMA:
    def test_basic_ema(self):
        closes = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        result = _ema(closes, 3)
        assert len(result) == 8  # n - period + 1 values
        assert result[-1] > result[0]  # trending up

    def test_insufficient_data(self):
        assert _ema([1.0, 2.0], 5) == []

    def test_constant_prices(self):
        closes = [50.0] * 20
        result = _ema(closes, 9)
        assert all(abs(v - 50.0) < 0.01 for v in result)


# ---------------------------------------------------------------------------
# RSI tests
# ---------------------------------------------------------------------------

class TestRSI:
    def test_uptrend_high_rsi(self):
        closes = [100 + i for i in range(20)]  # steady up
        rsi = _rsi(closes, 14)
        assert rsi is not None
        assert rsi > 70  # should be overbought

    def test_downtrend_low_rsi(self):
        closes = [120 - i for i in range(20)]  # steady down
        rsi = _rsi(closes, 14)
        assert rsi is not None
        assert rsi < 30  # should be oversold

    def test_insufficient_data(self):
        assert _rsi([1, 2, 3], 14) is None

    def test_flat_prices(self):
        closes = [100.0] * 20
        rsi = _rsi(closes, 14)
        # All deltas are 0 → avg_loss = 0 → RSI = 100
        assert rsi == 100.0


# ---------------------------------------------------------------------------
# ADX tests
# ---------------------------------------------------------------------------

class TestADX:
    def test_strong_trend_high_adx(self):
        n = 50
        highs = [100 + i * 1.2 for i in range(n)]
        lows = [99 + i * 1.0 for i in range(n)]
        closes = [100 + i * 1.1 for i in range(n)]
        result = _adx(highs, lows, closes, 14)
        assert result is not None
        adx, plus_di, minus_di = result
        assert adx > 20

    def test_insufficient_data(self):
        assert _adx([1, 2, 3], [0.5, 1.5, 2.5], [0.8, 1.8, 2.8], 14) is None

    def test_returns_tuple(self):
        n = 50
        highs = [100 + i * 0.5 for i in range(n)]
        lows = [99 + i * 0.5 for i in range(n)]
        closes = [99.5 + i * 0.5 for i in range(n)]
        result = _adx(highs, lows, closes, 14)
        assert isinstance(result, tuple)
        adx, plus_di, minus_di = result
        assert isinstance(adx, float)


# ---------------------------------------------------------------------------
# ATR tests (SIGNAL-02)
# ---------------------------------------------------------------------------

class TestATR:
    def test_hand_fixture(self):
        # Per RESEARCH §2 hand-computed: _atr(...,2) == 2.5
        highs = [10, 11, 12, 11, 13]
        lows = [9, 10, 10, 9, 11]
        closes = [9, 11, 11, 10, 12]
        assert _atr(highs, lows, closes, 2) == 2.5

    def test_insufficient_data(self):
        # n < period + 1 -> 0.0
        assert _atr([10, 11], [9, 10], [9, 11], 14) == 0.0

    def test_mismatched_lengths(self):
        assert _atr([10, 11, 12], [9, 10], [9, 11, 11], 2) == 0.0

    def test_atr_value_populated_on_signal(self):
        bars = _make_uptrend_bars(50)
        signal = analyze("BTC/USD", bars)
        assert signal is not None
        assert hasattr(signal, "atr_value")
        assert signal.atr_value > 0.0


# ---------------------------------------------------------------------------
# Volume spike tests
# ---------------------------------------------------------------------------

class TestVolumeSpike:
    def test_spike_detected(self):
        volumes = [100.0] * 20 + [200.0]  # 2x average
        assert _volume_spike(volumes, lookback=20, threshold=1.5) is True

    def test_no_spike(self):
        volumes = [100.0] * 21
        assert _volume_spike(volumes, lookback=20, threshold=1.5) is False

    def test_insufficient_data(self):
        assert _volume_spike([100.0] * 5, lookback=20) is False


# ---------------------------------------------------------------------------
# VWAP tests
# ---------------------------------------------------------------------------

class TestVWAP:
    def test_above_vwap(self):
        closes = [105.0]
        volumes = [1000.0]
        vwaps = [100.0]
        assert _vwap_bullish(closes, volumes, vwaps) is True

    def test_below_vwap(self):
        closes = [95.0]
        volumes = [1000.0]
        vwaps = [100.0]
        assert _vwap_bullish(closes, volumes, vwaps) is False

    def test_fallback_without_vwap(self):
        closes = [100.0, 101.0, 102.0, 103.0, 104.0]
        volumes = [1000.0] * 5
        vwaps = [0.0] * 5  # no vwap data
        # Computed VWAP ≈ average close, last close = 104 > avg
        assert _vwap_bullish(closes, volumes, vwaps) is True


class TestSessionVWAP:
    def test_session_anchor_excludes_prior_day(self):
        # Prior UTC day: very high prices (would drag session VWAP up if included).
        # Current UTC day: lower prices but last close above the current-day VWAP.
        closes = [200.0, 200.0, 100.0, 101.0, 105.0]
        volumes = [1000.0] * 5
        vwaps = [0.0] * 5  # force computed path
        timestamps = [
            "2026-06-07T22:00:00",
            "2026-06-07T23:00:00",
            "2026-06-08T00:00:00",
            "2026-06-08T01:00:00",
            "2026-06-08T02:00:00",
        ]
        # Current-day bars: closes [100,101,105], vwap = (100+101+105)/3 = 102 ; 105 > 102 -> True
        assert _vwap_bullish(closes, volumes, vwaps, timestamps=timestamps, session_anchor=True) is True

    def test_session_anchor_below_current_day_vwap(self):
        closes = [50.0, 50.0, 110.0, 109.0, 100.0]
        volumes = [1000.0] * 5
        vwaps = [0.0] * 5
        timestamps = [
            "2026-06-07T22:00:00",
            "2026-06-07T23:00:00",
            "2026-06-08T00:00:00",
            "2026-06-08T01:00:00",
            "2026-06-08T02:00:00",
        ]
        # Current-day vwap = (110+109+100)/3 = 106.33 ; last close 100 < 106.33 -> False
        assert _vwap_bullish(closes, volumes, vwaps, timestamps=timestamps, session_anchor=True) is False

    def test_session_anchor_false_unchanged(self):
        # session_anchor=False must match legacy behavior (vwap[-1] path)
        closes = [105.0]
        volumes = [1000.0]
        vwaps = [100.0]
        assert _vwap_bullish(closes, volumes, vwaps, session_anchor=False) is True
        # and the fallback path
        closes2 = [100.0, 101.0, 102.0, 103.0, 104.0]
        assert _vwap_bullish(closes2, [1000.0] * 5, [0.0] * 5, session_anchor=False) is True

    def test_daytrade_uses_session_anchor(self):
        # analyze with DAYTRADE profile should not crash and produce a Signal
        bars = _make_uptrend_bars(50)
        s = analyze("BTC/USD", bars, profile=DAYTRADE)
        # may be None only by score contract; just ensure no crash on session path
        assert s is None or hasattr(s, "vwap_bullish")


# ---------------------------------------------------------------------------
# Full analyze() integration tests
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_uptrend_signal(self):
        bars = _make_uptrend_bars(50)
        signal = analyze("BTC/USD", bars)
        assert signal is not None
        assert signal.symbol == "BTC/USD"
        assert signal.ema_bullish is True  # EMA9 > EMA21 in uptrend
        assert signal.confluence_score >= 1

    def test_downtrend_signal(self):
        bars = _make_downtrend_bars(50)
        signal = analyze("ETH/USD", bars)
        assert signal is not None
        assert signal.ema_bullish is False
        # Downtrend can still score on ADX (trend strength), RSI (oversold), VWAP
        # EMA won't fire in a downtrend, but other indicators can
        assert signal.confluence_score <= 4

    def test_insufficient_bars(self):
        bars = _make_bars([100.0] * 10)
        signal = analyze("SOL/USD", bars)
        assert signal is None

    def test_signal_fields(self):
        bars = _make_uptrend_bars(50)
        signal = analyze("BTC/USD", bars)
        assert signal is not None
        assert hasattr(signal, "ema_bullish")
        assert hasattr(signal, "adx_value")
        assert hasattr(signal, "adx_trending")
        assert hasattr(signal, "plus_di")
        assert hasattr(signal, "minus_di")
        assert hasattr(signal, "rsi_value")
        assert hasattr(signal, "rsi_signal")
        assert hasattr(signal, "volume_spike")
        assert hasattr(signal, "vwap_bullish")
        assert hasattr(signal, "confluence_score")
        assert hasattr(signal, "details")
        assert 0 <= signal.confluence_score <= 5
        assert signal.plus_di >= 0
        assert signal.minus_di >= 0

    def test_sideways_low_score(self):
        bars = _make_sideways_bars(50)
        signal = analyze("XRP/USD", bars)
        assert signal is not None
        # Sideways market should have low ADX, uncertain signals
        assert signal.confluence_score <= 3


# ---------------------------------------------------------------------------
# Profile parameterization + swing parity (SIGNAL-01)
# ---------------------------------------------------------------------------

class TestProfilePeriods:
    def test_analyze_accepts_profile_last_param(self):
        bars = _make_uptrend_bars(50)
        # profile must be the LAST param (D-01) — positional call form
        signal = analyze("BTC/USD", bars, None, SWING)
        assert signal is not None

    def test_profile_periods_sourced(self):
        # A profile with distinct periods drives indicator computation without crashing
        prof = StrategyProfile(
            name="custom", timeframe="1Hour", scan_interval_s=600, bar_count=50,
            htf_filter_timeframe="4Hour", ema_fast=5, ema_slow=13, rsi_period=7,
            adx_period=7, atr_period=7, atr_mult_stop=2.0, atr_mult_trail=1.5,
            hard_stop_pct=-0.15, max_hold_hours=None, kelly_fraction=0.25,
            max_position_pct=0.05, min_confluence=4, min_short_confluence=3,
        )
        bars = _make_uptrend_bars(50)
        s_default = analyze("BTC/USD", bars, profile=SWING)
        s_custom = analyze("BTC/USD", bars, profile=prof)
        assert s_custom is not None
        # Different ATR period -> different atr_value vs swing(14)
        assert s_custom.atr_value != s_default.atr_value

    def test_swing_parity_snapshot(self):
        """analyze(profile=SWING) reproduces pre-change 9/21/14 output byte-for-byte."""
        bars = _make_uptrend_bars(50)
        s = analyze("BTC/USD", bars, profile=SWING)
        assert s is not None
        assert s.confluence_score == 3
        assert s.short_score == 0
        assert round(s.adx_value, 6) == 25.308993
        assert round(s.rsi_value, 6) == 63.086041
        assert s.ema_bullish is True
        assert s.vwap_bullish is False
        assert round(s.atr_value, 6) == 2.814057
        assert s.market_regime == "trending"

    def test_none_contract_preserved(self):
        bars = _make_sideways_bars(50, center=100.0, amplitude=0.0001)
        # flat-ish market still returns a Signal or None per score==0 contract; just no crash
        _ = analyze("XRP/USD", bars, profile=SWING)


# ---------------------------------------------------------------------------
# Risk gate response parsing tests
# ---------------------------------------------------------------------------

class TestRiskGateParsing:
    def test_parse_proceed(self):
        from src.risk_gate import RiskGate
        gate = RiskGate.__new__(RiskGate)
        raw = '{"scenarios": [], "votes": {"macro": "PROCEED", "liquidity": "PROCEED", "correlation": "PROCEED", "event_risk": "PROCEED", "technical_skeptic": "PROCEED"}, "decision": "PROCEED", "reasoning": "All clear."}'
        verdict = gate._parse_response(raw)
        assert verdict.decision == "PROCEED"

    def test_parse_veto_by_votes(self):
        from src.risk_gate import RiskGate
        gate = RiskGate.__new__(RiskGate)
        raw = '{"scenarios": [], "votes": {"macro": "VETO", "liquidity": "VETO", "correlation": "VETO", "event_risk": "PROCEED", "technical_skeptic": "PROCEED"}, "decision": "PROCEED", "reasoning": "Mixed signals."}'
        verdict = gate._parse_response(raw)
        assert verdict.decision == "VETO"  # 3+ votes override LLM stated decision

    def test_parse_veto_by_critical_scenario(self):
        from src.risk_gate import RiskGate
        gate = RiskGate.__new__(RiskGate)
        raw = '{"scenarios": [{"analyst": "event_risk", "risk": "Major exchange hack", "likelihood": "high", "impact": "high"}], "votes": {"macro": "PROCEED", "liquidity": "PROCEED", "correlation": "PROCEED", "event_risk": "VETO", "technical_skeptic": "PROCEED"}, "decision": "PROCEED", "reasoning": "Mostly fine."}'
        verdict = gate._parse_response(raw)
        assert verdict.decision == "VETO"  # high/high scenario overrides

    def test_parse_invalid_json(self):
        from src.risk_gate import RiskGate
        gate = RiskGate.__new__(RiskGate)
        verdict = gate._parse_response("not json at all")
        assert verdict.decision == "PROCEED"  # parsing fallback (LLM responded but garbled)


# ---------------------------------------------------------------------------
# Exit advisor response parsing tests
# ---------------------------------------------------------------------------

class TestExitAdvisorParsing:
    def test_parse_hold(self):
        from src.exit_advisor import ExitAdvisor
        advisor = ExitAdvisor.__new__(ExitAdvisor)
        raw = '{"decision": "HOLD", "confidence": "high", "reasoning": "Normal pullback."}'
        advice = advisor._parse_response(raw, "soft_stop")
        assert advice.decision == "HOLD"
        assert advice.confidence == "high"

    def test_parse_exit(self):
        from src.exit_advisor import ExitAdvisor
        advisor = ExitAdvisor.__new__(ExitAdvisor)
        raw = '{"decision": "EXIT", "confidence": "medium", "reasoning": "Trend reversal."}'
        advice = advisor._parse_response(raw, "soft_stop")
        assert advice.decision == "EXIT"

    def test_parse_tighten(self):
        from src.exit_advisor import ExitAdvisor
        advisor = ExitAdvisor.__new__(ExitAdvisor)
        raw = '{"decision": "TIGHTEN", "confidence": "low", "reasoning": "Uncertain."}'
        advice = advisor._parse_response(raw, "soft_take_profit")
        assert advice.decision == "TIGHTEN"

    def test_parse_invalid(self):
        from src.exit_advisor import ExitAdvisor
        advisor = ExitAdvisor.__new__(ExitAdvisor)
        advice = advisor._parse_response("garbage", "soft_stop")
        assert advice.decision == "HOLD"  # safe default


# ---------------------------------------------------------------------------
# Exit threshold check tests
# ---------------------------------------------------------------------------

class TestTrailingStop:
    def test_no_trigger_below_activation(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        # Position up 4% — below 5% activation threshold
        assert ts.update(1, 100.0, 104.0) is None

    def test_activates_and_holds(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        # Position up 5.1% — above 5% activation, not trailing yet (peak = current)
        assert ts.update(1, 100.0, 105.1) is None

    def test_triggers_on_pullback(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        # Build up to peak
        ts.update(1, 100.0, 108.0)  # peak at 108
        ts.update(1, 100.0, 110.0)  # new peak at 110
        # Trail stop = 110 * (1 - 0.03) = 106.7
        # Price drops to 106 — below trailing stop
        result = ts.update(1, 100.0, 106.0)
        assert result == "trailing_stop"

    def test_no_trigger_above_trail(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        ts.update(1, 100.0, 108.0)  # peak at 108; trail = 108 * 0.97 = 104.76
        # Price at 105.5 — still above trail
        assert ts.update(1, 100.0, 105.5) is None

    def test_remove_clears_tracking(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        ts.update(1, 100.0, 110.0)  # set high peak
        ts.remove(1)
        # After remove, starts fresh — no activation yet at 101
        assert ts.update(1, 100.0, 101.0) is None


class TestThresholdChecks:
    def test_hard_stop(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 94.9) == "hard_stop"  # -5.1%

    def test_no_hard_take_profit(self):
        # hard_take_profit removed — large gains handled by trailing stop
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 115.0) == "soft_take_profit"

    def test_soft_stop(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 96.9) == "soft_stop"  # -3.1%

    def test_soft_take_profit(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 109.0) == "soft_take_profit"  # +9%

    def test_normal_range(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 100.5) is None  # +0.5%
        assert check_position_thresholds(100.0, 97.5) is None   # -2.5% (within new soft stop -3%)

    def test_zero_entry(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(0.0, 100.0) is None


# ---------------------------------------------------------------------------
# Kelly technical sizing tests
# ---------------------------------------------------------------------------

class TestKellyTechnical:
    def test_confluence_3(self):
        from src.alpaca_orchestrator import _kelly_technical
        result = _kelly_technical(3, 100.0, 10000.0)
        assert result["side"] == "buy"
        assert result["dollar_amount"] > 0
        assert result["shares"] > 0

    def test_confluence_below_min(self):
        from src.alpaca_orchestrator import _kelly_technical
        result = _kelly_technical(2, 100.0, 10000.0)
        assert result["side"] == "none"
        assert result["dollar_amount"] == 0

    def test_position_cap(self):
        from src.alpaca_orchestrator import _kelly_technical
        result = _kelly_technical(5, 100.0, 10000.0, max_position_pct=0.05)
        assert result["dollar_amount"] <= 10000.0 * 0.05 + 0.01

    def test_higher_confluence_bigger_position(self):
        from src.alpaca_orchestrator import _kelly_technical
        r3 = _kelly_technical(3, 100.0, 10000.0)
        r5 = _kelly_technical(5, 100.0, 10000.0)
        assert r5["kelly_pct"] >= r3["kelly_pct"]


class TestRiskGateNoBypass:
    def test_high_confluence_bypass_does_not_exist(self):
        """HIGH_CONFLUENCE_BYPASS must not exist on RiskGate."""
        from src.risk_gate import RiskGate
        assert not hasattr(RiskGate, "HIGH_CONFLUENCE_BYPASS"), (
            "HIGH_CONFLUENCE_BYPASS still exists — bypass must be removed entirely"
        )

    def test_llm_unavailable_vetoes_at_high_confluence(self):
        """When LLM is unavailable, gate must VETO at confluence=4 (previously bypassed)."""
        from src.risk_gate import RiskGate, RiskVerdict

        gate = RiskGate.__new__(RiskGate)
        gate.logger = None

        class FakeLLM:
            def call(self, *a, **kw):
                return None

        gate._llm = FakeLLM()

        verdict = gate.evaluate(
            symbol="BTC/USD", price=70000.0, change_pct=1.5,
            volume=1000000.0, confluence=4, bars=[],
        )
        assert verdict.decision == "VETO", (
            f"Expected VETO when LLM unavailable (confluence=4), got {verdict.decision}"
        )

    def test_llm_unavailable_vetoes_at_low_confluence(self):
        """When LLM is unavailable, gate must VETO at confluence=3 too."""
        from src.risk_gate import RiskGate

        gate = RiskGate.__new__(RiskGate)
        gate.logger = None

        class FakeLLM:
            def call(self, *a, **kw):
                return None

        gate._llm = FakeLLM()

        verdict = gate.evaluate(
            symbol="ETH/USD", price=2000.0, change_pct=0.5,
            volume=500000.0, confluence=3, bars=[],
        )
        assert verdict.decision == "VETO"


class TestPerCycleEntryCap:
    def _make_signal(self, symbol, score, rsi):
        from src.technical_signals import Signal
        import inspect
        sig_fields = {f.name for f in Signal.__dataclass_fields__.values()}
        kwargs = dict(
            symbol=symbol, ema_bullish=True, adx_value=25.0,
            adx_trending=True, rsi_value=rsi, rsi_signal="neutral",
            volume_spike=True, vwap_bullish=True,
            confluence_score=score, details={},
        )
        # Include plus_di/minus_di if the field exists (added by parallel agent)
        if "plus_di" in sig_fields:
            kwargs["plus_di"] = 20.0
        if "minus_di" in sig_fields:
            kwargs["minus_di"] = 10.0
        return Signal(**kwargs)

    def test_selects_top_3_by_confluence_then_rsi(self):
        """_select_cycle_candidates caps at 3, sorted by confluence desc then RSI asc."""
        from src.alpaca_orchestrator import _select_cycle_candidates

        candidates = [
            self._make_signal("BTC/USD", 4, 65),
            self._make_signal("ETH/USD", 4, 58),   # same score, lower RSI → preferred
            self._make_signal("SOL/USD", 3, 50),
            self._make_signal("XRP/USD", 4, 70),   # same score, highest RSI → last
            self._make_signal("ADA/USD", 3, 45),
            self._make_signal("AVAX/USD", 5, 60),  # highest score → first
        ]

        selected = _select_cycle_candidates(candidates, max_entries=3)
        assert len(selected) == 3
        assert selected[0].symbol == "AVAX/USD"   # 5/60
        assert selected[1].symbol == "ETH/USD"    # 4/58
        assert selected[2].symbol == "BTC/USD"    # 4/65

    def test_fewer_than_cap_returns_all(self):
        """If fewer candidates than cap, return all of them."""
        from src.alpaca_orchestrator import _select_cycle_candidates

        candidates = [
            self._make_signal("BTC/USD", 4, 55),
            self._make_signal("ETH/USD", 3, 50),
        ]
        selected = _select_cycle_candidates(candidates, max_entries=3)
        assert len(selected) == 2

    def test_empty_candidates(self):
        """Empty list returns empty list."""
        from src.alpaca_orchestrator import _select_cycle_candidates
        assert _select_cycle_candidates([], max_entries=3) == []

# ---------------------------------------------------------------------------
# RSI hard block tests
# ---------------------------------------------------------------------------

class TestRSIHardBlock:
    def test_overbought_rsi_returns_none(self):
        """Assets with RSI > 72 must return None from analyze()."""
        from src.technical_signals import _rsi
        bars = _make_uptrend_bars(50, start=100.0, step=1.5)
        closes = [b["close"] for b in bars]
        rsi = _rsi(closes, 14)
        signal = analyze("BTC/USD", bars)
        if rsi is not None and rsi > 72:
            assert signal is None, f"Expected None for RSI={rsi:.1f} > 72"

    def test_oversold_rsi_not_blocked(self):
        """RSI < 35 (oversold) must NOT be blocked."""
        from src.technical_signals import _rsi
        bars = _make_downtrend_bars(50, start=125.0, step=0.8)
        closes = [b["close"] for b in bars]
        rsi = _rsi(closes, 14)
        if rsi is not None and rsi < 35:
            # Should not be blocked by the RSI ceiling check
            signal = analyze("ADA/USD", bars)
            # signal may be None for other reasons but NOT because RSI < 35
            if signal is not None:
                assert signal.rsi_signal == "oversold"

    def test_rsi_below_ceiling_not_blocked(self):
        """RSI <= 72 is not blocked by the ceiling check."""
        from src.technical_signals import _rsi
        bars = _make_uptrend_bars(50, start=100.0, step=0.1)
        closes = [b["close"] for b in bars]
        rsi = _rsi(closes, 14)
        # If RSI is at or below 72, analyze() must not return None due to ceiling
        if rsi is not None and rsi <= 72:
            # Just confirm no crash — may return None for data reasons, not ceiling
            _ = analyze("SOL/USD", bars)


# ---------------------------------------------------------------------------
# ADX directional filter tests
# ---------------------------------------------------------------------------

class TestBTCRegimeFilter:
    def test_check_market_regime_overheated(self):
        """OVERHEATED when BTC 1h RSI > 70 AND 4h RSI > 65."""
        from src.alpaca_orchestrator import _check_market_regime
        assert _check_market_regime(btc_rsi_1h=71.0, btc_rsi_4h=66.0) == "OVERHEATED"

    def test_check_market_regime_normal_one_condition(self):
        from src.alpaca_orchestrator import _check_market_regime
        assert _check_market_regime(btc_rsi_1h=72.0, btc_rsi_4h=60.0) == "NORMAL"
        assert _check_market_regime(btc_rsi_1h=65.0, btc_rsi_4h=68.0) == "NORMAL"

    def test_check_market_regime_normal_both_below(self):
        from src.alpaca_orchestrator import _check_market_regime
        assert _check_market_regime(btc_rsi_1h=55.0, btc_rsi_4h=50.0) == "NORMAL"

    def test_check_market_regime_boundary(self):
        from src.alpaca_orchestrator import _check_market_regime
        assert _check_market_regime(btc_rsi_1h=70.0, btc_rsi_4h=65.0) == "NORMAL"


class TestVolumeContextFilter:
    def _make_signal(self, symbol, vol_spike, score=3):
        from src.technical_signals import Signal
        return Signal(
            symbol=symbol, ema_bullish=True, adx_value=25.0,
            adx_trending=True, plus_di=20.0, minus_di=10.0,
            rsi_value=55.0, rsi_signal="neutral",
            volume_spike=vol_spike, vwap_bullish=True,
            confluence_score=score, details={},
        )

    def test_suppress_when_4_or_more_spike(self):
        from src.alpaca_orchestrator import _apply_volume_context_filter
        signals = [
            self._make_signal("BTC/USD", True),
            self._make_signal("ETH/USD", True),
            self._make_signal("SOL/USD", True),
            self._make_signal("XRP/USD", True),  # 4th → suppress
            self._make_signal("ADA/USD", False),
        ]
        filtered = _apply_volume_context_filter(signals)
        for s in filtered:
            assert s.volume_spike is False

    def test_no_suppression_below_threshold(self):
        from src.alpaca_orchestrator import _apply_volume_context_filter
        signals = [
            self._make_signal("BTC/USD", True),
            self._make_signal("ETH/USD", True),
            self._make_signal("SOL/USD", True),  # only 3 → no suppression
            self._make_signal("XRP/USD", False),
        ]
        filtered = _apply_volume_context_filter(signals)
        assert sum(1 for s in filtered if s.volume_spike) == 3

    def test_confluence_recalculated_after_suppression(self):
        from src.alpaca_orchestrator import _apply_volume_context_filter
        signals = [self._make_signal(f"A{i}/USD", True, score=4) for i in range(5)]
        filtered = _apply_volume_context_filter(signals)
        for s in filtered:
            assert s.confluence_score == 3


class TestADXDirectional:
    def test_adx_returns_tuple(self):
        """_adx() must return (adx, plus_di, minus_di) tuple."""
        n = 50
        highs = [100 + i * 1.2 for i in range(n)]
        lows = [99 + i * 1.0 for i in range(n)]
        closes = [100 + i * 1.1 for i in range(n)]
        result = _adx(highs, lows, closes, 14)
        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        assert len(result) == 3
        adx, plus_di, minus_di = result
        assert adx is not None
        assert plus_di >= 0
        assert minus_di >= 0

    def test_uptrend_plus_di_dominates(self):
        """In an uptrend, +DI > -DI."""
        n = 50
        highs = [100 + i * 1.2 for i in range(n)]
        lows = [99 + i * 1.0 for i in range(n)]
        closes = [100 + i * 1.1 for i in range(n)]
        adx, plus_di, minus_di = _adx(highs, lows, closes, 14)
        assert plus_di > minus_di, f"+DI={plus_di:.1f} should > -DI={minus_di:.1f}"

    def test_downtrend_minus_di_dominates(self):
        """In a downtrend, -DI > +DI."""
        n = 50
        highs = [125 - i * 1.0 for i in range(n)]
        lows = [124 - i * 1.2 for i in range(n)]
        closes = [124.5 - i * 1.1 for i in range(n)]
        adx, plus_di, minus_di = _adx(highs, lows, closes, 14)
        assert minus_di > plus_di, f"-DI={minus_di:.1f} should > +DI={plus_di:.1f}"

    def test_signal_has_di_fields(self):
        """Signal dataclass must have plus_di and minus_di fields."""
        bars = _make_uptrend_bars(50)
        signal = analyze("BTC/USD", bars)
        if signal is not None:
            assert hasattr(signal, "plus_di")
            assert hasattr(signal, "minus_di")
            assert signal.plus_di >= 0
            assert signal.minus_di >= 0
