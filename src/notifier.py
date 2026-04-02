"""
Email notifications for the trading bot via AWS SES.

Sends alerts for: bot crashes, unhandled exceptions, drawdown stops,
position monitor failures, and daily summaries.
"""

import json
import logging
import traceback
from pathlib import Path

log = logging.getLogger(__name__)

SECRETS_PATH = Path.home() / ".claude" / "secrets" / "services.json"
SENDER = "alerts@emails4agents.com"
RECIPIENT = "articulatedesigns@gmail.com"


def _get_ses_client():
    """Create a boto3 SES client from secrets."""
    import boto3
    with open(SECRETS_PATH) as f:
        aws = json.load(f)["aws"]
    return boto3.client(
        "ses",
        region_name=aws["ses_region"],
        aws_access_key_id=aws["access_key_id"],
        aws_secret_access_key=aws["secret_access_key"],
    )


def send_alert(subject: str, body: str) -> bool:
    """Send an alert email. Returns True on success, False on failure.

    Never raises — errors are logged but swallowed so alerts don't crash the bot.
    """
    try:
        ses = _get_ses_client()
        ses.send_email(
            Source=SENDER,
            Destination={"ToAddresses": [RECIPIENT]},
            Message={
                "Subject": {"Data": f"[AI Predicted Wins] {subject}"},
                "Body": {"Text": {"Data": body}},
            },
        )
        log.info("Alert email sent: %s", subject)
        return True
    except Exception as exc:
        log.error("Failed to send alert email: %s", exc)
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
    return send_alert("BOT CRASHED", body)


def alert_drawdown_stop(daily_pnl: float, limit: float, bankroll: float) -> bool:
    """Alert that the daily drawdown stop was triggered."""
    body = (
        f"Daily drawdown stop triggered.\n\n"
        f"Daily P&L: ${daily_pnl:+,.2f}\n"
        f"Limit: -${abs(limit):,.2f}\n"
        f"Bankroll: ${bankroll:,.2f}\n\n"
        f"The bot is pausing for 1 hour before resuming."
    )
    return send_alert("DRAWDOWN STOP", body)


def alert_monitor_error(symbol: str, error: Exception) -> bool:
    """Alert that the position monitor hit an error."""
    body = (
        f"Position monitor error for {symbol}.\n\n"
        f"Error: {error}\n\n"
        f"The position may not be monitored correctly."
    )
    return send_alert(f"Monitor error: {symbol}", body)


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
    return send_alert(f"Position closed: {symbol} ${pnl:+,.2f}", body)


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
    return send_alert("Daily Summary", body)
