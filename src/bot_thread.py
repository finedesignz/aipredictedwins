# src/bot_thread.py
"""BotThread — isolated per-bot scan/monitor loop with atomic config swap.

Each BotThread owns its own AlpacaClient, TradeLogger, ExitAdvisor, RiskGate,
and PositionMonitor. Config is held as an atomic reference so it can be
hot-swapped (via update_config) without restarting the thread.
"""

import logging
import threading
import time
from typing import Callable

from src.bot_config import BotConfig
from src.config import Config
from src.alpaca_client import AlpacaClient
from src.trade_logger import TradeLogger
from src.risk_gate import RiskGate
from src.exit_advisor import ExitAdvisor, HARD_STOP_PCT, SOFT_TAKE_PROFIT_PCT
from src.technical_signals import scan_assets
from src.alpaca_orchestrator import (
    PositionMonitor,
    _kelly_technical,
    _select_cycle_candidates,
    MAX_TOTAL_EXPOSURE_PCT,
    DRAWDOWN_STOP_PCT,
    CYCLE_SLEEP_SECONDS,
)
from src.alpaca_evaluator import MEME_CRYPTO
from src.pipeline_state import PipelineState
from src import db as _db

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
        exit_advisor = ExitAdvisor()
        risk_gate = RiskGate(logger=logger)

        # -- Start position monitor --------------------------------------------
        monitor = PositionMonitor(alpaca, logger, exit_advisor)
        monitor.start()
        log.info("[bot:%s] Position monitor started", bot_id)

        try:
            self._scan_loop(cfg, alpaca, logger, risk_gate, alpaca_cfg)
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
        risk_gate: RiskGate,
        alpaca_cfg: Config,
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
            log.info("[bot:%s] Cycle %d starting", bot_id, cycle_count)

            try:
                self._run_cycle(cfg, alpaca, logger, risk_gate, starting_bankroll, cycle_count)
            except Exception as exc:
                log.exception("[bot:%s] Cycle %d failed: %s", bot_id, cycle_count, exc)
                # Don't crash the thread — log and continue after sleep

            # Sleep between cycles, waking early if stop requested
            self._stop_event.wait(CYCLE_SLEEP_SECONDS)

    def _run_cycle(
        self,
        cfg: BotConfig,
        alpaca: AlpacaClient,
        logger: TradeLogger,
        risk_gate: RiskGate,
        starting_bankroll: float,
        cycle_count: int,
    ) -> None:
        """Execute one full scan → filter → risk-gate → size → order cycle."""
        bot_id = cfg.bot_id

        # -- Check account state -----------------------------------------------
        account = alpaca.get_account()
        bankroll = account["buying_power"]
        equity = account.get("equity", bankroll)

        open_positions = logger.get_open_alpaca_positions()
        open_symbols = {p.get("symbol") for p in open_positions}

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
        log.info("[bot:%s] Layer 1: technical scan (%d symbols)", bot_id, len(cfg.symbols))
        try:
            signals = scan_assets(alpaca, cfg.symbols, timeframe="1Hour", bar_count=50)
        except Exception as exc:
            log.error("[bot:%s] Technical scan failed: %s", bot_id, exc)
            return

        # Persist scan results to DB so the dashboard signals page shows real data
        try:
            _db.persist_scan_signals(bot_id, signals)
        except Exception as exc:
            log.warning("[bot:%s] Failed to persist scan signals: %s", bot_id, exc)

        # Filter: min confluence, dedup open positions, exclude meme coins
        all_candidates = [
            s for s in signals
            if s.confluence_score >= cfg.min_confluence
            and s.symbol not in open_symbols
            and s.symbol not in MEME_CRYPTO
            and s.rsi_value < cfg.rsi_ceiling
        ]

        candidates = _select_cycle_candidates(all_candidates)
        log.info(
            "[bot:%s] %d/%d candidates after filtering (confluence>=%d, rsi<%.0f)",
            bot_id, len(candidates), len(signals), cfg.min_confluence, cfg.rsi_ceiling,
        )

        if not candidates:
            log.info("[bot:%s] No candidates this cycle", bot_id)
            return

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

            sizing = _kelly_technical(
                confluence=signal.confluence_score,
                current_price=price,
                bankroll=bankroll,
                kelly_fraction=cfg.kelly_fraction,
                max_position_pct=cfg.max_position_pct,
            )

            if sizing["side"] == "none" or sizing["shares"] <= 0 or sizing["dollar_amount"] < 10:
                log.info("[bot:%s] Skipping %s — position too small", bot_id, symbol)
                continue

            log.info(
                "[bot:%s] Placing BUY %.4f %s @ $%.2f ($%.2f, kelly=%.2f%%, confluence=%d/5%s)",
                bot_id, sizing["shares"], symbol, price, sizing["dollar_amount"],
                sizing["adjusted_pct"] * 100, signal.confluence_score,
                " CAPPED" if sizing["capped"] else "",
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
                    "target_price": price * (1 + SOFT_TAKE_PROFIT_PCT),
                    "stop_loss": price * (1 + HARD_STOP_PCT),
                    "simulation_id": f"tech_{symbol}_{int(time.time())}",
                    "notes": (
                        f"EMA={'bull' if signal.ema_bullish else 'bear'} "
                        f"ADX={signal.adx_value:.0f} RSI={signal.rsi_value:.0f} "
                        f"VolSpike={signal.volume_spike} VWAP={'bull' if signal.vwap_bullish else 'bear'} "
                        f"bot={bot_id}"
                    ),
                })

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
