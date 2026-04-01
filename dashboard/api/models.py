"""
Pydantic response models for the trading dashboard API.

All endpoints return a standard envelope:
    {"data": ..., "meta": {"timestamp": "...", "count": N}}
"""

from datetime import datetime, timezone
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# -- Envelope ----------------------------------------------------------------

class Meta(BaseModel):
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    count: Optional[int] = None


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: Meta = Field(default_factory=Meta)


# -- Portfolio ----------------------------------------------------------------

class PortfolioData(BaseModel):
    equity: float = 0.0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    open_positions: int = 0
    daily_pnl: float = 0.0
    trades_resolved: int = 0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0


# -- Positions ----------------------------------------------------------------

class OpenPosition(BaseModel):
    id: int
    timestamp: str
    symbol: str
    asset_class: str
    side: str
    qty: float
    entry_price: float
    mirofish_prob: float
    market_sentiment: Optional[str] = None
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    status: str
    simulation_id: Optional[str] = None
    notes: Optional[str] = None


class ClosedPosition(BaseModel):
    id: int
    timestamp: str
    symbol: str
    asset_class: str
    side: str
    qty: float
    entry_price: float
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    mirofish_prob: float
    market_sentiment: Optional[str] = None
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    status: str
    closed_at: Optional[str] = None
    simulation_id: Optional[str] = None
    notes: Optional[str] = None


# -- Trades -------------------------------------------------------------------

class TradeRecord(BaseModel):
    id: int
    timestamp: str
    symbol: str
    asset_class: str
    side: str
    qty: float
    entry_price: float
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    mirofish_prob: float
    market_sentiment: Optional[str] = None
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    status: str
    closed_at: Optional[str] = None
    simulation_id: Optional[str] = None
    notes: Optional[str] = None


# -- Signals ------------------------------------------------------------------

class SignalRecord(BaseModel):
    symbol: str
    ema_bullish: bool
    adx_value: float
    rsi_value: float
    volume_spike: bool
    vwap_bullish: bool
    confluence_score: int


# -- Risk Gate ----------------------------------------------------------------

class RiskGateRecord(BaseModel):
    id: int
    timestamp: str
    symbol: str
    event_title: str
    confluence: float
    decision: str
    confidence: Optional[float] = None
    risk_assessment: Optional[str] = None
    veto_reason: Optional[str] = None
    proposed_side: Optional[str] = None
    mirofish_prob: Optional[float] = None


class RiskGateDetail(RiskGateRecord):
    kalshi_price: Optional[float] = None
    gap: Optional[float] = None
    adjusted_probability: Optional[float] = None
    size_multiplier: Optional[float] = None
    sentiment_report: Optional[str] = None
    news_report: Optional[str] = None
    contrarian_report: Optional[str] = None
    trade_id: Optional[int] = None


# -- Settings -----------------------------------------------------------------

class BotConfig(BaseModel):
    max_position_pct: float = 0.05
    max_simultaneous_positions: int = 5
    drawdown_stop_pct: float = 0.10
    min_paper_trades: int = 50
    min_win_rate: float = 0.40
    min_confluence: int = 3
    kelly_fraction: float = 0.25
    starting_bankroll: float = 1000.0
    live_trading_threshold: float = 100000.0
    hard_stop_pct: float = -0.04
    hard_take_profit_pct: float = 0.10
    soft_stop_pct: float = -0.02
    asset_universe: list[str] = [
        "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD",
        "ADA/USD", "AVAX/USD", "DOT/USD", "LINK/USD",
    ]


class SystemHealth(BaseModel):
    claude_cli: str = "unknown"
    alpaca_api: str = "unknown"
    db_size_mb: float = 0.0


class PaperProgress(BaseModel):
    total_trades: int = 0
    target_trades: int = 50
    win_rate: float = 0.0
    target_win_rate: float = 0.40
    equity: float = 0.0
    target_equity: float = 100000.0
    ready_for_live: bool = False


class SettingsData(BaseModel):
    config: BotConfig = Field(default_factory=BotConfig)
    health: SystemHealth = Field(default_factory=SystemHealth)
    paper_progress: PaperProgress = Field(default_factory=PaperProgress)


# -- Activity SSE -------------------------------------------------------------

class ActivityEvent(BaseModel):
    type: str
    data: dict[str, Any]
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
