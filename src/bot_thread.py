# src/bot_thread.py
"""BotThread — isolated per-bot scan/monitor loop with atomic config swap.

Each BotThread owns its own AlpacaClient, TradeLogger, RulesGate,
and PositionMonitor. Config is held as an atomic reference so it can be
hot-swapped (via update_config) without restarting the thread.
"""

import datetime
import logging
import os
import threading
import time
from typing import Callable
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")


def _market_is_open() -> bool:
    """Return True if US equity markets are currently open (9:30–16:00 ET, Mon–Fri)."""
    now = datetime.datetime.now(_ET)
    if now.weekday() >= 5:
        return False
    open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= now < close_t


def _seconds_until_market_open() -> float:
    """Return seconds until next US market open (9:30 ET, Mon–Fri)."""
    now = datetime.datetime.now(_ET)
    candidate = now.replace(hour=9, minute=29, second=0, microsecond=0)
    if candidate <= now:
        candidate += datetime.timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += datetime.timedelta(days=1)
    return max(60.0, (candidate - now).total_seconds())


def _seconds_until_tradingagents_run() -> float:
    """Return seconds until the next TradingAgents daily run (16:30 ET, Mon–Fri).

    Runs 30 minutes after the US equity close so end-of-day data is available.
    Skips weekends.
    """
    now = datetime.datetime.now(_ET)
    candidate = now.replace(hour=16, minute=30, second=0, microsecond=0)
    if candidate <= now:
        candidate += datetime.timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += datetime.timedelta(days=1)
    return max(60.0, (candidate - now).total_seconds())

from src.bot_config import BotConfig
from src.config import Config
from src.alpaca_client import AlpacaClient
from src.trade_logger import TradeLogger
from src.rules_gate import RulesGate
from src.exit_advisor import HARD_STOP_PCT, SOFT_STOP_PCT, SOFT_TAKE_PROFIT_PCT
from src.fee_gate import clears_fee_hurdle, TAKER_FEE, SLIPPAGE_BUFFER
from src.technical_signals import scan_assets, bear_fraction
from src.strategy_profile import PROFILES, SWING
from src.alpaca_orchestrator import (
    PositionMonitor,
    _kelly_technical,
    _select_cycle_candidates,
    MAX_TOTAL_EXPOSURE_PCT,
    DRAWDOWN_STOP_PCT,
    CYCLE_SLEEP_SECONDS,
    BEAR_MARKET_PAUSE_THRESHOLD,
    _ALPACA_UNTRADEABLE,
)
from src.signal_validator import SignalValidator
from src.alpaca_evaluator import MEME_CRYPTO, get_dynamic_crypto_universe
from src.pipeline_state import PipelineState
from src import db as _db

try:
    from src.trade_memory import TradeMemory
    from src.trade_memory import should_enforce_learning
    from src.learning_loop import LearningLoop
    _HAS_LEARNING = True
except ImportError:
    _HAS_LEARNING = False

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_alpaca_config(bot_cfg: BotConfig) -> Config:
    """Build a Config from BotConfig — no env var reads."""
    return Config(
        alpaca_api_key=bot_cfg.alpaca_api_key,
        alpaca_secret_key=bot_cfg.alpaca_secret_key,
        alpaca_env="paper",
        kelly_fraction=bot_cfg.kelly_fraction,
        max_position_pct=bot_cfg.max_position_pct,
    )


def select_long_candidates(signals, cfg, open_symbols, recent_loss_symbols):
    """Filter signals to bullish long candidates for one cycle.

    Bullish confluence, not already open / recently stopped out, tradeable,
    RSI not overextended (``< cfg.rsi_ceiling``), not bearish on 4H.

    Broad-bear pause is applied by the caller (it suppresses ALL longs); this
    predicate is the per-signal long filter shared by the live loop and tests.
    """
    return _select_cycle_candidates([
        s for s in signals
        if s.confluence_score >= cfg.min_confluence
        and s.symbol not in open_symbols
        and s.symbol not in recent_loss_symbols
        and s.symbol not in MEME_CRYPTO
        and s.symbol not in _ALPACA_UNTRADEABLE
        and s.rsi_value < cfg.rsi_ceiling
        and getattr(s, "trend_4h", "unknown") != "bearish"
    ])


def select_short_candidates(signals, cfg, open_symbols, recent_loss_symbols):
    """Filter signals to bearish short candidates for one cycle."""
    short_enabled = getattr(cfg, "short_enabled", True)
    if not short_enabled:
        return []
    min_short = getattr(cfg, "min_short_confluence", 3)
    return _select_cycle_candidates([
        s for s in signals
        if getattr(s, "short_score", 0) >= min_short
        and s.symbol not in open_symbols
        and s.symbol not in recent_loss_symbols
        and s.symbol not in MEME_CRYPTO
        and s.symbol not in _ALPACA_UNTRADEABLE
        and getattr(s, "trend_4h", "unknown") != "bullish"
    ])


# ---------------------------------------------------------------------------
# BotThread
# ---------------------------------------------------------------------------

class BotThread(threading.Thread):
    """A single bot's scan/monitor loop running in its own thread.

    Config can be hot-swapped atomically via update_config() while the loop
    is running — each cycle re-reads the config reference under a lock.

    Parameters
    ----------
    config : BotConfig
        Initial per-bot configuration snapshot.
    on_status_change : Callable[[str, str, str], None]
        Callback invoked as ``on_status_change(bot_id, status, detail)``
        whenever the thread's status changes. Typically writes to the DB.
    """

    def __init__(
        self,
        config: BotConfig,
        on_status_change: Callable[[str, str, str], None] | None = None,
    ):
        super().__init__(
            daemon=True,
            name=f"bot-{config.bot_id}",
        )
        self._config_lock = threading.Lock()
        self._config: BotConfig = config
        self._on_status_change = on_status_change or (lambda bot_id, status, detail: None)
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def bot_id(self) -> str:
        return self._config.bot_id

    @property
    def config(self) -> BotConfig:
        """Thread-safe read of the current config snapshot."""
        with self._config_lock:
            return self._config

    def update_config(self, new_config: BotConfig) -> None:
        """Atomically replace the config. Takes effect on next cycle."""
        with self._config_lock:
            self._config = new_config
        log.info("[bot:%s] Config updated — takes effect next cycle", new_config.bot_id)

    def stop(self) -> None:
        """Signal the thread to stop gracefully after the current cycle."""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_status(self, status: str, detail: str) -> None:
        try:
            self._on_status_change(self.bot_id, status, detail)
        except Exception as exc:
            log.warning("[bot:%s] on_status_change raised: %s", self.bot_id, exc)

    # ------------------------------------------------------------------
    # Thread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        bot_id = self.bot_id
        log.info("[bot:%s] Thread starting", bot_id)
        self._set_status("running", "")

        try:
            self._main_loop()
        except Exception as exc:
            log.exception("[bot:%s] Unhandled exception in run()", bot_id)
            self._set_status("error", str(exc))
            return

        self._set_status("stopped", "")
        log.info("[bot:%s] Thread stopped cleanly", bot_id)

    def _main_loop(self) -> None:
        cfg = self.config
        bot_id = cfg.bot_id

        # -- Build per-bot components ------------------------------------------
        alpaca_cfg = _make_alpaca_config(cfg)
        alpaca = AlpacaClient(alpaca_cfg)
        logger = TradeLogger(bot_id=bot_id)
        risk_gate = RulesGate()

        # -- Build learning components -----------------------------------------
        memory = None
        learning_loop = None
        if _HAS_LEARNING:
            try:
                memory = TradeMemory(bot_id=bot_id)
                learning_loop = LearningLoop(memory=memory, logger=logger)
                log.info("[bot:%s] Learning loop initialised", bot_id)
            except Exception as exc:
                log.warning("[bot:%s] Could not init learning loop: %s", bot_id, exc)
                memory = None
                learning_loop = None

        # -- Resolve asset universe -----------------------------------------------
        if cfg.asset_class == "stock":
            universe = list(cfg.symbols)
            log.info("[bot:%s] Stock universe: %d symbols", bot_id, len(universe))
        else:
            top_n = getattr(cfg, "dynamic_universe_size", 20)
            try:
                universe = get_dynamic_crypto_universe(alpaca, top_n=top_n)
                log.info("[bot:%s] Dynamic universe: %d symbols", bot_id, len(universe))
            except Exception as exc:
                log.warning("[bot:%s] Dynamic universe fetch failed (%s), using static list", bot_id, exc)
                universe = list(cfg.symbols)

        # -- Start position monitor --------------------------------------------
        _monitor_profile = PROFILES.get(os.environ.get("BOT_PROFILE", "swing").lower(), SWING)
        monitor = PositionMonitor(alpaca, logger, _monitor_profile)
        monitor.start()
        log.info("[bot:%s] Position monitor started", bot_id)

        try:
            self._scan_loop(cfg, alpaca, logger, risk_gate, alpaca_cfg, memory, learning_loop, universe)
        finally:
            # Always shut down the monitor cleanly
            monitor.stop()
            monitor.join(timeout=10)
            log.info(
                "[bot:%s] Position monitor stopped (checks=%d, closes=%d, pnl=$%.2f)",
                bot_id,
                monitor.checks,
                monitor.closes,
                monitor.total_pnl,
            )

    def _scan_loop(
        self,
        initial_cfg: BotConfig,
        alpaca: AlpacaClient,
        logger: TradeLogger,
        risk_gate: RulesGate,
        alpaca_cfg: Config,
        memory=None,
        learning_loop=None,
        universe: list | None = None,
    ) -> None:
        """Inner scan/sleep loop — re-reads config each cycle."""
        bot_id = initial_cfg.bot_id

        # Get initial bankroll
        account = alpaca.get_account()
        starting_bankroll = account.get("equity", 100_000.0)

        cycle_count = 0

        while not self._stop_event.is_set():
            # Re-read config atomically at the top of each cycle
            cfg = self.config
            cycle_count += 1

            # TradingAgents bots run once daily 30 min after close — never during the day.
            if getattr(cfg, "strategy", "confluence") == "tradingagents":
                sleep_secs = _seconds_until_tradingagents_run()
                log.info(
                    "[bot:%s] TradingAgents — sleeping %.0fs (%.1fh) until next daily run",
                    bot_id, sleep_secs, sleep_secs / 3600,
                )
                self._stop_event.wait(sleep_secs)
                if self._stop_event.is_set():
                    break
                try:
                    self._run_cycle(self.config, alpaca, logger, risk_gate, starting_bankroll,
                                    cycle_count + 1, memory, learning_loop, universe)
                except Exception as exc:
                    log.exception("[bot:%s] TradingAgents cycle failed: %s", bot_id, exc)
                cycle_count += 1
                continue

            # Stock bots: skip entirely when markets are closed, sleep until near open
            if cfg.asset_class == "stock" and not _market_is_open():
                sleep_secs = _seconds_until_market_open()
                log.debug("[bot:%s] Market closed — sleeping %.0fs until open", bot_id, sleep_secs)
                self._stop_event.wait(sleep_secs)
                continue

            log.info("[bot:%s] Cycle %d starting", bot_id, cycle_count)

            try:
                effective_universe = list(cfg.symbols) if cfg.asset_class == "stock" else (universe or list(cfg.symbols))
                self._run_cycle(cfg, alpaca, logger, risk_gate, starting_bankroll, cycle_count, memory, learning_loop, effective_universe)
            except Exception as exc:
                log.exception("[bot:%s] Cycle %d failed: %s", bot_id, cycle_count, exc)

            # Sleep between cycles, waking early if stop requested
            self._stop_event.wait(CYCLE_SLEEP_SECONDS)

    def _run_cycle(
        self,
        cfg: BotConfig,
        alpaca: AlpacaClient,
        logger: TradeLogger,
        risk_gate: RulesGate,
        starting_bankroll: float,
        cycle_count: int,
        memory=None,
        learning_loop=None,
        universe: list | None = None,
    ) -> None:
        """Execute one full scan → filter → risk-gate → size → order cycle."""
        bot_id = cfg.bot_id

        # -- Strategy branch: trend-follower bypasses confluence pipeline ------
        if getattr(cfg, "strategy", "confluence") == "trend_btc":
            from src.trend_strategy import run_trend_cycle
            try:
                run_trend_cycle(cfg, alpaca, logger)
            except Exception as exc:
                log.exception("[bot:%s] trend cycle error: %s", bot_id, exc)
            return

        # -- Strategy branch: TradingAgents (TauricResearch) auto-trader -------
        if getattr(cfg, "strategy", "confluence") == "tradingagents":
            from src.bot_c.strategy import run_tradingagents_cycle
            try:
                run_tradingagents_cycle(cfg, alpaca, logger)
            except Exception as exc:
                log.exception("[bot:%s] tradingagents cycle error: %s", bot_id, exc)
            return

        # -- Run learning cycle before scanning --------------------------------
        if learning_loop is not None:
            try:
                summary = learning_loop.run_cycle()
                if summary["outcomes_updated"] > 0 or summary["lessons_generated"] > 0:
                    log.info(
                        "[bot:%s] Learning: %d outcomes synced, %d new lessons",
                        bot_id, summary["outcomes_updated"], summary["lessons_generated"],
                    )
            except Exception as exc:
                log.warning("[bot:%s] Learning cycle failed: %s", bot_id, exc)


        # -- Check account state -----------------------------------------------
        account = alpaca.get_account()
        bankroll = account["buying_power"]
        equity = account.get("equity", bankroll)

        open_positions = logger.get_open_alpaca_positions()
        open_symbols = {p.get("symbol") for p in open_positions}

        # 24h re-entry cooldown — don't re-buy what we just got stopped out of.
        try:
            recent_loss_symbols = _db.get_recent_loss_symbols(bot_id, hours=24)
        except Exception as exc:
            log.warning("[bot:%s] recent-loss lookup failed: %s", bot_id, exc)
            recent_loss_symbols = set()

        # Calculate total exposure
        total_exposure = sum(
            float(p.get("entry_price", 0)) * float(p.get("qty", 0))
            for p in open_positions
        )
        exposure_pct = total_exposure / equity if equity > 0 else 1.0

        if exposure_pct >= MAX_TOTAL_EXPOSURE_PCT:
            log.info(
                "[bot:%s] Exposure at %.0f%% (%.2f/%.2f) — skipping scan",
                bot_id, exposure_pct * 100, total_exposure, equity,
            )
            return

        # -- Layer 1: Technical scan -------------------------------------------
        scan_universe = universe or list(cfg.symbols)
        is_stock = cfg.asset_class == "stock"
        log.info("[bot:%s] Layer 1: technical scan (%d %s symbols)", bot_id, len(scan_universe), cfg.asset_class)
        _profile = PROFILES.get(os.environ.get("BOT_PROFILE", "swing").lower(), SWING)
        try:
            signals = scan_assets(alpaca, scan_universe, timeframe="1Hour", bar_count=50, fetch_4h=not is_stock, profile=_profile)
        except Exception as exc:
            log.error("[bot:%s] Technical scan failed: %s", bot_id, exc)
            return

        # Persist scan results to DB so the dashboard signals page shows real data
        try:
            _db.persist_scan_signals(bot_id, signals)
        except Exception as exc:
            log.warning("[bot:%s] Failed to persist scan signals: %s", bot_id, exc)

        # Broad-market bear pause: if most of the universe has EMA=bearish, skip
        # new longs (shorts unaffected). Mirrors the CLI orchestrator path.
        bear_frac = bear_fraction(signals)
        market_is_broadly_bearish = bear_frac >= BEAR_MARKET_PAUSE_THRESHOLD
        if market_is_broadly_bearish:
            log.info(
                "[bot:%s] BROAD BEAR PAUSE: %.0f%% of universe EMA=bearish (>= %.0f%%) — skipping new longs",
                bot_id, bear_frac * 100, BEAR_MARKET_PAUSE_THRESHOLD * 100,
            )

        # Long candidates: bullish confluence, not bearish on 4H, RSI not overextended.
        # Broad-bear pause suppresses the whole long set; the per-signal predicate
        # lives in select_long_candidates (shared with tests).
        long_candidates = [] if market_is_broadly_bearish else select_long_candidates(
            signals, cfg, open_symbols, recent_loss_symbols
        )

        # Short candidates: bearish confluence, not bullish on 4H
        short_candidates = select_short_candidates(
            signals, cfg, open_symbols, recent_loss_symbols
        )

        candidates = long_candidates
        log.info(
            "[bot:%s] %d long / %d short candidates (confluence>=%d, rsi<%.0f, 4H filtered)",
            bot_id, len(long_candidates), len(short_candidates), cfg.min_confluence, cfg.rsi_ceiling,
        )

        if not candidates and not short_candidates:
            log.info("[bot:%s] No candidates this cycle", bot_id)
            return

        # -- Dynamic thresholds computed ONCE per cycle (not per-candidate) ----
        thresholds = memory.get_dynamic_thresholds() if memory is not None else None

        # -- Shadow gate computed ONCE per cycle (Phase 8 / LEARN-06) ----------
        # Replaces the static LEARNING_ENFORCE flag: count-based, with explicit
        # LEARNING_ENFORCE=0 forcing shadow. Avoids N count queries per cycle.
        enforce = should_enforce_learning(memory, bot_id)

        # -- Layer 2+3: Risk gate → size → order (LONG) -----------------------

        # -- Layer 2: Risk gate ------------------------------------------------
        approved_states: list[PipelineState] = []
        side_data: dict[str, dict] = {}

        for signal in candidates:
            symbol = signal.symbol
            try:
                price = alpaca.get_latest_price(symbol)
                bars = alpaca.get_bars(symbol, timeframe="1Hour", limit=24)

                if not bars:
                    log.warning("[bot:%s] Skipping %s — no bar data", bot_id, symbol)
                    continue

                if len(bars) >= 2:
                    open_24h = bars[0]["open"]
                    change_pct = ((price - open_24h) / open_24h * 100) if open_24h > 0 else 0.0
                else:
                    change_pct = 0.0

                volume_24h = sum(b["volume"] for b in bars) if bars else 0

                if cfg.skip_risk_gate:
                    log.info("[bot:%s] APPROVED %s (risk gate disabled)", bot_id, symbol)
                    approved_states.append(PipelineState(symbol=symbol, bars=tuple(bars), signal=signal))
                    side_data[symbol] = {"price": price, "change_pct": change_pct, "volume_24h": volume_24h}
                    continue

                log.info("[bot:%s] Layer 2: risk gate for %s", bot_id, symbol)
                verdict = risk_gate.evaluate(
                    symbol=symbol,
                    price=price,
                    change_pct=change_pct,
                    volume=volume_24h,
                    confluence=signal.confluence_score,
                    bars=bars,
                )

                if verdict.decision == "PROCEED":
                    log.info("[bot:%s] PROCEED %s — %s", bot_id, symbol, verdict.reasoning[:80])
                    approved_states.append(PipelineState(symbol=symbol, bars=tuple(bars), signal=signal))
                    side_data[symbol] = {"price": price, "change_pct": change_pct, "volume_24h": volume_24h}
                else:
                    veto_count = sum(1 for v in verdict.votes.values() if str(v).upper() == "VETO")
                    log.info("[bot:%s] VETO %s (%d/5 analysts) — %s",
                             bot_id, symbol, veto_count, verdict.reasoning[:80])

            except Exception as exc:
                log.exception("[bot:%s] Risk gate error for %s: %s", bot_id, symbol, exc)

        # -- Layer 3: Size and place orders ------------------------------------
        validator = SignalValidator() if getattr(cfg, "tradingagents_enabled", False) else None
        cycle_exposure = 0.0
        for state in approved_states:
            # Re-check exposure before each order
            if equity > 0 and (total_exposure + cycle_exposure) / equity >= MAX_TOTAL_EXPOSURE_PCT:
                log.info(
                    "[bot:%s] Exposure limit (%.0f%%) reached — skipping remaining",
                    bot_id, MAX_TOTAL_EXPOSURE_PCT * 100,
                )
                break

            signal = state.signal
            symbol = signal.symbol
            price = side_data[symbol]["price"]
            change_pct = side_data[symbol]["change_pct"]
            volume_24h = side_data[symbol]["volume_24h"]
            signal_type = f"technical_confluence_{signal.confluence_score}"

            if validator is not None:
                decision, reason = validator.validate(symbol, "long", signal, price, change_pct)
                if decision == "VETO":
                    log.info("[bot:%s] VALIDATOR VETO %s (long): %s", bot_id, symbol, reason)
                    continue

            # -- Memory advisory (layer 3a): consult trade history --------------
            adj = 1.0
            if memory is not None:
                try:
                    advice = memory.get_advice(
                        symbol=symbol,
                        signal_type=signal_type,
                        sentiment=signal.confluence_score / 4.0,
                        price_change=change_pct,
                    )
                    if not advice["should_trade"]:
                        log.info(
                            "[bot:%s] learn_veto %s — %s (WR=%.0f%% over %d trades, enforce=%s)",
                            bot_id, symbol, advice["reasoning"],
                            (advice.get("win_rate_for_pattern") or 0) * 100,
                            advice.get("sample_size", 0), enforce,
                        )
                        if enforce:
                            continue
                        log.info("[bot:%s] learn_shadow: WOULD veto %s", bot_id, symbol)
                    elif enforce:
                        adj = advice.get("confidence_adjustment", 1.0)
                    elif advice.get("confidence_adjustment", 1.0) != 1.0:
                        log.info(
                            "[bot:%s] learn_shadow: WOULD scale ×%.2f %s",
                            bot_id, advice.get("confidence_adjustment", 1.0), symbol,
                        )
                    if advice.get("sample_size", 0) >= 2:
                        log.info("[bot:%s] Memory: %s", bot_id, advice["reasoning"])
                except Exception as exc:
                    log.warning("[bot:%s] Memory advisory failed for %s: %s", bot_id, symbol, exc)

            expected_move_pct = abs(SOFT_TAKE_PROFIT_PCT)
            if not clears_fee_hurdle(expected_move_pct, TAKER_FEE, SLIPPAGE_BUFFER):
                log.info(
                    "[bot:%s] fee_gate_skip %s move=%.4f hurdle=%.4f",
                    bot_id, symbol, expected_move_pct, 2 * TAKER_FEE + SLIPPAGE_BUFFER,
                )
                continue

            if thresholds is not None and enforce:
                eff_max = min(cfg.max_position_pct, thresholds["max_position_pct"])
                eff_min = thresholds["min_position_pct"]
            else:
                eff_max = cfg.max_position_pct
                eff_min = None

            sizing = _kelly_technical(
                confluence=signal.confluence_score,
                current_price=price,
                bankroll=bankroll,
                kelly_fraction=cfg.kelly_fraction,
                max_position_pct=eff_max,
                confidence_adjustment=adj,
                min_position_pct=eff_min,
            )

            if sizing["side"] == "none" or sizing["shares"] <= 0 or sizing["dollar_amount"] < 10:
                log.info("[bot:%s] Skipping %s — position too small", bot_id, symbol)
                continue

            log.info(
                "[bot:%s] Placing BUY %.4f %s @ $%.2f ($%.2f, kelly=%.2f%%, confluence=%d/4 regime=%s%s)",
                bot_id, sizing["shares"], symbol, price, sizing["dollar_amount"],
                sizing["adjusted_pct"] * 100, signal.confluence_score,
                signal.market_regime,
                " CAPPED" if sizing["capped"] else "",
            )

            try:
                order = alpaca.place_market_order(
                    symbol=symbol,
                    qty=sizing["shares"],
                    side="buy",
                )

                trade_id = logger.log_alpaca_trade({
                    "symbol": symbol,
                    "asset_class": cfg.asset_class if cfg.asset_class == "stock" else "crypto",
                    "side": "buy",
                    "qty": sizing["shares"],
                    "entry_price": price,
                    "mirofish_prob": signal.confluence_score / 4.0,
                    "market_sentiment": signal_type,
                    "target_price": price * (1 + SOFT_TAKE_PROFIT_PCT),
                    "stop_loss": price * (1 + HARD_STOP_PCT),
                    "simulation_id": f"tech_{symbol}_{int(time.time())}",
                    "notes": (
                        f"EMA={'bull' if signal.ema_bullish else 'bear'} "
                        f"ADX={signal.adx_value:.0f} RSI={signal.rsi_value:.0f} "
                        f"regime={signal.market_regime} "
                        f"VolSpike={signal.volume_spike} VWAP={'bull' if signal.vwap_bullish else 'bear'} "
                        f"bot={bot_id}"
                    ),
                })

                # -- Record trade context for learning loop ------------------
                if memory is not None and trade_id:
                    try:
                        memory.record_trade_context({
                            "trade_id": trade_id,
                            "symbol": symbol,
                            "signal_type": signal_type,
                            "sentiment": signal.confluence_score / 4.0,
                            "confidence": signal.confluence_score / 4.0,
                            "price_at_entry": price,
                            "price_change_24h": change_pct,
                            "volume_24h": volume_24h,
                            "atr_value": signal.atr_value,
                            "trajectory": "up" if signal.ema_bullish else "mixed",
                            "bull_arguments": [
                                f"EMA_bull={signal.ema_bullish}",
                                f"ADX={signal.adx_value:.1f}",
                                f"regime={signal.market_regime}",
                            ],
                            "bear_arguments": [
                                f"RSI={signal.rsi_value:.1f}",
                                f"VWAP_bull={signal.vwap_bullish}",
                            ],
                        })
                    except Exception as exc:
                        log.warning("[bot:%s] Failed to record trade context: %s", bot_id, exc)

                cycle_exposure += sizing["dollar_amount"]
                bankroll -= sizing["dollar_amount"]

                log.info(
                    "[bot:%s] Order placed: %s — status: %s",
                    bot_id,
                    order.get("order_id", "N/A"),
                    order.get("status", "submitted"),
                )

            except Exception as exc:
                log.exception("[bot:%s] Order placement failed for %s: %s", bot_id, symbol, exc)

        # -- Layer 2+3: Risk gate → size → order (SHORT) ----------------------
        short_approved: list[PipelineState] = []
        short_side_data: dict[str, dict] = {}

        for signal in short_candidates:
            symbol = signal.symbol
            try:
                price = alpaca.get_latest_price(symbol)
                bars = alpaca.get_bars(symbol, timeframe="1Hour", limit=24)

                if not bars:
                    log.warning("[bot:%s] Skipping short %s — no bar data", bot_id, symbol)
                    continue

                change_pct = (
                    ((price - bars[0]["open"]) / bars[0]["open"] * 100)
                    if len(bars) >= 2 and bars[0]["open"] > 0 else 0.0
                )
                volume_24h = sum(b["volume"] for b in bars) if bars else 0

                if cfg.skip_risk_gate:
                    short_approved.append(PipelineState(symbol=symbol, bars=tuple(bars), signal=signal))
                    short_side_data[symbol] = {"price": price, "change_pct": change_pct, "volume_24h": volume_24h}
                    continue

                verdict = risk_gate.evaluate(
                    symbol=symbol,
                    price=price,
                    change_pct=change_pct,
                    volume=volume_24h,
                    confluence=getattr(signal, "short_score", 0),
                    bars=bars,
                )

                if verdict.decision == "PROCEED":
                    log.info("[bot:%s] SHORT PROCEED %s — %s", bot_id, symbol, verdict.reasoning[:80])
                    short_approved.append(PipelineState(symbol=symbol, bars=tuple(bars), signal=signal))
                    short_side_data[symbol] = {"price": price, "change_pct": change_pct, "volume_24h": volume_24h}
                else:
                    log.info("[bot:%s] SHORT VETO %s — %s", bot_id, symbol, verdict.reasoning[:80])

            except Exception as exc:
                log.exception("[bot:%s] Short risk gate error for %s: %s", bot_id, symbol, exc)

        for state in short_approved:
            if equity > 0 and (total_exposure + cycle_exposure) / equity >= MAX_TOTAL_EXPOSURE_PCT:
                log.info("[bot:%s] Exposure limit reached — skipping short orders", bot_id)
                break

            signal = state.signal
            symbol = signal.symbol
            price = short_side_data[symbol]["price"]
            short_score = getattr(signal, "short_score", 0)
            signal_type = f"technical_short_{short_score}"

            if validator is not None:
                decision, reason = validator.validate(symbol, "short", signal, price, short_side_data[symbol]["change_pct"])
                if decision == "VETO":
                    log.info("[bot:%s] VALIDATOR VETO %s (short): %s", bot_id, symbol, reason)
                    continue

            change_pct = short_side_data[symbol]["change_pct"]
            volume_24h = short_side_data[symbol]["volume_24h"]

            # -- Memory advisory (layer 3a): consult trade history --------------
            adj = 1.0
            if memory is not None:
                try:
                    advice = memory.get_advice(
                        symbol=symbol,
                        signal_type=signal_type,
                        sentiment=short_score / 4.0,
                        price_change=change_pct,
                    )
                    if not advice["should_trade"]:
                        log.info(
                            "[bot:%s] learn_veto %s (short) — %s (WR=%.0f%% over %d trades, enforce=%s)",
                            bot_id, symbol, advice["reasoning"],
                            (advice.get("win_rate_for_pattern") or 0) * 100,
                            advice.get("sample_size", 0), enforce,
                        )
                        if enforce:
                            continue
                        log.info("[bot:%s] learn_shadow: WOULD veto %s (short)", bot_id, symbol)
                    elif enforce:
                        adj = advice.get("confidence_adjustment", 1.0)
                    elif advice.get("confidence_adjustment", 1.0) != 1.0:
                        log.info(
                            "[bot:%s] learn_shadow: WOULD scale ×%.2f %s (short)",
                            bot_id, advice.get("confidence_adjustment", 1.0), symbol,
                        )
                    if advice.get("sample_size", 0) >= 2:
                        log.info("[bot:%s] Memory (short): %s", bot_id, advice["reasoning"])
                except Exception as exc:
                    log.warning("[bot:%s] Memory advisory failed for %s: %s", bot_id, symbol, exc)

            expected_move_pct = abs(SOFT_TAKE_PROFIT_PCT)
            if not clears_fee_hurdle(expected_move_pct, TAKER_FEE, SLIPPAGE_BUFFER):
                log.info(
                    "[bot:%s] fee_gate_skip %s move=%.4f hurdle=%.4f",
                    bot_id, symbol, expected_move_pct, 2 * TAKER_FEE + SLIPPAGE_BUFFER,
                )
                continue

            if thresholds is not None and enforce:
                eff_max = min(cfg.max_position_pct, thresholds["max_position_pct"])
                eff_min = thresholds["min_position_pct"]
            else:
                eff_max = cfg.max_position_pct
                eff_min = None

            sizing = _kelly_technical(
                confluence=short_score,
                current_price=price,
                bankroll=bankroll,
                kelly_fraction=cfg.kelly_fraction,
                max_position_pct=eff_max,
                confidence_adjustment=adj,
                min_position_pct=eff_min,
            )

            if sizing["side"] == "none" or sizing["shares"] <= 0 or sizing["dollar_amount"] < 10:
                log.info("[bot:%s] Skipping short %s — position too small", bot_id, symbol)
                continue

            log.info(
                "[bot:%s] Placing SELL (short) %.4f %s @ $%.2f ($%.2f, short_score=%d/4 4H=%s)",
                bot_id, sizing["shares"], symbol, price, sizing["dollar_amount"],
                short_score, getattr(signal, "trend_4h", "?"),
            )

            try:
                order = alpaca.place_market_order(symbol=symbol, qty=sizing["shares"], side="sell")

                trade_id = logger.log_alpaca_trade({
                    "symbol": symbol,
                    "asset_class": cfg.asset_class if cfg.asset_class == "stock" else "crypto",
                    "side": "sell",
                    "qty": sizing["shares"],
                    "entry_price": price,
                    "mirofish_prob": short_score / 4.0,
                    "market_sentiment": signal_type,
                    "target_price": price * (1 - SOFT_TAKE_PROFIT_PCT),
                    "stop_loss": price * (1 - SOFT_STOP_PCT),
                    "simulation_id": f"short_{symbol}_{int(time.time())}",
                    "notes": (
                        f"SHORT EMA={'bear' if not signal.ema_bullish else 'bull'} "
                        f"ADX={signal.adx_value:.0f} RSI={signal.rsi_value:.0f} "
                        f"trend_4h={getattr(signal, 'trend_4h', '?')} "
                        f"bot={bot_id}"
                    ),
                })

                # -- Record trade context for learning loop (SHORT) ----------
                if memory is not None and trade_id:
                    try:
                        memory.record_trade_context({
                            "trade_id": trade_id,
                            "symbol": symbol,
                            "signal_type": signal_type,
                            "sentiment": short_score / 4.0,
                            "confidence": short_score / 4.0,
                            "price_at_entry": price,
                            "price_change_24h": change_pct,
                            "volume_24h": volume_24h,
                            "atr_value": signal.atr_value,
                            "trajectory": "down" if not signal.ema_bullish else "mixed",
                            "bull_arguments": [
                                f"RSI={signal.rsi_value:.1f}",
                            ],
                            "bear_arguments": [
                                f"EMA_bull={signal.ema_bullish}",
                                f"ADX={signal.adx_value:.1f}",
                                f"trend_4h={getattr(signal, 'trend_4h', '?')}",
                            ],
                        })
                    except Exception as exc:
                        log.warning("[bot:%s] Failed to record short trade context: %s", bot_id, exc)

                cycle_exposure += sizing["dollar_amount"]
                bankroll -= sizing["dollar_amount"]

                log.info(
                    "[bot:%s] Short order placed: %s — status: %s",
                    bot_id, order.get("order_id", "N/A"), order.get("status", "submitted"),
                )

            except Exception as exc:
                log.exception("[bot:%s] Short order placement failed for %s: %s", bot_id, symbol, exc)
