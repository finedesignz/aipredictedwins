import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.backtester.metrics import sharpe_ratio, max_drawdown, win_rate, monitor_pnl, compute_summary


class TestSharpeRatio:
    def test_positive_returns(self):
        returns = [0.01] * 252
        sr = sharpe_ratio(returns)
        assert sr > 0

    def test_zero_returns(self):
        assert sharpe_ratio([0.0] * 10) == 0.0

    def test_negative_returns(self):
        returns = [-0.01] * 100
        assert sharpe_ratio(returns) < 0

    def test_empty_returns(self):
        assert sharpe_ratio([]) == 0.0


class TestMaxDrawdown:
    def test_no_drawdown(self):
        curve = [100.0 + i for i in range(10)]
        assert max_drawdown(curve) == 0.0

    def test_simple_drawdown(self):
        curve = [100.0, 105.0, 110.0, 99.0, 102.0]
        dd = max_drawdown(curve)
        assert abs(dd - (110 - 99) / 110) < 0.001

    def test_empty(self):
        assert max_drawdown([]) == 0.0


class TestWinRate:
    def test_all_wins(self):
        trades = [{"pnl": 100}, {"pnl": 50}, {"pnl": 200}]
        assert win_rate(trades) == 1.0

    def test_half_wins(self):
        trades = [{"pnl": 100}, {"pnl": -50}, {"pnl": 200}, {"pnl": -30}]
        assert win_rate(trades) == 0.5

    def test_empty(self):
        assert win_rate([]) == 0.0


class TestMonitorPnl:
    def test_sum_of_pnl(self):
        trades = [{"pnl": 100.0}, {"pnl": -50.0}, {"pnl": 75.0}]
        assert monitor_pnl(trades) == 125.0

    def test_empty(self):
        assert monitor_pnl([]) == 0.0


class TestComputeSummary:
    def test_full_summary(self):
        trades = [
            {"pnl": 500.0, "entry_timestamp": "2026-03-01T00:00:00",
             "exit_timestamp": "2026-03-02T00:00:00", "symbol": "BTC/USD"},
            {"pnl": -200.0, "entry_timestamp": "2026-03-03T00:00:00",
             "exit_timestamp": "2026-03-03T12:00:00", "symbol": "ETH/USD"},
        ]
        equity_curve = [100_000.0, 100_500.0, 100_300.0]
        result = compute_summary(trades, equity_curve, starting_equity=100_000.0)
        assert result["trade_count"] == 2
        assert result["monitor_pnl"] == 300.0
        assert result["win_rate"] == 0.5
        assert "sharpe_ratio" in result
        assert "max_drawdown" in result
        assert "total_return_pct" in result
