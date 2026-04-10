"""
Bot registry endpoint.

GET /api/bots  -- returns all registered bots from the bots table
"""

from fastapi import APIRouter

from db import get_db
from models import BotInfo, Envelope, Meta

router = APIRouter(prefix="/api", tags=["bots"])


@router.get("/bots")
def get_bots():
    """Return all bots from the bots registry table."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, label, starting_equity, alpaca_key_prefix, config_flags FROM bots ORDER BY id"
        ).fetchall()
    data = [BotInfo(**r) for r in rows]
    return Envelope(data=data, meta=Meta(count=len(data)))
