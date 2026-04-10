# tests/test_pipeline_state.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline_state import PipelineState


class TestPipelineState:
    def _bars(self):
        return tuple({"close": 100.0 + i, "open": 100.0 + i, "high": 101.0 + i,
                      "low": 99.0 + i, "volume": 1000.0, "timestamp": f"2026-03-01T{i:02d}:00:00"}
                     for i in range(5))

    def test_construct(self):
        s = PipelineState(symbol="BTC/USD", bars=self._bars())
        assert s.symbol == "BTC/USD"
        assert len(s.bars) == 5
        assert s.signal is None
        assert s.kelly_fraction == 0.0
        assert s.skipped_reason is None

    def test_with_updates_returns_new(self):
        s = PipelineState(symbol="BTC/USD", bars=self._bars())
        s2 = s.with_updates(kelly_fraction=0.15)
        assert s2.kelly_fraction == 0.15
        assert s.kelly_fraction == 0.0  # original unchanged

    def test_with_updates_preserves_other_fields(self):
        s = PipelineState(symbol="ETH/USD", bars=self._bars(), correlation_penalty=0.1)
        s2 = s.with_updates(kelly_fraction=0.20)
        assert s2.correlation_penalty == 0.1
        assert s2.symbol == "ETH/USD"

    def test_immutable(self):
        import dataclasses
        s = PipelineState(symbol="BTC/USD", bars=self._bars())
        try:
            s.symbol = "ETH/USD"
            assert False, "should have raised FrozenInstanceError"
        except dataclasses.FrozenInstanceError:
            pass

    def test_skipped(self):
        s = PipelineState(symbol="BTC/USD", bars=self._bars(),
                          skipped_reason="reentry_blocked: hard_stop 2h ago")
        assert s.skipped_reason is not None
