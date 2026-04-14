"""
Technical signals endpoint.

GET /api/signals?bot=A|B|both

Returns the latest technical scan results written by BotThread after each
scan cycle. Falls back to an empty list if no scan has run yet.
"""

from typing import Literal

from fastapi import APIRouter, Query

from db import get_db
from models import Envelope, Meta

router = APIRouter(prefix="/api", tags=["signals"])


def _derive_signals(row: dict) -> dict:
    """Add derived signal fields (ema_signal, adx_signal, etc.) to a raw DB row."""
    ema_bullish = row.get("ema_bullish") or False
    adx_value = float(row.get("adx_value") or 0.0)
    rsi_value = float(row.get("rsi_value") or 50.0)
    vwap_bullish = row.get("vwap_bullish") or False
    confluence_score = int(row.get("confluence_score") or 0)

    ema_signal = "bullish" if ema_bullish else "bearish"

    if adx_value >= 25:
        adx_signal = "bullish"
    elif adx_value >= 20:
        adx_signal = "neutral"
    else:
        adx_signal = "neutral"

    if rsi_value < 40:
        rsi_signal = "bullish"
    elif rsi_value > 70:
        rsi_signal = "bearish"
    else:
        rsi_signal = "neutral"

    vwap_signal = "bullish" if vwap_bullish else "bearish"

    if confluence_score >= 3:
        action = "BUY"
    elif confluence_score >= 1:
        action = "WATCH"
    else:
        action = "SKIP"

    scanned_at = row.get("scanned_at")
    if scanned_at and hasattr(scanned_at, "isoformat"):
        scanned_at = scanned_at.isoformat()

    return {
        "symbol": row["symbol"],
        "ema_signal": ema_signal,
        "adx_value": adx_value,
        "adx_signal": adx_signal,
        "rsi_value": rsi_value,
        "rsi_signal": rsi_signal,
        "volume_spike": bool(row.get("volume_spike") or False),
        "vwap_signal": vwap_signal,
        "confluence_score": confluence_score,
        "action": action,
        "scanned_at": scanned_at,
        "bot_id": row.get("bot_id"),
    }


@router.get("/signals")
def get_signals(bot: Literal["A", "B", "both"] = Query("both")):
    """Return the latest technical scan results from the signals table.

    Each bot writes its scan results after every cycle (~30 min). The response
    reflects the most recent scan per bot. Returns empty list if no scan has run.
    """
    bot_ids = ["A", "B"] if bot == "both" else [bot]

    rows = []
    with get_db() as conn:
        for bot_id in bot_ids:
            # Get the timestamp of the most recent scan for this bot
            latest = conn.execute(
                "SELECT MAX(scanned_at) AS ts FROM signals WHERE bot_id = %s",
                (bot_id,),
            ).fetchone()
            if not latest or not latest["ts"]:
                continue
            # Fetch all signals from that scan batch
            batch = conn.execute(
                """
                SELECT symbol, ema_bullish, adx_value, rsi_value,
                       volume_spike, vwap_bullish, confluence_score, scanned_at, bot_id
                FROM signals
                WHERE bot_id = %s AND scanned_at = %s
                ORDER BY confluence_score DESC, symbol
                """,
                (bot_id, latest["ts"]),
            ).fetchall()
            rows.extend(batch)

    data = [_derive_signals(r) for r in rows]
    return Envelope(data=data, meta=Meta(count=len(data)))
