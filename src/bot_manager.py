# src/bot_manager.py
"""BotManager — manages N BotThread instances from FastAPI lifespan."""

import logging
import os
import threading
import time
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

from src.bot_config import BotConfig
from src.bot_thread import BotThread

log = logging.getLogger(__name__)

_WATCHDOG_INTERVAL = 60          # seconds between dead-thread checks
_DEATH_ALERT_COOLDOWN = 3600     # only alert once per hour per bot re-death
_SILENCE_HOURS = int(os.environ.get("TRADE_SILENCE_ALERT_HOURS", "24"))
_SILENCE_CHECK_INTERVAL = 3600   # check for trade silence once per hour


class BotManager:
    """Owns all running BotThread instances.

    Usage (FastAPI lifespan):
        manager = BotManager(db_url)
        manager.start_all()
        yield  # app runs
        manager.stop_all()

    A background watchdog thread restarts any enabled bot whose thread has died,
    so bots always come back after crashes or container restarts.

    Email alerts (via AWS SES / emails4agents.com) are sent when:
      - A bot thread is found dead and restarted (max once/hour per bot)
      - No trades have been placed in TRADE_SILENCE_ALERT_HOURS (default 24h)
    """

    def __init__(self, db_url: str):
        self._db_url = db_url
        self._threads: dict[str, BotThread] = {}
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._pool = ConnectionPool(
            conninfo=db_url,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row},
            open=True,
        )
        # Track last death-alert time per bot to avoid spam
        self._last_death_alert: dict[str, float] = {}
        # Track last silence-alert time (single global timer)
        self._last_silence_alert: float = 0.0
        self._last_silence_check: float = 0.0

        self._watchdog = threading.Thread(
            target=self._watchdog_loop,
            name="bot-watchdog",
            daemon=True,
        )

    def start_all(self) -> None:
        """Read enabled bots from DB, spawn threads, and start the watchdog."""
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM bots WHERE enabled = TRUE "
                "AND alpaca_api_key IS NOT NULL AND alpaca_api_key != ''"
            ).fetchall()
        log.info("BotManager: starting %d enabled bots", len(rows))
        with self._lock:
            for row in rows:
                try:
                    cfg = BotConfig.from_row(row)
                    self._spawn(cfg)
                except Exception as exc:
                    log.error("Failed to start bot %s: %s", row.get("bot_id"), exc)
        self._watchdog.start()
        log.info(
            "BotManager: watchdog started (interval=%ds, silence_alert=%dh)",
            _WATCHDOG_INTERVAL, _SILENCE_HOURS,
        )

    def _watchdog_loop(self) -> None:
        """Periodically restart dead bots and check for trade silence."""
        while not self._stopping.wait(_WATCHDOG_INTERVAL):
            try:
                self._revive_dead_bots()
            except Exception as exc:
                log.warning("BotManager watchdog (revive) error: %s", exc)
            try:
                self._check_trade_silence()
            except Exception as exc:
                log.warning("BotManager watchdog (silence) error: %s", exc)

    # ------------------------------------------------------------------
    # Dead-bot revival
    # ------------------------------------------------------------------

    def _revive_dead_bots(self) -> None:
        """Check each enabled bot — restart thread if dead, alert if needed."""
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM bots WHERE enabled = TRUE "
                "AND alpaca_api_key IS NOT NULL AND alpaca_api_key != ''"
            ).fetchall()
        with self._lock:
            for row in rows:
                bot_id = row.get("bot_id", "")
                thread = self._threads.get(bot_id)
                if thread is None or not thread.is_alive():
                    log.warning("BotManager: bot %s thread dead — restarting", bot_id)
                    self._maybe_send_death_alert(bot_id, row)
                    try:
                        cfg = BotConfig.from_row(row)
                        self._spawn(cfg)
                    except Exception as exc:
                        log.error("Failed to revive bot %s: %s", bot_id, exc)

    def _maybe_send_death_alert(self, bot_id: str, row: dict) -> None:
        """Send a bot-death alert email — at most once per hour per bot."""
        now = time.time()
        last = self._last_death_alert.get(bot_id, 0.0)
        if now - last < _DEATH_ALERT_COOLDOWN:
            return
        self._last_death_alert[bot_id] = now
        label = row.get("label", bot_id)
        try:
            from src.notifier import send_alert
            send_alert(
                f"Bot {bot_id} thread died — restarting",
                f"Bot {bot_id} ({label}) thread was found dead and is being restarted by the watchdog.\n\n"
                f"Open positions may have been unmonitored briefly. The bot will resume scanning "
                f"within one cycle (~30 minutes).\n\n"
                f"If this alert repeats frequently, check the container logs for root cause.",
            )
        except Exception as exc:
            log.warning("Failed to send death alert for bot %s: %s", bot_id, exc)

    # ------------------------------------------------------------------
    # Trade-silence check
    # ------------------------------------------------------------------

    def _check_trade_silence(self) -> None:
        """Alert if no trades have been placed in TRADE_SILENCE_ALERT_HOURS."""
        now = time.time()
        # Only run this check once per hour
        if now - self._last_silence_check < _SILENCE_CHECK_INTERVAL:
            return
        self._last_silence_check = now

        # Only alert once per silence window
        if now - self._last_silence_alert < _SILENCE_HOURS * 3600:
            return

        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    "SELECT MAX(timestamp) AS last_trade FROM alpaca_trades"
                ).fetchone()
        except Exception as exc:
            log.warning("Trade silence check DB error: %s", exc)
            return

        last_trade_ts = row["last_trade"] if row else None

        if last_trade_ts is None:
            # No trades ever — don't alert (fresh deployment)
            return

        # psycopg3 returns a datetime; calculate age in hours
        import datetime as dt
        if hasattr(last_trade_ts, "tzinfo") and last_trade_ts.tzinfo is None:
            last_trade_ts = last_trade_ts.replace(tzinfo=dt.timezone.utc)
        now_dt = dt.datetime.now(dt.timezone.utc)
        hours_since = (now_dt - last_trade_ts).total_seconds() / 3600

        if hours_since < _SILENCE_HOURS:
            return

        # Check at least one bot is running — silence expected if all bots are down
        with self._lock:
            any_alive = any(t.is_alive() for t in self._threads.values())
        if not any_alive:
            return  # bots are down; death alert handles that separately

        self._last_silence_alert = now
        log.warning(
            "Trade silence: no trades in %.1f hours — sending alert", hours_since
        )
        try:
            from src.notifier import send_alert
            send_alert(
                f"No trades in {hours_since:.0f}h — possible signal drought or issue",
                f"No trades have been placed in the last {hours_since:.0f} hours "
                f"(threshold: {_SILENCE_HOURS}h).\n\n"
                f"Last trade: {last_trade_ts.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
                f"Possible causes:\n"
                f"  - Low confluence signals (normal in sideways/quiet markets)\n"
                f"  - Technical scan failing silently\n"
                f"  - Alpaca API connectivity issue\n"
                f"  - RSI ceiling filtering all candidates\n\n"
                f"Both bots are currently running. Check the dashboard for current "
                f"signal scores and bot logs.",
            )
        except Exception as exc:
            log.warning("Failed to send trade silence alert: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def stop_all(self) -> None:
        """Stop watchdog and all bot threads (called from FastAPI lifespan on shutdown)."""
        self._stopping.set()
        with self._lock:
            snapshot = list(self._threads.items())
            self._threads.clear()
        for bot_id, thread in snapshot:
            log.info("BotManager: stopping bot %s", bot_id)
            thread.stop()
        for _, thread in snapshot:
            thread.join(timeout=15)

    def add(self, row: dict) -> None:
        """Spawn a new bot thread from a freshly-inserted DB row."""
        cfg = BotConfig.from_row(row)
        with self._lock:
            self._spawn(cfg)

    def update(self, bot_id: str, row: dict) -> None:
        """Push updated config to live thread. Thread picks it up next cycle."""
        with self._lock:
            thread = self._threads.get(bot_id)
            if thread and thread.is_alive():
                thread.update_config(BotConfig.from_row(row))
            elif row.get("enabled"):
                self._spawn(BotConfig.from_row(row))

    def stop_bot(self, bot_id: str) -> None:
        """Gracefully stop a single bot thread."""
        with self._lock:
            thread = self._threads.pop(bot_id, None)
        if thread:
            thread.stop()
            thread.join(timeout=15)

    def enable_bot(self, bot_id: str, row: dict) -> None:
        """Spawn thread for a previously-disabled bot."""
        with self._lock:
            if bot_id not in self._threads or not self._threads[bot_id].is_alive():
                self._spawn(BotConfig.from_row(row))

    def status(self) -> dict[str, dict]:
        """Return {bot_id: {thread_alive, config_label}} for all tracked threads."""
        with self._lock:
            return {
                bot_id: {
                    "thread_alive": thread.is_alive(),
                    "config_label": thread.config.label,
                }
                for bot_id, thread in self._threads.items()
            }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _spawn(self, cfg: BotConfig) -> None:
        """Start a new BotThread, stopping any existing one first.

        Must be called with self._lock held.
        """
        old = self._threads.get(cfg.bot_id)
        if old and old.is_alive():
            old.stop()
            old.join(timeout=5)
        thread = BotThread(cfg, on_status_change=self._on_status_change)
        self._threads[cfg.bot_id] = thread
        thread.start()
        log.info("BotManager: spawned bot %s (%s)", cfg.bot_id, cfg.label)

    def _on_status_change(self, bot_id: str, status: str, detail: str) -> None:
        """Write status back to DB when thread changes state."""
        try:
            with self._pool.connection() as conn:
                conn.execute(
                    "UPDATE bots SET status = %s, status_detail = %s, updated_at = NOW() "
                    "WHERE bot_id = %s",
                    (status, detail, bot_id),
                )
        except Exception as exc:
            log.warning("Failed to write status for bot %s: %s", bot_id, exc)
