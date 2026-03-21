"""
Main orchestrator for the Kalshi + MiroFish trading bot.

Ties together all modules into a scan-simulate-trade loop:
  1. Scan Kalshi for active markets meeting volume/time filters
  2. Run MiroFish swarm simulations to get independent probability estimates
  3. Detect pricing gaps between MiroFish and Kalshi
  4. Size positions with fractional Kelly Criterion
  5. Place limit orders and track P&L

Supports --mode paper (default) and --mode live.
"""

import argparse
import logging
import sys
import time

from rich.console import Console
from rich.panel import Panel

from src.config import load_config
from src.kalshi_client import KalshiClient
from src.mirofish_client import MiroFishClient, run_full_simulation
from src.event_formatter import format_event, get_event_question
from src.gap_detector import detect_gap, filter_opportunities
from src.position_sizer import kelly_size
from src.trade_logger import TradeLogger
from src.market_evaluator import evaluate_markets, print_evaluation

# ---------------------------------------------------------------------------
# Constants — hardcoded risk management rules
# ---------------------------------------------------------------------------
MAX_POSITION_PCT = 0.05          # 5% bankroll per position
MIN_GAP_THRESHOLD = 0.15         # 15% minimum gap to trade
MIN_MARKET_VOLUME = 10_000       # $10k minimum market volume
MAX_CORRELATED_POSITIONS = 3     # max positions on same event
DRAWDOWN_STOP_PCT = 0.20         # 20% drawdown kills the bot
MIN_PAPER_TRADES = 50            # required before live mode
CYCLE_SLEEP_SECONDS = 7200       # 2 hours between cycles
MAX_SIMS_PER_CYCLE = 10          # cap simulations per scan

console = Console()
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    """Configure structured logging to stdout."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def _print_banner(mode: str, balance: float, config) -> None:
    """Print a startup banner with current mode and config summary."""
    env_label = config.kalshi_env.upper()
    banner = (
        f"[bold cyan]Kalshi + MiroFish Trading Bot[/bold cyan]\n"
        f"\n"
        f"  Mode            : [bold {'red' if mode == 'live' else 'yellow'}]{mode.upper()}[/]\n"
        f"  Kalshi env      : {env_label}\n"
        f"  Balance         : ${balance:,.2f}\n"
        f"  Bankroll target : ${config.starting_bankroll:,.2f}\n"
        f"  Kelly fraction  : {config.kelly_fraction:.0%}\n"
        f"  Max position    : {MAX_POSITION_PCT:.0%} of bankroll\n"
        f"  Min gap         : {MIN_GAP_THRESHOLD:.0%}\n"
        f"  Min volume      : ${MIN_MARKET_VOLUME:,}\n"
        f"  Max correlated  : {MAX_CORRELATED_POSITIONS}\n"
        f"  Drawdown stop   : {DRAWDOWN_STOP_PCT:.0%}\n"
        f"  Cycle interval  : {CYCLE_SLEEP_SECONDS // 60} min\n"
        f"  Agents/sim      : {config.mirofish_agent_count}\n"
        f"  Rounds/sim      : {config.mirofish_rounds}"
    )
    console.print(Panel(banner, title="Startup", border_style="cyan"))


def _confirm_live_mode(balance: float) -> bool:
    """Require explicit confirmation before live trading."""
    console.print(
        Panel(
            f"[bold red]LIVE MODE[/bold red]\n\n"
            f"  Account balance: ${balance:,.2f}\n\n"
            f"  Real money will be used. Type [bold]CONFIRM[/bold] to proceed.",
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
    """Return True if enough paper trades have been logged."""
    accuracy = logger.get_accuracy()
    total = accuracy.get("total_trades", 0)
    if total < MIN_PAPER_TRADES:
        console.print(
            f"[bold red]Blocked:[/bold red] Only {total} paper trades logged. "
            f"Need at least {MIN_PAPER_TRADES} before live mode."
        )
        return False
    console.print(
        f"[green]Paper trade gate passed: {total} trades "
        f"({accuracy.get('win_rate', 0):.1%} win rate)[/green]"
    )
    return True


def _resolve_open_positions(kalshi: KalshiClient, logger: TradeLogger) -> float:
    """Check settled markets for open positions and update the logger.

    Returns the net P&L from newly resolved trades this cycle.
    """
    resolved_pnl = 0.0
    open_positions = logger.get_open_positions()

    for position in open_positions:
        ticker = position.get("ticker")
        if not ticker:
            continue

        settlement = kalshi.get_market_settlement(ticker)
        if settlement is None:
            continue

        result = settlement.get("result", "")
        revenue = settlement.get("revenue", 0)

        # revenue from Kalshi is in cents
        pnl_dollars = revenue / 100.0 if isinstance(revenue, (int, float)) else 0.0

        logger.update_trade(
            ticker=ticker,
            status="settled",
            result=result,
            pnl=pnl_dollars,
        )

        resolved_pnl += pnl_dollars
        console.print(
            f"  Settled [cyan]{ticker}[/cyan] -> "
            f"{'[green]WIN' if pnl_dollars > 0 else '[red]LOSS'}[/] "
            f"${pnl_dollars:+,.2f}"
        )

    return resolved_pnl


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main(mode: str = "paper", max_trades: int = 0) -> None:
    """Run the scan-simulate-trade loop.

    If max_trades > 0, stops after that many trades and prints a report.
    """
    _setup_logging()

    # ── 1. Initialize ────────────────────────────────────────────────────
    config = load_config()
    kalshi = KalshiClient(config)
    mirofish = MiroFishClient(config)
    logger = TradeLogger()

    balance = kalshi.get_balance()
    starting_bankroll = max(balance, config.starting_bankroll)

    _print_banner(mode, balance, config)

    # ── 2. Live-mode gates ───────────────────────────────────────────────
    if mode == "live":
        if not _check_paper_trade_minimum(logger):
            sys.exit(1)
        if not _confirm_live_mode(balance):
            sys.exit(0)

    # ── 3. Tracking state ────────────────────────────────────────────────
    total_pnl = 0.0
    total_trades = 0
    cycle_count = 0

    # ── 4. Main loop ─────────────────────────────────────────────────────
    while True:
        cycle_count += 1
        console.rule(f"[bold]Cycle {cycle_count}[/bold]")

        # ── 4a. Drawdown stop ────────────────────────────────────────────
        if total_pnl < -(starting_bankroll * DRAWDOWN_STOP_PCT):
            console.print(
                Panel(
                    f"[bold red]DRAWDOWN STOP[/bold red]\n\n"
                    f"  Total P&L: ${total_pnl:+,.2f}\n"
                    f"  Limit:     -${starting_bankroll * DRAWDOWN_STOP_PCT:,.2f} "
                    f"({DRAWDOWN_STOP_PCT:.0%} of ${starting_bankroll:,.2f})\n\n"
                    f"  Bot halted to protect capital.",
                    title="Risk Management",
                    border_style="red",
                )
            )
            break

        # ── 4b. Scan and evaluate markets ──────────────────────────────
        console.print("[cyan]Scanning Kalshi markets...[/cyan]")
        try:
            raw_markets = kalshi.get_active_markets(
                min_volume=MIN_MARKET_VOLUME,
                min_hours_to_close=24,
            )
        except Exception as exc:
            console.print(f"[red]Market scan failed: {exc}[/red]")
            log.exception("Market scan failed")
            time.sleep(CYCLE_SLEEP_SECONDS)
            continue

        console.print(f"  Found {len(raw_markets)} markets meeting volume/time filters")

        # Evaluate and rank by MiroFish fit
        evaluated = evaluate_markets(raw_markets, max_results=MAX_SIMS_PER_CYCLE * 2)
        console.print(f"  {len(evaluated)} markets after tier evaluation (Tier 1 & 2 only)")
        if evaluated:
            print_evaluation(evaluated[:15])

        # ── 4c. Filter already simulated today ──────────────────────────
        simulated_today = logger.get_simulated_tickers_today()
        markets = [
            m for m in evaluated
            if m["ticker"] not in simulated_today
        ]
        console.print(f"  {len(markets)} after removing already-simulated tickers")

        # ── 4d. Cap at MAX_SIMS_PER_CYCLE ───────────────────────────────
        markets = markets[:MAX_SIMS_PER_CYCLE]

        # ── 4e. Simulate each market ────────────────────────────────────
        opportunities: list[dict] = []

        for i, market in enumerate(markets, 1):
            ticker = market["ticker"]
            title = market.get("title", "")
            subtitle = market.get("subtitle", "")
            label = subtitle or title
            console.print(
                f"\n  [{i}/{len(markets)}] Simulating [bold]{ticker}[/bold]: {label[:60]}"
            )

            try:
                seed_text = format_event(market)
                event_question = get_event_question(market)

                sim_result = run_full_simulation(
                    client=mirofish,
                    seed_text=seed_text,
                    event_question=event_question,
                )

                logger.log_simulation(
                    ticker=ticker,
                    sim_id=sim_result.get("sim_id"),
                    status=sim_result.get("status"),
                    probability=sim_result.get("probability"),
                    cost=sim_result.get("estimated_cost", 0),
                )

                if sim_result.get("status") != "completed":
                    console.print(
                        f"    [yellow]Simulation {sim_result.get('status', 'unknown')} "
                        f"— skipping[/yellow]"
                    )
                    continue

                mf_prob = sim_result["probability"]
                # yes_price is already 0.0-1.0 (dollars) from SDK v3
                kalshi_price = market["yes_price"]

                signal = detect_gap(
                    mirofish_prob=mf_prob,
                    kalshi_price=kalshi_price,
                    min_gap=MIN_GAP_THRESHOLD,
                )

                direction_icon = "+" if signal["direction"] == "yes" else "-"
                console.print(
                    f"    MiroFish: {mf_prob:.1%}  |  Kalshi: {kalshi_price:.1%}  |  "
                    f"Gap: {direction_icon}{signal['abs_gap']:.1%}  |  "
                    f"Tradeable: {'YES' if signal['tradeable'] else 'no'}  |  "
                    f"Confidence: {signal['confidence']}"
                )

                if signal["tradeable"]:
                    opportunities.append({
                        "market": market,
                        "signal": signal,
                        "sim_result": sim_result,
                    })

            except Exception as exc:
                console.print(f"    [red]Error: {exc}[/red]")
                log.exception("Simulation failed for %s", ticker)
                continue

        # ── 4f. Rank opportunities ──────────────────────────────────────
        open_positions = logger.get_open_positions()
        ranked = filter_opportunities(
            markets_with_signals=opportunities,
            open_positions=open_positions,
            max_correlated=MAX_CORRELATED_POSITIONS,
        )
        console.print(f"\n  [bold]{len(ranked)}[/bold] tradeable opportunities after filtering")

        # ── 4g. Size and place orders ───────────────────────────────────
        trades_placed = 0
        bankroll = kalshi.get_balance()

        for opp in ranked:
            market = opp["market"]
            signal = opp["signal"]
            ticker = market["ticker"]

            sizing = kelly_size(
                win_prob=signal["mirofish_prob"],
                kalshi_price=signal["kalshi_price"],
                bankroll=bankroll,
                kelly_fraction=config.kelly_fraction,
                max_position_pct=MAX_POSITION_PCT,
            )

            if sizing["contracts"] < 1:
                console.print(
                    f"  Skipping [cyan]{ticker}[/cyan] — position too small "
                    f"({sizing['contracts']} contracts)"
                )
                continue

            console.print(
                f"  Placing order: [bold]{sizing['side'].upper()}[/bold] "
                f"{sizing['contracts']} contracts on [cyan]{ticker}[/cyan] "
                f"@ {sizing['price_cents']}c "
                f"(${sizing['dollar_amount']:.2f}, "
                f"kelly={sizing['adjusted_pct']:.2%}"
                f"{' CAPPED' if sizing['capped'] else ''})"
            )

            try:
                order = kalshi.place_order(
                    ticker=ticker,
                    side=sizing["side"],
                    contracts=sizing["contracts"],
                    price_cents=sizing["price_cents"],
                )

                logger.log_trade(
                    ticker=ticker,
                    side=sizing["side"],
                    contracts=sizing["contracts"],
                    price_cents=sizing["price_cents"],
                    order_id=order.get("order_id"),
                    mirofish_prob=signal["mirofish_prob"],
                    kalshi_price=signal["kalshi_price"],
                    gap=signal["gap"],
                    kelly_pct=sizing["adjusted_pct"],
                    dollar_amount=sizing["dollar_amount"],
                )

                trades_placed += 1
                total_trades += 1
                bankroll -= sizing["dollar_amount"]

                console.print(
                    f"    [green]Order placed:[/green] {order.get('order_id', 'N/A')} "
                    f"— status: {order.get('status', 'unknown')}"
                )

            except Exception as exc:
                console.print(f"    [red]Order failed: {exc}[/red]")
                log.exception("Order placement failed for %s", ticker)
                continue

        # ── 4h. Check resolved trades ───────────────────────────────────
        console.print("\n  [cyan]Checking settlements...[/cyan]")
        resolved_pnl = _resolve_open_positions(kalshi, logger)
        total_pnl += resolved_pnl

        # ── 4i. Cycle summary ───────────────────────────────────────────
        accuracy = logger.get_accuracy()
        console.print(
            Panel(
                f"  Markets scanned  : {len(markets)}\n"
                f"  Simulations run  : {len(markets)}\n"
                f"  Trades placed    : {trades_placed}\n"
                f"  Resolved P&L     : ${resolved_pnl:+,.2f}\n"
                f"  Total P&L        : ${total_pnl:+,.2f}\n"
                f"  Bankroll         : ${bankroll:,.2f}\n"
                f"  Win rate         : {accuracy.get('win_rate', 0):.1%} "
                f"({accuracy.get('wins', 0)}/{accuracy.get('total_trades', 0)})",
                title=f"Cycle {cycle_count} Summary",
                border_style="green" if resolved_pnl >= 0 else "red",
            )
        )

        # ── 4j. Check max trades target ──────────────────────────────────
        if max_trades > 0 and total_trades >= max_trades:
            console.print(
                f"\n  [bold green]Target reached: {total_trades} trades placed.[/bold green]"
            )
            _print_final_report(logger, total_trades, total_pnl, cycle_count)
            break

        # ── 4k. Sleep until next cycle ──────────────────────────────────
        console.print(
            f"  Sleeping {CYCLE_SLEEP_SECONDS // 60} minutes until next cycle...\n"
        )
        time.sleep(CYCLE_SLEEP_SECONDS)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _print_final_report(logger: TradeLogger, total_trades: int,
                        total_pnl: float, cycles: int) -> None:
    """Print a comprehensive final report after reaching trade target."""
    accuracy = logger.get_accuracy()
    wins = accuracy.get("wins", 0)
    losses = accuracy.get("losses", 0)
    resolved = accuracy.get("resolved", 0)
    win_rate = accuracy.get("win_rate", 0)
    avg_gap = accuracy.get("avg_gap", 0)

    report = (
        f"[bold cyan]PAPER TRADING REPORT[/bold cyan]\n"
        f"\n"
        f"  Cycles completed     : {cycles}\n"
        f"  Total trades placed  : {total_trades}\n"
        f"  Trades resolved      : {resolved}\n"
        f"  Wins / Losses        : {wins} / {losses}\n"
        f"  Win rate             : {win_rate:.1%}\n"
        f"  Total P&L            : ${total_pnl:+,.2f}\n"
        f"  Avg gap at entry     : {avg_gap:.1%}\n"
        f"\n"
        f"  [bold]Assessment:[/bold]\n"
    )

    if resolved < 10:
        report += "  Not enough resolved trades for assessment. Keep running.\n"
    elif win_rate >= 0.58:
        report += "  [bold green]EXCELLENT[/bold green] — Strategy showing strong edge. Consider Phase 3.\n"
    elif win_rate >= 0.54:
        report += "  [bold green]GOOD[/bold green] — Strategy is profitable. Continue paper trading to confirm.\n"
    elif win_rate >= 0.52:
        report += "  [bold yellow]MARGINAL[/bold yellow] — Slight edge detected. Needs more data.\n"
    else:
        report += "  [bold red]BELOW THRESHOLD[/bold red] — Strategy not working. Reassess before live trading.\n"

    report += (
        f"\n"
        f"  CSV export: data/trades_report.csv\n"
        f"  Dashboard:  streamlit run dashboard/app.py"
    )

    console.print(Panel(report, title="Final Report", border_style="cyan"))

    # Export CSV
    try:
        logger.export_csv("data/trades_report.csv")
        console.print("  [green]Trade data exported to data/trades_report.csv[/green]")
    except Exception as e:
        console.print(f"  [yellow]CSV export failed: {e}[/yellow]")


def evaluate(top_n: int = 30) -> None:
    """Evaluate mode: scan and rank markets without trading."""
    _setup_logging()
    config = load_config()
    kalshi = KalshiClient(config)

    console.print(Panel("[bold cyan]Market Evaluation Mode[/bold cyan]\n\nScanning Kalshi and ranking markets by MiroFish simulation fit.", border_style="cyan"))

    balance = kalshi.get_balance()
    console.print(f"  Balance: ${balance:,.2f}")
    console.print(f"  Environment: {config.kalshi_env.upper()}\n")

    console.print("[cyan]Scanning markets...[/cyan]")
    raw_markets = kalshi.get_active_markets(min_volume=500, min_hours_to_close=12)
    console.print(f"  {len(raw_markets)} markets found")

    evaluated = evaluate_markets(raw_markets, max_results=top_n)
    console.print(f"  {len(evaluated)} markets after evaluation\n")

    print_evaluation(evaluated)

    # Print tier breakdown
    t1 = sum(1 for m in evaluated if m["tier"] == 1)
    t2 = sum(1 for m in evaluated if m["tier"] == 2)
    console.print(f"\n  Tier 1 (Strong fit): {t1} markets")
    console.print(f"  Tier 2 (Moderate fit): {t2} markets")
    console.print(f"\n  Top pick: [bold green]{evaluated[0]['ticker']}[/bold green] — {evaluated[0]['evaluation']}" if evaluated else "")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Kalshi + MiroFish trading bot orchestrator",
    )
    parser.add_argument(
        "--mode",
        choices=["paper", "live", "evaluate"],
        default="paper",
        help="'evaluate' ranks markets without trading, "
             "'paper' runs full simulation loop, "
             "'live' requires confirmation and 50+ paper trades.",
    )
    parser.add_argument(
        "--top", type=int, default=30,
        help="Number of markets to show in evaluate mode (default 30)",
    )
    parser.add_argument(
        "--max-trades", type=int, default=0,
        help="Stop after N trades and print report (0 = run forever)",
    )
    args = parser.parse_args()

    if args.mode == "evaluate":
        evaluate(top_n=args.top)
    else:
        main(mode=args.mode, max_trades=args.max_trades)
