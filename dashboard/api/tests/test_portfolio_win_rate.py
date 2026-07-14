"""Phase 18 — the dashboard's TWO duplicated win-rate denominators (VALIDATION case 13).

The dashboard does NOT call src.db.get_alpaca_accuracy. portfolio.py (the HEADLINE)
and settings.py (the PAPER-GATE readout) each carry their own copy of the same
`(pnl or 0) > 0` / `losses = len(rows) - wins` arithmetic. Fixing src/db.py alone
leaves both wrong AND books every honest NULL row (Plan 18-03) as a fresh loss.

Static half runs everywhere (with a positive control so it cannot pass vacuously).
Behavioral half is TEST_DATABASE_URL-gated and skips visibly.
"""
import os
import pathlib

import pytest

_ROUTES = pathlib.Path(__file__).resolve().parents[1] / "routes"
_needs_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — skipping behavioral win-rate check")


@pytest.mark.parametrize("fname", ["portfolio.py", "settings.py"])
def test_portfolio_and_settings_exclude_null_pnl(fname):
    src = (_ROUTES / fname).read_text(encoding="utf-8")

    # POSITIVE CONTROL — we really are reading the closed-trades query.
    assert "status IN ('closed', 'stopped', 'target_hit')" in src, \
        f"{fname}: positive control failed — the closed-trades query moved"

    assert "pnl IS NOT NULL" in src, \
        f"{fname}: the win-rate denominator still counts NULL-pnl rows as losses"


@_needs_db
def test_portfolio_win_rate_is_33_not_20():
    """The case-9 fixture through the real route: 2/6 == 33.3%, not 2/10 == 20.0%."""
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from fastapi.testclient import TestClient
    from main import app
    from db import get_db

    pnls = [100.0, 50.0, -10.0, -20.0, -30.0, 0.0, None, None, None, None]
    with get_db() as conn:
        conn.execute("DELETE FROM alpaca_trades WHERE bot_id = 'A'")
        for p in pnls:
            conn.execute(
                """INSERT INTO alpaca_trades
                   (bot_id, timestamp, symbol, asset_class, side, qty, entry_price,
                    status, pnl, closed_at)
                   VALUES ('A', NOW()::text, 'BTC/USD', 'crypto', 'buy', 1, 100,
                           'closed', %s, NOW()::text)""",
                (p,),
            )

    client = TestClient(app)
    data = client.get("/api/portfolio?bot=A").json()["data"]
    assert data["win_rate"] == pytest.approx(33.3, abs=0.1)


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 19 (RUN-02) — cases 15, 16, 18, 19, 20, 21.
#
# RESOLVED := `pnl IS NOT NULL AND pnl <> 0`. A 0.0 sentinel is excluded from the
# win-rate NUMERATOR *and DENOMINATOR* and from the realized-P&L sum, and reported as
# its own `unresolved` count — never folded into losses.
#
# And the headline P&L must be the RECONCILED Alpaca-derived number, with pnl_source /
# stale set on EVERY branch. portfolio.py:111-122 falls back from Alpaca to the raw
# trade-log sum SILENTLY today, with no flag on the response.
# ═══════════════════════════════════════════════════════════════════════════════

def _portfolio_src():
    return (_ROUTES / "portfolio.py").read_text(encoding="utf-8")


# ── Case 15 ───────────────────────────────────────────────────────────────────

def test_portfolio_win_rate_excludes_sentinels():
    src = _portfolio_src()
    assert "status IN ('closed', 'stopped', 'target_hit')" in src, \
        "positive control failed — the closed-trades query moved"
    assert "pnl <> 0" in src, \
        "the headline win rate still books ~395 pnl=0.0 sentinels as LOSSES"
    assert "unresolved" in src, \
        "the sentinels left the denominator but are not reported anywhere"


# ── Case 16 ───────────────────────────────────────────────────────────────────

def test_portfolio_realized_sum_excludes_sentinels():
    """NUMERICALLY VACUOUS BY CONSTRUCTION — zeros sum to zero, so the realized total
    does not move. Its value is entirely in the STATIC half: the sum's POPULATION is now
    the same population as the win rate's. Two figures on one card that silently disagree
    about what a trade IS is exactly how this class of bug survives. Stated out loud
    rather than overclaimed as a behavioral catch."""
    src = _portfolio_src()
    assert "closed_pnl" in src, "positive control failed — the realized sum moved"
    assert src.count("pnl <> 0") >= 2


# ── Case 18 — the FIFTH reader (research N7) ─────────────────────────────────

def test_daily_pnl_uses_the_same_predicate():
    """Also NUMERICALLY VACUOUS (zeros sum to zero). The static half is the real
    assertion: the daily-P&L query at :93-101 has NO pnl filter AT ALL today — a fifth
    reader with a fifth opinion about what a resolved trade is."""
    src = _portfolio_src()
    assert "DATE(closed_at::timestamptz)" in src, \
        "positive control failed — the daily-P&L query moved"
    daily = src.split("DATE(closed_at::timestamptz)")[0].rsplit("SELECT pnl", 1)[-1]
    assert "pnl <> 0" in daily or src.count("pnl <> 0") >= 2, \
        "the daily-P&L reader still disagrees with the other four"


# ── Case 19 — the headline IS the reconciled number ──────────────────────────

def test_headline_pnl_is_the_reconciled_number():
    """RUN-02 in one line. 017_reconciliation.sql's own header says 'Consumed by the
    dashboard headline in Phase 19'. Nothing consumed it."""
    src = _portfolio_src()
    assert "FROM reconciliation" in src, \
        "the headline never reads the reconciliation row it was built for"
    assert "alpaca_realized_pnl" in src


# ── Case 20 — the silent fallback becomes a LABELLED fallback ────────────────

def test_pnl_source_is_surfaced_and_correct():
    src = _portfolio_src()
    assert "_fetch_alpaca_account" in src, "positive control failed"
    assert src.count("pnl_source") >= 3, \
        "pnl_source must be set on EVERY branch — reconciled / alpaca_live / trade_log"
    for branch in ('"reconciled"', '"alpaca_live"', '"trade_log"'):
        assert branch in src, f"branch {branch} is unlabelled"


# ── Case 21 — a stale number is still SHOWN, but FLAGGED ────────────────────

def test_stale_is_surfaced():
    src = _portfolio_src()
    assert "stale" in src, "an unreconciled number is being presented as reconciled"
    assert "RECONCILE_INTERVAL_HOURS" in src, \
        "staleness is not measured against the reconcile interval"
