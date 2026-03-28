#!/usr/bin/env python3
"""
Daily audit script for the AI Predicted Wins trading bot.

Run daily via cron / Windows Task Scheduler:
    python -m scripts.daily_audit

Performs health checks, gathers portfolio metrics, and emails an HTML
report via AWS SES.
"""

import logging
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# Ensure project root is on the path so we can import src.*
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import load_config  # noqa: E402
from src.trade_logger import TradeLogger  # noqa: E402
from src.alerter import Alerter  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Health check helpers
# ---------------------------------------------------------------------------

def _check_bot_process() -> dict:
    """Check if the orchestrator process is running."""
    try:
        if sys.platform == "win32":
            output = subprocess.check_output(
                ["tasklist", "/FO", "CSV", "/NH"],
                text=True, timeout=10,
            )
            running = "orchestrator" in output.lower()
        else:
            output = subprocess.check_output(
                ["ps", "aux"], text=True, timeout=10,
            )
            running = "orchestrator" in output.lower()
        return {"status": "ok" if running else "down", "detail": "Process detected" if running else "Not found"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_gateway() -> dict:
    """GET https://gateway.aipredictedwins.com/health"""
    try:
        resp = requests.get(
            "https://gateway.aipredictedwins.com/health",
            timeout=15,
        )
        if resp.status_code == 200:
            return {"status": "ok", "detail": f"HTTP {resp.status_code}"}
        return {"status": "warning", "detail": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"status": "down", "detail": str(exc)}


def _check_mirofish() -> dict:
    """GET https://app.aipredictedwins.com/api/graph/project/list"""
    try:
        resp = requests.get(
            "https://app.aipredictedwins.com/api/graph/project/list",
            timeout=15,
        )
        if resp.status_code == 200:
            return {"status": "ok", "detail": f"HTTP {resp.status_code}"}
        return {"status": "warning", "detail": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"status": "down", "detail": str(exc)}


def _check_kalshi_balance(config) -> dict:
    """Attempt to get the Kalshi balance."""
    try:
        from src.kalshi_client import KalshiClient
        kalshi = KalshiClient(config)
        balance = kalshi.get_balance()
        return {"status": "ok", "balance": balance, "detail": f"${balance:,.2f}"}
    except Exception as exc:
        return {"status": "error", "balance": None, "detail": str(exc)}


# ---------------------------------------------------------------------------
# Portfolio analysis
# ---------------------------------------------------------------------------

def _analyse_portfolio(logger: TradeLogger, starting_bankroll: float) -> dict:
    """Run all portfolio checks and return structured results."""
    now = datetime.now(timezone.utc)
    cutoff_24h = (now - timedelta(hours=24)).isoformat()

    # Open positions
    open_positions = logger.get_open_positions()

    # Recent activity (24h)
    conn = logger._get_conn()
    try:
        sims_24h = conn.execute(
            "SELECT COUNT(*) FROM simulations WHERE timestamp >= ?",
            (cutoff_24h,),
        ).fetchone()[0]
        trades_24h = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE timestamp >= ?",
            (cutoff_24h,),
        ).fetchone()[0]

        # Last 5 trades
        last_trades = conn.execute(
            "SELECT kalshi_ticker, side, entry_price_cents, gap, dollar_amount, status, pnl, timestamp "
            "FROM trades ORDER BY timestamp DESC LIMIT 5"
        ).fetchall()
        last_trades = [dict(r) for r in last_trades]

        # Last 5 vetoes
        last_vetoes = conn.execute(
            "SELECT kalshi_ticker, event_title, veto_reason, timestamp "
            "FROM validations WHERE decision = 'VETO' "
            "ORDER BY timestamp DESC LIMIT 5"
        ).fetchall()
        last_vetoes = [dict(r) for r in last_vetoes]

    finally:
        conn.close()

    # Side balance
    yes_count = sum(1 for p in open_positions if p.get("side") == "yes")
    no_count = sum(1 for p in open_positions if p.get("side") == "no")
    total_open = yes_count + no_count
    side_imbalance = False
    if total_open > 0:
        dominant_pct = max(yes_count, no_count) / total_open
        side_imbalance = dominant_pct > 0.80

    # Category concentration (use ticker prefix as proxy for category)
    categories: dict[str, int] = {}
    for p in open_positions:
        ticker = p.get("kalshi_ticker", "")
        # Extract category prefix (e.g., KXPRESPARTY from KXPRESPARTY-2028-R)
        cat = ticker.split("-")[0] if "-" in ticker else ticker[:6]
        categories[cat] = categories.get(cat, 0) + 1
    category_warning = None
    if total_open > 0:
        for cat, count in categories.items():
            if count / total_open > 0.60:
                category_warning = f"{cat} has {count}/{total_open} positions ({count/total_open:.0%})"

    # Drawdown
    accuracy = logger.get_accuracy()
    total_pnl = accuracy.get("total_pnl", 0.0)
    drawdown_pct = abs(min(0, total_pnl)) / starting_bankroll if starting_bankroll > 0 else 0
    drawdown_level = (
        "critical" if drawdown_pct >= 0.15
        else "warning" if drawdown_pct >= 0.10
        else "ok"
    )

    return {
        "open_positions": open_positions,
        "total_open": total_open,
        "yes_count": yes_count,
        "no_count": no_count,
        "side_imbalance": side_imbalance,
        "categories": categories,
        "category_warning": category_warning,
        "sims_24h": sims_24h,
        "trades_24h": trades_24h,
        "accuracy": accuracy,
        "total_pnl": total_pnl,
        "drawdown_pct": drawdown_pct,
        "drawdown_level": drawdown_level,
        "last_trades": last_trades,
        "last_vetoes": last_vetoes,
    }


# ---------------------------------------------------------------------------
# HTML report builder
# ---------------------------------------------------------------------------

_STATUS_COLORS = {
    "ok": "#16a34a",
    "warning": "#f59e0b",
    "down": "#dc2626",
    "error": "#dc2626",
    "critical": "#dc2626",
}

_STATUS_ICONS = {
    "ok": "&#9989;",       # green check
    "warning": "&#9888;",  # warning triangle
    "down": "&#128680;",   # red siren
    "error": "&#128680;",
    "critical": "&#128680;",
}


def _status_cell(status: str, detail: str = "") -> str:
    color = _STATUS_COLORS.get(status, "#6b7280")
    icon = _STATUS_ICONS.get(status, "")
    return (
        f'<td style="padding:8px; color:{color}; font-weight:bold;">'
        f'{icon} {status.upper()}</td>'
        f'<td style="padding:8px; color:#374151;">{detail}</td>'
    )


def _build_html_report(
    health_checks: dict,
    portfolio: dict,
    report_date: str,
) -> tuple[str, str]:
    """Build the HTML email body and determine overall status.

    Returns (subject, body_html).
    """
    # Determine overall status
    statuses = [v["status"] for v in health_checks.values()]
    warnings_list: list[str] = []

    if "down" in statuses or "error" in statuses:
        overall = "CRITICAL"
        overall_icon = "&#128680;"
    elif "warning" in statuses or portfolio["side_imbalance"] or portfolio["category_warning"] or portfolio["drawdown_level"] != "ok":
        overall = "WARNINGS"
        overall_icon = "&#9888;"
    else:
        overall = "HEALTHY"
        overall_icon = "&#9989;"

    # Collect risk warnings
    if portfolio["side_imbalance"]:
        dominant = "YES" if portfolio["yes_count"] > portfolio["no_count"] else "NO"
        warnings_list.append(
            f"Side imbalance: {dominant} has {max(portfolio['yes_count'], portfolio['no_count'])}/"
            f"{portfolio['total_open']} positions"
        )
    if portfolio["category_warning"]:
        warnings_list.append(f"Category concentration: {portfolio['category_warning']}")
    if portfolio["drawdown_level"] == "critical":
        warnings_list.append(f"Drawdown CRITICAL: {portfolio['drawdown_pct']:.1%} of bankroll")
    elif portfolio["drawdown_level"] == "warning":
        warnings_list.append(f"Drawdown warning: {portfolio['drawdown_pct']:.1%} of bankroll")
    if portfolio["sims_24h"] == 0:
        warnings_list.append("No simulations in last 24 hours")
    if portfolio["trades_24h"] == 0:
        warnings_list.append("No trades in last 24 hours")

    for name, check in health_checks.items():
        if check["status"] in ("down", "error"):
            warnings_list.append(f"{name} is {check['status'].upper()}: {check['detail']}")

    subject = f"AI Predicted Wins \u2014 Daily Audit Report [{report_date}] {overall_icon} {overall}"

    # --- Build HTML ---
    acc = portfolio["accuracy"]
    kalshi_check = health_checks.get("Kalshi Balance", {})
    balance_str = kalshi_check.get("detail", "N/A")

    html = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 700px; margin: 0 auto; background: #f9fafb; padding: 20px;">

        <!-- Header -->
        <div style="background: #1e293b; color: white; padding: 20px; border-radius: 8px 8px 0 0; text-align: center;">
            <h1 style="margin: 0; font-size: 22px;">AI Predicted Wins</h1>
            <p style="margin: 5px 0 0; font-size: 14px; color: #94a3b8;">Daily Audit Report &mdash; {report_date}</p>
            <p style="margin: 10px 0 0; font-size: 18px; color: {_STATUS_COLORS.get(overall.lower().replace('warnings','warning').replace('healthy','ok').replace('critical','critical'), '#fff')};">
                {overall_icon} {overall}
            </p>
        </div>

        <!-- System Health -->
        <div style="background: white; padding: 20px; border: 1px solid #e5e7eb; margin-top: 2px;">
            <h2 style="margin: 0 0 12px; font-size: 16px; color: #1e293b;">System Health</h2>
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="background: #f1f5f9;">
                    <th style="padding: 8px; text-align: left; width: 30%;">Component</th>
                    <th style="padding: 8px; text-align: left; width: 20%;">Status</th>
                    <th style="padding: 8px; text-align: left;">Detail</th>
                </tr>
    """

    for name, check in health_checks.items():
        html += f"""
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">{name}</td>
                    {_status_cell(check['status'], check.get('detail', ''))}
                </tr>
        """

    html += """
            </table>
        </div>
    """

    # Portfolio Summary
    html += f"""
        <div style="background: white; padding: 20px; border: 1px solid #e5e7eb; margin-top: 2px;">
            <h2 style="margin: 0 0 12px; font-size: 16px; color: #1e293b;">Portfolio Summary</h2>
            <table style="width: 100%; border-collapse: collapse;">
                <tr><td style="padding: 6px; font-weight: 600;">Balance</td>
                    <td style="padding: 6px;">{balance_str}</td></tr>
                <tr style="background:#f9fafb;"><td style="padding: 6px; font-weight: 600;">Open Positions</td>
                    <td style="padding: 6px;">{portfolio['total_open']} (YES: {portfolio['yes_count']}, NO: {portfolio['no_count']})</td></tr>
                <tr><td style="padding: 6px; font-weight: 600;">Total P&L</td>
                    <td style="padding: 6px; color: {'#16a34a' if portfolio['total_pnl'] >= 0 else '#dc2626'};">
                        ${portfolio['total_pnl']:+,.2f}</td></tr>
                <tr style="background:#f9fafb;"><td style="padding: 6px; font-weight: 600;">Win Rate</td>
                    <td style="padding: 6px;">{acc.get('win_rate', 0):.1%} ({acc.get('wins', 0)}W / {acc.get('losses', 0)}L of {acc.get('resolved', 0)} resolved)</td></tr>
                <tr><td style="padding: 6px; font-weight: 600;">Avg Gap at Entry</td>
                    <td style="padding: 6px;">{acc.get('avg_gap', 0):.1%}</td></tr>
                <tr style="background:#f9fafb;"><td style="padding: 6px; font-weight: 600;">Drawdown</td>
                    <td style="padding: 6px; color: {_STATUS_COLORS.get(portfolio['drawdown_level'], '#374151')};">
                        {portfolio['drawdown_pct']:.1%}</td></tr>
                <tr><td style="padding: 6px; font-weight: 600;">Sims (24h)</td>
                    <td style="padding: 6px;">{portfolio['sims_24h']}</td></tr>
                <tr style="background:#f9fafb;"><td style="padding: 6px; font-weight: 600;">Trades (24h)</td>
                    <td style="padding: 6px;">{portfolio['trades_24h']}</td></tr>
            </table>
        </div>
    """

    # Risk Alerts
    if warnings_list:
        html += """
        <div style="background: #fffbeb; padding: 20px; border: 1px solid #f59e0b; margin-top: 2px;">
            <h2 style="margin: 0 0 12px; font-size: 16px; color: #92400e;">Risk Alerts</h2>
            <ul style="margin: 0; padding-left: 20px;">
        """
        for w in warnings_list:
            html += f'<li style="padding: 4px 0; color: #92400e;">{w}</li>'
        html += """
            </ul>
        </div>
        """

    # Recent Trades
    html += """
        <div style="background: white; padding: 20px; border: 1px solid #e5e7eb; margin-top: 2px;">
            <h2 style="margin: 0 0 12px; font-size: 16px; color: #1e293b;">Recent Trades (Last 5)</h2>
    """
    if portfolio["last_trades"]:
        html += """
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <tr style="background: #f1f5f9;">
                    <th style="padding: 6px; text-align: left;">Ticker</th>
                    <th style="padding: 6px;">Side</th>
                    <th style="padding: 6px;">Price</th>
                    <th style="padding: 6px;">Gap</th>
                    <th style="padding: 6px;">Status</th>
                    <th style="padding: 6px;">P&L</th>
                </tr>
        """
        for t in portfolio["last_trades"]:
            pnl_val = t.get("pnl")
            pnl_str = f"${pnl_val:+,.2f}" if pnl_val is not None else "--"
            pnl_color = "#16a34a" if (pnl_val or 0) > 0 else "#dc2626" if (pnl_val or 0) < 0 else "#6b7280"
            html += f"""
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 6px; font-weight: 600;">{t.get('kalshi_ticker', '')}</td>
                    <td style="padding: 6px; text-align: center;">{(t.get('side') or '').upper()}</td>
                    <td style="padding: 6px; text-align: center;">{t.get('entry_price_cents', 0)}c</td>
                    <td style="padding: 6px; text-align: center;">{t.get('gap', 0):.1%}</td>
                    <td style="padding: 6px; text-align: center;">{(t.get('status') or '').upper()}</td>
                    <td style="padding: 6px; text-align: center; color: {pnl_color};">{pnl_str}</td>
                </tr>
            """
        html += "</table>"
    else:
        html += '<p style="color: #6b7280;">No trades recorded yet.</p>'
    html += "</div>"

    # Recent Vetoes
    html += """
        <div style="background: white; padding: 20px; border: 1px solid #e5e7eb; margin-top: 2px;">
            <h2 style="margin: 0 0 12px; font-size: 16px; color: #1e293b;">Recent Vetoes (Last 5)</h2>
    """
    if portfolio["last_vetoes"]:
        html += """
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <tr style="background: #f1f5f9;">
                    <th style="padding: 6px; text-align: left;">Ticker</th>
                    <th style="padding: 6px; text-align: left;">Reason</th>
                    <th style="padding: 6px;">Time</th>
                </tr>
        """
        for v in portfolio["last_vetoes"]:
            reason = (v.get("veto_reason") or "No reason given")[:120]
            ts = v.get("timestamp", "")[:16]
            html += f"""
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 6px; font-weight: 600;">{v.get('kalshi_ticker', '')}</td>
                    <td style="padding: 6px;">{reason}</td>
                    <td style="padding: 6px; text-align: center; white-space: nowrap;">{ts}</td>
                </tr>
            """
        html += "</table>"
    else:
        html += '<p style="color: #6b7280;">No vetoes recorded.</p>'
    html += "</div>"

    # Recommendations
    recommendations: list[str] = []
    if health_checks.get("Bot Process", {}).get("status") != "ok":
        recommendations.append("Restart the orchestrator process.")
    if health_checks.get("Gateway", {}).get("status") in ("down", "error"):
        recommendations.append("Check the Claude Code Bridge gateway on Coolify.")
    if health_checks.get("MiroFish", {}).get("status") in ("down", "error"):
        recommendations.append("Check MiroFish backend on Coolify.")
    if portfolio["drawdown_level"] == "critical":
        recommendations.append("Drawdown is critical. Consider pausing the bot and reviewing recent losses.")
    if portfolio["side_imbalance"]:
        recommendations.append("Side imbalance detected. Review portfolio diversification settings.")
    if portfolio["sims_24h"] == 0:
        recommendations.append("No simulations ran in 24h. Check if the bot is stuck or if markets are filtered out.")

    if recommendations:
        html += """
        <div style="background: #eff6ff; padding: 20px; border: 1px solid #3b82f6; margin-top: 2px; border-radius: 0 0 8px 8px;">
            <h2 style="margin: 0 0 12px; font-size: 16px; color: #1e40af;">Recommendations</h2>
            <ul style="margin: 0; padding-left: 20px;">
        """
        for r in recommendations:
            html += f'<li style="padding: 4px 0; color: #1e40af;">{r}</li>'
        html += """
            </ul>
        </div>
        """
    else:
        html += """
        <div style="background: #f0fdf4; padding: 20px; border: 1px solid #16a34a; margin-top: 2px; border-radius: 0 0 8px 8px;">
            <p style="margin: 0; color: #166534;">&#9989; All systems nominal. No action required.</p>
        </div>
        """

    # Footer
    html += f"""
        <div style="text-align: center; padding: 15px; color: #9ca3af; font-size: 12px;">
            Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} by daily_audit.py
        </div>
    </div>
    """

    return subject, html


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_audit() -> None:
    """Execute the full daily audit and send email report."""
    log.info("Starting daily audit...")
    report_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    config = load_config(env_path=_PROJECT_ROOT / ".env")
    logger = TradeLogger(db_path=str(_PROJECT_ROOT / "data" / "trades.db"))

    # Health checks
    log.info("Running health checks...")
    health_checks = {
        "Bot Process": _check_bot_process(),
        "Gateway": _check_gateway(),
        "MiroFish": _check_mirofish(),
        "Kalshi Balance": _check_kalshi_balance(config),
    }

    for name, result in health_checks.items():
        log.info("  %s: %s — %s", name, result["status"], result.get("detail", ""))

    # Portfolio analysis
    log.info("Analysing portfolio...")
    portfolio = _analyse_portfolio(logger, config.starting_bankroll)

    # Build report
    subject, body_html = _build_html_report(health_checks, portfolio, report_date)

    # Send via Alerter
    log.info("Sending audit email...")
    alerter = Alerter(config)
    alerter.daily_summary({"subject": subject, "body_html": body_html})

    log.info("Daily audit complete.")


if __name__ == "__main__":
    run_audit()
