"""
Configuration management for the Kalshi + MiroFish + Alpaca trading system.

Loads environment variables from .env, validates required keys,
and provides typed access via a Config dataclass.

Alpaca fields are optional -- the system runs in Kalshi-only mode
when ALPACA_API_KEY / ALPACA_SECRET_KEY are absent.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEMO_HOST = "https://demo-api.kalshi.co/trade-api/v2"
_PROD_HOST = "https://api.elections.kalshi.com/trade-api/v2"

_ALPACA_PAPER_HOST = "https://paper-api.alpaca.markets"
_ALPACA_LIVE_HOST = "https://api.alpaca.markets"

# Alpaca bot only needs ALPACA_API_KEY + ALPACA_SECRET_KEY.
# Kalshi/LLM/Zep keys are optional (v1 legacy, paused).
_REQUIRED_KEYS: list[str] = []


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Config:
    """Typed, immutable configuration for the trading system."""

    # --- Kalshi ---
    kalshi_api_key_id: str = ""
    kalshi_private_key_path: str = ""
    kalshi_env: str = "demo"  # "demo" | "prod"

    # --- LLM ---
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model_name: str = ""

    # --- Memory ---
    zep_api_key: str = ""

    # --- Trading parameters ---
    min_gap_threshold: float = 0.15
    max_position_pct: float = 0.05
    kelly_fraction: float = 0.25
    min_market_volume: int = 10_000
    max_correlated_positions: int = 3
    drawdown_stop_pct: float = 0.20
    starting_bankroll: float = 1000.0

    # --- MiroFish simulation ---
    mirofish_agent_count: int = 1000
    mirofish_rounds: int = 30
    mirofish_backend_url: str = "http://localhost:5001"

    # --- TradingAgents Gate (optional) ---
    tradingagents_enabled: bool = False
    tradingagents_veto_is_final: bool = True

    # --- Quick Screening (optional) ---
    quick_sim_enabled: bool = False
    quick_sim_min_gap: float = 0.10
    max_quick_screen: int = 50

    # --- Alpaca (optional) ---
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_env: str = "paper"  # "paper" | "live"

    @property
    def kalshi_api_host(self) -> str:
        """Return the Kalshi API base URL for the configured environment."""
        if self.kalshi_env == "prod":
            return _PROD_HOST
        return _DEMO_HOST

    @property
    def alpaca_api_host(self) -> str:
        """Return the Alpaca API base URL for the configured environment."""
        if self.alpaca_env == "live":
            return _ALPACA_LIVE_HOST
        return _ALPACA_PAPER_HOST

    @property
    def alpaca_enabled(self) -> bool:
        """Return True if Alpaca credentials are configured."""
        return bool(self.alpaca_api_key and self.alpaca_secret_key)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------
def _env(key: str, default=None):
    """Fetch an env var, returning *default* when the key is absent."""
    return os.environ.get(key, default)


def load_config(env_path: str | Path | None = None) -> Config:
    """Load configuration from .env, validate, and return a Config instance.

    Parameters
    ----------
    env_path : str | Path | None
        Explicit path to a .env file.  When *None* python-dotenv walks up
        from the working directory to find one automatically.
    """
    if env_path is not None:
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()

    # --- Validate required keys -------------------------------------------
    missing = [k for k in _REQUIRED_KEYS if not os.environ.get(k)]
    if missing:
        print(
            f"[config] FATAL  Missing required environment variables:\n"
            + "\n".join(f"  - {k}" for k in missing),
            file=sys.stderr,
        )
        sys.exit(1)

    # --- Build Config -----------------------------------------------------
    return Config(
        kalshi_api_key_id=_env("KALSHI_API_KEY_ID"),
        kalshi_private_key_path=_env("KALSHI_PRIVATE_KEY_PATH"),
        kalshi_env=_env("KALSHI_ENV", "demo"),
        llm_api_key=_env("LLM_API_KEY"),
        llm_base_url=_env("LLM_BASE_URL"),
        llm_model_name=_env("LLM_MODEL_NAME"),
        zep_api_key=_env("ZEP_API_KEY"),
        min_gap_threshold=float(_env("MIN_GAP_THRESHOLD", "0.15")),
        max_position_pct=float(_env("MAX_POSITION_PCT", "0.05")),
        kelly_fraction=float(_env("KELLY_FRACTION", "0.25")),
        min_market_volume=int(_env("MIN_MARKET_VOLUME", "10000")),
        max_correlated_positions=int(_env("MAX_CORRELATED_POSITIONS", "3")),
        drawdown_stop_pct=float(_env("DRAWDOWN_STOP_PCT", "0.20")),
        starting_bankroll=float(_env("STARTING_BANKROLL", "1000.0")),
        mirofish_agent_count=int(_env("MIROFISH_AGENT_COUNT", "1000")),
        mirofish_rounds=int(_env("MIROFISH_ROUNDS", "30")),
        mirofish_backend_url=_env("MIROFISH_BACKEND_URL", "http://localhost:5001"),
        tradingagents_enabled=_env("TRADINGAGENTS_ENABLED", "false").lower() in ("true", "1", "yes"),
        tradingagents_veto_is_final=_env("TRADINGAGENTS_VETO_IS_FINAL", "true").lower() in ("true", "1", "yes"),
        quick_sim_enabled=_env("QUICK_SIM_ENABLED", "false").lower() in ("true", "1", "yes"),
        quick_sim_min_gap=float(_env("QUICK_SIM_MIN_GAP", "0.10")),
        max_quick_screen=int(_env("MAX_QUICK_SCREEN", "50")),
        alpaca_api_key=_env("ALPACA_API_KEY", ""),
        alpaca_secret_key=_env("ALPACA_SECRET_KEY", ""),
        alpaca_env=_env("ALPACA_ENV", "paper"),
    )
