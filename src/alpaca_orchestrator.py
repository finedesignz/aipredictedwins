"""
Alpaca trading orchestrator — Technical-First, deterministic risk + exits.

Three-layer architecture:
  1. Technical Signal Engine — EMA, ADX, RSI, Volume, VWAP confluence scoring
  2. RulesGate — deterministic risk gate vetoes bad trades before entry (no LLM)
  3. Deterministic exits — ATR trailing stop + hard/soft pct thresholds

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
from src.alpaca_evaluator import get_trending_crypto, TOP_CRYPTO_TICKERS, MEME_CRYPTO, get_dynamic_crypto_universe
from src.technical_signals import scan_assets, analyze, _atr
from src.rules_gate import RulesGate
from src.risk_gate import RiskGate  # keep for backward compat / type hints
from src.exit_advisor import TrailingStop, HARD_STOP_PCT, SOFT_STOP_PCT, SOFT_TAKE_PROFIT_PCT
from src.fee_gate import clears_fee_hurdle, TAKER_FEE, SLIPPAGE_BUFFER
from src.trade_logger import TradeLogger

from src.notifier import alert_bot_crash, alert_drawdown_stop, alert_monitor_error, alert_position_closed, send_alert
from src.pipeline_state import PipelineState

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

from src.strategy_profile import PROFILES, SWING
# Resolve active profile from BOT_PROFILE at module load, BEFORE the style-constant
# defaults below read PROFILE.* — keeps the Phase-1 env-default chain intact.
# Unknown value fails fast (no silent fallback); selection is case-insensitive.
_PROFILE_NAME = _os.environ.get("BOT_PROFILE", "swing").lower()
if _PROFILE_NAME not in PROFILES:
    raise ValueError(
        f"Unknown BOT_PROFILE={_PROFILE_NAME!r}; valid: {sorted(PROFILES)}"
    )
PROFILE = PROFILES[_PROFILE_NAME]

MAX_POSITION_PCT = float(_os.environ.get("MAX_POSITION_PCT", str(PROFILE.max_position_pct)))
MAX_TOTAL_EXPOSURE_PCT = float(_os.environ.get("MAX_TOTAL_EXPOSURE_PCT", "0.80"))
# Shadow seam: "1" (default) enforces learning veto/scaling; "0" logs only.
LEARNING_ENFORCE = _os.environ.get("LEARNING_ENFORCE", "1") == "1"
DRAWDOWN_STOP_PCT = float(_os.environ.get("DRAWDOWN_STOP_PCT", "0.10"))
MIN_PAPER_TRADES = int(_os.environ.get("MIN_PAPER_TRADES", "50"))
MIN_WIN_RATE = float(_os.environ.get("MIN_WIN_RATE", "0.40"))
MIN_CONFLUENCE = int(_os.environ.get("MIN_CONFLUENCE", str(PROFILE.min_confluence)))
# Shorts require fewer signals (3/4) since bear setups are more fleeting
MIN_SHORT_CONFLUENCE = int(_os.environ.get("MIN_SHORT_CONFLUENCE", str(PROFILE.min_short_confluence)))

# Symbols that Alpaca paper accounts reject OR have shown 0% win rate across 5+ trades.
# LDO/POL/ONDO/RENDER: ghost trades (silently rejected by Alpaca paper).
# DOT/ARB/SUSHI: 0% win rate across 6+, 5, 7 real trades respectively.
_ALPACA_UNTRADEABLE = frozenset(
    _os.environ.get(
        "ALPACA_UNTRADEABLE",
        "LDO/USD,POL/USD,ONDO/USD,RENDER/USD,DOT/USD,ARB/USD,SUSHI/USD,HYPE/USD,LINK/USD,ETH/USD",
    ).split(",")
)

# Fraction of universe with EMA=bearish that triggers a broad-market pause on new longs.
BEAR_MARKET_PAUSE_THRESHOLD = float(_os.environ.get("BEAR_MARKET_PAUSE_THRESHOLD", "0.60"))
CYCLE_SLEEP_SECONDS = int(_os.environ.get("CYCLE_SLEEP_SECONDS", str(PROFILE.scan_interval_s)))
POSITION_CHECK_INTERVAL = int(_os.environ.get("POSITION_CHECK_INTERVAL", "60"))
SKIP_RISK_GATE = _os.environ.get("SKIP_RISK_GATE", "").lower() in ("1", "true", "yes")
BOT_LABEL = _os.environ.get("BOT_LABEL", "Agent A")
SHORT_ENABLED = _os.environ.get("SHORT_ENABLED", "true").lower() in ("1", "true", "yes")
DYNAMIC_UNIVERSE_SIZE = int(_os.environ.get("DYNAMIC_UNIVERSE_SIZE", "20"))

# User-configurable live trading threshold (set via env var)
LIVE_TRADING_THRESHOLD = float(_os.environ.get("LIVE_TRADING_THRESHOLD", "100000"))

console = Console()
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Position Monitor — background thread with deterministic ATR exits
# ---------------------------------------------------------------------------

class PositionMonitor(threading.Thread):
    """Background thread that checks open positions every 60 seconds.

    Exits are fully deterministic: ATR trailing stop + hard/soft pct thresholds.
    No LLM calls.
    """

    def __init__(self, alpaca: AlpacaClient, logger: TradeLogger, profile=SWING):
        super().__init__(daemon=True, name="position-monitor")
        self.alpaca = alpaca
        self.logger = logger
        self.profile = profile
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
                alert_monitor_error("all", exc)
            self._stop_event.wait(POSITION_CHECK_INTERVAL)
        log.info("Position monitor stopped (checks=%d, closes=%d, pnl=$%.2f)",
                 self.checks, self.closes, self.total_pnl)

    def _check_all_positions(self):
        self.checks += 1
        open_trades = self.logger.get_open_alpaca_positions()
        if not open_trades:
            return

        # Reconcile: fetch live Alpaca positions once and build a lookup by symbol.
        # Any DB-open trade that Alpaca no longer holds was closed externally — mark it
        # closed so the monitor stops trying (and emailing) about it.
        try:
            live_positions = self.alpaca.get_positions()
            live_symbols = {p["symbol"] for p in live_positions}  # e.g. {"BTCUSD", "ETHUSD"}
        except Exception as exc:
            log.warning("Could not fetch live positions for reconciliation: %s", exc)
            live_positions = []
            live_symbols = None  # don't reconcile if the fetch itself failed

        if live_symbols is not None:
            for trade in open_trades:
                sym = trade.get("symbol", "")
                alpaca_sym = sym.replace("/", "")
                if alpaca_sym and alpaca_sym not in live_symbols:
                    log.info("[MONITOR] %s not in Alpaca positions — marking closed (externally exited)", sym)
                    self.logger.update_alpaca_trade(
                        trade_id=trade["id"],
                        status="closed",
                        exit_price=trade.get("entry_price", 0),
                        pnl=0.0,
                    )
            # Re-fetch so the loop below only processes genuinely live positions
            open_trades = self.logger.get_open_alpaca_positions()
            if not open_trades:
                return

        for trade in open_trades:
            symbol = trade.get("symbol")
            entry_price = trade.get("entry_price", 0)
            side = trade.get("side", "buy")
            trade_id = trade.get("id")
            qty = trade.get("qty", 0)

            if not symbol:
                continue

            try:
                current_price = self.alpaca.get_latest_price(symbol)
            except Exception:
                continue

            if not current_price or current_price <= 0:
                continue

            # Use Alpaca's live entry price if DB entry is near-zero (sub-penny tokens)
            if entry_price <= 0:
                for pos in live_positions:
                    if pos["symbol"] == symbol.replace("/", ""):
                        entry_price = float(pos.get("avg_entry_price", 0))
                        break
                if entry_price <= 0:
                    log.warning("Skipping %s: entry_price is zero in DB and Alpaca", symbol)
                    continue

            if side in ("sell", "short"):
                # Short position: profit when price falls
                pnl_pct = (entry_price - current_price) / entry_price
                trade_pnl = (entry_price - current_price) * qty
            else:
                # Long position: profit when price rises
                pnl_pct = (current_price - entry_price) / entry_price
                trade_pnl = (current_price - entry_price) * qty

            # Hours held — computed per position, unconditionally (used by max_hold).
            ts = trade.get("timestamp", "")
            hours_held = 0.0
            if ts:
                try:
                    entry_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    hours_held = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600
                except ValueError:
                    hours_held = 0.0

            # ATR at the active profile's timeframe (live fetch; 0.0 on insufficient bars).
            atr = 0.0
            try:
                atr_bars = self.alpaca.get_bars(
                    symbol, timeframe=self.profile.timeframe, limit=self.profile.atr_period + 5
                )
                if atr_bars:
                    highs = [b["high"] for b in atr_bars]
                    lows = [b["low"] for b in atr_bars]
                    closes = [b["close"] for b in atr_bars]
                    atr = _atr(highs, lows, closes, self.profile.atr_period)
            except Exception as exc:
                log.warning("ATR fetch failed for %s (%s) — falling back to overrides only", symbol, exc)

            # ----- Deterministic exit ladder (EXIT-02/EXIT-03), first-match wins -----
            # Precedence: hard_stop_pct -> max_hold -> ATR trailing stop -> ATR stop.
            # No LLM: exits are fully deterministic.
            threshold = None

            # 1. Hard stop — absolute, side-aware pnl_pct already computed above.
            if pnl_pct <= self.profile.hard_stop_pct:
                threshold = "hard_stop"
            # 2. Max hold — only when configured (swing = None never time-closes).
            elif self.profile.max_hold_hours is not None and hours_held > self.profile.max_hold_hours:
                threshold = "max_hold"
            # 3. ATR trailing stop (side-aware, only when ATR is valid).
            elif atr > 0 and self._trailing.update_atr(
                trade_id, side, entry_price, current_price, atr, self.profile.atr_mult_trail
            ):
                threshold = "trailing_stop"
            # 4. ATR fixed stop (side-aware) — only when ATR is valid.
            elif atr > 0:
                if side in ("sell", "short"):
                    atr_stop_level = entry_price + self.profile.atr_mult_stop * atr
                    if current_price >= atr_stop_level:
                        threshold = "atr_stop"
                else:
                    atr_stop_level = entry_price - self.profile.atr_mult_stop * atr
                    if current_price <= atr_stop_level:
                        threshold = "atr_stop"

            # Dormant tightened-stop rung (harmless; nothing sets _tightened this phase).
            if not threshold and trade_id in self._tightened and current_price < entry_price:
                threshold = "tightened_stop"

            if not threshold:
                continue

            close_reason = threshold

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
                    alert_position_closed(symbol, side, entry_price, current_price, trade_pnl, close_reason)
                except Exception as exc:
                    log.error("[MONITOR] Failed to close %s: %s", symbol, exc)
                    alert_monitor_error(symbol, exc)

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
    risk_mode = "[red]DISABLED[/red]" if SKIP_RISK_GATE else "Rules gate (deterministic) + deterministic ATR exits"
    banner = (
        f"[bold cyan]Alpaca Technical Bot[/bold cyan]\n"
        f"\n"
        f"  Bot label       : [bold]{BOT_LABEL}[/bold]\n"
        f"  Profile         : [bold]{PROFILE.name}[/bold]\n"
        f"  Mode            : [bold {'red' if mode == 'live' else 'yellow'}]{mode.upper()}[/]\n"
        f"  Signal          : Technical indicators (EMA/ADX/RSI/Volume/VWAP)\n"
        f"  Guardian        : {risk_mode}\n"
        f"  Balance         : ${balance:,.2f}\n"
        f"  Live threshold  : ${LIVE_TRADING_THRESHOLD:,.2f} (set LIVE_TRADING_THRESHOLD env to change)\n"
        f"  Min confluence  : {MIN_CONFLUENCE}/5 indicators\n"
        f"  Max position    : {MAX_POSITION_PCT:.0%} of bankroll\n"
        f"  Kelly fraction  : {config.kelly_fraction}\n"
        f"  Hard stop-loss  : {abs(HARD_STOP_PCT):.0%}\n"
        f"  Soft take-profit: 8% (trailing stop captures large gains)\n"
        f"  Max exposure    : {MAX_TOTAL_EXPOSURE_PCT:.0%} of bankroll\n"
        f"  Drawdown stop   : {DRAWDOWN_STOP_PCT:.0%} daily\n"
        f"  Cycle interval  : {CYCLE_SLEEP_SECONDS // 60} min\n"
        f"  Shorts          : {'enabled' if SHORT_ENABLED else 'disabled'}\n"
        f"  Universe size   : {DYNAMIC_UNIVERSE_SIZE} assets (dynamic by volume)"
    )
    console.print(Panel(banner, title=f"Alpaca Orchestrator v2 — {BOT_LABEL}", border_style="cyan"))


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
    confidence_adjustment: float = 1.0,
    min_position_pct: float | None = None,
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

    # Risk/reward: soft take-profit at 8%, hard stop at 5%
    # b = 0.08 / 0.05 = 1.6
    b = 0.08 / 0.05
    p = win_prob
    q = 1.0 - p

    kelly_pct = max(0.0, (b * p - q) / b)
    adjusted_pct = kelly_pct * kelly_fraction

    # LEARN-02: scale by learned confidence before any cap.
    adjusted_pct *= confidence_adjustment

    # LEARN-03: dynamic floor (only when position is non-zero).
    if min_position_pct and adjusted_pct > 0:
        adjusted_pct = max(adjusted_pct, min_position_pct)

    # Hard ceiling clamp stays LAST so the static cap is inviolate.
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


MAX_ENTRIES_PER_CYCLE = int(_os.environ.get("MAX_ENTRIES_PER_CYCLE", "3"))


def _select_cycle_candidates(candidates: list, max_entries: int = MAX_ENTRIES_PER_CYCLE) -> list:
    """Select the best candidates for this cycle, capped at max_entries.

    Selection priority:
    1. Highest confluence score (more bullish indicators = better)
    2. Lowest RSI as tiebreaker (more room to run before overbought)

    Prevents deploying all capital in one correlated burst when the
    whole market moves simultaneously.
    """
    sorted_candidates = sorted(
        candidates,
        key=lambda s: (-s.confluence_score, s.rsi_value),
    )
    return sorted_candidates[:max_entries]


def _check_market_regime(btc_rsi_1h: float, btc_rsi_4h: float) -> str:
    """Classify crypto market regime using BTC RSI on two timeframes.
    OVERHEATED: BTC RSI(1h) > 70 AND RSI(4h) > 65 — skip new entries.
    NORMAL: everything else.
    """
    if btc_rsi_1h > 70.0 and btc_rsi_4h > 65.0:
        return "OVERHEATED"
    return "NORMAL"


def _get_btc_regime(alpaca_client) -> tuple[str, float, float]:
    """Fetch BTC RSI on 1h and 4h, return (regime, rsi_1h, rsi_4h).
    Falls back to NORMAL on any error.
    """
    try:
        bars_1h = alpaca_client.get_bars("BTC/USD", timeframe="1Hour", limit=50)
        rsi_1h = 50.0
        if bars_1h and len(bars_1h) >= 15:
            from src.technical_signals import _rsi
            closes_1h = [b["close"] for b in bars_1h]
            rsi_1h = _rsi(closes_1h, 14) or 50.0
    except Exception as exc:
        log.warning("Failed to fetch BTC 1h bars for regime check: %s", exc)
        return "NORMAL", 50.0, 50.0

    try:
        bars_4h = alpaca_client.get_bars("BTC/USD", timeframe="4Hour", limit=50)
        rsi_4h = 50.0
        if bars_4h and len(bars_4h) >= 15:
            from src.technical_signals import _rsi
            closes_4h = [b["close"] for b in bars_4h]
            rsi_4h = _rsi(closes_4h, 14) or 50.0
    except Exception as exc:
        log.warning("Failed to fetch BTC 4h bars for regime check: %s", exc)
        rsi_4h = 50.0

    regime = _check_market_regime(rsi_1h, rsi_4h)
    return regime, rsi_1h, rsi_4h


VOLUME_PUMP_THRESHOLD = int(_os.environ.get("VOLUME_PUMP_THRESHOLD", "4"))


def _apply_volume_context_filter(signals: list) -> list:
    """Suppress volume spike signal when 4+ assets spike simultaneously (market-wide pump).
    A spike on one asset = institutional interest (valid).
    A spike across 4+ = retail FOMO pump (noise).
    Recalculates confluence score after suppression.
    """
    spiking_count = sum(1 for s in signals if s.volume_spike)
    if spiking_count < VOLUME_PUMP_THRESHOLD:
        return signals

    log.info(
        "Volume context filter: %d/%d assets spiking — suppressing volume signal (market-wide pump)",
        spiking_count, len(signals),
    )

    from dataclasses import replace
    updated = []
    for s in signals:
        if not s.volume_spike:
            updated.append(s)
        else:
            updated.append(replace(s, volume_spike=False, confluence_score=max(0, s.confluence_score - 1)))
    return updated


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
    risk_gate = RulesGate()

    # Dynamic asset universe — refreshed at startup
    log.info("Fetching dynamic crypto universe (top %d by volume)...", DYNAMIC_UNIVERSE_SIZE)
    try:
        universe = get_dynamic_crypto_universe(alpaca, top_n=DYNAMIC_UNIVERSE_SIZE)
    except Exception as _e:
        log.warning("Dynamic universe fetch failed, using default: %s", _e)
        universe = list(TOP_CRYPTO_TICKERS)
    # Strip out known-untradeable symbols so they never reach the signal scanner
    universe = [s for s in universe if s not in _ALPACA_UNTRADEABLE]
    console.print(f"  [cyan]Universe: {len(universe)} assets[/cyan] ({', '.join(s.replace('/USD','') for s in universe[:10])}...)")
    _universe_last_refresh = datetime.now(timezone.utc)

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

    # -- 1b. Start position monitor (deterministic ATR exits) -----------------
    monitor = PositionMonitor(alpaca, logger, PROFILE)
    monitor.start()
    console.print(f"  [green]Position monitor started[/green] (deterministic ATR exits)")

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

        # Refresh universe once per day
        _hours_since_refresh = (datetime.now(timezone.utc) - _universe_last_refresh).total_seconds() / 3600
        if _hours_since_refresh >= 24:
            try:
                universe = get_dynamic_crypto_universe(alpaca, top_n=DYNAMIC_UNIVERSE_SIZE)
                universe = [s for s in universe if s not in _ALPACA_UNTRADEABLE]
                _universe_last_refresh = datetime.now(timezone.utc)
                log.info("Universe refreshed: %d assets", len(universe))
            except Exception as _e:
                log.warning("Universe refresh failed, keeping previous: %s", _e)

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
            alert_drawdown_stop(daily_pnl, starting_bankroll * DRAWDOWN_STOP_PCT, starting_bankroll)
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

        # Check total exposure instead of hard position count cap
        account = alpaca.get_account()
        bankroll = account["buying_power"]
        equity = account.get("equity", bankroll)
        total_exposure = sum(
            float(p.get("entry_price", 0)) * float(p.get("qty", 0))
            for p in open_positions
        )
        exposure_pct = total_exposure / equity if equity > 0 else 1.0

        if exposure_pct >= MAX_TOTAL_EXPOSURE_PCT:
            console.print(
                f"  [yellow]Exposure at {exposure_pct:.0%} of equity "
                f"(${total_exposure:,.0f}/${equity:,.0f}) -- skipping scan[/yellow]"
            )
        else:
            # BTC market regime check — skip new entries if OVERHEATED
            regime, btc_rsi_1h, btc_rsi_4h = _get_btc_regime(alpaca)
            console.print(
                f"  [cyan]Market regime: {regime}[/cyan] "
                f"(BTC RSI 1h={btc_rsi_1h:.1f}, 4h={btc_rsi_4h:.1f})"
            )
            if regime == "OVERHEATED":
                console.print(
                    "  [bold yellow]OVERHEATED regime — skipping new entries this cycle[/bold yellow]"
                )
                log.info(
                    "Cycle %d: OVERHEATED regime (BTC RSI 1h=%.1f, 4h=%.1f) — no new entries",
                    cycle_count, btc_rsi_1h, btc_rsi_4h,
                )
                time.sleep(CYCLE_SLEEP_SECONDS)
                continue

            # -- 4b. Layer 1: Technical Signal Engine --------------------------
            console.print("[cyan]Layer 1: Technical signal scan...[/cyan]")
            try:
                signals = scan_assets(alpaca, universe, timeframe="1Hour", bar_count=50, fetch_4h=True, profile=PROFILE)
                signals = _apply_volume_context_filter(signals)
            except Exception as exc:
                console.print(f"  [red]Technical scan failed: {exc}[/red]")
                log.exception("Technical scan failed")
                time.sleep(CYCLE_SLEEP_SECONDS)
                continue

            # Filter: minimum confluence, dedup, blocklist
            # Broad-market bear pause: if most of the universe has EMA=bearish, skip new longs.
            ema_bear_count = sum(1 for s in signals if not s.ema_bullish)
            bear_fraction = ema_bear_count / len(signals) if signals else 0.0
            market_is_broadly_bearish = bear_fraction >= BEAR_MARKET_PAUSE_THRESHOLD
            if market_is_broadly_bearish:
                console.print(
                    f"  [yellow]BROAD BEAR PAUSE[/yellow] {ema_bear_count}/{len(signals)} assets "
                    f"have EMA=bearish ({bear_fraction:.0%}) — skipping new long entries[/yellow]"
                )

            # Long candidates: EMA must be bullish (hard gate), confluence >= threshold,
            # not already open, not a meme coin, not an Alpaca-untradeable symbol,
            # and 4H trend not explicitly bearish.
            long_candidates = [] if market_is_broadly_bearish else [
                s for s in signals
                if s.ema_bullish  # hard gate: EMA crossover must confirm uptrend
                and s.confluence_score >= MIN_CONFLUENCE
                and s.symbol not in open_symbols
                and s.symbol not in MEME_CRYPTO
                and s.symbol not in _ALPACA_UNTRADEABLE
                and s.trend_4h != "bearish"
            ]

            # Short candidates: bearish signal AND 4H trend not explicitly bullish
            short_candidates = []
            if SHORT_ENABLED:
                short_candidates = [
                    s for s in signals
                    if s.short_score >= MIN_SHORT_CONFLUENCE
                    and s.symbol not in open_symbols
                    and s.symbol not in MEME_CRYPTO
                    and s.symbol not in _ALPACA_UNTRADEABLE
                    and s.trend_4h != "bullish"  # don't short into 4H uptrend
                ]

            # Per-cycle cap: pick best 3 by confluence → lowest RSI tiebreaker
            all_candidates = _select_cycle_candidates(long_candidates)
            # Add short candidates up to the same per-cycle cap
            short_candidates_selected = sorted(short_candidates, key=lambda s: (-s.short_score, -s.rsi_value))[:MAX_ENTRIES_PER_CYCLE]

            signals_found = len(all_candidates) + len(short_candidates_selected)

            if len(long_candidates) > len(all_candidates):
                console.print(
                    f"  [yellow]Cycle cap: {len(long_candidates)} long candidates filtered to "
                    f"{len(all_candidates)} (max {MAX_ENTRIES_PER_CYCLE}/cycle)[/yellow]"
                )

            if all_candidates or short_candidates_selected:
                console.print(f"  [bold]{len(all_candidates)}[/bold] long + [bold]{len(short_candidates_selected)}[/bold] short candidates")
                for c in all_candidates:
                    console.print(f"    LONG  {c.symbol}: score={c.confluence_score} rsi={c.rsi_value:.0f} trend_4h={c.trend_4h}")
                for c in short_candidates_selected:
                    console.print(f"    SHORT {c.symbol}: score={c.short_score} rsi={c.rsi_value:.0f} trend_4h={c.trend_4h}")
            else:
                console.print("  No assets meet confluence threshold")

            # Alias for the existing long trade loop below
            candidates = all_candidates

            # -- 4c. Layer 2: MiroFish Risk Gate ------------------------------
            approved_states: list[PipelineState] = []
            side_data: dict[str, dict] = {}

            for signal in candidates:
                symbol = signal.symbol

                try:
                    # Get fresh price data for risk gate context
                    price = alpaca.get_latest_price(symbol)
                    bars = alpaca.get_bars(symbol, timeframe="1Hour", limit=24)

                    if not bars:
                        console.print(f"  [yellow]Skipping {symbol} — no bar data available[/yellow]")
                        continue

                    # Calculate 24h change
                    if bars and len(bars) >= 2:
                        open_24h = bars[0]["open"]
                        change_pct = ((price - open_24h) / open_24h * 100) if open_24h > 0 else 0.0
                    else:
                        change_pct = 0.0

                    volume_24h = sum(b["volume"] for b in bars) if bars else 0

                    if SKIP_RISK_GATE:
                        # Bypass risk gate — approve all technical signals
                        risk_gate_passed += 1
                        console.print(f"  [green]APPROVED[/green] {symbol} (risk gate disabled)")
                        approved_states.append(
                            PipelineState(
                                symbol=symbol,
                                bars=tuple(bars),
                                signal=signal,
                            )
                        )
                        side_data[symbol] = {"price": price, "change_pct": change_pct, "volume_24h": volume_24h}
                        continue

                    console.print(f"\n  [cyan]Layer 2: Risk gate for {symbol}...[/cyan]")
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
                        approved_states.append(
                            PipelineState(
                                symbol=symbol,
                                bars=tuple(bars),
                                signal=signal,
                            )
                        )
                        side_data[symbol] = {"price": price, "change_pct": change_pct, "volume_24h": volume_24h}
                    else:
                        veto_count = sum(1 for v in verdict.votes.values() if str(v).upper() == "VETO")
                        console.print(
                            f"    [red]VETO[/red] ({veto_count}/5 analysts) — {verdict.reasoning[:80]}"
                        )

                except Exception as exc:
                    console.print(f"    [red]Risk gate error: {exc}[/red]")
                    log.exception("Risk gate failed for %s", symbol)

            # -- 4d. Layer 3: Size and place orders ---------------------------
            # Dynamic thresholds computed ONCE per cycle (not per-candidate).
            thresholds = memory.get_dynamic_thresholds() if memory is not None else None
            cycle_exposure = 0.0
            for state in approved_states:
                # Re-check total exposure before each trade
                if equity > 0 and (total_exposure + cycle_exposure) / equity >= MAX_TOTAL_EXPOSURE_PCT:
                    console.print(
                        f"  [yellow]Exposure limit ({MAX_TOTAL_EXPOSURE_PCT:.0%}) reached "
                        f"— skipping remaining candidates[/yellow]"
                    )
                    break

                signal = state.signal
                symbol = signal.symbol
                price = side_data[symbol]["price"]
                signal_type = f"technical_confluence_{signal.confluence_score}"

                # -- Memory advisory: consult trade history (mirrors bot_thread) --
                adj = 1.0
                if memory is not None:
                    try:
                        advice = memory.get_advice(
                            symbol=symbol,
                            signal_type=signal_type,
                            sentiment=signal.confluence_score / 4.0,
                            price_change=side_data[symbol]["change_pct"],
                        )
                        if not advice["should_trade"]:
                            console.print(
                                f"  [yellow]learn_veto[/yellow] {symbol} — {advice['reasoning']} "
                                f"(enforce={LEARNING_ENFORCE})"
                            )
                            if LEARNING_ENFORCE:
                                continue
                        elif LEARNING_ENFORCE:
                            adj = advice.get("confidence_adjustment", 1.0)
                    except Exception as exc:
                        log.warning("Memory advisory failed for %s: %s", symbol, exc)

                expected_move_pct = 0.08  # long soft target: price * (1 + 0.08)
                if not clears_fee_hurdle(expected_move_pct, TAKER_FEE, SLIPPAGE_BUFFER):
                    console.print(
                        f"  Skipping {symbol} -- fee_gate_skip "
                        f"move={expected_move_pct:.4f} hurdle={2*TAKER_FEE+SLIPPAGE_BUFFER:.4f}"
                    )
                    continue

                if thresholds is not None and LEARNING_ENFORCE:
                    eff_max = min(MAX_POSITION_PCT, thresholds["max_position_pct"])
                    eff_min = thresholds["min_position_pct"]
                else:
                    eff_max = MAX_POSITION_PCT
                    eff_min = None

                sizing = _kelly_technical(
                    confluence=signal.confluence_score,
                    current_price=price,
                    bankroll=bankroll,
                    kelly_fraction=config.kelly_fraction,
                    max_position_pct=eff_max,
                    confidence_adjustment=adj,
                    min_position_pct=eff_min,
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

                    trade_id = logger.log_alpaca_trade({
                        "symbol": symbol,
                        "asset_class": "crypto",
                        "side": "buy",
                        "qty": sizing["shares"],
                        "entry_price": price,
                        "mirofish_prob": signal.confluence_score / 4.0,
                        "market_sentiment": signal_type,
                        "target_price": price * (1 + 0.08),  # soft take-profit at 8%
                        "stop_loss": price * (1 + HARD_STOP_PCT),
                        "simulation_id": f"tech_{symbol}_{int(time.time())}",
                        "notes": (
                            f"EMA={'bull' if signal.ema_bullish else 'bear'} "
                            f"ADX={signal.adx_value:.0f} RSI={signal.rsi_value:.0f} "
                            f"regime={signal.market_regime} "
                            f"VolSpike={signal.volume_spike} VWAP={'bull' if signal.vwap_bullish else 'bear'}"
                        ),
                    })

                    trades_placed += 1
                    total_trades += 1
                    cycle_exposure += sizing["dollar_amount"]
                    bankroll -= sizing["dollar_amount"]

                    console.print(
                        f"    [green]Order placed:[/green] {order.get('order_id', 'N/A')} "
                        f"-- status: {order.get('status', 'submitted')}"
                    )

                    # Record to learning system
                    if memory is not None:
                        try:
                            memory.record_trade_context({
                                "trade_id": trade_id,
                                "symbol": symbol,
                                "signal_type": signal_type,
                                "sentiment": signal.confluence_score / 4.0,
                                "confidence": signal.confluence_score / 4.0,
                                "price_at_entry": price,
                                "price_change_24h": side_data[symbol]["change_pct"],
                                "volume_24h": side_data[symbol]["volume_24h"],
                                "trajectory": "up" if signal.ema_bullish else "mixed",
                            })
                        except Exception:
                            pass

                except Exception as exc:
                    console.print(f"    [red]Order failed: {exc}[/red]")
                    log.exception("Order failed for %s", symbol)

            # -- SHORT candidate processing --
            for signal in short_candidates_selected:
                symbol = signal.symbol
                try:
                    price = alpaca.get_latest_price(symbol)
                    bars = alpaca.get_bars(symbol, timeframe="1Hour", limit=24)
                    if not bars:
                        continue

                    change_pct = ((price - bars[0]["open"]) / bars[0]["open"] * 100) if bars else 0.0
                    volume_24h = sum(b["volume"] for b in bars) if bars else 0

                    # Rules gate check (same gate as longs)
                    if not SKIP_RISK_GATE:
                        verdict = risk_gate.evaluate(
                            symbol=symbol,
                            price=price,
                            change_pct=change_pct,
                            volume=volume_24h,
                            confluence=signal.short_score,
                            bars=bars,
                        )
                        if verdict.decision == "VETO":
                            console.print(f"  [yellow]VETOED SHORT[/yellow] {symbol}: {verdict.reasoning[:80]}")
                            continue

                    risk_gate_passed += 1

                    # Canonical short signal_type for advice + context (NOT the
                    # short_technical_ order-log string).
                    signal_type = f"technical_short_{signal.short_score}"

                    # -- Memory advisory: consult trade history (mirrors bot_thread) --
                    adj = 1.0
                    if memory is not None:
                        try:
                            advice = memory.get_advice(
                                symbol=symbol,
                                signal_type=signal_type,
                                sentiment=signal.short_score / 4.0,
                                price_change=change_pct,
                            )
                            if not advice["should_trade"]:
                                console.print(
                                    f"  [yellow]learn_veto SHORT[/yellow] {symbol} — "
                                    f"{advice['reasoning']} (enforce={LEARNING_ENFORCE})"
                                )
                                if LEARNING_ENFORCE:
                                    continue
                            elif LEARNING_ENFORCE:
                                adj = advice.get("confidence_adjustment", 1.0)
                        except Exception as exc:
                            log.warning("Memory advisory failed for %s: %s", symbol, exc)

                    expected_move_pct = 0.08  # short soft target: price * (1 - 0.08)
                    if not clears_fee_hurdle(expected_move_pct, TAKER_FEE, SLIPPAGE_BUFFER):
                        console.print(
                            f"  Skipping {symbol} -- fee_gate_skip "
                            f"move={expected_move_pct:.4f} hurdle={2*TAKER_FEE+SLIPPAGE_BUFFER:.4f}"
                        )
                        continue

                    if thresholds is not None and LEARNING_ENFORCE:
                        eff_max = min(MAX_POSITION_PCT, thresholds["max_position_pct"])
                        eff_min = thresholds["min_position_pct"]
                    else:
                        eff_max = MAX_POSITION_PCT
                        eff_min = None

                    # Kelly sizing for short (same formula, different side)
                    sizing = _kelly_technical(
                        confluence=signal.short_score,
                        current_price=price,
                        bankroll=bankroll,
                        kelly_fraction=config.kelly_fraction,
                        max_position_pct=eff_max,
                        confidence_adjustment=adj,
                        min_position_pct=eff_min,
                    )
                    if sizing["dollar_amount"] <= 0:
                        continue

                    qty = sizing["shares"]
                    if qty <= 0:
                        continue

                    # Place short order (sell without holding)
                    console.print(
                        f"  [bold magenta]SHORT[/bold magenta] {symbol}: "
                        f"short_score={signal.short_score} rsi={signal.rsi_value:.0f} "
                        f"trend_4h={signal.trend_4h} qty={qty:.4f} @ ${price:.2f}"
                    )
                    order = alpaca.place_market_order(symbol, qty, side="sell")

                    # Log to trade DB with side="sell"
                    trade_id = logger.log_alpaca_trade({
                        "symbol": symbol,
                        "asset_class": "crypto",
                        "side": "sell",
                        "qty": qty,
                        "entry_price": price,
                        "mirofish_prob": signal.short_score / 4.0,
                        "market_sentiment": f"short_technical_{signal.short_score}",
                        "target_price": price * (1 - 0.08),  # soft take-profit at 8% down
                        "stop_loss": price * (1 + abs(HARD_STOP_PCT)),
                        "simulation_id": f"short_{symbol}_{int(time.time())}",
                        "notes": (
                            f"SHORT short_score={signal.short_score} "
                            f"RSI={signal.rsi_value:.0f} trend_4h={signal.trend_4h}"
                        ),
                    })
                    trades_placed += 1
                    total_trades += 1
                    cycle_exposure += sizing["dollar_amount"]
                    bankroll -= sizing["dollar_amount"]

                    console.print(
                        f"    [green]Short order placed:[/green] {order.get('order_id', 'N/A')} "
                        f"-- status: {order.get('status', 'submitted')}"
                    )

                    # Record to learning system (canonical technical_short_ signal_type)
                    if memory is not None and trade_id:
                        try:
                            memory.record_trade_context({
                                "trade_id": trade_id,
                                "symbol": symbol,
                                "signal_type": signal_type,
                                "sentiment": signal.short_score / 4.0,
                                "confidence": signal.short_score / 4.0,
                                "price_at_entry": price,
                                "price_change_24h": change_pct,
                                "volume_24h": volume_24h,
                                "trajectory": "down" if not signal.ema_bullish else "mixed",
                            })
                        except Exception as exc:
                            log.warning("Failed to record short trade context for %s: %s", symbol, exc)

                except Exception as exc:
                    log.error("Short entry failed for %s: %s", symbol, exc)
                    continue

        # -- 4e. Cycle summary ------------------------------------------------
        open_positions = logger.get_open_alpaca_positions()
        equity = alpaca.get_account()["equity"]
        _cycle_summary(
            cycle_count=cycle_count,
            assets_scanned=len(universe),
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
        f"[bold cyan]ALPACA PAPER TRADING REPORT (v2 — Technical + deterministic exits)[/bold cyan]\n"
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
    signals = scan_assets(alpaca, TOP_CRYPTO_TICKERS, timeframe="1Hour", bar_count=50, profile=PROFILE)

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
        description="Alpaca Technical trading bot (deterministic risk gate + ATR exits)",
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
        try:
            main(mode=args.mode, max_trades=args.max_trades)
        except KeyboardInterrupt:
            console.print("\n[yellow]Bot stopped by user[/yellow]")
        except Exception as exc:
            console.print(f"\n[bold red]Bot crashed: {exc}[/bold red]")
            log.exception("Bot crashed")
            alert_bot_crash(exc)
            sys.exit(1)
