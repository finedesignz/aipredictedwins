# tests/test_symbol_stats.py
"""Phase 17 (TUNE-02) — the per-symbol stats contract.

RED-first: this module imports ``src.symbol_stats`` at the top, which does not
exist until Plan 03. That ImportError IS the RED proof (convention:
tests/test_pnl.py).

Six load-bearing specs, each pinned because the repo proved a naive premise FALSE:

1. A Phase-15 gate block writes ``status='rejected', pnl=0`` (src/bot_thread.py:309).
   It is NOT a trade and must never score as a loss. (case 12)
2. An externally-exited position writes ``status='closed', pnl=0.0``
   (src/alpaca_orchestrator.py:167-176). That row PASSES the terminal-status
   filter and is not NULL. A genuine flat trade is INDISTINGUISHABLE from it, so
   ``pnl == 0.0`` is bucketed (``zero_pnl``) and NEVER scored. (cases 2, 3)
3. src/bot_c/strategy.py:393-395 and src/trend_strategy.py:172-173 store a GROSS
   ``pnl`` and pass no ``fees`` — so NULL ``fees`` is the TELL. ``null_fees`` is the
   wide set; ``gross_pnl_rows`` is the COUNTED subset. They must be able to
   diverge. (case 7)
4. A NULL ``pnl`` is a resolution defect — excluded and counted, never coerced to
   zero. (cases 13, 14)
5. The divergence against the dashboard's number is in the COUNTS, not the sum:
   src/db.py:228-229 ``losses = resolved - wins`` books every sentinel zero and
   every NULL as a LOSS. (case 17)
6. Phase 17 opens no write path — and the fence that proves it must scan CODE, not
   prose. (cases 20, 21)
"""

from __future__ import annotations

import ast
import os
import re
import pathlib
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest

from src.symbol_stats import MIN_SAMPLE, aggregate

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _row(**over) -> dict:
    """A psycopg3 dict_row-shaped row as db.get_resolved_trades returns it."""
    row = {
        "bot_id": "A",
        "symbol": "BTC/USD",
        "asset_class": "crypto",
        "side": "buy",
        "status": "closed",
        "pnl": 0.0,
        "fees": 1.0,
        "entry_ts": "2026-01-01T00:00:00+00:00",
        "closed_at": "2026-01-02T00:00:00+00:00",
    }
    row.update(over)
    return row


def _one(rows, **kw) -> dict:
    cells = aggregate(rows, **kw)
    assert len(cells) == 1, f"expected exactly one cell, got {len(cells)}"
    return cells[0]


# ── cases 1-7: buckets, fabricated-loss traps, the fee split ──────────────────

def test_win_definition_positive():
    """case 1 — pnl > 0 is a win (mirrors src/db.py:228's definition, not its coercion)."""
    cell = _one([_row(pnl=10.0)])
    assert cell["wins"] == 1
    assert cell["losses"] == 0
    assert cell["trades"] == 1
    assert cell["win_rate"] == pytest.approx(1.0)


def test_zero_pnl_is_bucketed_not_a_loss():
    """case 2 — a `closed` row with pnl == 0.0 is NEITHER a win NOR a loss.

    src/alpaca_orchestrator.py:167-176 writes status="closed", pnl=0.0 for every
    externally-exited position. A genuine flat trade is INDISTINGUISHABLE from that
    sentinel, so neither is scored. Booking it as a loss would fabricate a losing
    record on every externally-exited position.
    """
    cell = _one([_row(pnl=0.0)])
    assert cell["losses"] == 0
    assert cell["wins"] == 0
    assert cell["trades"] == 0
    assert cell["zero_pnl"] == 1
    assert cell["null_pnl"] == 0
    assert cell["realized_pnl"] == pytest.approx(0.0)


def test_external_exit_sentinel_not_a_loss():
    """case 3 — the literal sentinel alongside real losers: losses == 2, NOT 3.

    Two shapes, both real:
      * src/alpaca_orchestrator.py:167-176 — exit_price == entry_price, pnl = 0.0
      * src/bot_c/strategy.py:393 / src/trend_strategy.py:172 — entry_price == 0 -> pnl = 0.0
    Both land on a `closed` row, so the SQL status filter cannot catch them.
    """
    rows = [
        _row(pnl=-10.0, entry_ts="2026-01-01T00:00:00+00:00"),
        _row(pnl=-5.0, entry_ts="2026-01-02T00:00:00+00:00"),
        _row(pnl=0.0, entry_ts="2026-01-03T00:00:00+00:00"),   # external-exit sentinel
        _row(pnl=0.0, fees=None, entry_ts="2026-01-04T00:00:00+00:00"),  # bot_c/trend shape
    ]
    cell = _one(rows)
    assert cell["losses"] == 2
    assert cell["trades"] == 2
    assert cell["zero_pnl"] == 2
    assert cell["realized_pnl"] == pytest.approx(-15.0)


def test_avg_loss_is_negative():
    """case 4 — avg_loss is carried NEGATIVE (expectancy sign drift otherwise)."""
    cell = _one([_row(pnl=-20.0), _row(pnl=-10.0)])
    assert cell["avg_loss"] == pytest.approx(-15.0)
    assert cell["avg_win"] == pytest.approx(0.0)


def test_expectancy_invariant():
    """case 5 — expectancy == win_rate*avg_win + (1-win_rate)*avg_loss == realized_pnl/trades.

    The 0.0 and the None row are excluded from BOTH sides.
    """
    rows = [
        _row(pnl=30.0), _row(pnl=10.0), _row(pnl=0.0), _row(pnl=None),
        _row(pnl=-20.0), _row(pnl=-5.0),
    ]
    cell = _one(rows)
    assert cell["trades"] == 4
    assert cell["zero_pnl"] == 1
    assert cell["null_pnl"] == 1
    expected = (
        cell["win_rate"] * cell["avg_win"]
        + (1 - cell["win_rate"]) * cell["avg_loss"]
    )
    assert cell["expectancy"] == pytest.approx(expected)
    assert cell["expectancy"] == pytest.approx(cell["realized_pnl"] / cell["trades"])


def test_fees_not_double_subtracted():
    """case 6 — realized_pnl == sum(pnl) EXACTLY. Fees are reported beside it, never subtracted."""
    cell = _one([_row(pnl=100.0, fees=3.0), _row(pnl=-40.0, fees=2.0)])
    assert cell["realized_pnl"] == pytest.approx(60.0)
    assert cell["total_fees"] == pytest.approx(5.0)


def test_null_fees_vs_gross_pnl_rows():
    """case 7 — null_fees and gross_pnl_rows are DISTINCT SETS (R3-W1).

    src/bot_c/strategy.py:393-395 and src/trend_strategy.py:172-173 store a GROSS
    pnl and pass no fees arg, so `fees` lands NULL (src/db.py:107,118). NULL fees on
    a COUNTED row is the TELL that its pnl is GROSS -> gross_pnl_rows.
    `null_fees` is wider: it also counts zero_pnl / null_pnl rows with NULL fees.
    total_fees must NEVER be read as "this bot paid $0 drag".
    """
    rows = [
        _row(pnl=10.0, fees=None),   # counted, gross
        _row(pnl=5.0, fees=2.0),     # counted, net
        _row(pnl=0.0, fees=None),    # zero_pnl, no fee data
        _row(pnl=None, fees=None),   # null_pnl, no fee data
    ]
    cell = _one(rows)
    assert cell["trades"] == 2
    assert cell["gross_pnl_rows"] == 1
    assert cell["null_fees"] == 3
    assert cell["total_fees"] == pytest.approx(2.0)
    assert cell["gross_pnl_rows"] < cell["null_fees"]


# ── cases 12-15: the gate block, the NULL rule, zero denominators ─────────────

def test_nonposition_terminal_never_counts():
    """case 12 — a non-position terminal is NOT a trade. Asserted as an EMPTY LIST.

    A Phase-15 gate block writes status='rejected', pnl=0 (src/bot_thread.py:309,317,332).
    Scoring it as a zero-P&L loss would make Phase 18 quarantine on fabricated evidence.
    """
    nonposition = [
        _row(status=s, pnl=0)
        for s in ("rejected", "canceled", "cancelled", "expired", "open", "submitted")
    ]
    assert aggregate(nonposition) == []

    mixed = [_row(pnl=7.0), _row(pnl=-3.0), _row(pnl=2.0)] + [
        _row(status="rejected", pnl=0) for _ in range(4)
    ]
    cell = _one(mixed)
    assert cell["trades"] == 3
    assert cell["zero_pnl"] == 0     # dropped BEFORE bucketing — never reach pnl == 0.0
    assert cell["null_pnl"] == 0


def test_null_pnl_excluded_and_counted():
    """case 13 — NULL pnl is a resolution defect: excluded, counted, never coerced to 0.0."""
    rows = [_row(pnl=None), _row(pnl=8.0), _row(pnl=-2.0)]
    cell = _one(rows)
    assert cell["trades"] == 2
    assert cell["null_pnl"] == 1
    assert cell["zero_pnl"] == 0     # None and 0.0 are DIFFERENT buckets
    assert cell["losses"] == 1
    assert cell["realized_pnl"] == pytest.approx(6.0)
    assert cell["expectancy"] == pytest.approx(cell["realized_pnl"] / cell["trades"])


def test_all_null_pnl_cell():
    """case 14 — an all-NULL cell is still EMITTED, loudly, with zeroed ratios."""
    cell = _one([_row(pnl=None) for _ in range(3)])
    assert cell["trades"] == 0
    assert cell["null_pnl"] == 3
    assert cell["wins"] == 0
    assert cell["losses"] == 0
    assert cell["win_rate"] == pytest.approx(0.0)
    assert cell["avg_win"] == pytest.approx(0.0)
    assert cell["avg_loss"] == pytest.approx(0.0)
    assert cell["expectancy"] == pytest.approx(0.0)
    assert cell["realized_pnl"] == pytest.approx(0.0)
    assert cell["sample"] == "insufficient"


def test_empty_and_zero_denominators():
    """case 15 — aggregate([]) == []; no ZeroDivisionError anywhere."""
    assert aggregate([]) == []

    all_wins = _one([_row(pnl=5.0), _row(pnl=15.0)])
    assert all_wins["avg_loss"] == pytest.approx(0.0)
    assert all_wins["avg_win"] == pytest.approx(10.0)

    all_losses = _one([_row(pnl=-5.0), _row(pnl=-15.0)])
    assert all_losses["avg_win"] == pytest.approx(0.0)
    assert all_losses["avg_loss"] == pytest.approx(-10.0)
    assert all_losses["win_rate"] == pytest.approx(0.0)


# ── case 17: the divergence that can actually fire ────────────────────────────

def test_naive_accuracy_divergence():
    """case 17 (R3-B2) — the divergence lives in the COUNTS, not the sum.

    src/db.py:228-229 computes `losses = resolved - wins`, booking EVERY sentinel
    zero and EVERY NULL as a LOSS. Its total_pnl, however, sums `(pnl or 0.0)` — and
    a zero contributes 0.0 and a NULL contributes 0.0, exactly what we exclude. So a
    realized_pnl DELTA is identically 0.00 and can never fire: printing it would tell
    the operator the data is clean. The DENOMINATOR is where the lie is.
    """
    rows = [
        _row(pnl=30.0), _row(pnl=20.0), _row(pnl=10.0),
        _row(pnl=-5.0), _row(pnl=-15.0),
        _row(pnl=0.0),    # external-exit sentinel
        _row(pnl=None),   # resolution defect
    ]
    # re-derived inline exactly as src/db.py:227-238 does it
    resolved = len(rows)
    naive_wins = sum(1 for r in rows if (r["pnl"] or 0) > 0)
    naive_losses = resolved - naive_wins
    naive_win_rate = naive_wins / resolved
    naive_total = sum((r["pnl"] or 0.0) for r in rows)

    cell = _one(rows)
    assert cell["trades"] == 5
    assert resolved - cell["trades"] == cell["zero_pnl"] + cell["null_pnl"] == 2
    assert cell["losses"] == 2
    assert naive_losses == 4                                    # the fabricated losses, named
    assert cell["win_rate"] != pytest.approx(naive_win_rate)    # THE DIVERGENCE
    assert cell["realized_pnl"] == pytest.approx(naive_total)   # the sums agree by construction
