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
    total_pnl_percent: float = 0.0
    win_rate: float = 0.0         # 0-100 percentage
    open_positions: int = 0
    daily_pnl: float = 0.0
    daily_pnl_percent: float = 0.0
    mode: str = "paper"
    trades_resolved: int = 0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0


# -- Positions ----------------------------------------------------------------

class OpenPosition(BaseModel):
    """Open position with fields mapped to match the frontend Position type."""
    id: int
    symbol: str
    side: str              # mapped to "long"/"short"
    entry_price: float
    current_price: float   # fallback to entry_price (no live data)
    quantity: float        # mapped from qty
    unrealized_pnl: float = 0.0
    unrealized_pnl_percent: float = 0.0
    confluence_score: float  # mapped from mirofish_prob * 5
    trailing_stop: Optional[float] = None
    opened_at: str         # mapped from timestamp
    bot: Optional[str] = None  # "Agent A" or "Agent B"


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
    bot: Optional[str] = None  # "Agent A" or "Agent B"


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

class HealthStatus(BaseModel):
    claude_cli: bool = True
    alpaca_api: bool = True
    sqlite_db: bool = True
    db_size_mb: float = 0.0


class SettingsData(BaseModel):
    """Flat structure matching the BotSettings frontend type."""
    mode: str = "paper"
    running: bool = True
    last_cycle: Optional[str] = None
    uptime_seconds: int = 0
    cycle_count: int = 0
    paper_trades_completed: int = 0
    paper_trades_target: int = 50
    win_rate: float = 0.0       # 0-100 percentage
    win_rate_target: float = 40.0
    equity: float = 0.0
    equity_target: float = 100000.0
    health: HealthStatus = Field(default_factory=HealthStatus)
    config: dict = Field(default_factory=dict)


# -- Activity SSE -------------------------------------------------------------

class ActivityEvent(BaseModel):
    type: str
    data: dict[str, Any]
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
