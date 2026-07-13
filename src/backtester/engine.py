"""
BacktestEngine — time-aligned replay of the trading pipeline.

Phase 0 behaviour:
  - Technical signals (analyze()) on a 50-bar sliding window
  - Entry: confluence >= config.min_confluence, no existing position in symbol
  - Exit: hard thresholds only (-4% hard stop, +10% hard take-profit)
  - No LLM calls in Phase 0
  - Sizing: Kelly based on confluence, capped at max_position_pct
"""
from __future__ import annotations

import logging
from typing import Any

from src.backtester.config import PhaseConfig
from src.backtester.portfolio import BacktestPortfolio
from src.exit_advisor import HARD_STOP_PCT, HARD_TAKE_PROFIT_PCT
from src.universe import entry_allowed

log = logging.getLogger(__name__)

SIGNAL_WINDOW = 50
SCAN_INTERVAL_BARS = 30

_KELLY_PROBS = {3: 0.55, 4: 0.60, 5: 0.65}


def _position_dollar_amount(confluence: int, kelly_fraction: float,
                             max_position_pct: float, equity: float) -> float:
    win_prob = _KELLY_PROBS.get(confluence, 0.55)
    edge = win_prob - (1 - win_prob)
    raw_kelly = edge * kelly_fraction
    capped = min(raw_kelly, max_position_pct)
    return capped * equity


class BacktestEngine:
    def __init__(self, config: PhaseConfig, starting_equity: float | None = None):
        self.config = config
        self._starting_equity = starting_equity or config.starting_equity
        self._equity_curve: list[float] = []

    def run(
        self,
        bars_by_symbol: dict[str, list[dict]],
        start_iso: str,
        end_iso: str,
    ) -> BacktestPortfolio:
        portfolio = BacktestPortfolio(self._starting_equity)

        # Collect all timestamps in range from all symbols
        all_timestamps = sorted({
            b["timestamp"]
            for bars in bars_by_symbol.values()
            for b in bars
            if b["timestamp"][:10] >= start_iso[:10] and b["timestamp"][:10] <= end_iso[:10]
        })

        if not all_timestamps:
            log.warning("No bars in date range %s-%s", start_iso, end_iso)
            self._equity_curve = [self._starting_equity]
            return portfolio

        # Pre-index bars by timestamp per symbol
        bars_by_ts: dict[str, dict[str, dict]] = {sym: {} for sym in bars_by_symbol}
        for sym, bars in bars_by_symbol.items():
            for bar in bars:
                bars_by_ts[sym][bar["timestamp"]] = bar

        windows: dict[str, list[dict]] = {sym: [] for sym in bars_by_symbol}
        last_scan_idx: dict[str, int] = {sym: -SCAN_INTERVAL_BARS for sym in bars_by_symbol}
        open_trade_ids: dict[str, int] = {}  # symbol -> trade_id

        equity_curve: list[float] = [self._starting_equity]

        for ts_idx, ts in enumerate(all_timestamps):
            current_prices: dict[str, float] = {}

            # Advance sliding windows
            for sym in bars_by_symbol:
                bar = bars_by_ts[sym].get(ts)
                if bar:
                    windows[sym].append(bar)
                    if len(windows[sym]) > SIGNAL_WINDOW + 10:
                        windows[sym] = windows[sym][-SIGNAL_WINDOW:]
                    current_prices[sym] = bar["close"]

            # Check exits for open positions
            for sym, trade_id in list(open_trade_ids.items()):
                price = current_prices.get(sym)
                if price is None:
                    continue
                pos_list = [p for p in portfolio.open_positions() if p.trade_id == trade_id]
                if not pos_list:
                    del open_trade_ids[sym]
                    continue
                pos = pos_list[0]
                pnl_pct = (price - pos.entry_price) / pos.entry_price
                if pnl_pct <= HARD_STOP_PCT:
                    portfolio.close_position(trade_id, price, ts, "hard_stop")
                    del open_trade_ids[sym]
                elif pnl_pct >= HARD_TAKE_PROFIT_PCT:
                    portfolio.close_position(trade_id, price, ts, "hard_take_profit")
                    del open_trade_ids[sym]

            # Scan for new entries (throttled)
            for sym, bars_window in windows.items():
                if sym in open_trade_ids:
                    continue
                # THE LIVE GATE (bot_thread.py:146), imported — never re-implemented.
                if not entry_allowed(sym, self.config.symbols, self.config.quarantined)[0]:
                    continue
                if len(bars_window) < SIGNAL_WINDOW:
                    continue
                if ts_idx - last_scan_idx.get(sym, -SCAN_INTERVAL_BARS) < SCAN_INTERVAL_BARS:
                    continue

                last_scan_idx[sym] = ts_idx

                try:
                    from src.technical_signals import analyze
                    signal = analyze(sym, bars_window)
                except Exception as exc:
                    log.debug("Signal error for %s: %s", sym, exc)
                    continue

                if signal is None or signal.confluence_score < self.config.min_confluence:
                    continue

                # The live bot refuses overbought longs (bot_thread.py:147, strict <).
                if signal.rsi_value >= self.config.rsi_ceiling:
                    continue

                price = current_prices.get(sym)
                if price is None or price <= 0:
                    continue

                equity = portfolio.equity(prices=current_prices)
                dollar_amt = _position_dollar_amount(
                    signal.confluence_score,
                    self.config.kelly_fraction,
                    self.config.max_position_pct,
                    equity,
                )
                if dollar_amt < 10:
                    continue

                qty = dollar_amt / price
                trade_id = portfolio.open_position(sym, price, qty, ts)
                open_trade_ids[sym] = trade_id
                log.debug("ENTRY %s @ %.2f (confluence=%d, $%.0f)",
                          sym, price, signal.confluence_score, dollar_amt)

            equity_curve.append(portfolio.equity(prices=current_prices))

        # Force-close any open positions at the last available bar's close price
        last_prices: dict[str, float] = {}
        for sym, bars in bars_by_symbol.items():
            in_window = [b for b in bars if start_iso[:10] <= b.get("timestamp", "")[:10] <= end_iso[:10]]
            if in_window:
                last_prices[sym] = in_window[-1].get("close", 0.0)

        for pos in list(portfolio.open_positions()):
            close_price = last_prices.get(pos.symbol, pos.entry_price)
            portfolio.close_position(pos.trade_id, close_price, end_iso + "T23:59:59", "end_of_backtest")

        self._equity_curve = equity_curve
        return portfolio

    def equity_curve(self) -> list[float]:
        return list(self._equity_curve)
