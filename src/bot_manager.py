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

_WATCHDOG_INTERVAL = 60  # seconds between dead-thread checks


class BotManager:
    """Owns all running BotThread instances.

    Usage (FastAPI lifespan):
        manager = BotManager(db_url)
        manager.start_all()
        yield  # app runs
        manager.stop_all()

    A background watchdog thread restarts any enabled bot whose thread has died,
    so bots always come back after crashes or container restarts.
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
        log.info("BotManager: watchdog started (interval=%ds)", _WATCHDOG_INTERVAL)

    def _watchdog_loop(self) -> None:
        """Periodically restart any enabled bot whose thread has died."""
        while not self._stopping.wait(_WATCHDOG_INTERVAL):
            try:
                self._revive_dead_bots()
            except Exception as exc:
                log.warning("BotManager watchdog error: %s", exc)

    def _revive_dead_bots(self) -> None:
        """Check each enabled bot — restart thread if dead."""
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
                    log.warning(
                        "BotManager: bot %s thread dead — restarting", bot_id
                    )
                    try:
                        cfg = BotConfig.from_row(row)
                        self._spawn(cfg)
                    except Exception as exc:
                        log.error("Failed to revive bot %s: %s", bot_id, exc)

    def stop_all(self) -> None:
        """Stop watchdog and all bot threads (called from FastAPI lifespan on shutdown)."""
        self._stopping.set()  # signal watchdog to exit
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
