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
