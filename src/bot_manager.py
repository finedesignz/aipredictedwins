# src/bot_manager.py
"""BotManager — manages N BotThread instances from FastAPI lifespan."""

import logging
import os
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

from src.bot_config import BotConfig
from src.bot_thread import BotThread

log = logging.getLogger(__name__)


class BotManager:
    """Owns all running BotThread instances.

    Usage (FastAPI lifespan):
        manager = BotManager(db_url)
        manager.start_all()
        yield  # app runs
        manager.stop_all()
    """

    def __init__(self, db_url: str):
        self._db_url = db_url
        self._threads: dict[str, BotThread] = {}
        self._pool = ConnectionPool(
            conninfo=db_url,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row},
            open=True,
        )

    def start_all(self) -> None:
        """Read enabled bots from DB and spawn threads."""
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM bots WHERE enabled = TRUE "
                "AND alpaca_api_key IS NOT NULL AND alpaca_api_key != ''"
            ).fetchall()
        log.info("BotManager: starting %d enabled bots", len(rows))
        for row in rows:
            try:
                cfg = BotConfig.from_row(row)
                self._spawn(cfg)
            except Exception as exc:
                log.error("Failed to start bot %s: %s", row.get("bot_id"), exc)

    def stop_all(self) -> None:
        """Stop all threads (called from FastAPI lifespan on shutdown)."""
        for bot_id, thread in list(self._threads.items()):
            log.info("BotManager: stopping bot %s", bot_id)
            thread.stop()
        for thread in self._threads.values():
            thread.join(timeout=15)
        self._threads.clear()

    def add(self, row: dict) -> None:
        """Spawn a new bot thread from a freshly-inserted DB row."""
        cfg = BotConfig.from_row(row)
        self._spawn(cfg)

    def update(self, bot_id: str, row: dict) -> None:
        """Push updated config to live thread. Thread picks it up next cycle."""
        thread = self._threads.get(bot_id)
        if thread and thread.is_alive():
            thread.update_config(BotConfig.from_row(row))
        elif row.get("enabled"):
            self._spawn(BotConfig.from_row(row))

    def stop_bot(self, bot_id: str) -> None:
        """Gracefully stop a single bot thread."""
        thread = self._threads.pop(bot_id, None)
        if thread:
            thread.stop()
            thread.join(timeout=15)

    def enable_bot(self, bot_id: str, row: dict) -> None:
        """Spawn thread for a previously-disabled bot."""
        if bot_id not in self._threads or not self._threads[bot_id].is_alive():
            self._spawn(BotConfig.from_row(row))

    def status(self) -> dict[str, dict]:
        """Return {bot_id: {thread_alive, config_label}} for all tracked threads."""
        return {
            bot_id: {
                "thread_alive": thread.is_alive(),
                "config_label": thread.config.label,
            }
            for bot_id, thread in self._threads.items()
        }

    def _spawn(self, cfg: BotConfig) -> None:
        """Start a new BotThread, stopping any existing one first."""
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
