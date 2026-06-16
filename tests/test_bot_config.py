# tests/test_bot_config.py
from src.bot_config import BotConfig


def test_from_row_defaults():
    """None values in DB row fall back to defaults."""
    row = {
        "bot_id": "A", "label": "Agent A",
        "alpaca_api_key": "key", "alpaca_secret_key": "secret",
        "kelly_fraction": None, "min_confluence": None,
        "hard_stop_pct": None, "soft_stop_pct": None,
        "rsi_ceiling": None, "crypto_universe": None,
        "skip_risk_gate": None, "max_position_pct": None,
    }
    cfg = BotConfig.from_row(row)
    assert cfg.bot_id == "A"
    assert cfg.label == "Agent A"
    assert cfg.alpaca_api_key == "key"
    assert cfg.kelly_fraction == 0.25
    assert cfg.min_confluence == 4
    assert cfg.hard_stop_pct == -0.08
    assert cfg.soft_stop_pct == -0.05
    assert cfg.rsi_ceiling == 65.0
    assert cfg.skip_risk_gate is False
    assert cfg.max_position_pct == 0.05
    assert cfg.symbols == [
        "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD",
        "ADA/USD", "AVAX/USD", "DOT/USD", "LINK/USD",
    ]


def test_from_row_custom():
    """Explicit values in DB row are used as-is."""
    row = {
        "bot_id": "B", "label": "Agent B",
        "alpaca_api_key": "k2", "alpaca_secret_key": "s2",
        "kelly_fraction": 0.5, "min_confluence": 2,
        "hard_stop_pct": -0.10, "soft_stop_pct": -0.06,
        "rsi_ceiling": 70.0, "crypto_universe": "BTC/USD,ETH/USD",
        "skip_risk_gate": True, "max_position_pct": 0.03,
    }
    cfg = BotConfig.from_row(row)
    assert cfg.kelly_fraction == 0.5
    assert cfg.min_confluence == 2
    assert cfg.hard_stop_pct == -0.10
    assert cfg.skip_risk_gate is True
    assert cfg.symbols == ["BTC/USD", "ETH/USD"]


def test_symbols_strips_whitespace():
    """Symbols property handles spaces around commas."""
    row = {
        "bot_id": "C", "label": "C",
        "alpaca_api_key": "", "alpaca_secret_key": "",
        "kelly_fraction": None, "min_confluence": None,
        "hard_stop_pct": None, "soft_stop_pct": None,
        "rsi_ceiling": None, "crypto_universe": " BTC/USD , ETH/USD , SOL/USD ",
        "skip_risk_gate": None, "max_position_pct": None,
    }
    cfg = BotConfig.from_row(row)
    assert cfg.symbols == ["BTC/USD", "ETH/USD", "SOL/USD"]


def test_empty_alpaca_keys():
    """Missing API keys produce empty strings, not None."""
    row = {
        "bot_id": "D", "label": "D",
        "alpaca_api_key": None, "alpaca_secret_key": None,
        "kelly_fraction": None, "min_confluence": None,
        "hard_stop_pct": None, "soft_stop_pct": None,
        "rsi_ceiling": None, "crypto_universe": None,
        "skip_risk_gate": None, "max_position_pct": None,
    }
    cfg = BotConfig.from_row(row)
    assert cfg.alpaca_api_key == ""
    assert cfg.alpaca_secret_key == ""


def test_zero_values_not_replaced_by_defaults():
    """Zero values for numeric fields must be kept, not swapped for defaults."""
    row = {
        "bot_id": "E", "label": "E",
        "alpaca_api_key": "k", "alpaca_secret_key": "s",
        "kelly_fraction": 0.0, "min_confluence": 0,
        "hard_stop_pct": 0.0, "soft_stop_pct": 0.0,
        "rsi_ceiling": 0.0, "crypto_universe": None,
        "skip_risk_gate": None, "max_position_pct": 0.0,
    }
    cfg = BotConfig.from_row(row)
    assert cfg.kelly_fraction == 0.0
    assert cfg.min_confluence == 0
    assert cfg.max_position_pct == 0.0
