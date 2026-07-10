"""Pure order-state classification (extracted from Phase-11 BotThread._classify).

Maps a parsed Alpaca order dict to ``(db_status, pnl)`` with zero I/O so a
standalone script (the Phase-14 backfill) can classify entry orders without
importing the heavy ``BotThread`` graph. ``BotThread._classify`` delegates here
so the Phase-11 suite stays green.
"""

# Alpaca terminal statuses that did NOT become a position (pnl=0, excluded from
# win/loss + open queries). Canonical set — the single source of truth.
_TERMINAL_NONPOSITION = frozenset({"canceled", "cancelled", "expired", "rejected"})


def classify_order(order: dict) -> tuple[str | None, int | None]:
    """Map a parsed Alpaca order to ``(db_status, pnl)``.

    - filled OR any ``filled_qty > 0`` → ``("open", None)``: genuine/partial position.
    - canceled/cancelled/expired/rejected with 0 fill → ``(status, 0)``: terminal
      non-position (``cancelled`` normalized to ``canceled``).
    - still in-flight (new/accepted/pending_*) → ``(None, None)``: leave submitted.
    """
    filled_qty = float(order.get("filled_qty", 0) or 0)
    status = str(order.get("status", "")).split(".")[-1].lower()
    if status == "filled" or filled_qty > 0:
        return "open", None
    if status in _TERMINAL_NONPOSITION:
        return ("canceled" if status == "cancelled" else status), 0
    return None, None
