"""EXIT-02 / EXIT-03 behavioral spec — deterministic ATR exit ladder, no LLM.

These tests drive the shared ``PositionMonitor`` through each exit branch and
assert the deterministic close reason. They are RED until 04-02 adds the
``profile`` constructor arg and the ATR decision ladder.

The exit decision must be LLM-free: ``ExitAdvisor.should_exit`` is never called
for the exit decision (``test_no_llm_call``).
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.alpaca_orchestrator import PositionMonitor
from src.strategy_profile import SWING, DAYTRADE


ATR = 2.0  # known ATR for all bar fixtures here
ENTRY = 100.0


def _bars():
    # Constant-true-range bars (flat closes, high-low=ATR) => Wilder ATR == ATR.
    base = 100.0
    return [
        {"high": base + ATR / 2, "low": base - ATR / 2, "close": base,
         "open": base, "volume": 1000.0}
        for _ in range(20)
    ]


def _trade(side="buy", entry=ENTRY, ts=None, trade_id=1):
    if ts is None:
        ts = datetime.now(timezone.utc).isoformat()
    return {
        "id": trade_id,
        "symbol": "BTC/USD",
        "side": side,
        "entry_price": entry,
        "qty": 1.0,
        "timestamp": ts,
    }


def _run(mock_alpaca, mock_logger, mock_advisor, trade, current_price,
         profile=SWING, bars=None):
    """Seed mocks, run one monitor pass, return captured close_reason or None."""
    mock_logger.get_open_alpaca_positions.return_value = [trade]
    mock_alpaca.get_positions.return_value = [
        {"symbol": "BTCUSD", "avg_entry_price": trade["entry_price"]}
    ]
    mock_alpaca.get_latest_price.return_value = current_price
    mock_alpaca.get_bars.return_value = bars if bars is not None else _bars()

    monitor = PositionMonitor(mock_alpaca, mock_logger, mock_advisor, profile)

    captured = {}

    def _capture(symbol, side, entry_price, current, pnl, reason):
        captured["reason"] = reason

    with patch("src.alpaca_orchestrator.alert_position_closed", side_effect=_capture):
        monitor._check_all_positions()

    return captured.get("reason"), monitor


def test_long_atr_stop_level(mock_alpaca, mock_logger, mock_advisor):
    # price below entry - atr_mult_stop*ATR (2.0*2.0=4.0 -> 96.0)
    price = ENTRY - SWING.atr_mult_stop * ATR - 0.5
    reason, _ = _run(mock_alpaca, mock_logger, mock_advisor, _trade("buy"), price)
    assert reason == "atr_stop"
    mock_alpaca.close_position.assert_called_once()


def test_short_atr_stop_level(mock_alpaca, mock_logger, mock_advisor):
    # short: price above entry + atr_mult_stop*ATR
    price = ENTRY + SWING.atr_mult_stop * ATR + 0.5
    reason, _ = _run(mock_alpaca, mock_logger, mock_advisor, _trade("sell"), price)
    assert reason == "atr_stop"
    mock_alpaca.close_position.assert_called_once()


def test_atr_trail_ratchet(mock_alpaca, mock_logger, mock_advisor):
    # Long: ratchet up to a high-water, then drop into trail = hw - mult_trail*ATR.
    mock_logger.get_open_alpaca_positions.return_value = [_trade("buy")]
    mock_alpaca.get_positions.return_value = [
        {"symbol": "BTCUSD", "avg_entry_price": ENTRY}
    ]
    mock_alpaca.get_bars.return_value = _bars()
    monitor = PositionMonitor(mock_alpaca, mock_logger, mock_advisor, SWING)

    with patch("src.alpaca_orchestrator.alert_position_closed") as alert:
        # advance high-water well above entry (no close)
        mock_alpaca.get_latest_price.return_value = 120.0
        monitor._check_all_positions()
        alert.assert_not_called()
        # drop into trail: 120 - 1.5*2.0 = 117.0
        mock_alpaca.get_latest_price.return_value = 116.0
        monitor._check_all_positions()
        assert alert.call_args[0][5] == "trailing_stop"

    # Short mirror: low-water down only, trail = lw + mult_trail*ATR
    mock_logger.get_open_alpaca_positions.return_value = [_trade("sell", trade_id=2)]
    monitor2 = PositionMonitor(mock_alpaca, mock_logger, mock_advisor, SWING)
    mock_alpaca.close_position.reset_mock()
    with patch("src.alpaca_orchestrator.alert_position_closed") as alert:
        mock_alpaca.get_latest_price.return_value = 80.0  # profit, low-water
        monitor2._check_all_positions()
        alert.assert_not_called()
        mock_alpaca.get_latest_price.return_value = 84.0  # 80 + 1.5*2 = 83 -> breached
        monitor2._check_all_positions()
        assert alert.call_args[0][5] == "trailing_stop"


def test_zero_atr_safe(mock_alpaca, mock_logger, mock_advisor):
    # Insufficient bars -> ATR 0.0 -> no instant exit at a small loss.
    price = ENTRY - 0.5  # tiny loss, not past hard_stop_pct
    reason, _ = _run(mock_alpaca, mock_logger, mock_advisor, _trade("buy"), price,
                     bars=[])  # _atr returns 0.0
    assert reason is None
    mock_alpaca.close_position.assert_not_called()


def test_max_hold_fires(mock_alpaca, mock_logger, mock_advisor):
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    trade = _trade("buy", ts=old_ts)
    reason, _ = _run(mock_alpaca, mock_logger, mock_advisor, trade, ENTRY,
                     profile=DAYTRADE)
    assert reason == "max_hold"


def test_swing_no_time_close(mock_alpaca, mock_logger, mock_advisor):
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=240)).isoformat()
    trade = _trade("buy", ts=old_ts)
    # at entry, no atr breach -> swing (max_hold_hours None) never time-closes
    reason, _ = _run(mock_alpaca, mock_logger, mock_advisor, trade, ENTRY,
                     profile=SWING)
    assert reason != "max_hold"
    assert reason is None


def test_override_precedence(mock_alpaca, mock_logger, mock_advisor):
    # Satisfy hard_stop AND max_hold AND would-trail simultaneously; hard wins.
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    trade = _trade("buy", ts=old_ts)
    price = ENTRY * (1 + DAYTRADE.hard_stop_pct) - 1.0  # below hard_stop_pct
    reason, _ = _run(mock_alpaca, mock_logger, mock_advisor, trade, price,
                     profile=DAYTRADE)
    assert reason == "hard_stop"


def test_no_llm_call(mock_alpaca, mock_logger, mock_advisor):
    # Drive several exit types; ExitAdvisor.should_exit must never be called.
    for side, price, prof in [
        ("buy", ENTRY - 5.0, SWING),       # atr_stop
        ("sell", ENTRY + 5.0, SWING),      # atr_stop short
        ("buy", ENTRY * (1 + SWING.hard_stop_pct) - 1.0, SWING),  # hard_stop
    ]:
        mock_advisor.reset_mock()
        _run(mock_alpaca, mock_logger, mock_advisor, _trade(side), price, profile=prof)
        mock_advisor.should_exit.assert_not_called()
