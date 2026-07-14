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
from src.copytrade_thread import CopyTraderThread

log = logging.getLogger(__name__)

_WATCHDOG_INTERVAL = 60          # seconds between dead-thread checks
_DEATH_ALERT_COOLDOWN = 3600     # only alert once per hour per bot re-death
_SILENCE_HOURS = int(os.environ.get("TRADE_SILENCE_ALERT_HOURS", "24"))
_SILENCE_CHECK_INTERVAL = 3600   # check for trade silence once per hour
_BOTS_DOWN_COOLDOWN = 3600       # ALL BOTS DOWN repeats hourly until one bot is alive
_MISCONFIG_ALERT_COOLDOWN = 3600  # only alert once per hour per misconfigured bot
_HEARTBEAT_COMPONENT = "bot_manager"
_RECONCILE_INTERVAL_HOURS = float(os.environ.get("RECONCILE_INTERVAL_HOURS", "1"))


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
        # Track last misconfig-alert time per bot (a keyless bot never LIVED — it cannot
        # have "died", so it needs its own cooldown, not the death-alert one). N5.
        self._last_misconfig_alert: dict[str, float] = {}
        # Track last silence-alert time (single global timer)
        self._last_silence_alert: float = 0.0
        self._last_silence_check: float = 0.0
        # ALL BOTS DOWN: reset ONLY when a bot was alive AT SNAPSHOT TIME (see _tick).
        self._last_bots_down_alert: float = 0.0
        # Hourly reconciliation, self-throttled on the tick that already exists.
        self._last_reconcile: float = 0.0

        self._watchdog = threading.Thread(
            target=self._watchdog_loop,
            name="bot-watchdog",
            daemon=True,
        )

    def _enabled_rows(self) -> list[dict]:
        """Every ENABLED bot — **NO KEY PREDICATE**.

        The old query filtered on `alpaca_api_key IS NOT NULL AND alpaca_api_key != ''`,
        in start_all AND (byte-identically) in _revive_dead_bots. A keyless enabled bot was
        therefore INVISIBLE: never spawned, never revived, never alerted, and — because the
        death-alert loop only iterated rows this filter had already removed — never
        mentioned. An enabled bot must always be either RUNNING or LOUDLY BROKEN.
        """
        with self._pool.connection() as conn:
            return conn.execute("SELECT * FROM bots WHERE enabled = TRUE").fetchall()

    @staticmethod
    def _has_keys(row: dict) -> bool:
        """BOTH keys. An api-key-only check is NOT sufficient: bot_config.py:46-47 coerces
        a missing secret to `or ""` (EMPTY IS LEGAL); bot_thread.py:118-126 passes it
        straight into Config with no env reads; and config.py:74-76's frozen dataclass
        defaults its keys to "" and **DOES NOT RAISE**. So a row with an api_key and an
        EMPTY secret would spawn, 401 on its first Alpaca call, exit, and be revived every
        60 seconds FOREVER — the 1h cooldown throttles the EMAIL, not the SPAWN.
        (CLAUDE.md's "empty bare keys fail-clear (raise)" is the ORCHESTRATOR SERVICE's
        config path; it does NOT hold for BotConfig/BotThread.)
        """
        return bool(row.get("alpaca_api_key") and row.get("alpaca_secret_key"))

    def _mark_misconfigured(self, row: dict) -> None:
        """A keyless ENABLED bot: status='error' every tick, one alert per hour, NEVER
        spawned, and NEVER death-alerted (it has no thread; it never lived — N5)."""
        bot_id = row.get("bot_id", "")
        self._on_status_change(bot_id, "error", "missing alpaca keys")
        self._maybe_send_misconfig_alert(bot_id, row)

    def start_all(self) -> None:
        """Read enabled bots from DB, spawn threads, and start the watchdog."""
        rows = self._enabled_rows()
        log.info("BotManager: starting %d enabled bots", len(rows))
        with self._lock:
            for row in rows:
                if not self._has_keys(row):
                    log.error("BotManager: bot %s is enabled but has no Alpaca keys",
                              row.get("bot_id"))
                    self._mark_misconfigured(row)
                    continue
                try:
                    cfg = BotConfig.from_row(row)
                    self._spawn(cfg)
                except Exception as exc:
                    log.error("Failed to start bot %s: %s", row.get("bot_id"), exc)
        self._watchdog.start()

        # A trading system whose alerter is unconfigured is not monitored — and until now
        # nothing would have told you (send_alert swallows every failure).
        try:
            from src.notifier import alerts_configured, last_alert_error
            log.info("BotManager: alert path configured=%s last_error=%s",
                     alerts_configured(), last_alert_error())
        except Exception as exc:  # pragma: no cover - a self-check must never break startup
            log.warning("BotManager: alert path self-check failed: %s", exc)

        log.info(
            "BotManager: watchdog started (interval=%ds, silence_alert=%dh)",
            _WATCHDOG_INTERVAL, _SILENCE_HOURS,
        )

    def _watchdog_loop(self) -> None:
        """Drive one _tick per interval. A raising tick must never kill the loop."""
        while not self._stopping.wait(_WATCHDOG_INTERVAL):
            try:
                self._tick()
            except Exception as exc:  # pragma: no cover - _tick guards every step itself
                log.warning("BotManager watchdog (tick) error: %s", exc)

    def _tick(self) -> None:
        """ONE watchdog iteration. **THE ORDER IS LOAD-BEARING.**

        Liveness is SNAPSHOTTED FIRST, before anything can respawn, and passed to
        _check_bots_down as a PARAMETER. _revive_dead_bots (:117) calls _spawn ->
        thread.start(), so any bot revived in this same tick is `is_alive() == True` by the
        time a later step runs. If liveness were read after the revive — or recomputed
        inside _check_bots_down — then in the DOMINANT failure mode (threads crash-loop
        every cycle on bad keys / a 401 / an unhandled exception in _main_loop) alive > 0
        on EVERY tick and **the ALL BOTS DOWN alert would NEVER FIRE.** That is the same
        silence this phase exists to kill, reintroduced.

        _maybe_reconcile is LAST so a slow or raising reconcile can never delay or suppress
        the alert that matters. Every step gets its OWN try/except.
        """
        with self._lock:
            alive_before = sum(1 for t in self._threads.values() if t.is_alive())

        try:
            enabled = len(self._enabled_rows())
        except Exception as exc:
            log.warning("BotManager tick (enabled count) error: %s", exc)
            enabled = 0

        hours_since_trade = self._hours_since_last_trade()

        for step in (
            lambda: self._check_bots_down(alive_before, enabled, hours_since_trade),
            self._revive_dead_bots,
            self._check_trade_silence,
            self._heartbeat,
            self._maybe_reconcile,
        ):
            try:
                step()
            except Exception as exc:
                log.warning("BotManager tick step error: %s", exc)

    def _check_bots_down(self, alive_before: int, enabled: int,
                         hours_since_trade: float | None) -> None:
        """ALL BOTS DOWN — the loudest alert in the system.

        `alive_before` is a PARAMETER, snapshotted at tick start. This method must NEVER
        re-read thread liveness itself — see _tick's docstring for why doing so would
        silently disable the alert in the dominant failure mode.
        """
        if enabled > 0 and alive_before == 0:
            now = time.time()
            if now - self._last_bots_down_alert < _BOTS_DOWN_COOLDOWN:
                return
            self._last_bots_down_alert = now
            log.error("BotManager: ALL BOTS DOWN — %d enabled, 0 alive", enabled)
            try:
                from src.notifier import alert_all_bots_down
                alert_all_bots_down(enabled, hours_since_trade)
            except Exception as exc:
                log.warning("Failed to send all-bots-down alert: %s", exc)
            return

        # Reset the cooldown ONLY when a bot was alive AT SNAPSHOT TIME — never merely
        # because a revive succeeded later in the tick. Otherwise a crash-looping system
        # resets its cooldown every 60s and "repeats until one is alive" is a lie.
        if alive_before > 0:
            self._last_bots_down_alert = 0.0

    def _maybe_reconcile(self) -> None:
        """Run reconciliation once per RECONCILE_INTERVAL_HOURS, on the tick that already
        exists. NO second thread, NO scheduler, NO cron, NO new container.

        This is the LAST step of _tick: a slow or raising reconcile can never delay or
        suppress the ALL BOTS DOWN alert, which runs FIRST. `reconcile()` guards each bot
        itself (research N1), so one misconfigured bot costs exactly one bot's
        reconciliation.
        """
        now = time.time()
        if now - self._last_reconcile < _RECONCILE_INTERVAL_HOURS * 3600:
            return
        self._last_reconcile = now
        from src import reconciliation
        reconciliation.reconcile()

    def _heartbeat(self) -> None:
        """UPSERT the outside-the-process liveness signal (migration 019).

        Reports POST-revive liveness — the heartbeat is a status report; the ALERT trigger
        is the pre-revive snapshot.
        """
        with self._lock:
            alive = sum(1 for t in self._threads.values() if t.is_alive())
        enabled = len(self._enabled_rows())
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO runtime_heartbeat (component, beat_at, bots_alive, bots_enabled) "
                "VALUES (%s, NOW(), %s, %s) "
                "ON CONFLICT (component) DO UPDATE SET "
                "beat_at = EXCLUDED.beat_at, "
                "bots_alive = EXCLUDED.bots_alive, "
                "bots_enabled = EXCLUDED.bots_enabled",
                (_HEARTBEAT_COMPONENT, alive, enabled),
            )

    # ------------------------------------------------------------------
    # Dead-bot revival
    # ------------------------------------------------------------------

    def _revive_dead_bots(self) -> None:
        """Check each enabled bot — restart thread if dead, alert if needed."""
        rows = self._enabled_rows()
        with self._lock:
            for row in rows:
                bot_id = row.get("bot_id", "")
                # KEYLESS FIRST (research N5). A bot missing EITHER key never lived, so a
                # "thread died" alert about it is a lie — and _spawn must not be reached, or
                # a credential-less bot is respawned every 60 SECONDS FOREVER (the 1h
                # cooldown throttles the EMAIL, not the SPAWN).
                if not self._has_keys(row):
                    self._mark_misconfigured(row)
                    continue
                thread = self._threads.get(bot_id)
                if thread is None or not thread.is_alive():
                    log.warning("BotManager: bot %s thread dead — restarting", bot_id)
                    self._maybe_send_death_alert(bot_id, row)
                    try:
                        cfg = BotConfig.from_row(row)
                        self._spawn(cfg)
                    except Exception as exc:
                        log.error("Failed to revive bot %s: %s", bot_id, exc)

    def _maybe_send_misconfig_alert(self, bot_id: str, row: dict) -> None:
        """Alert that an ENABLED bot cannot start — at most once per hour per bot.

        Its own cooldown dict, separate from the death-alert one: this bot has no thread
        and never had one, so it cannot have died.
        """
        now = time.time()
        last = self._last_misconfig_alert.get(bot_id, 0.0)
        if now - last < _MISCONFIG_ALERT_COOLDOWN:
            return
        self._last_misconfig_alert[bot_id] = now
        try:
            from src.notifier import alert_bot_misconfigured
            alert_bot_misconfigured(bot_id, row.get("label", bot_id), "missing alpaca keys")
        except Exception as exc:
            log.warning("Failed to send misconfig alert for bot %s: %s", bot_id, exc)

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

    def _last_trade_ts(self):
        """The MAX(timestamp) of the trade log as an aware datetime, or None.

        None on a DB error OR on a fresh deployment with no trades — never fabricate a
        number.
        """
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    "SELECT MAX(timestamp) AS last_trade FROM alpaca_trades"
                ).fetchone()
        except Exception as exc:
            log.warning("Trade silence check DB error: %s", exc)
            return None

        ts = row["last_trade"] if row else None
        if ts is None:
            return None

        # psycopg3 may return a datetime or a string depending on column type
        import datetime as dt
        if isinstance(ts, str):
            ts = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if getattr(ts, "tzinfo", None) is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        return ts

    def _hours_since_last_trade(self) -> float | None:
        import datetime as dt
        ts = self._last_trade_ts()
        if ts is None:
            return None
        return (dt.datetime.now(dt.timezone.utc) - ts).total_seconds() / 3600

    def _check_trade_silence(self) -> None:
        """Alert if no trades have been placed in TRADE_SILENCE_ALERT_HOURS.

        PHASE 19 DELETED THE KILLER (the old :186-190). This method used to end by counting
        live threads and RETURNING WITHOUT ALERTING when the count was zero, deferring to a
        death alert that COULD NOT FIRE — that loop only iterated rows the key filter at
        :104-107 had already removed. So the ONLY alert that fires on "nothing is
        happening" disabled itself precisely when nothing was happening for the worst
        possible reason. Trade silence is now evaluated on its OWN merits, and
        all-bots-down is its own, louder, independent alert (_check_bots_down).
        """
        now = time.time()
        # Only run this check once per hour
        if now - self._last_silence_check < _SILENCE_CHECK_INTERVAL:
            return
        self._last_silence_check = now

        # Only alert once per silence window
        if now - self._last_silence_alert < _SILENCE_HOURS * 3600:
            return

        last_trade_ts = self._last_trade_ts()
        if last_trade_ts is None:
            # No trades ever (or a DB error) — don't alert
            return

        import datetime as dt
        hours_since = (
            dt.datetime.now(dt.timezone.utc) - last_trade_ts
        ).total_seconds() / 3600

        if hours_since < _SILENCE_HOURS:
            return

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
                f"  - RSI ceiling filtering all candidates\n"
                f"  - One or more bot threads are dead (see the ALL BOTS DOWN alert)\n\n"
                f"Check the dashboard for current signal scores, bot status, and logs.",
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
        """Start a new bot thread, stopping any existing one first.

        Dispatches on cfg.strategy:
          - 'copytrade' -> CopyTraderThread (ai4trade.ai poll loop)
          - anything else (confluence, trend_btc, ...) -> BotThread

        Must be called with self._lock held.
        """
        old = self._threads.get(cfg.bot_id)
        if old and old.is_alive():
            old.stop()
            old.join(timeout=5)
        if cfg.strategy == "copytrade":
            thread = CopyTraderThread(
                cfg,
                pool=self._pool,
                on_status_change=self._on_status_change,
            )
        else:
            thread = BotThread(cfg, on_status_change=self._on_status_change)
        self._threads[cfg.bot_id] = thread
        thread.start()
        log.info("BotManager: spawned bot %s (%s, strategy=%s)", cfg.bot_id, cfg.label, cfg.strategy)

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
