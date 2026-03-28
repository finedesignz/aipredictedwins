"""
Real-time email alerting module for the AI Predicted Wins trading bot.

Uses AWS SES (via boto3) to send alerts on trade events, system errors,
drawdown warnings, and daily summaries. Includes per-event-type rate
limiting to prevent email spam.

All public methods are safe to call from the orchestrator — failures are
logged but never re-raised, so the alerter can never crash the bot.
"""

import logging
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate-limit defaults (seconds between emails of the same event type)
# ---------------------------------------------------------------------------
_DEFAULT_COOLDOWN = 3600        # 1 hour for most events
_CRITICAL_COOLDOWN = 600        # 10 min for critical alerts (allows re-fire)
_TRADE_COOLDOWN = 60            # 1 min between trade notifications


class Alerter:
    """Send email alerts via AWS SES with built-in rate limiting."""

    def __init__(self, config, recipient: str | None = None):
        self.recipient = recipient or getattr(config, "alert_email", "articulatedesigns@gmail.com")
        self.sender = self.recipient  # SES sandbox: sender must be verified
        self._region = getattr(config, "aws_region", "us-east-1")

        # Rate limiter: event_type -> last-sent epoch
        self._last_sent: dict[str, float] = {}

        try:
            self._ses = boto3.client(
                "ses",
                region_name=self._region,
            )
            log.info("Alerter initialised (SES %s -> %s)", self._region, self.recipient)
        except Exception as exc:
            log.warning("Alerter failed to initialise SES client: %s", exc)
            self._ses = None

    # ------------------------------------------------------------------
    # Core send
    # ------------------------------------------------------------------

    def send_alert(
        self,
        subject: str,
        body_html: str,
        priority: str = "info",
        event_type: str | None = None,
    ) -> bool:
        """Send an HTML email via SES.

        Parameters
        ----------
        subject : str
            Email subject line.
        body_html : str
            HTML body content.
        priority : str
            "info", "warning", or "critical" — affects rate-limit window.
        event_type : str | None
            Key for rate limiting. If None, no rate limiting is applied.

        Returns True if the email was sent (or skipped due to rate limit),
        False on error.
        """
        if self._ses is None:
            log.warning("SES client not available — alert dropped: %s", subject)
            return False

        # Rate limiting
        if event_type:
            cooldown = (
                _CRITICAL_COOLDOWN if priority == "critical"
                else _TRADE_COOLDOWN if event_type.startswith("trade_")
                else _DEFAULT_COOLDOWN
            )
            last = self._last_sent.get(event_type, 0)
            if time.time() - last < cooldown:
                log.debug("Rate-limited alert [%s]: %s", event_type, subject)
                return True  # Not an error — just throttled

        # Prefix subject with priority icon
        prefix = {
            "info": "",
            "warning": "[WARNING] ",
            "critical": "[CRITICAL] ",
        }.get(priority, "")

        try:
            self._ses.send_email(
                Source=self.sender,
                Destination={"ToAddresses": [self.recipient]},
                Message={
                    "Subject": {"Data": f"{prefix}{subject}", "Charset": "UTF-8"},
                    "Body": {
                        "Html": {"Data": body_html, "Charset": "UTF-8"},
                    },
                },
            )
            if event_type:
                self._last_sent[event_type] = time.time()
            log.info("Alert sent: %s", subject)
            return True

        except (BotoCoreError, ClientError) as exc:
            log.error("SES send failed: %s — %s", subject, exc)
            return False
        except Exception as exc:
            log.error("Unexpected alert error: %s — %s", subject, exc)
            return False

    # ------------------------------------------------------------------
    # Event-specific helpers (all safe — never raise)
    # ------------------------------------------------------------------

    def trade_placed(self, trade_data: dict) -> None:
        """Alert when a trade is placed.

        Only fires for trades > $5 or if gate decision was ADJUST.
        """
        try:
            dollar = trade_data.get("dollar_amount", 0)
            gate = trade_data.get("gate_decision", "")
            if dollar <= 5.0 and gate != "ADJUST":
                return

            ticker = trade_data.get("kalshi_ticker", "???")
            side = trade_data.get("side", "???").upper()
            contracts = trade_data.get("contracts", 0)
            price_cents = trade_data.get("entry_price_cents", 0)

            subject = f"Trade Placed: {side} {contracts}x {ticker} @ {price_cents}c"
            body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px;">
                <h2 style="color: #2563eb;">Trade Placed</h2>
                <table style="border-collapse: collapse; width: 100%;">
                    <tr><td style="padding: 6px; font-weight: bold;">Ticker</td>
                        <td style="padding: 6px;">{ticker}</td></tr>
                    <tr><td style="padding: 6px; font-weight: bold;">Side</td>
                        <td style="padding: 6px;">{side}</td></tr>
                    <tr><td style="padding: 6px; font-weight: bold;">Contracts</td>
                        <td style="padding: 6px;">{contracts}</td></tr>
                    <tr><td style="padding: 6px; font-weight: bold;">Price</td>
                        <td style="padding: 6px;">{price_cents}c</td></tr>
                    <tr><td style="padding: 6px; font-weight: bold;">Cost</td>
                        <td style="padding: 6px;">${dollar:.2f}</td></tr>
                    <tr><td style="padding: 6px; font-weight: bold;">MiroFish Prob</td>
                        <td style="padding: 6px;">{trade_data.get('mirofish_prob', 0):.1%}</td></tr>
                    <tr><td style="padding: 6px; font-weight: bold;">Gap</td>
                        <td style="padding: 6px;">{trade_data.get('gap', 0):.1%}</td></tr>
                    <tr><td style="padding: 6px; font-weight: bold;">Gate</td>
                        <td style="padding: 6px;">{gate or 'N/A'}</td></tr>
                </table>
            </div>
            """
            self.send_alert(subject, body, priority="info", event_type=f"trade_{ticker}")

        except Exception as exc:
            log.error("Alerter.trade_placed failed: %s", exc)

    def trade_vetoed(self, market: dict, reason: str) -> None:
        """Alert when TradingAgents vetoes a trade."""
        try:
            ticker = market.get("ticker", "???")
            title = market.get("title", market.get("event_title", ""))
            subject = f"Trade Vetoed: {ticker}"
            body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px;">
                <h2 style="color: #f59e0b;">Trade Vetoed</h2>
                <p><strong>Ticker:</strong> {ticker}</p>
                <p><strong>Market:</strong> {title}</p>
                <p><strong>Reason:</strong> {reason}</p>
            </div>
            """
            self.send_alert(subject, body, priority="warning", event_type=f"veto_{ticker}")

        except Exception as exc:
            log.error("Alerter.trade_vetoed failed: %s", exc)

    def drawdown_warning(self, current_pnl: float, threshold: float) -> None:
        """Alert when drawdown approaches or exceeds a threshold."""
        try:
            pct = abs(current_pnl / 1000.0) * 100  # assuming $1000 bankroll
            severity = "critical" if pct >= 15 else "warning"
            subject = f"Drawdown Alert: -${abs(current_pnl):.2f} ({pct:.1f}% of bankroll)"
            body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px;">
                <h2 style="color: {'#dc2626' if severity == 'critical' else '#f59e0b'};">
                    Drawdown {'CRITICAL' if severity == 'critical' else 'Warning'}
                </h2>
                <p><strong>Current P&L:</strong> ${current_pnl:+,.2f}</p>
                <p><strong>Drawdown:</strong> {pct:.1f}%</p>
                <p><strong>Threshold:</strong> {threshold:.0%}</p>
                <p style="color: #dc2626;">
                    {'Bot will halt if drawdown reaches 20%.' if pct < 20 else 'Bot has been halted.'}
                </p>
            </div>
            """
            self.send_alert(subject, body, priority=severity, event_type="drawdown")

        except Exception as exc:
            log.error("Alerter.drawdown_warning failed: %s", exc)

    def system_error(self, component: str, error: str) -> None:
        """Alert on system-level errors (gateway down, MiroFish unreachable, etc.)."""
        try:
            subject = f"System Error: {component}"
            body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px;">
                <h2 style="color: #dc2626;">System Error</h2>
                <p><strong>Component:</strong> {component}</p>
                <p><strong>Error:</strong> <code>{error}</code></p>
                <p><strong>Time:</strong> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            </div>
            """
            self.send_alert(subject, body, priority="critical", event_type=f"error_{component}")

        except Exception as exc:
            log.error("Alerter.system_error failed: %s", exc)

    def position_settled(self, ticker: str, result: str, pnl: float) -> None:
        """Alert when a position settles."""
        try:
            won = pnl > 0
            subject = f"Position Settled: {ticker} — {'WON' if won else 'LOST'} ${pnl:+,.2f}"
            color = "#16a34a" if won else "#dc2626"
            body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px;">
                <h2 style="color: {color};">Position Settled</h2>
                <p><strong>Ticker:</strong> {ticker}</p>
                <p><strong>Result:</strong> {result}</p>
                <p style="font-size: 1.4em; color: {color};"><strong>${pnl:+,.2f}</strong></p>
            </div>
            """
            self.send_alert(subject, body, priority="info", event_type=f"settled_{ticker}")

        except Exception as exc:
            log.error("Alerter.position_settled failed: %s", exc)

    def daily_summary(self, stats: dict) -> None:
        """Send the full daily audit report. Called by daily_audit.py."""
        try:
            subject = stats.get("subject", "AI Predicted Wins — Daily Audit Report")
            body = stats.get("body_html", "<p>No report data.</p>")
            # No rate limiting on the daily summary — it runs once a day
            self.send_alert(subject, body, priority="info", event_type=None)

        except Exception as exc:
            log.error("Alerter.daily_summary failed: %s", exc)
