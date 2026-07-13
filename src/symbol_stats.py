# src/symbol_stats.py
"""Pure per-(bot, symbol) aggregator — Phase 17 (TUNE-02).

SQL selects, Python decides. Zero I/O: no DB, no env, no network, no logging. A
plain dict IS a row, which is what keeps every rule below reachable from a unit
test with no database at all.

FOUR NON-NEGOTIABLES — each exists because the repo proved a naive premise false:

1. A NON-POSITION TERMINAL IS NOT A TRADE. A Phase-15 gate block writes
   ``status='rejected', pnl=0`` (src/bot_thread.py:309,317,332). Rows whose status
   is outside ``_POSITION_CLOSED`` are dropped BEFORE bucketing, so such a row can
   never reach the ``pnl == 0.0`` branch and can never score as a loss. The SQL
   filter in ``db.get_resolved_trades`` is the belt; this is the braces.

2. A ``closed`` ROW MAY CARRY ``pnl = 0.0``. src/alpaca_orchestrator.py:167-176
   writes exactly that for every externally-exited position (same shape at
   src/bot_c/strategy.py:393 and src/trend_strategy.py:172 when entry_price == 0).
   That row PASSES the terminal-status filter, and a genuine flat trade is
   INDISTINGUISHABLE from the sentinel — so ``pnl == 0.0`` is BUCKETED
   (``zero_pnl``), never scored. Scoring it as a loss would fabricate a losing
   record on every externally-exited position.

3. ``alpaca_trades.pnl`` IS NOT UNIFORMLY NET OF FEES. src/bot_c/strategy.py:393-395
   and src/trend_strategy.py:172-173 store a GROSS pnl and pass no fees argument, so
   ``fees`` lands NULL (src/db.py:107,118). NULL ``fees`` is therefore the TELL.
   ``null_fees`` counts EVERY row in the cell with no fee data; ``gross_pnl_rows``
   counts only the COUNTED ones — the un-fee-adjusted part of ``realized_pnl``.
   ``total_fees`` is INCOMPLETE disclosure and is never fee-subtracted from
   ``realized_pnl``.

4. A NULL ``pnl`` ON A POSITION-CLOSED ROW IS A RESOLUTION DEFECT. It is excluded
   and counted (``null_pnl``), never coerced to zero. src/db.py:228,259 do coerce;
   this module must not.

``null_pnl`` and ``zero_pnl`` are DIFFERENT buckets with DIFFERENT causes, tested
with ``pnl is None`` and ``pnl == 0.0`` explicitly — never with truthiness.
"""

from __future__ import annotations

from src.universe import normalize

MIN_SAMPLE = 5

# The position-closed terminal set — the literal at src/db.py:215. This repo already
# carries four spellings of it; do not add a fifth.
_POSITION_CLOSED = ("closed", "stopped", "target_hit")


def _cell_key(row: dict, key: tuple[str, ...]) -> tuple:
    return tuple(
        normalize(row.get("symbol")) if k == "symbol" else row.get(k)
        for k in key
    )


def aggregate(
    rows: list[dict],
    min_sample: int = MIN_SAMPLE,
    key: tuple[str, ...] = ("bot_id", "symbol"),
) -> list[dict]:
    """Aggregate resolved-trade rows into per-cell statistics. Pure.

    ``rows`` are psycopg3 dict_row dicts from ``db.get_resolved_trades``. Returns one
    cell per group, ordered by ``realized_pnl`` ascending (the report re-sorts).
    Insufficient cells are MARKED (``sample``), never hidden.
    """
    groups: dict[tuple, dict] = {}

    for row in rows:
        if row.get("status") not in _POSITION_CLOSED:
            continue                                    # non-position terminal: NOT a trade

        k = _cell_key(row, key)
        g = groups.get(k)
        if g is None:
            g = groups[k] = {
                "bot_id": row.get("bot_id") if "bot_id" in key else None,
                "symbol": normalize(row.get("symbol")) if "symbol" in key else None,
                "display": row.get("symbol") if "symbol" in key else None,
                "asset_class": row.get("asset_class"),
                "wins": 0,
                "losses": 0,
                "zero_pnl": 0,
                "null_pnl": 0,
                "gross_pnl_rows": 0,
                "null_fees": 0,
                "win_sum": 0.0,
                "loss_sum": 0.0,
                "total_fees": 0.0,
                "pnls": [],
                "entry_ts": [],
            }

        pnl = row.get("pnl")
        fees = row.get("fees")

        if fees is None:
            g["null_fees"] += 1                          # the WIDE set — every row with no fee data

        if pnl is None:
            g["null_pnl"] += 1                           # resolution defect — never coerced to zero
            continue
        if pnl == 0.0:
            g["zero_pnl"] += 1                           # external-exit sentinel — never scored
            continue

        # COUNTED from here down.
        if fees is None:
            g["gross_pnl_rows"] += 1                     # the COUNTED subset — this pnl is probably GROSS
        else:
            g["total_fees"] += float(fees)

        if pnl > 0:
            g["wins"] += 1
            g["win_sum"] += float(pnl)
        else:
            g["losses"] += 1
            g["loss_sum"] += float(pnl)

        g["pnls"].append(float(pnl))
        if row.get("entry_ts") is not None:
            g["entry_ts"].append(row["entry_ts"])

    cells: list[dict] = []
    for g in groups.values():
        wins, losses = g["wins"], g["losses"]
        trades = wins + losses
        win_rate = wins / trades if trades else 0.0
        avg_win = g["win_sum"] / wins if wins else 0.0
        avg_loss = g["loss_sum"] / losses if losses else 0.0   # carried NEGATIVE
        realized = g["win_sum"] + g["loss_sum"]                 # sum(pnl); never fee-adjusted
        cells.append({
            "bot_id": g["bot_id"],
            "symbol": g["symbol"],
            "display": g["display"],
            "asset_class": g["asset_class"],
            "trades": trades,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "realized_pnl": realized,
            "total_fees": g["total_fees"],
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "expectancy": win_rate * avg_win + (1 - win_rate) * avg_loss,
            "best": max(g["pnls"]) if g["pnls"] else 0.0,
            "worst": min(g["pnls"]) if g["pnls"] else 0.0,
            "first_trade": min(g["entry_ts"]) if g["entry_ts"] else None,
            "last_trade": max(g["entry_ts"]) if g["entry_ts"] else None,
            "zero_pnl": g["zero_pnl"],
            "null_pnl": g["null_pnl"],
            "gross_pnl_rows": g["gross_pnl_rows"],
            "null_fees": g["null_fees"],
            "sample": "sufficient" if trades >= min_sample else "insufficient",
        })

    cells.sort(key=lambda c: c["realized_pnl"])
    return cells
