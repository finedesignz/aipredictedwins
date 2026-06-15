"""
Fail-clear regression test for AlpacaClient (BOT-01 / D-01).

When the orchestrator runs with empty bare ALPACA_API_KEY/ALPACA_SECRET_KEY,
AlpacaClient must raise ValueError naming the keys — it must NEVER silently
substitute another bot's (A/B) credentials. Each bot service supplies its own
bare keys; empty keys are an operator error that must fail loudly.

No network client is constructed: the empty-key guard fires before any
alpaca-py TradingClient is built, so this test needs no live SDK behavior.
"""
import types

import pytest

from src.alpaca_client import AlpacaClient


def _cfg(api_key: str, secret_key: str) -> types.SimpleNamespace:
    """Minimal Config stand-in exposing only what _init_clients reads."""
    return types.SimpleNamespace(
        alpaca_api_key=api_key,
        alpaca_secret_key=secret_key,
        alpaca_env="paper",
    )


def test_empty_both_keys_raises():
    with pytest.raises(ValueError, match="ALPACA_API_KEY"):
        AlpacaClient(_cfg("", ""))


def test_empty_api_key_raises():
    with pytest.raises(ValueError, match="ALPACA_API_KEY"):
        AlpacaClient(_cfg("", "secret"))


def test_empty_secret_key_raises():
    with pytest.raises(ValueError, match="ALPACA_API_KEY"):
        AlpacaClient(_cfg("key", ""))
