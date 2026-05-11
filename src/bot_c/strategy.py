"""Bot C strategy — daily TradingAgents cycle with Alpaca auto-execution.

Flow per cycle (once per market day, after the close)
-----------------------------------------------------
1. For each symbol in cfg.symbols (capped at BOT_C_MAX_TICKERS_PER_CYCLE):
   a. Call ``TradingAgentsGraph.propagate(symbol, today)``.
   b. Extract the 5-tier rating (Buy / Overweight / Hold / Underweight / Sell)
      via the upstream signal processor.
   c. Map rating → action: bullish → enter, bearish → exit, hold → skip.
2. Enter:
   - Skip if already holding (no pyramiding).
   - Skip if symbol lost in the last 24h (re-entry cooldown reused).
   - Size via Kelly using the rating's confidence weight.
   - Place a paper market order on Bot C's dedicated Alpaca account.
   - Log to alpaca_trades with bot_id="C" and the full decision text in notes.
3. Exit:
   - Close any open position for the symbol via a market sell.
   - Update the trade row with exit_price and realised PnL.

Cadence: daily. The BotThread sleep is overridden to ~24h when
``cfg.strategy == "tradingagents"``. Stock bots also auto-skip when the US
equity market is closed, so the loop naturally lands once per trading day.

The framework is talked to over the local LLM shim (``http://localhost:8765``)
which routes every call through ``ClaudeLLM`` — no external API key.
"""

from __future__ import annotations

import datetime
import logging
import os
import time
from typing import Optional

from src.alpaca_client import AlpacaClient
from src.bot_config import BotConfig
from src.trade_logger import TradeLogger
from src import db as _db

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Cap tickers per cycle to bound LLM cost (~30-80 calls/ticker at default depth).
MAX_TICKERS_PER_CYCLE = int(os.environ.get("BOT_C_MAX_TICKERS_PER_CYCLE", "4"))

# Per-trade sizing: fraction of bankroll * rating multiplier, capped by
# cfg.max_position_pct. Buy = full Kelly, Overweight = half Kelly.
_RATING_WEIGHTS = {
    "Buy":         1.0,
    "Overweight":  0.6,
    "Hold":        0.0,
    "Underweight": 0.0,
    "Sell":        0.0,
}

_BULLISH = {"Buy", "Overweight"}
_BEARISH = {"Sell", "Underweight"}


# ---------------------------------------------------------------------------
# TradingAgentsGraph cached singleton
# ---------------------------------------------------------------------------

_graph_cache = {"graph": None}


def _ensure_vendor_on_path() -> None:
    """Add the vendored TradingAgents repo to sys.path."""
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    vendor = os.path.abspath(os.path.join(here, "..", "..", "vendor", "TradingAgents"))
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


def _get_graph():
    """Lazily build and cache the TradingAgentsGraph."""
    if _graph_cache["graph"] is not None:
        return _graph_cache["graph"]

    _ensure_vendor_on_path()
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    # Force the shim — overrides anything in default_config so we never accidentally
    # hit the real OpenAI/Anthropic endpoint.
    config["llm_provider"] = "openai"
    config["backend_url"] = os.environ.get(
        "TRADINGAGENTS_LLM_BACKEND_URL", "http://localhost:8765/v1"
    )
    # Use Claude model IDs so the shim's resolver picks the right model directly.
    config["deep_think_llm"] = os.environ.get("TRADINGAGENTS_DEEP_THINK_LLM", "claude-sonnet-4-6")
    config["quick_think_llm"] = os.environ.get("TRADINGAGENTS_QUICK_THINK_LLM", "claude-sonnet-4-6")
    config["max_debate_rounds"] = int(os.environ.get("TRADINGAGENTS_MAX_DEBATE_ROUNDS", "1"))
    config["max_risk_discuss_rounds"] = int(os.environ.get("TRADINGAGENTS_MAX_RISK_ROUNDS", "1"))

    graph = TradingAgentsGraph(debug=False, config=config)
    _graph_cache["graph"] = graph
    return graph


def _parse_rating(decision_text: str) -> str:
    """Extract one of Buy / Overweight / Hold / Underweight / Sell."""
    _ensure_vendor_on_path()
    from tradingagents.agents.utils.rating import parse_rating
    try:
        return parse_rating(decision_text)
    except Exception:
        return "Hold"


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------

def _kelly_size(
    rating: str,
    price: float,
    bankroll: float,
    kelly_fraction: float,
    max_position_pct: float,
) -> dict:
    """Compute order quantity for a bullish rating. Returns shares + dollar amount."""
    weight = _RATING_WEIGHTS.get(rating, 0.0)
    if weight <= 0 or price <= 0 or bankroll <= 0:
        return {"shares": 0.0, "dollar_amount": 0.0, "pct": 0.0}

    raw_pct = kelly_fraction * weight
    pct = min(raw_pct, max_position_pct)
    dollar_amount = bankroll * pct
    shares = round(dollar_amount / price, 4)
    return {"shares": shares, "dollar_amount": shares * price, "pct": pct}


# ---------------------------------------------------------------------------
# Symbol selection
# ---------------------------------------------------------------------------

def _select_tickers(
    cfg: BotConfig,
    open_symbols: set[str],
) -> list[str]:
    """Pick which tickers to evaluate this cycle.

    Prioritises symbols not currently held (so we look for new entries first),
    then symbols that are held (to potentially exit). Caps at
    MAX_TICKERS_PER_CYCLE to bound LLM cost.
    """
    universe = list(cfg.symbols)
    not_held = [s for s in universe if s not in open_symbols]
    held = [s for s in universe if s in open_symbols]
    selected = (not_held + held)[:MAX_TICKERS_PER_CYCLE]
    return selected


# ---------------------------------------------------------------------------
# Cycle entry point
# ---------------------------------------------------------------------------

def run_tradingagents_cycle(
    cfg: BotConfig,
    alpaca: AlpacaClient,
    logger: TradeLogger,
) -> None:
    """Execute one TradingAgents cycle for Bot C."""
    bot_id = cfg.bot_id

    # Snapshot account + positions ------------------------------------------
    try:
        account = alpaca.get_account()
        bankroll = float(account.get("cash") or account.get("buying_power") or 0)
        equity = float(account.get("equity") or bankroll)
    except Exception as exc:
        log.error("[bot:%s][ta] account fetch failed: %s", bot_id, exc)
        return

    try:
        positions = alpaca.get_positions()
    except Exception as exc:
        log.error("[bot:%s][ta] positions fetch failed: %s", bot_id, exc)
        positions = []

    open_by_symbol = {p.get("symbol"): p for p in positions if float(p.get("qty", 0)) > 0}
    open_symbols = set(open_by_symbol.keys())

    try:
        recent_loss_symbols = _db.get_recent_loss_symbols(bot_id, hours=24)
    except Exception as exc:
        log.warning("[bot:%s][ta] recent-loss lookup failed: %s", bot_id, exc)
        recent_loss_symbols = set()

    tickers = _select_tickers(cfg, open_symbols)
    if not tickers:
        log.info("[bot:%s][ta] no tickers selected this cycle", bot_id)
        return

    log.info(
        "[bot:%s][ta] cycle start: equity=$%.2f cash=$%.2f tickers=%s",
        bot_id, equity, bankroll, ",".join(tickers),
    )

    today = datetime.date.today().isoformat()

    try:
        graph = _get_graph()
    except Exception as exc:
        log.exception("[bot:%s][ta] failed to initialise TradingAgentsGraph: %s", bot_id, exc)
        return

    cycle_exposure = 0.0
    for symbol in tickers:
        try:
            _process_ticker(
                symbol=symbol,
                today=today,
                graph=graph,
                cfg=cfg,
                alpaca=alpaca,
                logger=logger,
                bankroll=bankroll - cycle_exposure,
                equity=equity,
                open_by_symbol=open_by_symbol,
                recent_loss_symbols=recent_loss_symbols,
                bot_id=bot_id,
                cycle_exposure_tracker=lambda d: None,
            )
        except Exception as exc:
            log.exception("[bot:%s][ta] %s — unhandled error: %s", bot_id, symbol, exc)


def _process_ticker(
    symbol: str,
    today: str,
    graph,
    cfg: BotConfig,
    alpaca: AlpacaClient,
    logger: TradeLogger,
    bankroll: float,
    equity: float,
    open_by_symbol: dict,
    recent_loss_symbols: set,
    bot_id: str,
    cycle_exposure_tracker,
) -> None:
    """Run the agent debate for one ticker and execute the resulting decision."""
    log.info("[bot:%s][ta] propagating %s for %s", bot_id, symbol, today)
    t0 = time.time()
    try:
        _, decision_text = graph.propagate(symbol, today)
    except Exception as exc:
        log.exception("[bot:%s][ta] propagate failed for %s: %s", bot_id, symbol, exc)
        return
    elapsed = time.time() - t0

    rating = _parse_rating(decision_text or "")
    log.info(
        "[bot:%s][ta] %s → %s (%.1fs, decision=%d chars)",
        bot_id, symbol, rating, elapsed, len(decision_text or ""),
    )

    is_held = symbol in open_by_symbol

    # ─── Exit path ─────────────────────────────────────────────────────────
    if rating in _BEARISH:
        if not is_held:
            log.info("[bot:%s][ta] %s %s — not held, no exit", bot_id, symbol, rating)
            return
        _exit_position(
            symbol=symbol, position=open_by_symbol[symbol],
            alpaca=alpaca, logger=logger, bot_id=bot_id,
            rating=rating, decision_text=decision_text,
        )
        return

    # ─── Hold path ─────────────────────────────────────────────────────────
    if rating not in _BULLISH:
        log.info("[bot:%s][ta] %s Hold — no action", bot_id, symbol)
        return

    # ─── Entry path ────────────────────────────────────────────────────────
    if is_held:
        log.info("[bot:%s][ta] %s %s — already holding, no pyramid", bot_id, symbol, rating)
        return
    if symbol in recent_loss_symbols:
        log.info("[bot:%s][ta] %s %s — recent-loss cooldown, skipping", bot_id, symbol, rating)
        return

    try:
        price = alpaca.get_latest_price(symbol)
    except Exception as exc:
        log.error("[bot:%s][ta] price fetch failed for %s: %s", bot_id, symbol, exc)
        return

    sizing = _kelly_size(
        rating=rating, price=price, bankroll=bankroll,
        kelly_fraction=cfg.kelly_fraction,
        max_position_pct=cfg.max_position_pct,
    )

    if sizing["shares"] <= 0 or sizing["dollar_amount"] < 10:
        log.info(
            "[bot:%s][ta] %s %s — position too small ($%.2f), skip",
            bot_id, symbol, rating, sizing["dollar_amount"],
        )
        return

    try:
        order = alpaca.place_market_order(symbol=symbol, qty=sizing["shares"], side="buy")
    except Exception as exc:
        log.exception("[bot:%s][ta] BUY %s failed: %s", bot_id, symbol, exc)
        return

    log.info(
        "[bot:%s][ta] BUY %s qty=%.4f @ $%.2f ($%.2f, %.1f%% bankroll, rating=%s)",
        bot_id, symbol, sizing["shares"], price, sizing["dollar_amount"],
        sizing["pct"] * 100, rating,
    )

    decision_snippet = (decision_text or "").strip().replace("\n", " ")[:400]
    try:
        logger.log_alpaca_trade({
            "bot_id": bot_id,
            "symbol": symbol,
            "asset_class": "stock",
            "side": "long",
            "qty": sizing["shares"],
            "entry_price": price,
            "target_price": None,
            "stop_loss": None,
            "mirofish_prob": None,
            "market_sentiment": f"tradingagents_{rating.lower()}",
            "simulation_id": f"tradingagents_{symbol}_{today}",
            "notes": f"strategy=tradingagents rating={rating} decision={decision_snippet}",
            "confluence_score": None,
        })
    except Exception as exc:
        log.warning("[bot:%s][ta] DB log failed for %s: %s", bot_id, symbol, exc)


def _exit_position(
    symbol: str,
    position: dict,
    alpaca: AlpacaClient,
    logger: TradeLogger,
    bot_id: str,
    rating: str,
    decision_text: Optional[str],
) -> None:
    """Close an open position and mark the matching trade rows as closed."""
    qty = float(position.get("qty") or 0)
    if qty <= 0:
        return

    try:
        current_price = alpaca.get_latest_price(symbol)
    except Exception:
        current_price = float(position.get("current_price") or 0)

    try:
        order = alpaca.place_market_order(symbol=symbol, qty=qty, side="sell")
    except Exception as exc:
        log.exception("[bot:%s][ta] SELL %s failed: %s", bot_id, symbol, exc)
        return

    log.info(
        "[bot:%s][ta] SELL %s qty=%.4f @ ~$%.2f (rating=%s, order=%s)",
        bot_id, symbol, qty, current_price, rating, order.get("id"),
    )

    # Mark matching open rows closed with realised PnL.
    try:
        for row in logger.get_open_alpaca_positions():
            if row.get("symbol") != symbol:
                continue
            entry = float(row.get("entry_price") or 0)
            q = float(row.get("qty") or 0)
            pnl = (current_price - entry) * q if entry > 0 else 0.0
            logger.update_alpaca_trade(
                row["id"], status="closed", exit_price=current_price, pnl=pnl,
            )
    except Exception as exc:
        log.warning("[bot:%s][ta] DB close error for %s: %s", bot_id, symbol, exc)
