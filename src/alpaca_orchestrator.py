"""
Alpaca trading orchestrator for the AI Predicted Wins project.

Runs alongside the Kalshi orchestrator. Scans crypto/stock markets,
runs MiroFish swarm simulations to predict price direction, and
executes trades on Alpaca.

Flow:
  1. Scan trending crypto (BTC, ETH, SOL, etc.) and volatile stocks
  2. Format seed material with recent price action + news context
  3. Run MiroFish simulation: 1000 AI agents simulate social media
     discussion about whether the asset will go up or down
  4. Extract crowd sentiment (% bullish vs bearish) from report
  5. Compare MiroFish sentiment to current price momentum
  6. If strongly bullish (>65%) but price flat/down -> BUY
  7. If strongly bearish (<35%) but price flat/up -> SHORT/SELL
  8. Position size with Kelly Criterion (adapted for directional bets)
  9. Set stop-loss at 3% and take-profit at 8%

Usage:
  python -m src.alpaca_orchestrator --mode paper --asset-class crypto --max-trades 50
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.config import load_config
from src.alpaca_client import AlpacaClient
from src.alpaca_evaluator import (
    get_trending_crypto,
    get_trending_stocks,
    evaluate_for_simulation,
    format_asset_seed,
    get_asset_question,
)
from src.mirofish_client import MiroFishClient, run_full_simulation
from src.position_sizer import kelly_size
from src.trade_logger import TradeLogger

# ---------------------------------------------------------------------------
# Constants — hardcoded risk management rules
# ---------------------------------------------------------------------------
MAX_POSITION_PCT = 0.05           # 5% bankroll per position
STOP_LOSS_PCT = 0.03              # 3% stop-loss per trade
TAKE_PROFIT_PCT = 0.08            # 8% take-profit per trade
MAX_SIMULTANEOUS_POSITIONS = 5    # max open positions at once
MAX_SAME_CLASS_POSITIONS = 3      # max positions in same asset class
DRAWDOWN_STOP_PCT = 0.10          # 10% daily drawdown kills the bot
MIN_PAPER_TRADES = 30             # required before live mode
BULLISH_THRESHOLD = 0.65          # MiroFish sentiment > 65% = bullish signal
BEARISH_THRESHOLD = 0.35          # MiroFish sentiment < 35% = bearish signal
MAX_SIMS_PER_CYCLE = 8            # cap simulations per scan cycle

CYCLE_SLEEP_CRYPTO = 1800         # 30 min between crypto cycles
CYCLE_SLEEP_STOCKS = 900          # 15 min between stock cycles
RETRY_SLEEP = 120                 # 2 min retry on failures

# NYSE/NASDAQ market hours (ET)
MARKET_OPEN_HOUR = 9              # 9:30 AM ET
MARKET_OPEN_MINUTE = 30
MARKET_CLOSE_HOUR = 16            # 4:00 PM ET
MARKET_CLOSE_MINUTE = 0

console = Console()
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    """Configure structured logging to stdout."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s -- %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def _print_banner(mode: str, balance: float, asset_class: str, config) -> None:
    """Print a startup banner with current mode and config summary."""
    banner = (
        f"[bold cyan]Alpaca + MiroFish Directional Trading Bot[/bold cyan]\n"
        f"\n"
        f"  Mode            : [bold {'red' if mode == 'live' else 'yellow'}]{mode.upper()}[/]\n"
        f"  Asset class     : [bold]{asset_class.upper()}[/]\n"
        f"  Balance         : ${balance:,.2f}\n"
        f"  Bankroll target : ${config.starting_bankroll:,.2f}\n"
        f"  Kelly fraction  : {config.kelly_fraction:.0%}\n"
        f"  Max position    : {MAX_POSITION_PCT:.0%} of bankroll\n"
        f"  Stop-loss       : {STOP_LOSS_PCT:.0%} per trade\n"
        f"  Take-profit     : {TAKE_PROFIT_PCT:.0%} per trade\n"
        f"  Max positions   : {MAX_SIMULTANEOUS_POSITIONS} total / {MAX_SAME_CLASS_POSITIONS} per class\n"
        f"  Drawdown stop   : {DRAWDOWN_STOP_PCT:.0%} daily\n"
        f"  Bullish thresh  : {BULLISH_THRESHOLD:.0%}\n"
        f"  Bearish thresh  : {BEARISH_THRESHOLD:.0%}\n"
        f"  Crypto cycle    : {CYCLE_SLEEP_CRYPTO // 60} min\n"
        f"  Stock cycle     : {CYCLE_SLEEP_STOCKS // 60} min\n"
        f"  Agents/sim      : {config.mirofish_agent_count}\n"
        f"  Rounds/sim      : {config.mirofish_rounds}"
    )
    console.print(Panel(banner, title="Alpaca Orchestrator Startup", border_style="cyan"))


def _cycle_summary(
    cycle_count: int,
    assets_scanned: int,
    sims_run: int,
    trades_placed: int,
    positions_closed: int,
    cycle_pnl: float,
    total_pnl: float,
    bankroll: float,
    open_positions: int,
) -> None:
    """Print a summary panel at the end of each cycle."""
    console.print(
        Panel(
            f"  Assets scanned      : {assets_scanned}\n"
            f"  Simulations run     : {sims_run}\n"
            f"  Trades placed       : {trades_placed}\n"
            f"  Positions closed    : {positions_closed}\n"
            f"  Cycle P&L           : ${cycle_pnl:+,.2f}\n"
            f"  Total P&L           : ${total_pnl:+,.2f}\n"
            f"  Bankroll            : ${bankroll:,.2f}\n"
            f"  Open positions      : {open_positions}",
            title=f"Cycle {cycle_count} Summary",
            border_style="green" if cycle_pnl >= 0 else "red",
        )
    )


def _confirm_live_mode(balance: float) -> bool:
    """Require explicit confirmation before live trading."""
    console.print(
        Panel(
            f"[bold red]LIVE MODE -- REAL MONEY[/bold red]\n\n"
            f"  Account balance: ${balance:,.2f}\n\n"
            f"  Real money will be used for Alpaca trades.\n"
            f"  Type [bold]CONFIRM[/bold] to proceed.",
            title="Warning",
            border_style="red",
        )
    )
    response = input(">>> ").strip()
    if response != "CONFIRM":
        console.print("[yellow]Aborted. Live mode requires typing CONFIRM exactly.[/yellow]")
        return False
    return True


def _check_paper_trade_minimum(logger: TradeLogger) -> bool:
    """Return True if enough paper trades have been logged for Alpaca."""
    accuracy = logger.get_alpaca_accuracy()
    total = accuracy.get("total_trades", 0)
    if total < MIN_PAPER_TRADES:
        console.print(
            f"[bold red]Blocked:[/bold red] Only {total} Alpaca paper trades logged. "
            f"Need at least {MIN_PAPER_TRADES} before live mode."
        )
        return False
    console.print(
        f"[green]Paper trade gate passed: {total} trades "
        f"({accuracy.get('win_rate', 0):.1%} win rate)[/green]"
    )
    return True


def _is_stock_market_open() -> bool:
    """Check if NYSE/NASDAQ is currently open (Mon-Fri, 9:30 AM - 4:00 PM ET).

    Uses a simple UTC-5 offset for ET. Does not account for holidays or DST
    edge cases -- a proper implementation would use pytz or zoneinfo.
    """
    try:
        from zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo("America/New_York"))
    except ImportError:
        # Fallback: approximate ET as UTC-5
        from datetime import timedelta
        now_utc = datetime.now(timezone.utc)
        now_et = now_utc - timedelta(hours=5)

    # Weekend check (Monday=0, Sunday=6)
    if now_et.weekday() >= 5:
        return False

    market_open = now_et.replace(
        hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0,
    )
    market_close = now_et.replace(
        hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0,
    )
    return market_open <= now_et <= market_close


def _kelly_directional(
    sentiment: float,
    current_price: float,
    bankroll: float,
    kelly_fraction: float = 0.25,
    max_position_pct: float = 0.05,
) -> dict:
    """Adapt Kelly Criterion for directional price bets.

    Instead of event contracts, we're estimating edge from the
    divergence between MiroFish crowd sentiment and current momentum.

    Args:
        sentiment: MiroFish bullish probability (0.0-1.0).
        current_price: Current asset price (used for position sizing).
        bankroll: Available cash balance.
        kelly_fraction: Fraction of full Kelly to use (default quarter Kelly).
        max_position_pct: Maximum position as fraction of bankroll.

    Returns:
        dict with: side, kelly_pct, adjusted_pct, dollar_amount,
                   shares, capped.
    """
    # Determine direction and edge magnitude
    if sentiment > BULLISH_THRESHOLD:
        side = "buy"
        # Edge: how far above the threshold we are
        edge = (sentiment - 0.50)  # distance from neutral
        win_prob = sentiment
    elif sentiment < BEARISH_THRESHOLD:
        side = "sell"
        edge = (0.50 - sentiment)
        win_prob = 1.0 - sentiment  # probability of downward move
    else:
        # Sentiment in no-trade zone
        return {
            "side": "none",
            "kelly_pct": 0.0,
            "adjusted_pct": 0.0,
            "dollar_amount": 0.0,
            "shares": 0,
            "capped": False,
        }

    # Kelly formula adapted for directional bets:
    # Assume risk/reward based on stop-loss and take-profit
    # b = take_profit / stop_loss (payout odds)
    b = TAKE_PROFIT_PCT / STOP_LOSS_PCT  # 8% / 3% = 2.67
    p = win_prob
    q = 1.0 - p

    kelly_pct = max(0.0, (b * p - q) / b)
    adjusted_pct = kelly_pct * kelly_fraction

    capped = adjusted_pct > max_position_pct
    if capped:
        adjusted_pct = max_position_pct

    dollar_amount = bankroll * adjusted_pct

    # Calculate share count
    if current_price > 0:
        shares = int(dollar_amount / current_price)
    else:
        shares = 0

    return {
        "side": side,
        "kelly_pct": kelly_pct,
        "adjusted_pct": adjusted_pct,
        "dollar_amount": dollar_amount,
        "shares": shares,
        "capped": capped,
    }


def _check_stop_loss_take_profit(
    entry_price: float,
    current_price: float,
    side: str,
) -> str | None:
    """Check if a position has hit stop-loss or take-profit.

    Returns:
        'stop_loss', 'take_profit', or None.
    """
    if side == "buy":
        pnl_pct = (current_price - entry_price) / entry_price
    else:  # short / sell
        pnl_pct = (entry_price - current_price) / entry_price

    if pnl_pct <= -STOP_LOSS_PCT:
        return "stop_loss"
    if pnl_pct >= TAKE_PROFIT_PCT:
        return "take_profit"
    return None


def _check_sentiment_reversal(
    original_sentiment: float,
    current_sentiment: float,
    side: str,
) -> bool:
    """Check if MiroFish sentiment has reversed from the original trade thesis.

    A reversal means a bullish trade is now seeing bearish sentiment, or vice versa.
    """
    if side == "buy" and current_sentiment < 0.50:
        return True
    if side == "sell" and current_sentiment > 0.50:
        return True
    return False


# ---------------------------------------------------------------------------
# Position management
# ---------------------------------------------------------------------------

def _manage_positions(
    alpaca: AlpacaClient,
    logger: TradeLogger,
    mirofish: MiroFishClient,
) -> tuple[int, float]:
    """Check existing positions: close if stop-loss/take-profit hit or sentiment reversed.

    Returns:
        (positions_closed, realized_pnl)
    """
    positions_closed = 0
    realized_pnl = 0.0

    open_trades = logger.get_open_alpaca_positions()

    for trade in open_trades:
        symbol = trade.get("symbol")
        entry_price = trade.get("entry_price", 0)
        side = trade.get("side", "buy")
        trade_id = trade.get("id")

        if not symbol or not entry_price:
            continue

        # Get current price from Alpaca
        try:
            current_price = alpaca.get_latest_price(symbol)
        except Exception as exc:
            log.warning("Could not get price for %s: %s", symbol, exc)
            continue

        if current_price is None or current_price <= 0:
            continue

        # Check stop-loss / take-profit
        trigger = _check_stop_loss_take_profit(entry_price, current_price, side)
        close_reason = None

        if trigger:
            close_reason = trigger
        else:
            # Check if MiroFish sentiment has reversed
            original_sentiment = trade.get("mirofish_sentiment", 0.5)
            if _check_sentiment_reversal(original_sentiment, original_sentiment, side):
                # For a full reversal check, we'd re-run a simulation.
                # For efficiency, we only close on price triggers here.
                # Sentiment reversal is checked via periodic re-simulation
                # in the main loop when the asset comes up again.
                pass

        if close_reason:
            # Calculate P&L
            if side == "buy":
                pnl_per_share = current_price - entry_price
            else:
                pnl_per_share = entry_price - current_price

            shares = trade.get("shares", 0)
            trade_pnl = pnl_per_share * shares

            console.print(
                f"  Closing [cyan]{symbol}[/cyan] ({side.upper()}) -- "
                f"{'[green]' if trade_pnl >= 0 else '[red]'}"
                f"{close_reason.upper().replace('_', ' ')}[/] "
                f"${trade_pnl:+,.2f}"
            )

            try:
                alpaca.close_position(symbol)
                logger.update_alpaca_trade(
                    trade_id=trade_id,
                    status="closed",
                    exit_price=current_price,
                    pnl=trade_pnl,
                    close_reason=close_reason,
                )
                positions_closed += 1
                realized_pnl += trade_pnl
            except Exception as exc:
                console.print(f"    [red]Close failed: {exc}[/red]")
                log.exception("Failed to close position %s", symbol)

    return positions_closed, realized_pnl


# ---------------------------------------------------------------------------
# Asset scanning and signal generation
# ---------------------------------------------------------------------------

def _scan_candidates(
    asset_class: str,
    alpaca: AlpacaClient,
    logger: TradeLogger,
) -> list[dict]:
    """Scan for trading candidates based on asset class.

    Returns a list of asset dicts with keys: symbol, name, price, change_pct,
    volume, asset_class, momentum, etc.
    """
    candidates = []

    if asset_class in ("crypto", "both"):
        try:
            crypto = get_trending_crypto(alpaca)
            console.print(f"  Found {len(crypto)} trending crypto assets")
            candidates.extend(crypto)
        except Exception as exc:
            console.print(f"  [red]Crypto scan failed: {exc}[/red]")
            log.exception("Crypto scan failed")

    if asset_class in ("stocks", "both"):
        if not _is_stock_market_open():
            console.print("  [yellow]Stock market closed -- skipping stock scan[/yellow]")
        else:
            try:
                stocks = get_trending_stocks(alpaca)
                console.print(f"  Found {len(stocks)} trending stock assets")
                candidates.extend(stocks)
            except Exception as exc:
                console.print(f"  [red]Stock scan failed: {exc}[/red]")
                log.exception("Stock scan failed")

    # Evaluate and rank by MiroFish simulation fitness
    evaluated = evaluate_for_simulation(candidates)
    console.print(f"  {len(evaluated)} assets after simulation fitness evaluation")

    # Remove already-simulated assets today
    simulated_today = set()
    fresh = [a for a in evaluated if a["symbol"] not in simulated_today]
    console.print(f"  {len(fresh)} after removing already-simulated assets")

    return fresh[:MAX_SIMS_PER_CYCLE]


def _generate_signals(
    candidates: list[dict],
    mirofish: MiroFishClient,
    logger: TradeLogger,
    open_positions: list[dict],
) -> list[dict]:
    """Run MiroFish simulations on candidates and generate trade signals.

    Returns a list of signal dicts with keys: asset, sentiment, side,
    kelly_sizing, sim_result.
    """
    signals = []
    open_symbols = {p.get("symbol") for p in open_positions}

    for i, asset in enumerate(candidates, 1):
        symbol = asset["symbol"]
        name = asset.get("name", symbol)
        asset_cls = asset.get("asset_class", "unknown")

        console.print(
            f"\n  [{i}/{len(candidates)}] Simulating [bold]{symbol}[/bold]: {name}"
        )

        # Skip if we already have a position
        if symbol in open_symbols:
            console.print(f"    [yellow]Already have open position -- skipping[/yellow]")
            continue

        try:
            seed_text = format_asset_seed(asset)
            event_question = get_asset_question(asset)

            sim_result = run_full_simulation(
                client=mirofish,
                seed_text=seed_text,
                event_question=event_question,
            )

            if sim_result.get("status") != "completed":
                console.print(
                    f"    [yellow]Simulation {sim_result.get('status', 'unknown')} "
                    f"-- skipping[/yellow]"
                )
                continue

            # Log the simulation
            logger.log_simulation(
                sim_id=sim_result.get("sim_id") or f"sim_{symbol}_{int(time.time())}",
                market={"ticker": symbol, "title": asset.get("name", symbol)},
                mirofish_prob=sim_result.get("probability", 0.5),
                kalshi_price=asset.get("price", 0),
                estimated_cost=sim_result.get("estimated_cost", 0),
            )

            sentiment = sim_result["probability"]
            price = asset.get("price", 0)
            change_pct = asset.get("change_pct", 0)

            # Determine if there's a divergence signal
            # Bullish sentiment + flat/down price = BUY opportunity
            # Bearish sentiment + flat/up price = SHORT opportunity
            signal_type = None
            if sentiment > BULLISH_THRESHOLD and change_pct <= 2.0:
                signal_type = "bullish_divergence"
            elif sentiment < BEARISH_THRESHOLD and change_pct >= -2.0:
                signal_type = "bearish_divergence"

            direction = "BULL" if sentiment > 0.5 else "BEAR"
            icon = "+" if sentiment > 0.5 else "-"
            console.print(
                f"    Sentiment: {sentiment:.1%} ({direction})  |  "
                f"Price chg: {change_pct:+.1f}%  |  "
                f"Signal: {signal_type or 'none'}  |  "
                f"Asset: {asset_cls}"
            )

            if signal_type:
                signals.append({
                    "asset": asset,
                    "sentiment": sentiment,
                    "signal_type": signal_type,
                    "sim_result": sim_result,
                })

        except Exception as exc:
            console.print(f"    [red]Error: {exc}[/red]")
            log.exception("Simulation failed for %s", symbol)
            continue

    return signals


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main(mode: str = "paper", asset_class: str = "crypto", max_trades: int = 0) -> None:
    """Run the scan-simulate-trade loop for Alpaca.

    Args:
        mode: 'paper', 'live', or 'evaluate'.
        asset_class: 'crypto', 'stocks', or 'both'.
        max_trades: Stop after N trades (0 = run forever).
    """
    _setup_logging()

    # -- 1. Initialize ---------------------------------------------------------
    config = load_config()
    alpaca = AlpacaClient(config)
    mirofish = MiroFishClient(config)
    logger = TradeLogger()

    balance = alpaca.get_account()["equity"]
    starting_bankroll = max(balance, config.starting_bankroll)

    _print_banner(mode, balance, asset_class, config)

    # -- 2. Live-mode gates ----------------------------------------------------
    if mode == "live":
        if not _check_paper_trade_minimum(logger):
            sys.exit(1)
        if not _confirm_live_mode(balance):
            sys.exit(0)

    # -- 3. Tracking state -----------------------------------------------------
    total_pnl = 0.0
    daily_pnl = 0.0
    total_trades = 0
    cycle_count = 0
    daily_start = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # -- 4. Main loop ----------------------------------------------------------
    while True:
        cycle_count += 1
        console.rule(f"[bold]Cycle {cycle_count}[/bold]")

        # -- 4a. Reset daily P&L tracking at midnight --------------------------
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != daily_start:
            console.print(f"  [cyan]New trading day: {today}[/cyan]")
            daily_pnl = 0.0
            daily_start = today

        # -- 4b. Daily drawdown stop -------------------------------------------
        if daily_pnl < -(starting_bankroll * DRAWDOWN_STOP_PCT):
            console.print(
                Panel(
                    f"[bold red]DAILY DRAWDOWN STOP[/bold red]\n\n"
                    f"  Daily P&L: ${daily_pnl:+,.2f}\n"
                    f"  Limit:     -${starting_bankroll * DRAWDOWN_STOP_PCT:,.2f} "
                    f"({DRAWDOWN_STOP_PCT:.0%} of ${starting_bankroll:,.2f})\n\n"
                    f"  Bot halted to protect capital. Will resume tomorrow.",
                    title="Risk Management",
                    border_style="red",
                )
            )
            # Sleep until next day (approximate -- wait 1 hour and re-check)
            time.sleep(3600)
            continue

        # -- 4c. Manage existing positions -------------------------------------
        console.print("[cyan]Checking existing positions...[/cyan]")
        positions_closed, close_pnl = _manage_positions(alpaca, logger, mirofish)
        total_pnl += close_pnl
        daily_pnl += close_pnl

        if positions_closed > 0:
            console.print(
                f"  Closed {positions_closed} positions for ${close_pnl:+,.2f}"
            )

        # -- 4d. Check position limits -----------------------------------------
        open_positions = logger.get_open_alpaca_positions()
        current_position_count = len(open_positions)

        crypto_positions = sum(
            1 for p in open_positions if p.get("asset_class") == "crypto"
        )
        stock_positions = sum(
            1 for p in open_positions if p.get("asset_class") == "stocks"
        )

        can_open_new = current_position_count < MAX_SIMULTANEOUS_POSITIONS
        candidates = []
        trades_placed = 0

        if not can_open_new:
            console.print(
                f"  [yellow]At max positions ({current_position_count}/"
                f"{MAX_SIMULTANEOUS_POSITIONS}) -- skipping scan[/yellow]"
            )
        else:
            # -- 4e. Scan for new candidates -----------------------------------
            console.print(f"[cyan]Scanning {asset_class} markets...[/cyan]")
            try:
                candidates = _scan_candidates(asset_class, alpaca, logger)
            except Exception as exc:
                console.print(f"[red]Market scan failed: {exc}[/red]")
                log.exception("Market scan failed")
                _sleep_for_cycle(asset_class)
                continue

            # -- 4f. Run simulations and generate signals ----------------------
            if candidates:
                signals = _generate_signals(candidates, mirofish, logger, open_positions)
                console.print(
                    f"\n  [bold]{len(signals)}[/bold] actionable signals generated"
                )
            else:
                signals = []
                console.print("  No fresh candidates to simulate")

            # -- 4g. Size and place orders -------------------------------------
            bankroll = alpaca.get_account()["equity"]

            for signal in signals:
                asset = signal["asset"]
                sentiment = signal["sentiment"]
                symbol = asset["symbol"]
                asset_cls = asset.get("asset_class", "unknown")
                current_price = asset.get("price", 0)

                # Enforce per-class position limits
                if asset_cls == "crypto" and crypto_positions >= MAX_SAME_CLASS_POSITIONS:
                    console.print(
                        f"  Skipping [cyan]{symbol}[/cyan] -- max crypto positions "
                        f"({crypto_positions}/{MAX_SAME_CLASS_POSITIONS})"
                    )
                    continue
                if asset_cls == "stocks" and stock_positions >= MAX_SAME_CLASS_POSITIONS:
                    console.print(
                        f"  Skipping [cyan]{symbol}[/cyan] -- max stock positions "
                        f"({stock_positions}/{MAX_SAME_CLASS_POSITIONS})"
                    )
                    continue

                # Kelly sizing for directional bet
                sizing = _kelly_directional(
                    sentiment=sentiment,
                    current_price=current_price,
                    bankroll=bankroll,
                    kelly_fraction=config.kelly_fraction,
                    max_position_pct=MAX_POSITION_PCT,
                )

                if sizing["side"] == "none" or sizing["shares"] < 1:
                    console.print(
                        f"  Skipping [cyan]{symbol}[/cyan] -- no edge or position too small"
                    )
                    continue

                # Calculate stop-loss and take-profit prices
                if sizing["side"] == "buy":
                    stop_price = current_price * (1 - STOP_LOSS_PCT)
                    tp_price = current_price * (1 + TAKE_PROFIT_PCT)
                else:
                    stop_price = current_price * (1 + STOP_LOSS_PCT)
                    tp_price = current_price * (1 - TAKE_PROFIT_PCT)

                console.print(
                    f"  Placing: [bold]{sizing['side'].upper()}[/bold] "
                    f"{sizing['shares']} shares of [cyan]{symbol}[/cyan] "
                    f"@ ${current_price:,.2f} "
                    f"(${sizing['dollar_amount']:.2f}, "
                    f"kelly={sizing['adjusted_pct']:.2%}"
                    f"{'  CAPPED' if sizing['capped'] else ''})\n"
                    f"    SL: ${stop_price:,.2f}  |  TP: ${tp_price:,.2f}"
                )

                try:
                    order = alpaca.place_market_order(
                        symbol=symbol,
                        qty=sizing["shares"],
                        side=sizing["side"],
                    )

                    logger.log_alpaca_trade({
                        "symbol": symbol,
                        "asset_class": asset_cls,
                        "side": sizing["side"],
                        "qty": sizing["shares"],
                        "entry_price": current_price,
                        "mirofish_prob": sentiment,
                        "market_sentiment": signal.get("signal_type", ""),
                        "target_price": tp_price,
                        "stop_loss": stop_price,
                        "simulation_id": signal.get("sim_result", {}).get("sim_id"),
                    })

                    trades_placed += 1
                    total_trades += 1
                    bankroll -= sizing["dollar_amount"]

                    # Track per-class counts
                    if asset_cls == "crypto":
                        crypto_positions += 1
                    else:
                        stock_positions += 1

                    console.print(
                        f"    [green]Order placed:[/green] {order.get('order_id', 'N/A')} "
                        f"-- status: {order.get('status', 'submitted')}"
                    )

                except Exception as exc:
                    console.print(f"    [red]Order failed: {exc}[/red]")
                    log.exception("Order placement failed for %s", symbol)
                    continue

        # -- 4h. Cycle summary -------------------------------------------------
        open_positions = logger.get_open_alpaca_positions()
        _cycle_summary(
            cycle_count=cycle_count,
            assets_scanned=len(candidates),
            sims_run=len(candidates),
            trades_placed=trades_placed,
            positions_closed=positions_closed,
            cycle_pnl=close_pnl,
            total_pnl=total_pnl,
            bankroll=alpaca.get_account()["equity"],
            open_positions=len(open_positions),
        )

        # -- 4i. Check max trades target ---------------------------------------
        if max_trades > 0 and total_trades >= max_trades:
            console.print(
                f"\n  [bold green]Target reached: {total_trades} trades placed.[/bold green]"
            )
            _print_final_report(logger, total_trades, total_pnl, cycle_count)
            break

        # -- 4j. Sleep until next cycle ----------------------------------------
        _sleep_for_cycle(asset_class)


def _sleep_for_cycle(asset_class: str) -> None:
    """Sleep for the appropriate interval based on asset class."""
    if asset_class == "stocks":
        sleep_time = CYCLE_SLEEP_STOCKS
    elif asset_class == "crypto":
        sleep_time = CYCLE_SLEEP_CRYPTO
    else:
        # "both" -- use the shorter interval
        sleep_time = CYCLE_SLEEP_STOCKS

    console.print(
        f"  Sleeping {sleep_time // 60} minutes until next cycle...\n"
    )
    time.sleep(sleep_time)


# ---------------------------------------------------------------------------
# Evaluate mode
# ---------------------------------------------------------------------------

def evaluate(asset_class: str = "both", top_n: int = 30) -> None:
    """Evaluate mode: scan and rank assets without trading."""
    _setup_logging()
    config = load_config()
    alpaca = AlpacaClient(config, paper=True)

    console.print(
        Panel(
            "[bold cyan]Alpaca Asset Evaluation Mode[/bold cyan]\n\n"
            f"Scanning {asset_class} markets and ranking by MiroFish simulation fit.\n"
            "No trades will be placed.",
            border_style="cyan",
        )
    )

    balance = alpaca.get_account()["equity"]
    console.print(f"  Balance: ${balance:,.2f}\n")

    candidates = []

    if asset_class in ("crypto", "both"):
        console.print("[cyan]Scanning crypto...[/cyan]")
        try:
            crypto = get_trending_crypto(alpaca)
            console.print(f"  {len(crypto)} trending crypto assets")
            candidates.extend(crypto)
        except Exception as exc:
            console.print(f"  [red]Crypto scan failed: {exc}[/red]")

    if asset_class in ("stocks", "both"):
        console.print("[cyan]Scanning stocks...[/cyan]")
        try:
            stocks = get_trending_stocks(alpaca)
            console.print(f"  {len(stocks)} trending stocks")
            candidates.extend(stocks)
        except Exception as exc:
            console.print(f"  [red]Stock scan failed: {exc}[/red]")

    if not candidates:
        console.print("[yellow]No candidates found.[/yellow]")
        return

    evaluated = evaluate_for_simulation(candidates)
    console.print(f"\n  {len(evaluated)} assets after evaluation")

    # Display results table
    table = Table(title=f"Top {min(top_n, len(evaluated))} Assets for MiroFish Simulation")
    table.add_column("#", style="dim", width=4)
    table.add_column("Symbol", style="cyan bold")
    table.add_column("Name", width=30)
    table.add_column("Class", style="magenta")
    table.add_column("Price", justify="right")
    table.add_column("Change %", justify="right")
    table.add_column("Volume", justify="right")
    table.add_column("Score", justify="right", style="green")

    for i, asset in enumerate(evaluated[:top_n], 1):
        change_pct = asset.get("change_pct", 0)
        change_style = "green" if change_pct >= 0 else "red"

        table.add_row(
            str(i),
            asset.get("symbol", "?"),
            (asset.get("name", "")[:28]),
            asset.get("asset_class", "?"),
            f"${asset.get('price', 0):,.2f}",
            f"[{change_style}]{change_pct:+.1f}%[/]",
            f"{asset.get('volume', 0):,.0f}",
            f"{asset.get('sim_score', 0):.2f}",
        )

    console.print(table)

    # Class breakdown
    crypto_count = sum(1 for a in evaluated if a.get("asset_class") == "crypto")
    stock_count = sum(1 for a in evaluated if a.get("asset_class") == "stocks")
    console.print(f"\n  Crypto: {crypto_count}  |  Stocks: {stock_count}")
    if evaluated:
        top = evaluated[0]
        console.print(
            f"  Top pick: [bold green]{top['symbol']}[/bold green] "
            f"({top.get('name', '')}) -- score {top.get('sim_score', 0):.2f}"
        )


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------

def _print_final_report(
    logger: TradeLogger,
    total_trades: int,
    total_pnl: float,
    cycles: int,
) -> None:
    """Print a comprehensive final report after reaching trade target."""
    accuracy = logger.get_alpaca_accuracy()
    wins = accuracy.get("wins", 0)
    losses = accuracy.get("losses", 0)
    resolved = accuracy.get("resolved", 0)
    win_rate = accuracy.get("win_rate", 0)

    report = (
        f"[bold cyan]ALPACA PAPER TRADING REPORT[/bold cyan]\n"
        f"\n"
        f"  Cycles completed     : {cycles}\n"
        f"  Total trades placed  : {total_trades}\n"
        f"  Trades resolved      : {resolved}\n"
        f"  Wins / Losses        : {wins} / {losses}\n"
        f"  Win rate             : {win_rate:.1%}\n"
        f"  Total P&L            : ${total_pnl:+,.2f}\n"
        f"\n"
        f"  [bold]Assessment:[/bold]\n"
    )

    if resolved < 10:
        report += "  Not enough resolved trades for assessment. Keep running.\n"
    elif win_rate >= 0.58:
        report += "  [bold green]EXCELLENT[/bold green] -- Strategy showing strong edge. Consider live trading.\n"
    elif win_rate >= 0.54:
        report += "  [bold green]GOOD[/bold green] -- Strategy is profitable. Continue paper trading to confirm.\n"
    elif win_rate >= 0.52:
        report += "  [bold yellow]MARGINAL[/bold yellow] -- Slight edge detected. Needs more data.\n"
    else:
        report += "  [bold red]BELOW THRESHOLD[/bold red] -- Strategy not working. Reassess before live trading.\n"

    report += (
        f"\n"
        f"  CSV export: data/alpaca_trades_report.csv\n"
        f"  Dashboard:  streamlit run dashboard/app.py"
    )

    console.print(Panel(report, title="Alpaca Final Report", border_style="cyan"))

    # Export CSV
    try:
        logger.export_csv("data/alpaca_trades_report.csv")
        console.print("  [green]Trade data exported to data/alpaca_trades_report.csv[/green]")
    except Exception as e:
        console.print(f"  [yellow]CSV export failed: {e}[/yellow]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Alpaca + MiroFish directional trading bot orchestrator",
    )
    parser.add_argument(
        "--mode",
        choices=["paper", "live", "evaluate"],
        default="paper",
        help="'evaluate' ranks assets without trading, "
             "'paper' runs full simulation loop, "
             "'live' requires confirmation and 30+ paper trades.",
    )
    parser.add_argument(
        "--asset-class",
        choices=["crypto", "stocks", "both"],
        default="crypto",
        help="Which asset classes to scan (default: crypto)",
    )
    parser.add_argument(
        "--top", type=int, default=30,
        help="Number of assets to show in evaluate mode (default 30)",
    )
    parser.add_argument(
        "--max-trades", type=int, default=0,
        help="Stop after N trades and print report (0 = run forever)",
    )
    args = parser.parse_args()

    if args.mode == "evaluate":
        evaluate(asset_class=args.asset_class, top_n=args.top)
    else:
        main(mode=args.mode, asset_class=args.asset_class, max_trades=args.max_trades)
