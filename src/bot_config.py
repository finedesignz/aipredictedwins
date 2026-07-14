# src/bot_config.py
"""Per-bot configuration loaded from the bots DB row."""

from dataclasses import dataclass


@dataclass(frozen=True)
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
    min_confluence: int = 4
    hard_stop_pct: float = -0.08
    soft_stop_pct: float = -0.05
    rsi_ceiling: float = 65.0
    crypto_universe: str = "BTC/USD,ETH/USD,SOL/USD,XRP/USD,ADA/USD,AVAX/USD,DOT/USD,LINK/USD"
    stock_universe: str = "SPY,QQQ,NVDA,AAPL,MSFT,TSLA,META,AMZN,GOOGL,AMD,COIN,MSTR"
    asset_class: str = "crypto"   # "crypto" or "stock"
    skip_risk_gate: bool = False
    max_position_pct: float = 0.05
    short_enabled: bool = True
    dynamic_universe_size: int = 8
    min_short_confluence: int = 3
    tradingagents_enabled: bool = False
    # Strategy mode: "confluence" (default, technical scalper) | "trend_btc" (50DMA trend follower on BITX)
    strategy: str = "confluence"
    trend_ma_window: int = 50
    trend_symbol: str = "BITX"   # 2x BTC ETF; can swap to IBIT (1x) or ETHU (2x ETH)
    trend_benchmark: str = "BTC/USD"  # asset whose MA we follow
    # Phase 15 (UNIV-02): comma-separated deny-list. Same format as crypto_universe
    # ("BTC/USD" — a bare "BTC" will NOT match). Empty = nothing quarantined.
    quarantined_symbols: str = ""

    @classmethod
    def from_row(cls, row: dict) -> "BotConfig":
        """Construct from a psycopg3 dict_row from the bots table."""
        return cls(
            bot_id=row["bot_id"],
            label=row["label"],
            alpaca_api_key=row.get("alpaca_api_key") or "",
            alpaca_secret_key=row.get("alpaca_secret_key") or "",
            # READ-SIDE CLAMP: quarter-Kelly is a hardcoded ceiling (CLAUDE.md risk
            # rules). Rows written before the write-side bounds existed (Bot B's 0.50)
            # must be clamped here, not merely rejected at write — from_row is the
            # single choke point every bot reads through.
            kelly_fraction=min(float(row["kelly_fraction"] if row.get("kelly_fraction") is not None else 0.25), 0.25),
            min_confluence=int(row["min_confluence"] if row.get("min_confluence") is not None else 4),
            hard_stop_pct=float(row["hard_stop_pct"] if row.get("hard_stop_pct") is not None else -0.08),
            soft_stop_pct=float(row["soft_stop_pct"] if row.get("soft_stop_pct") is not None else -0.05),
            rsi_ceiling=float(row["rsi_ceiling"] if row.get("rsi_ceiling") is not None else 65.0),
            crypto_universe=row.get("crypto_universe") or "BTC/USD,ETH/USD,SOL/USD,XRP/USD,ADA/USD,AVAX/USD,DOT/USD,LINK/USD",
            stock_universe=row.get("stock_universe") or "SPY,QQQ,NVDA,AAPL,MSFT,TSLA,META,AMZN,GOOGL,AMD,COIN,MSTR",
            asset_class=row.get("asset_class") or "crypto",
            skip_risk_gate=bool(row.get("skip_risk_gate") or False),
            max_position_pct=float(row["max_position_pct"] if row.get("max_position_pct") is not None else 0.05),
            short_enabled=bool(row.get("short_enabled") if row.get("short_enabled") is not None else True),
            dynamic_universe_size=int(row["dynamic_universe_size"] if row.get("dynamic_universe_size") is not None else 8),
            min_short_confluence=int(row["min_short_confluence"] if row.get("min_short_confluence") is not None else 3),
            tradingagents_enabled=bool(row.get("tradingagents_enabled") or False),
            strategy=row.get("strategy") or "confluence",
            trend_ma_window=int(row["trend_ma_window"] if row.get("trend_ma_window") is not None else 50),
            trend_symbol=row.get("trend_symbol") or "BITX",
            trend_benchmark=row.get("trend_benchmark") or "BTC/USD",
            # A pre-migration row (key absent) yields "" -> [] -> nothing quarantined.
            quarantined_symbols=row.get("quarantined_symbols") or "",
        )

    @property
    def symbols(self) -> list[str]:
        """Return the active symbol list based on asset_class."""
        if self.asset_class == "stock":
            return [s.strip() for s in self.stock_universe.split(",") if s.strip()]
        return [s.strip() for s in self.crypto_universe.split(",") if s.strip()]

    @property
    def quarantined(self) -> list[str]:
        """Flat, asset-class-AGNOSTIC deny-list (Phase 15, UNIV-02)."""
        return [s.strip() for s in self.quarantined_symbols.split(",") if s.strip()]

    @property
    def all_symbols(self) -> list[str]:
        """UNION of crypto_universe and stock_universe (deduped, order-stable).

        The COPYTRADE allowlist: Bot E mirrors a leader across asset classes, so
        `symbols` (a single asset class) would wrongly block half its legitimate
        trades. TRUMP/FIL are in neither universe, so the leak still closes.
        """
        merged: list[str] = []
        seen: set[str] = set()
        for raw in (self.crypto_universe, self.stock_universe):
            for s in raw.split(","):
                s = s.strip()
                if s and s not in seen:
                    seen.add(s)
                    merged.append(s)
        return merged
