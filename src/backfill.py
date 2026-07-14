"""One-shot idempotent stale-trade backfill (PNL-05).

Walks genuinely-stale ``alpaca_trades`` rows (``status IN ('open','submitted')``
with an ``order_id``, older than a guard window) and resolves each to its true
terminal state from Alpaca order/position history, writing realized P&L via the
Phase-12 path. Reuses Phase-11 classification (``classify_order``), Phase-12 P&L
(``realized_pnl`` + ``TAKER_FEE``), and the Phase-13 per-bot key sourcing
(``reconciliation._client_for_bot`` — one account per bot, never bare keys).

- ``resolve_stale_row`` is a pure decision function (zero I/O), unit-tested.
- ``backfill(apply=False)`` is the per-bot driver. Dry-run is the DEFAULT: it
  computes identical counts but writes nothing. NEVER deletes/resets rows — the
  only mutation is ``TradeLogger.update_alpaca_trade`` (UPDATE-only).
"""
import datetime
import logging
import os

from src import db
from src import reconciliation
from src.order_resolution import classify_order
from src.pnl import realized_pnl
from src.fee_gate import TAKER_FEE
from src.trade_logger import TradeLogger
from src.universe import normalize

log = logging.getLogger(__name__)

# Close-match qty tolerance (fraction of entry filled_qty). A single opposite
# close whose filled_qty is within this band of the entry qty is treated as THE
# close; otherwise the row is unresolvable (partial-close aggregation is out of
# scope — reported, not guessed).
_QTY_TOLERANCE = 0.02


def _side(value: str) -> str:
    """Normalize an Alpaca side ('buy' / 'OrderSide.SELL' / 'short') → 'buy'|'sell'."""
    s = str(value).split(".")[-1].lower()
    return "buy" if s == "buy" else "sell"


def _parse_ts(value):
    try:
        dt = datetime.datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except Exception:
        return None


def resolve_stale_row(row: dict, entry_order: dict, live_symbols, close_order):
    """Pure resolution decision for one stale row.

    Returns ``(outcome, write_kwargs|None)`` where outcome is
    ``"resolved" | "unchanged" | "unresolvable"``:
      - entry canceled/rejected/expired 0-fill → resolved terminal non-position (pnl=0)
      - filled + symbol in ``live_symbols`` → unchanged (genuinely held)
      - filled + gone + ``close_order`` present → resolved closed (realized P&L + fees)
      - filled + gone + ``close_order`` None → unresolvable
      - in-flight entry → unchanged (re-poll next run)
    """
    status, pnl = classify_order(entry_order)

    # Terminal non-position: entry never became a position.
    if status is not None and status != "open":
        return "resolved", {"status": status, "exit_price": None,
                            "pnl": 0, "fees": None}

    # Became a position (filled / partial).
    if status == "open":
        # `live_symbols is None` means the get_positions() call FAILED — NOT "nothing is
        # held". The only safe answer is to leave the row alone; resolving it against
        # nothing would close a live position with a fabricated P&L.
        if live_symbols is None:
            return "unchanged", None
        # BOTH sides are normalized: Alpaca's get_positions() returns SLASHLESS symbols
        # (BTCUSD) while alpaca_trades.symbol is SLASHED (BTC/USD). Same helper, same
        # both-sides compare as the live monitor at src/alpaca_orchestrator.py:142-143.
        norm_live = {normalize(s) for s in live_symbols}
        if normalize(row.get("symbol")) in norm_live:
            return "unchanged", None
        if close_order is None:
            return "unresolvable", None

        exit_fill = float(close_order.get("filled_avg_price") or 0)
        if exit_fill <= 0:
            return "unresolvable", None

        entry_fill = float(row.get("filled_avg_price") or row.get("entry_price") or 0)
        qty = float(row.get("filled_qty") or row.get("qty") or 0)
        side = row["side"]
        fees = (entry_fill * qty + exit_fill * qty) * TAKER_FEE
        realized = realized_pnl(side, entry_fill, exit_fill, qty, TAKER_FEE)
        return "resolved", {"status": "closed", "exit_price": exit_fill,
                            "pnl": realized, "fees": fees}

    # Still in-flight — leave for the live resolver.
    return "unchanged", None


def _match_close(closes, entry_order, row):
    """Pick the single closing order for a filled entry.

    Keep opposite-side, filled (filled_qty>0), filled_at strictly after the
    entry's filled_at; choose the EARLIEST. Require its filled_qty ≈ the entry
    filled_qty (within ``_QTY_TOLERANCE``) else return None (partial/ambiguous →
    unresolvable). Returns the chosen close dict or None.
    """
    entry_side = _side(row.get("side") or entry_order.get("side"))
    want = "sell" if entry_side == "buy" else "buy"
    entry_ts = _parse_ts(entry_order.get("filled_at") or row.get("timestamp"))
    entry_qty = float(row.get("filled_qty") or row.get("qty") or 0)

    candidates = []
    for c in closes:
        if _side(c.get("side")) != want:
            continue
        if float(c.get("filled_qty") or 0) <= 0:
            continue
        cts = _parse_ts(c.get("filled_at"))
        if entry_ts is not None and (cts is None or cts <= entry_ts):
            continue
        candidates.append((cts, c))

    if not candidates:
        return None

    # Earliest close after entry.
    candidates.sort(key=lambda t: t[0])
    close = candidates[0][1]

    # Qty tolerance — a single close must roughly match the entry qty.
    if entry_qty > 0:
        tol = entry_qty * _QTY_TOLERANCE
        if abs(float(close.get("filled_qty") or 0) - entry_qty) > tol:
            return None
    return close


def backfill(apply: bool = False) -> list[tuple[str, dict]]:
    """Resolve stale rows for every enabled bot against its OWN Alpaca account.

    Dry-run (``apply=False``, default) computes identical counts but writes
    nothing. Returns ``[(bot_id, counts)]`` with counts keys
    ``resolved / unchanged / unresolvable / residue``.
    """
    guard = int(os.environ.get("BACKFILL_GUARD_MINUTES", "30"))
    results: list[tuple[str, dict]] = []

    for bot_id in reconciliation._enabled_bot_ids():
        client = reconciliation._client_for_bot(bot_id)  # per-bot keys, never bare
        logger = TradeLogger(bot_id)
        counts = {"resolved": 0, "unchanged": 0, "unresolvable": 0, "residue": 0}

        candidates = db.get_stale_alpaca_candidates(bot_id, guard)

        # The None sentinel is PRESERVED, never coerced to an empty list. `None` means the
        # ALPACA CALL FAILED — it does NOT mean "nothing is held". Coerced, an Alpaca
        # outage would make the ENTIRE BOOK look vanished and every held position
        # resolvable. Mirrors the live monitor's guard at src/alpaca_orchestrator.py:133-134.
        positions = client.get_positions()
        if positions is None:
            log.warning(
                "Backfill SKIPPED for bot %s: get_positions() returned None — the Alpaca "
                "call FAILED. Every row left unchanged.", bot_id,
            )
            counts["error"] = "positions_unavailable"
            counts["residue"] = db.count_unresolvable_alpaca_rows(bot_id)
            results.append((bot_id, counts))
            continue

        live_symbols = {normalize(p["symbol"]) for p in positions}

        for row in candidates:
            entry_order = client.get_order(row["order_id"])
            status, _ = classify_order(entry_order)

            close_order = None
            if status == "open" and normalize(row["symbol"]) not in live_symbols:
                closes = client.get_closed_orders(
                    row["symbol"], after=entry_order.get("filled_at") or None)
                close_order = _match_close(closes, entry_order, row)

            outcome, write_kwargs = resolve_stale_row(
                row, entry_order, live_symbols, close_order)
            counts[outcome] += 1

            if outcome == "resolved" and apply:
                # Drop None kwargs to mirror the Phase-12 monitor close call.
                payload = {k: v for k, v in write_kwargs.items() if v is not None}
                logger.update_alpaca_trade(row["id"], **payload)

        counts["residue"] = db.count_unresolvable_alpaca_rows(bot_id)
        results.append((bot_id, counts))

    return results
