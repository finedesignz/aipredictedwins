"""Backtester package — offline replay of the trading pipeline."""
from src.backtester.config import PhaseConfig, PHASE_PRESETS
from src.backtester.portfolio import BacktestPortfolio
from src.backtester.metrics import compute_summary

__all__ = ["PhaseConfig", "PHASE_PRESETS", "BacktestPortfolio", "compute_summary"]
