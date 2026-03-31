"""
Alpaca trading orchestrator — Technical-First, MiroFish-as-Guardian.

Three-layer architecture:
  1. Technical Signal Engine — EMA, ADX, RSI, Volume, VWAP confluence scoring
  2. MiroFish Risk Gate — LLM risk panel vetoes bad trades before entry
  3. MiroFish Exit Advisor — smart stop-loss/take-profit for open positions

Only trades crypto (top 8 by market cap). Paper-only until user-defined
equity target is reached (default $100k). Set LIVE_TRADING_THRESHOLD env
var to control when the bot auto-promotes to live (e.g. "120000").

Usage:
  python -m src.alpaca_orchestrator --mode paper --max-trades 50
"""

import argparse
import logging
import sys
import threading
import time
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.config import load_config
from src.alpaca_client import AlpacaClient
from src.alpaca_evaluator import get_trending_crypto, TOP_CRYPTO_TICKERS
from src.technical_signals import scan_assets, analyze
from src.risk_gate import RiskGate
from src.exit_advisor import ExitAdvisor, TrailingStop, check_position_thresholds, HARD_STOP_PCT, HARD_TAKE_PROFIT_PCT
from src.trade_logger import TradeLogger

try:
    from src.trade_memory import TradeMemory
    from src.learning_loop import LearningLoop
    _HAS_LEARNING = True
except ImportError:
    _HAS_LEARNING = False

# ---------------------------------------------------------------------------
# Constants — hardcoded risk management rules
# ---------------------------------------------------------------------------
import os as _os

MAX_POSITION_PCT = 0.05           # 5% bankroll per position
MAX_SIMULTANEOUS_POSITIONS = 5    # max open positions at once
DRAWDOWN_STOP_PCT = 0.10          # 10% daily drawdown kills the bot
MIN_PAPER_TRADES = 50             # required before live mode
MIN_WIN_RATE = 0.40               # required before live mode
MIN_CONFLUENCE = 3                # minimum technical score (out of 5) to trade
CYCLE_SLEEP_SECONDS = 1800        # 30 min between cycles
POSITION_CHECK_INTERVAL = 60      # check positions every 60 seconds

# User-configurable live trading threshold (set via env var)
LIVE_TRADING_THRESHOLD = float(_os.environ.get("LIVE_TRADING_THRESHOLD", "100000"))

console = Console()
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Position Monitor — background thread with MiroFish exit intelligence
# ---------------------------------------------------------------------------

class PositionMonitor(threading.Thread):
    """Background thread that checks open positions every 60 seconds.

    Uses MiroFish Exit Advisor for soft thresholds (-2%, +5%).
    Immediately exits on hard thresholds (-4%, +10%).
    """

    def __init__(self, alpaca: AlpacaClient, logger: TradeLogger, exit_advisor: ExitAdvisor):
        super().__init__(daemon=True, name="position-monitor")
        self.alpaca = alpaca
        self.logger = logger
        self.exit_advisor = exit_advisor
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self.checks = 0
        self.closes = 0
        self.total_pnl = 0.0
        self._tightened: set[int] = set()  # trade IDs with tightened stops
        self._trailing = TrailingStop()    # trailing stop tracker

    def stop(self):
        self._stop_event.set()

    def run(self):
        log.info("Position monitor started (checking every %ds)", POSITION_CHECK_INTERVAL)
        while not self._stop_event.is_set():
            try:
                self._check_all_positions()
            except Exception as exc:
                log.error("Position monitor error: %s", exc)
            self._stop_event.wait(POSITION_CHECK_INTERVAL)
        log.info("Position monitor stopped (checks=%d, closes=%d, pnl=$%.2f)",
                 self.checks, self.closes, self.total_pnl)

    def _check_all_positions(self):
        self.checks += 1
        open_trades = self.logger.get_open_alpaca_positions()
        if not open_trades:
            return

        for trade in open_trades:
            symbol = trade.get("symbol")
            entry_price = trade.get("entry_price", 0)
            side = trade.get("side", "buy")
            trade_id = trade.get("id")
            qty = trade.get("qty", 0)

            if not symbol or not entry_price:
                continue

            try:
                current_price = self.alpaca.get_latest_price(symbol)
            except Exception:
                continue

            if not current_price or current_price <= 0:
                continue

            pnl_pct = (current_price - entry_price) / entry_price
            trade_pnl = (current_price - entry_price) * qty

            # Check trailing stop first (it tracks high-water marks every tick)
            trail_trigger = self._trailing.update(trade_id, entry_price, current_price)
            if trail_trigger:
                threshold = trail_trigger
            else:
                # Check fixed threshold crossings
                threshold = check_position_thresholds(entry_price, current_price)

            # If tightened to breakeven, exit if below entry
            if not threshold and trade_id in self._tightened and current_price < entry_price:
                threshold = "tightened_stop"

            if not threshold:
                continue

            should_close = False
            close_reason = threshold

            if threshold in ("hard_stop", "hard_take_profit", "tightened_stop"):
                should_close = True
            elif threshold in ("soft_stop", "soft_take_profit"):
                # Consult MiroFish Exit Advisor
                try:
                    ts = trade.get("timestamp", "")
                    hours_held = 0.0
                    if ts:
                        entry_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        hours_held = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600

                    bars = self.alpaca.get_bars(symbol, timeframe="1Hour", limit=10)
                    advice = self.exit_advisor.should_exit(
                        symbol=symbol,
                        entry_price=entry_price,
                        current_price=current_price,
                        side=side,
                        hours_held=hours_held,
                        bars=bars,
                    )

                    if advice and advice.decision == "EXIT":
                        should_close = True
                        close_reason = f"exit_advisor_{threshold}"
                    elif advice and advice.decision == "TIGHTEN":
                        self._tightened.add(trade_id)
                        log.info("TIGHTENED stop for %s (trade %d) to breakeven", symbol, trade_id)
                        console.print(
                            f"  [yellow][MONITOR] TIGHTENED[/yellow] {symbol} — "
                            f"stop moved to breakeven (${entry_price:.2f})"
                        )
                        continue
                    else:
                        # HOLD — do nothing
                        continue
                except Exception as exc:
                    log.warning("Exit advisor failed for %s, holding: %s", symbol, exc)
                    continue

            if should_close:
                pnl_display = f"${trade_pnl:+,.2f}"
                trigger_label = close_reason.upper().replace("_", " ")
                color = "red" if trade_pnl < 0 else "green"

                log.info(
                    "[MONITOR] %s triggered for %s: entry=$%.2f current=$%.2f (%.1f%%) P&L=$%.2f",
                    trigger_label, symbol, entry_price, current_price, pnl_pct * 100, trade_pnl,
                )
                console.print(
                    f"  [bold {color}][MONITOR] {trigger_label}[/bold {color}] "
                    f"{symbol} {side.upper()} | entry=${entry_price:.2f} -> ${current_price:.2f} "
                    f"({pnl_pct * 100:+.1f}%) | P&L: {pnl_display}"
                )

                with self._lock:
                    try:
                        self.alpaca.close_position(symbol)
                        self.logger.update_alpaca_trade(
                            trade_id=trade_id,
                            status="closed",
                            exit_price=current_price,
                            pnl=trade_pnl,
                        )
                        self.closes += 1
                        self.total_pnl += trade_pnl
                        self._tightened.discard(trade_id)
                        self._trailing.remove(trade_id)
                    except Exception as exc:
                        log.error("[MONITOR] Failed to close %s: %s", symbol, exc)

    def get_stats(self) -> dict:
        return {
            "checks": self.checks,
            "closes": self.closes,
            "total_pnl": self.total_pnl,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s -- %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def _print_banner(mode: str, balance: float, config) -> None:
    banner = (
        f"[bold cyan]Alpaca Technical + MiroFish Guardian Bot[/bold cyan]\n"
        f"\n"
        f"  Mode            : [bold {'red' if mode == 'live' else 'yellow'}]{mode.upper()}[/]\n"
        f"  Signal          : Technical indicators (EMA/ADX/RSI/Volume/VWAP)\n"
        f"  Guardian        : MiroFish risk gate + exit advisor\n"
        f"  Balance         : ${balance:,.2f}\n"
        f"  Live threshold  : ${LIVE_TRADING_THRESHOLD:,.2f} (set LIVE_TRADING_THRESHOLD env to change)\n"
        f"  Min confluence  : {MIN_CONFLUENCE}/5 indicators\n"
        f"  Max position    : {MAX_POSITION_PCT:.0%} of bankroll\n"
        f"  Hard stop-loss  : {abs(HARD_STOP_PCT):.0%}\n"
        f"  Hard take-profit: {HARD_TAKE_PROFIT_PCT:.0%}\n"
        f"  Max positions   : {MAX_SIMULTANEOUS_POSITIONS}\n"
        f"  Drawdown stop   : {DRAWDOWN_STOP_PCT:.0%} daily\n"
        f"  Cycle interval  : {CYCLE_SLEEP_SECONDS // 60} min\n"
        f"  Assets          : {', '.join(s.replace('/USD','') for s in TOP_CRYPTO_TICKERS)}"
    )
    console.print(Panel(banner, title="Alpaca Orchestrator v2 Startup", border_style="cyan"))


def _cycle_summary(
    cycle_count: int,
    assets_scanned: int,
    signals_found: int,
    risk_gate_passed: int,
    trades_placed: int,
    positions_closed: int,
    cycle_pnl: float,
    total_pnl: float,
    bankroll: float,
    open_positions: int,
    monitor_stats: dict | None = None,
) -> None:
    lines = (
        f"  Assets scanned      : {assets_scanned}\n"
        f"  Technical signals   : {signals_found}\n"
        f"  Risk gate passed    : {risk_gate_passed}\n"
        f"  Trades placed       : {trades_placed}\n"
        f"  Positions closed    : {positions_closed}\n"
        f"  Cycle P&L           : ${cycle_pnl:+,.2f}\n"
        f"  Total P&L           : ${total_pnl:+,.2f}\n"
        f"  Bankroll            : ${bankroll:,.2f}\n"
        f"  Open positions      : {open_positions}"
    )
    if monitor_stats:
        lines += (
            f"\n  Monitor checks      : {monitor_stats['checks']}"
            f"\n  Monitor closes      : {monitor_stats['closes']}"
            f"\n  Monitor P&L         : ${monitor_stats['total_pnl']:+,.2f}"
        )
    console.print(
        Panel(lines, title=f"Cycle {cycle_count} Summary",
              border_style="green" if cycle_pnl >= 0 else "red")
    )


def _kelly_technical(
    confluence: int,
    current_price: float,
    bankroll: float,
    kelly_fraction: float = 0.25,
    max_position_pct: float = 0.05,
) -> dict:
    """Kelly sizing adapted for technical confluence signals.

    Uses confluence score normalized to a win probability estimate.
    Higher confluence = higher estimated edge = bigger position.
    """
    if confluence < MIN_CONFLUENCE:
        return {
            "side": "none", "kelly_pct": 0.0, "adjusted_pct": 0.0,
            "dollar_amount": 0.0, "shares": 0.0, "capped": False,
        }

    # Map confluence to estimated win probability
    # 3/5 = 55%, 4/5 = 60%, 5/5 = 65%
    win_prob_map = {3: 0.55, 4: 0.60, 5: 0.65}
    win_prob = win_prob_map.get(confluence, 0.55)

    # Risk/reward: soft take-profit at 5%, hard stop at 4%
    # b = reward / risk = 5% / 4% = 1.25
    b = 0.05 / 0.04
    p = win_prob
    q = 1.0 - p

    kelly_pct = max(0.0, (b * p - q) / b)
    adjusted_pct = kelly_pct * kelly_fraction

    capped = adjusted_pct > max_position_pct
    if capped:
        adjusted_pct = max_position_pct

    dollar_amount = bankroll * adjusted_pct
    shares = dollar_amount / current_price if current_price > 0 else 0.0

    return {
        "side": "buy",
        "kelly_pct": kelly_pct,
        "adjusted_pct": adjusted_pct,
        "dollar_amount": dollar_amount,
        "shares": shares,
        "capped": capped,
    }


def _confirm_live_mode(balance: float) -> bool:
    console.print(
        Panel(
            f"[bold red]LIVE MODE -- REAL MONEY[/bold red]\n\n"
            f"  Account balance: ${balance:,.2f}\n\n"
            f"  Type [bold]CONFIRM[/bold] to proceed.",
            title="Warning", border_style="red",
        )
    )
    response = input(">>> ").strip()
    return response == "CONFIRM"


def _check_paper_requirements(logger: TradeLogger, equity: float) -> tuple[bool, str]:
    """Check if live trading requirements are met.

    Returns (can_go_live, reason).
    """
    accuracy = logger.get_alpaca_accuracy()
    total = accuracy.get("total_trades", 0)

    if total < MIN_PAPER_TRADES:
        return False, f"Only {total}/{MIN_PAPER_TRADES} paper trades completed"

    win_rate = accuracy.get("win_rate", 0)
    if win_rate < MIN_WIN_RATE:
        return False, f"Win rate {win_rate:.1%} < {MIN_WIN_RATE:.0%} minimum"

    if equity < LIVE_TRADING_THRESHOLD:
        return False, f"Equity ${equity:,.2f} < ${LIVE_TRADING_THRESHOLD:,.2f} breakeven target"

    return True, "All requirements met"


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main(mode: str = "paper", max_trades: int = 0) -> None:
    """Run the technical-signal → risk-gate → trade loop."""
    _setup_logging()

    # -- 1. Initialize --------------------------------------------------------
    config = load_config()
    alpaca = AlpacaClient(config)
    logger = TradeLogger()
    risk_gate = RiskGate(logger=logger)
    exit_advisor = ExitAdvisor()

    # Learning system (optional)
    memory = None
    learner = None
    if _HAS_LEARNING:
        try:
            memory = TradeMemory()
            learner = LearningLoop(memory, logger)
            log.info("Trade learning system initialized")
        except Exception as exc:
            log.warning("Trade learning system failed to initialize: %s", exc)

    account = alpaca.get_account()
    balance = account["equity"]
    starting_bankroll = max(balance, config.starting_bankroll)

    _print_banner(mode, balance, config)

    # -- 1b. Start position monitor with exit advisor -------------------------
    monitor = PositionMonitor(alpaca, logger, exit_advisor)
    monitor.start()
    console.print(f"  [green]Position monitor started[/green] (MiroFish exit advisor active)")

    # -- 2. Live-mode gates ---------------------------------------------------
    if mode == "live":
        can_live, reason = _check_paper_requirements(logger, balance)
        if not can_live:
            console.print(f"[bold red]Blocked:[/bold red] {reason}")
            sys.exit(1)
        if not _confirm_live_mode(balance):
            sys.exit(0)

    # -- 3. Tracking state ----------------------------------------------------
    total_pnl = 0.0
    daily_pnl = 0.0
    total_trades = 0
    cycle_count = 0
    daily_start = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # -- 4. Main loop ---------------------------------------------------------
    while True:
        cycle_count += 1
        console.rule(f"[bold]Cycle {cycle_count}[/bold]")

        # Reset daily P&L at midnight
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != daily_start:
            console.print(f"  [cyan]New trading day: {today}[/cyan]")
            daily_pnl = 0.0
            daily_start = today

        # Daily drawdown stop
        if daily_pnl < -(starting_bankroll * DRAWDOWN_STOP_PCT):
            console.print(
                Panel(
                    f"[bold red]DAILY DRAWDOWN STOP[/bold red]\n\n"
                    f"  Daily P&L: ${daily_pnl:+,.2f}\n"
                    f"  Limit: -${starting_bankroll * DRAWDOWN_STOP_PCT:,.2f}",
                    title="Risk Management", border_style="red",
                )
            )
            time.sleep(3600)
            continue

        # -- 4a. Check position limits ----------------------------------------
        open_positions = logger.get_open_alpaca_positions()
        open_symbols = {p.get("symbol") for p in open_positions}
        current_position_count = len(open_positions)

        signals_found = 0
        risk_gate_passed = 0
        trades_placed = 0
        cycle_pnl = 0.0

        if current_position_count >= MAX_SIMULTANEOUS_POSITIONS:
            console.print(
                f"  [yellow]At max positions ({current_position_count}/"
                f"{MAX_SIMULTANEOUS_POSITIONS}) -- skipping scan[/yellow]"
            )
        else:
            # -- 4b. Layer 1: Technical Signal Engine --------------------------
            console.print("[cyan]Layer 1: Technical signal scan...[/cyan]")
            try:
                signals = scan_assets(alpaca, TOP_CRYPTO_TICKERS, timeframe="1Hour", bar_count=50)
            except Exception as exc:
                console.print(f"  [red]Technical scan failed: {exc}[/red]")
                log.exception("Technical scan failed")
                time.sleep(CYCLE_SLEEP_SECONDS)
                continue

            # Filter by minimum confluence and dedup against open positions
            candidates = [
                s for s in signals
                if s.confluence_score >= MIN_CONFLUENCE and s.symbol not in open_symbols
            ]
            signals_found = len(candidates)

            if candidates:
                console.print(f"  [bold]{signals_found}[/bold] candidates with confluence >= {MIN_CONFLUENCE}")
                for c in candidates:
                    console.print(
                        f"    {c.symbol}: score={c.confluence_score} "
                        f"ema={'UP' if c.ema_bullish else 'DN'} "
                        f"adx={c.adx_value:.0f} rsi={c.rsi_value:.0f} "
                        f"vol_spike={c.volume_spike} vwap={'UP' if c.vwap_bullish else 'DN'}"
                    )
            else:
                console.print("  No assets meet confluence threshold")

            # -- 4c. Layer 2: MiroFish Risk Gate ------------------------------
            bankroll = alpaca.get_account()["equity"]
            approved = []

            for signal in candidates:
                symbol = signal.symbol
                console.print(f"\n  [cyan]Layer 2: Risk gate for {symbol}...[/cyan]")

                try:
                    # Get fresh price data for risk gate context
                    price = alpaca.get_latest_price(symbol)
                    bars = alpaca.get_bars(symbol, timeframe="1Hour", limit=24)

                    # Calculate 24h change
                    if bars and len(bars) >= 2:
                        open_24h = bars[0]["open"]
                        change_pct = ((price - open_24h) / open_24h * 100) if open_24h > 0 else 0.0
                    else:
                        change_pct = 0.0

                    volume_24h = sum(b["volume"] for b in bars) if bars else 0

                    verdict = risk_gate.evaluate(
                        symbol=symbol,
                        price=price,
                        change_pct=change_pct,
                        volume=volume_24h,
                        confluence=signal.confluence_score,
                        bars=bars,
                    )

                    if verdict.decision == "PROCEED":
                        risk_gate_passed += 1
                        console.print(f"    [green]PROCEED[/green] — {verdict.reasoning[:80]}")
                        approved.append({
                            "signal": signal,
                            "price": price,
                            "change_pct": change_pct,
                            "volume_24h": volume_24h,
                            "bars": bars,
                        })
                    else:
                        veto_count = sum(1 for v in verdict.votes.values() if str(v).upper() == "VETO")
                        console.print(
                            f"    [red]VETO[/red] ({veto_count}/5 analysts) — {verdict.reasoning[:80]}"
                        )

                except Exception as exc:
                    console.print(f"    [red]Risk gate error: {exc}[/red]")
                    log.exception("Risk gate failed for %s", symbol)

            # -- 4d. Layer 3: Size and place orders ---------------------------
            for entry in approved:
                # Re-check position limit before each trade (not just once per cycle)
                if current_position_count + trades_placed >= MAX_SIMULTANEOUS_POSITIONS:
                    console.print(
                        f"  [yellow]Position limit reached ({current_position_count + trades_placed}/"
                        f"{MAX_SIMULTANEOUS_POSITIONS}) — skipping remaining candidates[/yellow]"
                    )
                    break

                signal = entry["signal"]
                symbol = signal.symbol
                price = entry["price"]

                sizing = _kelly_technical(
                    confluence=signal.confluence_score,
                    current_price=price,
                    bankroll=bankroll,
                    kelly_fraction=config.kelly_fraction,
                    max_position_pct=MAX_POSITION_PCT,
                )

                if sizing["side"] == "none" or sizing["shares"] <= 0 or sizing["dollar_amount"] < 10:
                    console.print(f"  Skipping {symbol} -- position too small")
                    continue

                console.print(
                    f"\n  Placing: [bold]BUY[/bold] {sizing['shares']:.4f} of [cyan]{symbol}[/cyan] "
                    f"@ ${price:,.2f} (${sizing['dollar_amount']:.2f}, "
                    f"kelly={sizing['adjusted_pct']:.2%}, confluence={signal.confluence_score}/5"
                    f"{'  CAPPED' if sizing['capped'] else ''})"
                )

                try:
                    order = alpaca.place_market_order(
                        symbol=symbol,
                        qty=sizing["shares"],
                        side="buy",
                    )

                    logger.log_alpaca_trade({
                        "symbol": symbol,
                        "asset_class": "crypto",
                        "side": "buy",
                        "qty": sizing["shares"],
                        "entry_price": price,
                        "mirofish_prob": signal.confluence_score / 5.0,
                        "market_sentiment": f"technical_confluence_{signal.confluence_score}",
                        "target_price": price * (1 + HARD_TAKE_PROFIT_PCT),
                        "stop_loss": price * (1 + HARD_STOP_PCT),
                        "simulation_id": f"tech_{symbol}_{int(time.time())}",
                        "notes": (
                            f"EMA={'bull' if signal.ema_bullish else 'bear'} "
                            f"ADX={signal.adx_value:.0f} RSI={signal.rsi_value:.0f} "
                            f"VolSpike={signal.volume_spike} VWAP={'bull' if signal.vwap_bullish else 'bear'}"
                        ),
                    })

                    trades_placed += 1
                    total_trades += 1
                    bankroll -= sizing["dollar_amount"]

                    console.print(
                        f"    [green]Order placed:[/green] {order.get('order_id', 'N/A')} "
                        f"-- status: {order.get('status', 'submitted')}"
                    )

                    # Record to learning system
                    if memory is not None:
                        try:
                            memory.record_trade_context({
                                "symbol": symbol,
                                "signal_type": f"technical_confluence_{signal.confluence_score}",
                                "sentiment": signal.confluence_score / 5.0,
                                "confidence": "strong" if signal.confluence_score >= 4 else "moderate",
                                "price_at_entry": price,
                                "price_change_24h": entry["change_pct"],
                                "volume_24h": entry["volume_24h"],
                            })
                        except Exception:
                            pass

                except Exception as exc:
                    console.print(f"    [red]Order failed: {exc}[/red]")
                    log.exception("Order failed for %s", symbol)

        # -- 4e. Cycle summary ------------------------------------------------
        open_positions = logger.get_open_alpaca_positions()
        equity = alpaca.get_account()["equity"]
        _cycle_summary(
            cycle_count=cycle_count,
            assets_scanned=len(TOP_CRYPTO_TICKERS),
            signals_found=signals_found,
            risk_gate_passed=risk_gate_passed,
            trades_placed=trades_placed,
            positions_closed=monitor.closes,
            cycle_pnl=cycle_pnl,
            total_pnl=total_pnl + monitor.total_pnl,
            bankroll=equity,
            open_positions=len(open_positions),
            monitor_stats=monitor.get_stats(),
        )

        # Breakeven check
        if equity >= LIVE_TRADING_THRESHOLD:
            can_live, reason = _check_paper_requirements(logger, equity)
            console.print(
                Panel(
                    f"[bold green]LIVE TRADING THRESHOLD REACHED![/bold green]\n"
                    f"Equity: ${equity:,.2f} >= ${LIVE_TRADING_THRESHOLD:,.2f}\n"
                    f"Paper requirements: {'MET' if can_live else 'NOT MET — ' + reason}\n\n"
                    f"To go live: python -m src.alpaca_orchestrator --mode live\n"
                    f"To raise the bar: set LIVE_TRADING_THRESHOLD env var higher",
                    border_style="green",
                )
            )

        # Learning cycle
        if learner is not None:
            try:
                learn_result = learner.run_cycle()
                if learn_result.get("new_lessons"):
                    for lesson in learn_result["new_lessons"]:
                        console.print(f"  [cyan]Learned: {lesson}[/cyan]")
            except Exception:
                pass

        # Max trades check
        if max_trades > 0 and total_trades >= max_trades:
            console.print(f"\n  [bold green]Target: {total_trades} trades placed.[/bold green]")
            _print_final_report(logger, total_trades, total_pnl + monitor.total_pnl, cycle_count)
            break

        # Sleep
        console.print(f"  Sleeping {CYCLE_SLEEP_SECONDS // 60} minutes...\n")
        time.sleep(CYCLE_SLEEP_SECONDS)


# ---------------------------------------------------------------------------
# Final report
# ---------------------------------------------------------------------------

def _print_final_report(logger: TradeLogger, total_trades: int, total_pnl: float, cycles: int) -> None:
    accuracy = logger.get_alpaca_accuracy()
    wins = accuracy.get("wins", 0)
    losses = accuracy.get("losses", 0)
    resolved = accuracy.get("resolved", 0)
    win_rate = accuracy.get("win_rate", 0)

    report = (
        f"[bold cyan]ALPACA PAPER TRADING REPORT (v2 — Technical + MiroFish Guardian)[/bold cyan]\n"
        f"\n"
        f"  Cycles completed     : {cycles}\n"
        f"  Total trades placed  : {total_trades}\n"
        f"  Trades resolved      : {resolved}\n"
        f"  Wins / Losses        : {wins} / {losses}\n"
        f"  Win rate             : {win_rate:.1%}\n"
        f"  Total P&L            : ${total_pnl:+,.2f}\n"
    )

    if resolved >= 10:
        if win_rate >= 0.55:
            report += "  [bold green]STRONG EDGE[/bold green] — Strategy working well.\n"
        elif win_rate >= 0.45:
            report += "  [bold yellow]MARGINAL[/bold yellow] — Edge exists but thin.\n"
        else:
            report += "  [bold red]NO EDGE[/bold red] — Strategy needs work.\n"

    console.print(Panel(report, title="Final Report", border_style="cyan"))


# ---------------------------------------------------------------------------
# Evaluate mode — scan and display signals without trading
# ---------------------------------------------------------------------------

def evaluate() -> None:
    _setup_logging()
    config = load_config()
    alpaca = AlpacaClient(config)

    console.print(
        Panel(
            "[bold cyan]Technical Signal Evaluation Mode[/bold cyan]\n"
            "Scanning crypto assets with technical indicators. No trades.",
            border_style="cyan",
        )
    )

    balance = alpaca.get_account()["equity"]
    console.print(f"  Balance: ${balance:,.2f}\n")

    console.print("[cyan]Running technical analysis on all assets...[/cyan]")
    signals = scan_assets(alpaca, TOP_CRYPTO_TICKERS, timeframe="1Hour", bar_count=50)

    table = Table(title="Technical Signal Scan")
    table.add_column("Symbol", style="cyan bold")
    table.add_column("Score", justify="center")
    table.add_column("EMA(9/21)", justify="center")
    table.add_column("ADX", justify="right")
    table.add_column("RSI", justify="right")
    table.add_column("Vol Spike", justify="center")
    table.add_column("VWAP", justify="center")
    table.add_column("Action", justify="center")

    for s in signals:
        action = "[green]BUY CANDIDATE[/green]" if s.confluence_score >= MIN_CONFLUENCE else "[dim]wait[/dim]"
        table.add_row(
            s.symbol,
            f"[{'green' if s.confluence_score >= MIN_CONFLUENCE else 'yellow'}]{s.confluence_score}/5[/]",
            "[green]BULL[/green]" if s.ema_bullish else "[red]BEAR[/red]",
            f"{s.adx_value:.0f}",
            f"{s.rsi_value:.0f}",
            "[green]YES[/green]" if s.volume_spike else "[dim]no[/dim]",
            "[green]ABOVE[/green]" if s.vwap_bullish else "[red]BELOW[/red]",
            action,
        )

    console.print(table)

    buy_count = sum(1 for s in signals if s.confluence_score >= MIN_CONFLUENCE)
    console.print(f"\n  {buy_count} buy candidates out of {len(signals)} analyzed")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Alpaca Technical + MiroFish Guardian trading bot",
    )
    parser.add_argument(
        "--mode", choices=["paper", "live", "evaluate"], default="paper",
        help="'evaluate' shows signals without trading, "
             "'paper' runs full loop, 'live' requires confirmation",
    )
    parser.add_argument(
        "--max-trades", type=int, default=0,
        help="Stop after N trades and print report (0 = run forever)",
    )
    args = parser.parse_args()

    if args.mode == "evaluate":
        evaluate()
    else:
        main(mode=args.mode, max_trades=args.max_trades)
