# src/bot_config.py
"""Per-bot configuration loaded from the bots DB row."""

from dataclasses import dataclass


@dataclass
class BotConfig:
    """Immutable snapshot of one bot's configuration.

    Constructed from a bots table row by BotManager.
    Replaced atomically when PUT /api/bots/{bot_id} is called.
    """
    bot_id: str
    label: str
    alpaca_api_key: str
    alpaca_secret_key: str
    kelly_fraction: float = 0.25
    min_confluence: int = 3
    hard_stop_pct: float = -0.08
    soft_stop_pct: float = -0.05
    rsi_ceiling: float = 65.0
    crypto_universe: str = "BTC/USD,ETH/USD,SOL/USD,XRP/USD"
    skip_risk_gate: bool = False
    max_position_pct: float = 0.05

    @classmethod
    def from_row(cls, row: dict) -> "BotConfig":
        """Construct from a psycopg3 dict_row from the bots table."""
        return cls(
            bot_id=row["bot_id"],
            label=row["label"],
            alpaca_api_key=row.get("alpaca_api_key") or "",
            alpaca_secret_key=row.get("alpaca_secret_key") or "",
            kelly_fraction=float(row.get("kelly_fraction") or 0.25),
            min_confluence=int(row.get("min_confluence") or 3),
            hard_stop_pct=float(row.get("hard_stop_pct") or -0.08),
            soft_stop_pct=float(row.get("soft_stop_pct") or -0.05),
            rsi_ceiling=float(row.get("rsi_ceiling") or 65.0),
            crypto_universe=row.get("crypto_universe") or "BTC/USD,ETH/USD,SOL/USD,XRP/USD",
            skip_risk_gate=bool(row.get("skip_risk_gate") or False),
            max_position_pct=float(row.get("max_position_pct") or 0.05),
        )

    @property
    def symbols(self) -> list[str]:
        """Parse crypto_universe string into a list of symbols."""
        return [s.strip() for s in self.crypto_universe.split(",") if s.strip()]
