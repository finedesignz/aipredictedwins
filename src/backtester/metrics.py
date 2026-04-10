"""Backtester performance metrics."""
from __future__ import annotations
import math


def sharpe_ratio(returns: list[float], risk_free: float = 0.0) -> float:
    """Annualised Sharpe ratio from per-period returns."""
    if len(returns) < 2:
        return 0.0
    n = len(returns)
    mean = sum(returns) / n - risk_free
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(252)


def max_drawdown(equity_curve: list[float]) -> float:
    """Maximum peak-to-trough drawdown as a fraction (0.0-1.0)."""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def win_rate(trades: list[dict]) -> float:
    if not trades:
        return 0.0
    return sum(1 for t in trades if t.get("pnl", 0) > 0) / len(trades)


def monitor_pnl(trades: list[dict]) -> float:
    return sum(t.get("pnl", 0.0) for t in trades)


def compute_summary(
    trades: list[dict],
    equity_curve: list[float],
    starting_equity: float = 100_000.0,
) -> dict:
    returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]
        returns.append((equity_curve[i] - prev) / prev if prev > 0 else 0.0)
    total_pnl = monitor_pnl(trades)
    final_equity = equity_curve[-1] if equity_curve else starting_equity
    return {
        "trade_count":      len(trades),
        "monitor_pnl":      round(total_pnl, 2),
        "win_rate":         round(win_rate(trades), 4),
        "sharpe_ratio":     round(sharpe_ratio(returns), 4),
        "max_drawdown":     round(max_drawdown(equity_curve), 4),
        "total_return_pct": round((final_equity - starting_equity) / starting_equity * 100, 4),
        "final_equity":     round(final_equity, 2),
    }
