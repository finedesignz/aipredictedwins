import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.backtester.portfolio import BacktestPortfolio


class TestBacktestPortfolio:
    def test_initial_equity(self):
        p = BacktestPortfolio(100_000.0)
        assert p.equity() == 100_000.0

    def test_open_reduces_cash(self):
        p = BacktestPortfolio(100_000.0)
        p.open_position("BTC/USD", entry_price=50_000.0, qty=0.5, timestamp="2026-03-01T00:00:00")
        assert p.cash() == 75_000.0

    def test_close_profitable(self):
        p = BacktestPortfolio(100_000.0)
        trade_id = p.open_position("BTC/USD", entry_price=50_000.0, qty=0.5,
                                    timestamp="2026-03-01T00:00:00")
        pnl = p.close_position(trade_id, exit_price=55_000.0, timestamp="2026-03-01T12:00:00",
                                reason="hard_take_profit")
        assert pnl == 2_500.0
        assert p.cash() == 102_500.0

    def test_close_loss(self):
        p = BacktestPortfolio(100_000.0)
        trade_id = p.open_position("ETH/USD", entry_price=3_000.0, qty=2.0,
                                    timestamp="2026-03-01T00:00:00")
        pnl = p.close_position(trade_id, exit_price=2_880.0, timestamp="2026-03-01T06:00:00",
                                reason="hard_stop")
        assert abs(pnl - (-240.0)) < 0.01
        assert abs(p.cash() - (100_000.0 - 240.0)) < 0.01

    def test_open_positions_count(self):
        p = BacktestPortfolio(100_000.0)
        p.open_position("BTC/USD", 50_000.0, 0.5, "t1")
        p.open_position("ETH/USD", 3_000.0, 1.0, "t2")
        assert len(p.open_positions()) == 2

    def test_equity_includes_open_positions(self):
        p = BacktestPortfolio(100_000.0)
        p.open_position("BTC/USD", 50_000.0, 0.5, "t1")
        assert abs(p.equity(prices={"BTC/USD": 50_000.0}) - 100_000.0) < 0.01

    def test_trade_history_after_close(self):
        p = BacktestPortfolio(100_000.0)
        tid = p.open_position("BTC/USD", 50_000.0, 0.5, "t1")
        p.close_position(tid, 52_000.0, "t2", "trailing_stop")
        hist = p.trade_history()
        assert len(hist) == 1
        assert hist[0]["pnl"] == 1_000.0
        assert hist[0]["reason"] == "trailing_stop"

    def test_close_unknown_trade_raises(self):
        p = BacktestPortfolio(100_000.0)
        try:
            p.close_position(999, 50_000.0, "t", "stop")
            assert False, "should raise KeyError"
        except KeyError:
            pass
