# tests/test_universe_resolution.py
"""Crypto universe resolution: curated list preferred, dynamic only as fallback."""

import src.bot_thread as bot_thread
from src.bot_config import BotConfig


def _cfg(crypto_universe: str) -> BotConfig:
    return BotConfig(
        bot_id="A",
        label="Agent A",
        alpaca_api_key="key",
        alpaca_secret_key="secret",
        crypto_universe=crypto_universe,
        asset_class="crypto",
    )


def test_curated_universe_preferred_dynamic_not_called(monkeypatch):
    """A non-empty curated crypto universe is used verbatim; dynamic not called."""
    called = {"dynamic": False}

    def _stub(*args, **kwargs):
        called["dynamic"] = True
        return ["GRT/USD", "ARB/USD"]

    monkeypatch.setattr(bot_thread, "get_dynamic_crypto_universe", _stub)

    cfg = _cfg("BTC/USD,ETH/USD,SOL/USD")
    universe = bot_thread._resolve_crypto_universe(cfg, alpaca=object(), bot_id="A")

    assert universe == ["BTC/USD", "ETH/USD", "SOL/USD"]
    assert called["dynamic"] is False


def test_empty_universe_falls_back_to_dynamic(monkeypatch):
    """An empty curated list falls back to the dynamic universe stub."""
    called = {"dynamic": False}

    def _stub(alpaca, top_n):
        called["dynamic"] = True
        return ["BTC/USD", "ETH/USD"]

    monkeypatch.setattr(bot_thread, "get_dynamic_crypto_universe", _stub)

    cfg = _cfg("")
    universe = bot_thread._resolve_crypto_universe(cfg, alpaca=object(), bot_id="A")

    assert universe == ["BTC/USD", "ETH/USD"]
    assert called["dynamic"] is True
