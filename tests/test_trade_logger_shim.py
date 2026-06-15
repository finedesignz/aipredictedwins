"""
Tests for the TradeLogger shim.

The BOT_ID validation tests run always (no DB needed).
src.db is mocked at the sys.modules level so psycopg_pool / DATABASE_URL are
never needed.
"""
import sys
import types
import pytest


def _make_fake_db():
    """Return a minimal fake src.db module (all functions are no-ops)."""
    fake = types.ModuleType("src.db")
    for fn in (
        "log_alpaca_trade", "update_alpaca_trade", "get_open_alpaca_positions",
        "get_alpaca_accuracy", "log_trade", "update_trade", "get_accuracy",
        "get_daily_summary", "get_simulated_tickers_today", "log_simulation",
        "log_validation", "log_screening", "get_veto_history", "connection",
    ):
        setattr(fake, fn, lambda *a, **kw: None)
    return fake


@pytest.fixture(autouse=True)
def mock_src_db():
    """Patch src.db in sys.modules before each test; restore afterwards."""
    original = sys.modules.get("src.db")
    sys.modules["src.db"] = _make_fake_db()
    # Force re-import of trade_logger so it picks up the stub
    sys.modules.pop("src.trade_logger", None)
    yield
    # Restore
    sys.modules.pop("src.trade_logger", None)
    if original is None:
        sys.modules.pop("src.db", None)
    else:
        sys.modules["src.db"] = original


def test_missing_bot_id_raises(monkeypatch):
    monkeypatch.delenv("BOT_ID", raising=False)
    from src.trade_logger import TradeLogger
    with pytest.raises(ValueError, match="BOT_ID"):
        TradeLogger()


def test_invalid_bot_id_raises(monkeypatch):
    # C/D are now valid; use a value outside KNOWN_BOT_IDS.
    monkeypatch.setenv("BOT_ID", "Z")
    from src.trade_logger import TradeLogger
    with pytest.raises(ValueError, match="BOT_ID"):
        TradeLogger()


def test_valid_bot_id_d(monkeypatch):
    monkeypatch.setenv("BOT_ID", "D")
    from src.trade_logger import TradeLogger
    logger = TradeLogger()
    assert logger.bot_id == "D"


def test_lowercase_bot_id_normalized(monkeypatch):
    monkeypatch.setenv("BOT_ID", "d")
    from src.trade_logger import TradeLogger
    logger = TradeLogger()
    assert logger.bot_id == "D"


def test_valid_bot_id_a(monkeypatch):
    monkeypatch.setenv("BOT_ID", "A")
    from src.trade_logger import TradeLogger
    logger = TradeLogger()
    assert logger.bot_id == "A"


def test_valid_bot_id_b(monkeypatch):
    monkeypatch.setenv("BOT_ID", "B")
    from src.trade_logger import TradeLogger
    logger = TradeLogger()
    assert logger.bot_id == "B"
