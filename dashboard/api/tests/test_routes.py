"""
Route integration tests for the dashboard API.

Requires a real Postgres instance. Set TEST_DATABASE_URL to run.
The tests seed synthetic trades for Bot A and Bot B.

Skip if TEST_DATABASE_URL is not set.
"""

import os
import sys
import pytest

# Add dashboard/api to path so we can import the app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — skipping route integration tests",
)


@pytest.fixture(scope="module")
def client():
    """Create a TestClient with seeded Postgres data."""
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    os.environ.pop("DASHBOARD_TOKEN", None)  # disable auth for tests

    from main import app
    from db import get_db
    from fastapi.testclient import TestClient

    # Seed test data
    with get_db() as conn:
        # Bot A: one winning closed trade
        conn.execute(
            """
            INSERT INTO alpaca_trades (
                bot_id, timestamp, symbol, asset_class, side, qty,
                entry_price, mirofish_prob, status, pnl, closed_at
            ) VALUES ('A', '2026-01-01T00:00:00Z', 'BTC/USD', 'crypto', 'buy',
                      0.01, 80000.0, 0.65, 'closed', 500.0, '2026-01-02T00:00:00Z')
            ON CONFLICT DO NOTHING
            """
        )
        # Bot B: one losing closed trade, one open trade
        conn.execute(
            """
            INSERT INTO alpaca_trades (
                bot_id, timestamp, symbol, asset_class, side, qty,
                entry_price, mirofish_prob, status, pnl, closed_at
            ) VALUES ('B', '2026-01-01T00:00:00Z', 'ETH/USD', 'crypto', 'buy',
                      0.1, 3000.0, 0.55, 'closed', -100.0, '2026-01-02T00:00:00Z')
            ON CONFLICT DO NOTHING
            """
        )
        conn.execute(
            """
            INSERT INTO alpaca_trades (
                bot_id, timestamp, symbol, asset_class, side, qty,
                entry_price, mirofish_prob, status
            ) VALUES ('B', '2026-01-03T00:00:00Z', 'SOL/USD', 'crypto', 'buy',
                      1.0, 150.0, 0.60, 'open')
            ON CONFLICT DO NOTHING
            """
        )
        # Bot A: one validation/veto
        conn.execute(
            """
            INSERT INTO validations (
                bot_id, timestamp, kalshi_ticker, event_title,
                mirofish_prob, kalshi_price, gap, proposed_side, decision, veto_reason
            ) VALUES ('A', '2026-01-01T00:00:00Z', 'TEST-TICK', 'Test Event',
                      0.7, 0.5, 0.2, 'yes', 'VETO', 'too risky')
            ON CONFLICT DO NOTHING
            """
        )

    return TestClient(app)


# ── /api/portfolio ──────────────────────────────────────────────────────────

def test_portfolio_both_returns_keyed_shape(client):
    r = client.get("/api/portfolio?bot=both")
    assert r.status_code == 200
    d = r.json()["data"]
    assert "A" in d and "B" in d
    assert "equity" in d["A"]
    assert "equity" in d["B"]


def test_portfolio_single_bot_returns_flat_shape(client):
    r = client.get("/api/portfolio?bot=A")
    assert r.status_code == 200
    d = r.json()["data"]
    assert "equity" in d
    assert "A" not in d  # flat shape, not keyed
    assert d["wins"] >= 1  # seeded one win for Bot A


def test_portfolio_bot_b_has_loss(client):
    r = client.get("/api/portfolio?bot=B")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["losses"] >= 1


# ── /api/equity ──────────────────────────────────────────────────────────────

def test_equity_both_returns_two_series(client):
    r = client.get("/api/equity?bot=both")
    assert r.status_code == 200
    series = r.json()["data"]["series"]
    assert len(series) == 2
    bot_ids = {s["bot_id"] for s in series}
    assert bot_ids == {"A", "B"}


def test_equity_has_return_pct_field(client):
    r = client.get("/api/equity?bot=A")
    assert r.status_code == 200
    series = r.json()["data"]["series"]
    assert len(series) == 1
    point = series[0]["points"][0]
    assert "return_pct" in point
    assert "equity" in point


def test_equity_return_pct_positive_for_winning_bot(client):
    r = client.get("/api/equity?bot=A")
    series = r.json()["data"]["series"]
    last_point = series[0]["points"][-1]
    assert last_point["return_pct"] > 0  # Bot A has a $500 win


# ── /api/bots ─────────────────────────────────────────────────────────────────

def test_bots_returns_both_bots(client):
    r = client.get("/api/bots")
    assert r.status_code == 200
    bots = r.json()["data"]
    assert len(bots) == 2
    ids = {b["id"] for b in bots}
    assert ids == {"A", "B"}


def test_bots_have_required_fields(client):
    r = client.get("/api/bots")
    bots = r.json()["data"]
    for bot in bots:
        assert "id" in bot
        assert "label" in bot
        assert "starting_equity" in bot


# ── /api/positions ───────────────────────────────────────────────────────────

def test_open_positions_returns_bot_b_open_trade(client):
    r = client.get("/api/positions/open?bot=both")
    assert r.status_code == 200
    positions = r.json()["data"]
    symbols = [p["symbol"] for p in positions]
    assert "SOL/USD" in symbols  # seeded open trade for Bot B


def test_open_positions_filtered_by_bot(client):
    r = client.get("/api/positions/open?bot=A")
    assert r.status_code == 200
    positions = r.json()["data"]
    # Bot A has no open trades in seed data
    assert not any(p["symbol"] == "SOL/USD" for p in positions)


# ── /api/health ──────────────────────────────────────────────────────────────

def test_health_returns_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
