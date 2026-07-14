# tests/test_gross_pnl_writers.py
"""Phase 20 — the TWO LIVE FEE-LESS GROSS-P&L WRITERS (cases W1-W6). RED until Plan 20-08.

    src/trend_strategy.py:172-173   pnl = (current_price - entry) * q   -> update_alpaca_trade(..., pnl=pnl)
    src/bot_c/strategy.py:400-402   pnl = (current_price - entry) * q   -> update_alpaca_trade(..., pnl=pnl)

**NO `fees=` ARGUMENT AT ALL.** Both are LIVE dispatch paths (src/bot_thread.py:552 ->
run_trend_cycle; :561 -> run_tradingagents_cycle). src/db.py:331 already names the tell out
loud: *"NULL fees is the TELL that pnl is gross."*

WHY THIS FILE EXISTS — THE BIAS STRUCTURALLY EXCEEDS THE TOLERANCE:
The post-T0 anchored window is the ONLY evidence VERIFY-02 has, and these two writers push
fee-less GROSS P&L straight into it. TAKER_FEE = 0.0025, so a round trip costs ~0.5% of
**NOTIONAL**, while `window_tolerance` is 0.5% of **REALIZED**. Those quantities differ by
10-100x. $50k of turnover producing $500 realized leaves a ~$250 fee residue against a $25
tolerance.

Without this fix, Phase 20 ships a reconciliation check that is **BIASED TO FAIL**, and then
reads its own failure as a finding. That is not verification — it is manufacturing an
artifact and then measuring it.

`(current_price - entry) * q` is ALSO SIGN-WRONG FOR A SHORT. Phase 17's EVIDENCE flags
sign-inverted shorts on exactly these fee-less rows.

Zero DB, zero network, zero live Alpaca, zero skips.
"""
import pytest

from src.fee_gate import TAKER_FEE
from src.pnl import realized_pnl

# Sized so gross-vs-net EXCEEDS the $25 tolerance floor by a wide margin — these cases are
# NOT numerically vacuous.
_ENTRY = 100.0
_EXIT = 120.0
_QTY = 500.0
_FEES = (_ENTRY * _QTY + _EXIT * _QTY) * TAKER_FEE          # = $275.00
_GROSS = (_EXIT - _ENTRY) * _QTY                            # = $10,000.00
_NET_LONG = realized_pnl("buy", _ENTRY, _EXIT, _QTY, TAKER_FEE)


def test_the_fixture_is_not_vacuous():
    """Positive control: gross-vs-net on this fixture is far larger than the $25 floor."""
    assert _GROSS - _NET_LONG == pytest.approx(_FEES, abs=1e-9)
    assert _FEES > 25.0, "fixture is vacuous — a gross/net error would hide inside tolerance"


class _RecordingLogger:
    """Records exactly what each writer hands to update_alpaca_trade."""

    def __init__(self, rows):
        self._rows = rows
        self.calls: list[dict] = []

    def get_open_alpaca_positions(self):
        return [dict(r) for r in self._rows]

    def update_alpaca_trade(self, trade_id, status, exit_price=None, pnl=None, fees=None):
        self.calls.append({"id": trade_id, "status": status, "exit_price": exit_price,
                           "pnl": pnl, "fees": fees})

    def log_alpaca_trade(self, data):     # never reached on the exit path
        return 1


def _row(side="buy", entry=_ENTRY, qty=_QTY, symbol="BITX"):
    return {"id": 1, "symbol": symbol, "side": side, "qty": qty, "entry_price": entry}


# ── the trend writer (src/trend_strategy.py) ────────────────────────────────

class _TrendAlpaca:
    """BEARISH benchmark (price < MA) + an OPEN position -> the exit branch runs."""

    def __init__(self, target="BITX"):
        self.target = target

    def get_bars(self, symbol, timeframe="1Day", limit=55):
        # 60 bars: a high plateau then a crash, so price < 50DMA -> BEARISH.
        return [{"close": 100.0} for _ in range(59)] + [{"close": 1.0}]

    def get_account(self):
        return {"cash": 0.0, "equity": 10_000.0}

    def get_positions(self):
        return [{"symbol": self.target, "qty": _QTY, "current_price": _EXIT}]

    def get_latest_price(self, symbol):
        return _EXIT

    def place_market_order(self, symbol, qty, side):
        return {"id": "ord-exit"}


def _run_trend(side):
    from src.bot_config import BotConfig
    from src.trend_strategy import run_trend_cycle

    cfg = BotConfig(bot_id="A", label="trend", alpaca_api_key="k",
                    alpaca_secret_key="s", strategy="trend_btc", trend_symbol="BITX",
                    trend_benchmark="BTC/USD", trend_ma_window=50)
    logger = _RecordingLogger([_row(side=side, symbol="BITX")])
    run_trend_cycle(cfg, _TrendAlpaca(), logger)
    assert logger.calls, "the exit branch never ran — fixture error, not a real RED"
    return logger.calls[0]


def test_w1_trend_writer_records_fees():
    """W1. RED: `fees` is never passed — it is None. NULL fees IS the gross tell."""
    call = _run_trend("buy")
    assert call["fees"] is not None, \
        "the trend exit writer records NO fees — src/db.py:331: 'NULL fees is the TELL " \
        "that pnl is gross'"
    assert call["fees"] == pytest.approx(_FEES, abs=1e-9)


def test_w2_trend_writer_records_net_pnl():
    """W2. RED: it records `(current_price - entry) * q` — GROSS.

    Gross-vs-net on this fixture is $275 — ELEVEN TIMES the $25 tolerance floor.
    """
    call = _run_trend("buy")
    assert call["pnl"] == pytest.approx(_NET_LONG, abs=1e-9), \
        f"gross P&L recorded ({call['pnl']}) instead of net ({_NET_LONG})"


def test_w3_trend_writer_short_sign_is_correct():
    """W3. A SHORT exiting BELOW entry is a PROFIT.

    RED: `(current_price - entry) * q` is SIGN-WRONG for a short — it records a LOSS.
    """
    from src.bot_config import BotConfig
    from src.trend_strategy import run_trend_cycle

    class _ShortAlpaca(_TrendAlpaca):
        def get_latest_price(self, symbol):
            return 80.0          # exit BELOW the 100.0 entry

        def get_positions(self):
            return [{"symbol": "BITX", "qty": _QTY, "current_price": 80.0}]

    cfg = BotConfig(bot_id="A", label="trend", alpaca_api_key="k",
                    alpaca_secret_key="s", strategy="trend_btc", trend_symbol="BITX",
                    trend_benchmark="BTC/USD", trend_ma_window=50)
    logger = _RecordingLogger([_row(side="sell", entry=_ENTRY, symbol="BITX")])
    run_trend_cycle(cfg, _ShortAlpaca(), logger)

    assert logger.calls, "the exit branch never ran — fixture error"
    pnl = logger.calls[0]["pnl"]
    expected = realized_pnl("sell", _ENTRY, 80.0, _QTY, TAKER_FEE)
    assert expected > 0, "fixture error — a short exiting below entry is a PROFIT"
    assert pnl > 0, f"a PROFITABLE short was recorded as a LOSS ({pnl}) — the sign is inverted"
    assert pnl == pytest.approx(expected, abs=1e-9)


# ── the bot_c / TradingAgents writer (src/bot_c/strategy.py) ────────────────

class _BotCAlpaca:
    def __init__(self, exit_price=_EXIT):
        self.exit_price = exit_price

    def get_latest_price(self, symbol):
        return self.exit_price

    def place_market_order(self, symbol, qty, side):
        return {"id": "ord-exit"}


def _run_bot_c(side, exit_price=_EXIT):
    from src.bot_c.strategy import _exit_position

    logger = _RecordingLogger([_row(side=side, symbol="AAPL")])
    _exit_position(
        symbol="AAPL",
        position={"qty": _QTY, "current_price": exit_price},
        alpaca=_BotCAlpaca(exit_price),
        logger=logger,
        bot_id="C",
        rating="Sell",
        decision_text="bearish",
    )
    assert logger.calls, "the exit branch never ran — fixture error, not a real RED"
    return logger.calls[0]


def test_w4_bot_c_writer_records_fees():
    """W4. RED: `fees` is never passed — it is None."""
    call = _run_bot_c("buy")
    assert call["fees"] is not None, \
        "the bot_c exit writer records NO fees — NULL fees is the TELL that pnl is gross"
    assert call["fees"] == pytest.approx(_FEES, abs=1e-9)


def test_w5_bot_c_writer_records_net_pnl():
    """W5. RED: it records GROSS. Gross-vs-net here is $275 — 11x the $25 floor."""
    call = _run_bot_c("buy")
    assert call["pnl"] == pytest.approx(_NET_LONG, abs=1e-9), \
        f"gross P&L recorded ({call['pnl']}) instead of net ({_NET_LONG})"


def test_w6_bot_c_writer_short_sign_is_correct():
    """W6. RED: a PROFITABLE short is recorded as a LOSS — the sign is inverted."""
    call = _run_bot_c("sell", exit_price=80.0)
    expected = realized_pnl("sell", _ENTRY, 80.0, _QTY, TAKER_FEE)
    assert expected > 0, "fixture error — a short exiting below entry is a PROFIT"
    assert call["pnl"] > 0, \
        f"a PROFITABLE short was recorded as a LOSS ({call['pnl']}) — the sign is inverted"
    assert call["pnl"] == pytest.approx(expected, abs=1e-9)
