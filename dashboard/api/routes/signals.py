"""
Technical signals endpoint.

GET /api/signals -- latest scan results.

TODO: Wire this to real signal data once the technical scanner persists
scan results to the database. Currently returns placeholder data with
the correct structure so the frontend can be built in parallel.
"""

from datetime import datetime, timezone
from fastapi import APIRouter
from models import Envelope, Meta

router = APIRouter(prefix="/api", tags=["signals"])

_NOW = lambda: datetime.now(timezone.utc).isoformat()

# Placeholder until technical scanner persists scan results to the database.
# Shape matches the frontend Signal type exactly.
_PLACEHOLDER_SIGNALS = [
    {
        "symbol": "BTC/USD",
        "ema_signal": "bullish",
        "adx_value": 28.5,
        "adx_signal": "bullish",
        "rsi_value": 55.2,
        "rsi_signal": "neutral",
        "volume_spike": False,
        "vwap_signal": "bullish",
        "confluence_score": 3,
        "action": "WATCH",
        "scanned_at": None,
    },
    {
        "symbol": "ETH/USD",
        "ema_signal": "bullish",
        "adx_value": 32.1,
        "adx_signal": "bullish",
        "rsi_value": 48.7,
        "rsi_signal": "neutral",
        "volume_spike": True,
        "vwap_signal": "bullish",
        "confluence_score": 4,
        "action": "BUY",
        "scanned_at": None,
    },
    {
        "symbol": "SOL/USD",
        "ema_signal": "bearish",
        "adx_value": 18.3,
        "adx_signal": "neutral",
        "rsi_value": 62.1,
        "rsi_signal": "neutral",
        "volume_spike": False,
        "vwap_signal": "bearish",
        "confluence_score": 1,
        "action": "SKIP",
        "scanned_at": None,
    },
    {
        "symbol": "XRP/USD",
        "ema_signal": "bullish",
        "adx_value": 25.0,
        "adx_signal": "bullish",
        "rsi_value": 51.4,
        "rsi_signal": "neutral",
        "volume_spike": False,
        "vwap_signal": "bullish",
        "confluence_score": 3,
        "action": "WATCH",
        "scanned_at": None,
    },
    {
        "symbol": "ADA/USD",
        "ema_signal": "bearish",
        "adx_value": 15.2,
        "adx_signal": "neutral",
        "rsi_value": 44.8,
        "rsi_signal": "neutral",
        "volume_spike": False,
        "vwap_signal": "bearish",
        "confluence_score": 0,
        "action": "SKIP",
        "scanned_at": None,
    },
    {
        "symbol": "AVAX/USD",
        "ema_signal": "bullish",
        "adx_value": 22.7,
        "adx_signal": "bullish",
        "rsi_value": 58.3,
        "rsi_signal": "neutral",
        "volume_spike": True,
        "vwap_signal": "neutral",
        "confluence_score": 3,
        "action": "WATCH",
        "scanned_at": None,
    },
    {
        "symbol": "DOT/USD",
        "ema_signal": "bearish",
        "adx_value": 12.9,
        "adx_signal": "neutral",
        "rsi_value": 39.5,
        "rsi_signal": "neutral",
        "volume_spike": False,
        "vwap_signal": "bearish",
        "confluence_score": 0,
        "action": "SKIP",
        "scanned_at": None,
    },
    {
        "symbol": "LINK/USD",
        "ema_signal": "bullish",
        "adx_value": 30.4,
        "adx_signal": "bullish",
        "rsi_value": 52.8,
        "rsi_signal": "neutral",
        "volume_spike": False,
        "vwap_signal": "bullish",
        "confluence_score": 3,
        "action": "WATCH",
        "scanned_at": None,
    },
]


@router.get("/signals")
def get_signals():
    """Return the latest technical signal scan results.

    TODO: Read from a `signals` table once the bot persists scan data.
    Currently returns placeholder data for all 8 crypto assets.
    """
    now = _NOW()
    data = [{**s, "scanned_at": s["scanned_at"] or now} for s in _PLACEHOLDER_SIGNALS]
    return Envelope(data=data, meta=Meta(count=len(data)))
