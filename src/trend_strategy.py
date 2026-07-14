"""
Trend-following strategy: ride leveraged BTC ETF when BTC > 50DMA, sit in cash otherwise.

Rationale: Technical-confluence scalping kept getting whipsawed in bull markets
(+0.2% vs BTC +14.4% over 28 days). Trend-following with a 2x leveraged ETF
captures the bull and avoids the bear by mechanical rule.

Rules:
  1. Compute N-day SMA on the benchmark (default: BTC/USD, 50-day).
  2. If price > MA AND no position → buy `trend_symbol` (default BITX) with all cash.
  3. If price < MA AND position open → sell all.
  4. Re-evaluate once per cycle. No intraday churn.

Logged to alpaca_trades with the bot's own bot_id so the dashboard tracks it.
"""

import logging
from typing import Optional

from src.alpaca_client import AlpacaClient
from src.bot_config import BotConfig
from src.fee_gate import TAKER_FEE
from src.pnl import realized_pnl
from src.trade_logger import TradeLogger
from src.universe import entry_allowed

log = logging.getLogger(__name__)


def _sma(values: list[float], window: int) -> Optional[float]:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _benchmark_signal(
    alpaca: AlpacaClient,
    benchmark_symbol: str,
    ma_window: int,
) -> tuple[Optional[bool], Optional[float], Optional[float]]:
    """Return (above_ma, price, ma_value). above_ma is None on data error."""
    try:
        bars = alpaca.get_bars(benchmark_symbol, timeframe="1Day", limit=ma_window + 5)
    except Exception as exc:
        log.warning("[trend] benchmark fetch failed for %s: %s", benchmark_symbol, exc)
        return (None, None, None)

    if not bars or len(bars) < ma_window:
        log.warning("[trend] insufficient bars for %s: got %d, need %d",
                    benchmark_symbol, len(bars or []), ma_window)
        return (None, None, None)

    closes = [b["close"] for b in bars]
    ma = _sma(closes, ma_window)
    price = closes[-1]
    if ma is None or price is None:
        return (None, None, None)
    return (price > ma, price, ma)


def run_trend_cycle(
    cfg: BotConfig,
    alpaca: AlpacaClient,
    logger: TradeLogger,
) -> None:
    """Execute one cycle of the trend-follower strategy."""
    bot_id = cfg.bot_id
    benchmark = cfg.trend_benchmark
    target = cfg.trend_symbol
    ma_window = cfg.trend_ma_window

    above_ma, price, ma = _benchmark_signal(alpaca, benchmark, ma_window)
    if above_ma is None:
        log.warning("[bot:%s][trend] no signal — skipping cycle", bot_id)
        return

    log.info(
        "[bot:%s][trend] %s=$%.2f vs %dDMA=$%.2f → %s",
        bot_id, benchmark, price, ma_window, ma, "BULLISH" if above_ma else "BEARISH",
    )

    # Account state
    try:
        account = alpaca.get_account()
        cash = float(account.get("cash") or account.get("buying_power") or 0)
        equity = float(account.get("equity") or cash)
    except Exception as exc:
        log.error("[bot:%s][trend] account fetch failed: %s", bot_id, exc)
        return

    # Current position in target symbol
    try:
        positions = alpaca.get_positions()
        target_pos = next((p for p in positions if p.get("symbol") == target), None)
    except Exception as exc:
        log.error("[bot:%s][trend] positions fetch failed: %s", bot_id, exc)
        return

    has_position = target_pos is not None and float(target_pos.get("qty", 0)) > 0

    if above_ma and not has_position:
        # Phase 15 (UNIV-01): hard-gate the ENTRY. The trend target (BITX) is not in
        # stock_universe by design, so it rides an explicit carve-out; a quarantined
        # target is still blocked. The SELL/exit path below is NEVER gated.
        allow = list(cfg.symbols) + [cfg.trend_symbol]
        allowed, reason = entry_allowed(target, allow, cfg.quarantined)
        if not allowed:
            log.warning(
                "[bot:%s][trend] ENTRY BLOCKED %s — reason=%s (universe hard-gate)",
                bot_id, target, reason,
            )
            return

        # Enter: buy target with all available cash
        if cash < 100:
            log.info("[bot:%s][trend] BULLISH but cash too low ($%.2f) — skipping", bot_id, cash)
            return
        try:
            price_target = alpaca.get_latest_price(target)
        except Exception as exc:
            log.error("[bot:%s][trend] price fetch %s failed: %s", bot_id, target, exc)
            return

        # Leave a small buffer for slippage
        qty = round((cash * 0.98) / price_target, 4)
        if qty <= 0:
            log.info("[bot:%s][trend] computed qty=0 — skipping", bot_id)
            return

        try:
            order = alpaca.place_market_order(symbol=target, qty=qty, side="buy")
            log.info(
                "[bot:%s][trend] BUY %s qty=%.4f @ ~$%.2f (cash=$%.2f, order=%s)",
                bot_id, target, qty, price_target, cash, order.get("id"),
            )
            logger.log_alpaca_trade({
                "bot_id": bot_id,
                "symbol": target,
                "asset_class": "stock",
                "side": "long",
                "qty": qty,
                "entry_price": price_target,
                "target_price": None,
                "stop_loss": None,
                "mirofish_prob": None,
                "market_sentiment": "trend_above_ma",
                "simulation_id": f"trend_{target}_{int(price_target)}",
                "notes": f"strategy=trend_btc benchmark={benchmark} ma{ma_window}=${ma:.2f} price=${price:.2f}",
                "confluence_score": None,
            })
        except Exception as exc:
            log.error("[bot:%s][trend] BUY failed: %s", bot_id, exc)
        return

    if not above_ma and has_position:
        # Exit: sell entire position
        qty = float(target_pos["qty"])
        try:
            current_price = alpaca.get_latest_price(target)
        except Exception:
            current_price = float(target_pos.get("current_price") or 0)
        try:
            order = alpaca.place_market_order(symbol=target, qty=qty, side="sell")
            log.info(
                "[bot:%s][trend] SELL %s qty=%.4f @ ~$%.2f (order=%s)",
                bot_id, target, qty, current_price, order.get("id"),
            )
            # Mark all open trend trades closed for this symbol.
            #
            # VERIFY-01, "realized-P&L math WITH FEES". This used to record a GROSS,
            # LONG-ONLY-SIGNED price difference with NO `fees=` argument at all. A NULL
            # `fees` is the TELL that pnl is gross (src/db.py:331). It now records NET
            # realized P&L via the SAME helpers src/backfill.py:84-85 uses, with the row's
            # ACTUAL side — the old formula was sign-WRONG for a short. Recording only:
            # the order above is already placed and nothing here decides a trade.
            try:
                for row in logger.get_open_alpaca_positions():
                    if row.get("symbol") == target:
                        side = row.get("side") or "buy"
                        entry = float(row.get("entry_price") or 0)
                        q = float(row.get("qty") or 0)
                        fees = (entry * q + current_price * q) * TAKER_FEE
                        pnl = (realized_pnl(side, entry, current_price, q, TAKER_FEE)
                               if entry > 0 else 0.0)
                        logger.update_alpaca_trade(row["id"], status="closed",
                                                   exit_price=current_price, pnl=pnl,
                                                   fees=fees)
            except Exception as exc:
                log.warning("[bot:%s][trend] DB close error: %s", bot_id, exc)
        except Exception as exc:
            log.error("[bot:%s][trend] SELL failed: %s", bot_id, exc)
        return

    # No action needed
    state = "HOLDING" if has_position else "FLAT"
    log.info("[bot:%s][trend] state=%s above_ma=%s — no action", bot_id, state, above_ma)
