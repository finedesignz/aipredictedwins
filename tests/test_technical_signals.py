"""Tests for the technical signal engine."""

import pytest
from src.technical_signals import _ema, _rsi, _adx, _volume_spike, _vwap_bullish, analyze


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
    """Generate an uptrend: steadily rising prices."""
    closes = [start + i * step for i in range(n)]
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
        adx = _adx(highs, lows, closes, 14)
        assert adx is not None
        assert adx > 20  # should indicate strong trend

    def test_insufficient_data(self):
        assert _adx([1, 2, 3], [0.5, 1.5, 2.5], [0.8, 1.8, 2.8], 14) is None

    def test_returns_float(self):
        n = 50
        highs = [100 + i * 0.5 for i in range(n)]
        lows = [99 + i * 0.5 for i in range(n)]
        closes = [99.5 + i * 0.5 for i in range(n)]
        adx = _adx(highs, lows, closes, 14)
        assert isinstance(adx, float)


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
        assert hasattr(signal, "rsi_value")
        assert hasattr(signal, "rsi_signal")
        assert hasattr(signal, "volume_spike")
        assert hasattr(signal, "vwap_bullish")
        assert hasattr(signal, "confluence_score")
        assert hasattr(signal, "details")
        assert 0 <= signal.confluence_score <= 5

    def test_sideways_low_score(self):
        bars = _make_sideways_bars(50)
        signal = analyze("XRP/USD", bars)
        assert signal is not None
        # Sideways market should have low ADX, uncertain signals
        assert signal.confluence_score <= 3


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
        assert verdict.decision == "PROCEED"  # safe default


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
        # Position up 2% — below 3% activation
        assert ts.update(1, 100.0, 102.0) is None

    def test_activates_and_holds(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        # Position up 5% — above 3% activation, not trailing yet
        assert ts.update(1, 100.0, 105.0) is None

    def test_triggers_on_pullback(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        # Build up to peak
        ts.update(1, 100.0, 105.0)  # peak at 105
        ts.update(1, 100.0, 107.0)  # new peak at 107
        # Trail stop = 107 * (1 - 0.02) = 104.86
        # Price drops to 104 — below trailing stop
        result = ts.update(1, 100.0, 104.0)
        assert result == "trailing_stop"

    def test_no_trigger_above_trail(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        ts.update(1, 100.0, 106.0)  # peak at 106
        # Trail stop = 106 * 0.98 = 103.88
        # Price at 105 — still above trail
        assert ts.update(1, 100.0, 105.0) is None

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
        assert check_position_thresholds(100.0, 95.0) == "hard_stop"  # -5%

    def test_hard_take_profit(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 111.0) == "hard_take_profit"  # +11%

    def test_soft_stop(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 97.5) == "soft_stop"  # -2.5%

    def test_soft_take_profit(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 106.0) == "soft_take_profit"  # +6%

    def test_normal_range(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 100.5) is None  # +0.5%

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
