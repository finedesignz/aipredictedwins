"""
Technical signals endpoint.

GET /api/signals -- latest scan results.

TODO: Wire this to real signal data once the technical scanner persists
scan results to the database. Currently returns placeholder data with
the correct structure so the frontend can be built in parallel.
"""

from fastapi import APIRouter

from models import Envelope, Meta, SignalRecord

router = APIRouter(prefix="/api", tags=["signals"])

# TODO: Replace this with real data from the technical scanner.
# The scanner (src/technical_signals.py) currently computes signals
# in-memory during each bot cycle but does not persist them to SQLite.
# When a `signals` table is added to trades.db, read from it here.
_PLACEHOLDER_SIGNALS: list[dict] = [
    {
        "symbol": "BTC/USD",
        "ema_bullish": True,
        "adx_value": 28.5,
        "rsi_value": 55.2,
        "volume_spike": False,
        "vwap_bullish": True,
        "confluence_score": 3,
    },
    {
        "symbol": "ETH/USD",
        "ema_bullish": True,
        "adx_value": 32.1,
        "rsi_value": 48.7,
        "volume_spike": True,
        "vwap_bullish": True,
        "confluence_score": 4,
    },
    {
        "symbol": "SOL/USD",
        "ema_bullish": False,
        "adx_value": 18.3,
        "rsi_value": 62.1,
        "volume_spike": False,
        "vwap_bullish": False,
        "confluence_score": 1,
    },
    {
        "symbol": "XRP/USD",
        "ema_bullish": True,
        "adx_value": 25.0,
        "rsi_value": 51.4,
        "volume_spike": False,
        "vwap_bullish": True,
        "confluence_score": 3,
    },
    {
        "symbol": "ADA/USD",
        "ema_bullish": False,
        "adx_value": 15.2,
        "rsi_value": 44.8,
        "volume_spike": False,
        "vwap_bullish": False,
        "confluence_score": 0,
    },
    {
        "symbol": "AVAX/USD",
        "ema_bullish": True,
        "adx_value": 22.7,
        "rsi_value": 58.3,
        "volume_spike": True,
        "vwap_bullish": False,
        "confluence_score": 3,
    },
    {
        "symbol": "DOT/USD",
        "ema_bullish": False,
        "adx_value": 12.9,
        "rsi_value": 39.5,
        "volume_spike": False,
        "vwap_bullish": False,
        "confluence_score": 0,
    },
    {
        "symbol": "LINK/USD",
        "ema_bullish": True,
        "adx_value": 30.4,
        "rsi_value": 52.8,
        "volume_spike": False,
        "vwap_bullish": True,
        "confluence_score": 3,
    },
]


@router.get("/signals", response_model=Envelope[list[SignalRecord]])
def get_signals():
    """Return the latest technical signal scan results.

    TODO: Read from a `signals` table once the bot persists scan data.
    Currently returns placeholder data for all 8 crypto assets.
    """
    return Envelope(
        data=_PLACEHOLDER_SIGNALS,
        meta=Meta(count=len(_PLACEHOLDER_SIGNALS)),
    )
