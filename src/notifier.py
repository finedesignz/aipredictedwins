"""
Email notifications for the trading bot via AWS SES.

Sends alerts for: bot crashes, unhandled exceptions, drawdown stops,
position monitor failures, and daily summaries.
"""

import json
import logging
import os
import threading
import time
import traceback
from pathlib import Path

log = logging.getLogger(__name__)

SECRETS_PATH = Path.home() / ".claude" / "secrets" / "services.json"
SENDER = "alerts@emails4agents.com"
RECIPIENT = "articulatedesigns@gmail.com"
BOT_LABEL = os.environ.get("BOT_LABEL", "Agent A")


def _get_ses_client():
    """Create a boto3 SES client from secrets file or env vars."""
    import boto3

    # Try secrets file first (local dev), fall back to env vars (container)
    if SECRETS_PATH.exists():
        with open(SECRETS_PATH) as f:
            aws = json.load(f)["aws"]
        return boto3.client(
            "ses",
            region_name=aws["ses_region"],
            aws_access_key_id=aws["access_key_id"],
            aws_secret_access_key=aws["secret_access_key"],
        )

    # In container: boto3 picks up AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
    # AWS_DEFAULT_REGION from env automatically
    return boto3.client("ses", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-west-2"))


_last_error: str | None = None

# Injectable clock (tests monkeypatch this instead of sleeping). time.monotonic never
# jumps backward on wall-clock changes, unlike time.time().
_monotonic = time.monotonic

# Default cooldown window for the (category, dedup_key) throttle below. Env-overridable,
# following the same pattern as every other numeric knob in this codebase.
ALERT_COOLDOWN_SECONDS = float(os.environ.get("ALERT_COOLDOWN_SECONDS", "900"))

# Guards _last_alert_sent — multiple bot threads (A/B/C/D position monitors) share this
# process and can call send_alert concurrently.
_cooldown_lock = threading.Lock()
_last_alert_sent: dict[tuple[str, str], float] = {}


# Every category that can be muted. `send_alert`'s default category is GENERAL, so an
# un-categorised caller is muted only by the global kill switch — never by a per-category
# one it does not know it has.
ALERT_CATEGORIES: tuple[str, ...] = (
    "BOTS_DOWN",
    "BOT_DEATH",
    "BOT_MISCONFIGURED",
    "RECONCILIATION",
    "TRADE_SILENCE",
    "MANAGER_NEVER_STARTED",
    "BOT_CRASH",
    "DRAWDOWN",
    "MONITOR_ERROR",
    "POSITION_CLOSED",
    "SUMMARY",
    "GENERAL",
)


def _env_flag(name: str, default: bool = True) -> bool:
    """An env flag that DEFAULTS TO ON. Absence of config must never mute a safety alert."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def alerts_enabled(category: str = "GENERAL") -> bool:
    """May this category's alert EMAIL be sent?

    Precedence: ALERTS_ENABLED=0 mutes everything; otherwise ALERT_<CATEGORY>_ENABLED
    decides. Both default to ON — a missing env var can never silence an alert.

    This gates the SEND, never the DETECT. Callers still run their checks and still log;
    a suppressed alert is logged at WARNING with its full body (see send_alert).
    """
    if not _env_flag("ALERTS_ENABLED"):
        return False
    return _env_flag(f"ALERT_{category.upper()}_ENABLED")


def alerts_suppressed() -> list[str]:
    """The categories whose email is currently muted — surfaced on the health payload.

    Muting is a VISIBLE state, not a hidden one. The dashboard shows what is silent.
    """
    return [c for c in ALERT_CATEGORIES if not alerts_enabled(c)]


def alerts_configured() -> bool:
    """Can this process send an alert AT ALL? Config PRESENCE only — no SES call, no send.

    Mirrors _get_ses_client's resolution order (:27-39) EXACTLY: the secrets file first,
    else boto3 picking up the two AWS env vars. A self-check that disagrees with the code
    that actually sends is worse than no check.

    A trading system whose alerter is unconfigured is not monitored — and today nothing
    would tell you, because send_alert swallows every failure.
    """
    if SECRETS_PATH.exists():
        return True
    return bool(os.environ.get("AWS_ACCESS_KEY_ID")
                and os.environ.get("AWS_SECRET_ACCESS_KEY"))


def last_alert_error() -> str | None:
    """The last exception send_alert swallowed, else None.

    CONFIG PRESENCE != DELIVERY. A valid-LOOKING config still 403s on an unverified SES
    identity or a bad region, and send_alert swallows it — so alerts_configured() alone
    would report a healthy alerter that has never delivered anything.
    """
    return _last_error


def _cooldown_ok(category: str, dedup_key: str) -> bool:
    """True if (category, dedup_key) hasn't alerted within ALERT_COOLDOWN_SECONDS.

    Thread-safe (module-level lock) — records the send timestamp under the same lock so
    two threads racing on the same key can't both slip through.
    """
    key = (category.upper(), dedup_key)
    now = _monotonic()
    with _cooldown_lock:
        last = _last_alert_sent.get(key)
        if last is not None and (now - last) < ALERT_COOLDOWN_SECONDS:
            return False
        _last_alert_sent[key] = now
        return True


def reset_alert_cooldown(category: str, dedup_key: str) -> None:
    """Clear a (category, dedup_key) cooldown entry so the next alert always sends.

    Used on recovery so a later, distinct outage can alert again immediately rather than
    waiting out a cooldown window that started during the prior outage.
    """
    with _cooldown_lock:
        _last_alert_sent.pop((category.upper(), dedup_key), None)


def send_alert(subject: str, body: str, category: str = "GENERAL",
               dedup_key: str | None = None) -> bool:
    """Send an alert email. Returns True on success, False on failure or suppression.

    Never raises — errors are logged but swallowed so alerts don't crash the bot. The
    swallowed exception is RECORDED in _last_error and surfaced by last_alert_error().

    If `category` is muted (see alerts_enabled), NO EMAIL IS SENT — but the alert is
    LOGGED AT WARNING WITH ITS FULL BODY, prefixed `[alert suppressed: <category>]`.
    SUPPRESSION IS NEVER SILENT: an alert that fires, sends nothing, and leaves no trace
    is the same class of lie this milestone exists to kill. The signal always survives in
    the container logs even when the email is off.

    If `dedup_key` is given, repeat alerts for the same (category, dedup_key) within
    ALERT_COOLDOWN_SECONDS are throttled — logged at WARNING with their full body
    (prefixed `[alert throttled: <category>]`), not emailed. Distinct dedup_keys within
    the same category are never collapsed into each other.
    """
    global _last_error
    if not alerts_enabled(category):
        log.warning("[alert suppressed: %s] %s\n\n%s", category.upper(), subject, body)
        return False
    if dedup_key is not None and not _cooldown_ok(category, dedup_key):
        log.warning("[alert throttled: %s] %s\n\n%s", category.upper(), subject, body)
        return False
    try:
        ses = _get_ses_client()
        ses.send_email(
            Source=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            Message={
                "Subject": {"Data": f"[AI Predicted Wins — {BOT_LABEL}] {subject}"},
                "Body": {"Text": {"Data": body}},
            },
        )
        log.info("Alert email sent: %s", subject)
        _last_error = None
        return True
    except Exception as exc:
        log.error("Failed to send alert email: %s", exc)
        _last_error = str(exc)
        return False


def alert_bot_crash(error: Exception, context: str = "") -> bool:
    """Alert that the bot process crashed."""
    tb = traceback.format_exception(type(error), error, error.__traceback__)
    body = (
        f"The Alpaca trading bot has crashed.\n\n"
        f"Context: {context or 'main loop'}\n"
        f"Error: {error}\n\n"
        f"Traceback:\n{''.join(tb)}\n\n"
        f"ACTION REQUIRED: Restart the bot. Open positions may be unmonitored."
    )
    return send_alert("BOT CRASHED", body, category="BOT_CRASH")


def alert_drawdown_stop(daily_pnl: float, limit: float, bankroll: float) -> bool:
    """Alert that the daily drawdown stop was triggered."""
    body = (
        f"Daily drawdown stop triggered.\n\n"
        f"Daily P&L: ${daily_pnl:+,.2f}\n"
        f"Limit: -${abs(limit):,.2f}\n"
        f"Bankroll: ${bankroll:,.2f}\n\n"
        f"The bot is pausing for 1 hour before resuming."
    )
    return send_alert("DRAWDOWN STOP", body, category="DRAWDOWN")


def alert_monitor_error(symbol: str, error: Exception, consecutive_failures: int = 1) -> bool:
    """Alert that the position monitor hit a SUSTAINED error (caller gates on
    consecutive_failures; see PositionMonitor.run in alpaca_orchestrator.py).

    Throttled via dedup_key=symbol so a prolonged outage sends at most one email per
    ALERT_COOLDOWN_SECONDS instead of one every check cycle.
    """
    body = (
        f"Position monitor error for {symbol}.\n\n"
        f"Error: {error}\n"
        f"Consecutive failed cycles: {consecutive_failures}\n\n"
        f"The position may not be monitored correctly."
    )
    return send_alert(f"Monitor error: {symbol}", body, category="MONITOR_ERROR",
                      dedup_key=symbol)


def alert_monitor_recovered(symbol: str, consecutive_failures: int) -> bool:
    """Alert that the position monitor recovered after a sustained outage.

    Sent exactly once per outage (caller only invokes this after a previously-alerted
    failure streak ends in a successful cycle).
    """
    body = (
        f"Position monitor recovered for {symbol}.\n\n"
        f"It had failed {consecutive_failures} consecutive cycles before this recovery."
    )
    ok = send_alert(f"Monitor recovered: {symbol}", body, category="MONITOR_ERROR")
    reset_alert_cooldown("MONITOR_ERROR", symbol)
    return ok


def alert_position_closed(symbol: str, side: str, entry: float, exit_price: float,
                          pnl: float, reason: str) -> bool:
    """Alert when a position is closed by the monitor."""
    pnl_pct = ((exit_price - entry) / entry * 100) if entry > 0 else 0
    body = (
        f"Position closed by monitor.\n\n"
        f"Symbol: {symbol}\n"
        f"Side: {side}\n"
        f"Entry: ${entry:.6f}\n"
        f"Exit: ${exit_price:.6f}\n"
        f"P&L: ${pnl:+,.2f} ({pnl_pct:+.1f}%)\n"
        f"Reason: {reason}"
    )
    return send_alert(f"Position closed: {symbol} ${pnl:+,.2f}", body,
                      category="POSITION_CLOSED")


def alert_reconciliation_breach(bot_id: str, delta: float, tolerance: float,
                                trade_log_pnl: float, alpaca_realized_pnl: float) -> bool:
    """Alert that a bot's trade-log vs Alpaca realized P&L reconciliation breached tolerance."""
    body = (
        f"Reconciliation breach for Bot {bot_id}.\n\n"
        f"Trade-log realized P&L: ${trade_log_pnl:+,.2f}\n"
        f"Alpaca realized P&L:    ${alpaca_realized_pnl:+,.2f}\n"
        f"Delta: ${delta:+,.2f}\n"
        f"Tolerance: ${tolerance:,.2f}\n\n"
        f"The summed trade-log P&L diverges from Alpaca's booked realized P&L "
        f"beyond tolerance. Investigate trade-log accuracy for this bot."
    )
    return send_alert(f"Reconciliation breach: Bot {bot_id}", body,
                      category="RECONCILIATION")


def alert_all_bots_down(bots_enabled: int, hours_since_trade: float | None) -> bool:
    """THE LOUDEST ALERT IN THE SYSTEM (RUN-01).

    All-bots-down was GUARANTEED SILENT before Phase 19: bot_manager.py:186-190 returned
    out of the trade-silence check precisely when no bot was alive, deferring to a death
    alert that could not fire. Four bots stopped and nothing said a word.
    """
    since = (f"{hours_since_trade:.0f} hours ago" if hours_since_trade is not None
             else "unknown")
    body = (
        f"NO BOT THREADS ARE ALIVE.\n\n"
        f"Enabled bots: {bots_enabled}\n"
        f"Last trade: {since}\n\n"
        f"The watchdog is attempting to revive them every 60 seconds. If this alert keeps "
        f"arriving, the revive is failing or the bots are crash-looping — check the "
        f"container logs and the bots' status/status_detail on the dashboard.\n\n"
        f"This alert repeats hourly until at least one bot is alive."
    )
    return send_alert("ALL BOTS DOWN — no bot threads alive", body,
                      category="BOTS_DOWN")


def alert_bot_misconfigured(bot_id: str, label: str, reason: str) -> bool:
    """An ENABLED bot that cannot start. It never lived, so it never 'died' (research N5).

    ``reason`` is the WHOLE detail (the literal "missing alpaca keys") — never a key, a
    key prefix, or any other credential material.
    """
    body = (
        f"Bot {bot_id} ({label}) is ENABLED but cannot start.\n\n"
        f"Reason: {reason}\n\n"
        f"It has been marked status='error' and is NOT being spawned. An enabled bot must "
        f"always be either RUNNING or LOUDLY BROKEN — 'invisible' is not a state we ship.\n\n"
        f"Fix the bot's configuration on the dashboard, then re-enable it."
    )
    return send_alert(f"Bot {bot_id} misconfigured — not trading", body,
                      category="BOT_MISCONFIGURED")


def alert_manager_never_started(error: str) -> bool:
    """Fired from dashboard/api/main.py's lifespan, NOT from BotManager (research N10).

    The watchdog cannot report its own non-existence: bot_manager.py:79 starts it AFTER
    the start_all query that can throw at :67-70.
    """
    body = (
        f"The BotManager never started. NO BOTS ARE RUNNING.\n\n"
        f"Error: {error}\n\n"
        f"The dashboard is still serving in read-only mode, so the container looks healthy "
        f"and no restart policy will fix this. Check DATABASE_URL and the container logs."
    )
    return send_alert("BotManager NEVER STARTED — no bots are running", body,
                      category="MANAGER_NEVER_STARTED")


def alert_cycle_summary(cycle: int, trades_placed: int, positions_closed: int,
                        cycle_pnl: float, total_pnl: float, bankroll: float,
                        open_positions: int) -> bool:
    """Send a daily summary (call once per day, not every cycle)."""
    body = (
        f"Daily trading summary (cycle {cycle}).\n\n"
        f"Trades placed today: {trades_placed}\n"
        f"Positions closed today: {positions_closed}\n"
        f"Today's P&L: ${cycle_pnl:+,.2f}\n"
        f"Total P&L: ${total_pnl:+,.2f}\n"
        f"Bankroll: ${bankroll:,.2f}\n"
        f"Open positions: {open_positions}"
    )
    return send_alert("Daily Summary", body, category="SUMMARY")
