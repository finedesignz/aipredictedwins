"""
BacktestPortfolio — simulated position tracking for backtesting.

Simulates fills at the close price of the entry bar.
No slippage, no partial fills, no commissions.
"""
from __future__ import annotations
import dataclasses


@dataclasses.dataclass
class _Position:
    trade_id: int
    symbol: str
    entry_price: float
    qty: float
    entry_timestamp: str
    cost_basis: float


class BacktestPortfolio:
    def __init__(self, starting_equity: float = 100_000.0):
        self._cash = starting_equity
        self._positions: dict[int, _Position] = {}
        self._history: list[dict] = []
        self._next_id = 1

    def open_position(self, symbol: str, entry_price: float, qty: float, timestamp: str) -> int:
        cost = entry_price * qty
        self._cash -= cost
        trade_id = self._next_id
        self._next_id += 1
        self._positions[trade_id] = _Position(
            trade_id=trade_id, symbol=symbol, entry_price=entry_price,
            qty=qty, entry_timestamp=timestamp, cost_basis=cost,
        )
        return trade_id

    def close_position(self, trade_id: int, exit_price: float, timestamp: str, reason: str) -> float:
        pos = self._positions.pop(trade_id)
        proceeds = exit_price * pos.qty
        pnl = proceeds - pos.cost_basis
        self._cash += proceeds
        self._history.append({
            "trade_id": trade_id, "symbol": pos.symbol,
            "entry_price": pos.entry_price, "exit_price": exit_price,
            "qty": pos.qty, "entry_timestamp": pos.entry_timestamp,
            "exit_timestamp": timestamp, "pnl": pnl, "reason": reason,
        })
        return pnl

    def cash(self) -> float:
        return self._cash

    def equity(self, prices: dict[str, float] | None = None) -> float:
        mtm = sum(
            (prices.get(pos.symbol, pos.entry_price) if prices else pos.entry_price) * pos.qty
            for pos in self._positions.values()
        )
        return self._cash + mtm

    def open_positions(self) -> list[_Position]:
        return list(self._positions.values())

    def trade_history(self) -> list[dict]:
        return list(self._history)
