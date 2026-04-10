"""
Smoke tests for src/db.py.

Skipped unless DATABASE_URL env var is set pointing to a real Postgres instance.
"""
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping Postgres smoke tests",
)


def test_log_and_query_alpaca_trade():
    from src import db

    trade_id = db.log_alpaca_trade("A", {
        "symbol": "BTC/USD",
        "asset_class": "crypto",
        "side": "buy",
        "qty": 0.001,
        "entry_price": 80000.0,
        "mirofish_prob": 0.65,
    })
    assert isinstance(trade_id, int)
    assert trade_id > 0

    positions = db.get_open_alpaca_positions("A")
    assert any(p["id"] == trade_id for p in positions)

    db.update_alpaca_trade("A", trade_id, "closed", exit_price=82000.0, pnl=200.0)

    stats = db.get_alpaca_accuracy("A")
    assert stats["resolved"] >= 1
    assert stats["wins"] >= 1


def test_log_validation():
    from src import db

    val_id = db.log_validation("B", {
        "kalshi_ticker": "TEST-TICK",
        "event_title": "Test Event",
        "mirofish_prob": 0.7,
        "kalshi_price": 0.5,
        "gap": 0.2,
        "proposed_side": "yes",
        "decision": "VETO",
        "veto_reason": "too risky",
    })
    assert isinstance(val_id, int)

    vetos = db.get_veto_history("B", last_n=10)
    assert any(v["id"] == val_id for v in vetos)
