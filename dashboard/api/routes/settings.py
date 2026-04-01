"""
Settings endpoint.

GET /api/settings -- bot config, system health, paper trading progress.

Config values are hardcoded from the orchestrator constants. System health
is placeholder until health-check probes are wired. Paper progress reads
from alpaca_trades to compute trade count and win rate.
"""

import os

from fastapi import APIRouter

from db import DB_PATH, get_db
from models import (
    BotConfig,
    Envelope,
    Meta,
    PaperProgress,
    SettingsData,
    SystemHealth,
)

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings", response_model=Envelope[SettingsData])
def get_settings():
    """Return bot configuration, system health, and paper trading progress."""

    # -- Config (hardcoded from src/alpaca_orchestrator.py constants) --------
    config = BotConfig(
        max_position_pct=0.05,
        max_simultaneous_positions=5,
        drawdown_stop_pct=0.10,
        min_paper_trades=50,
        min_win_rate=0.40,
        min_confluence=3,
        kelly_fraction=0.25,
        starting_bankroll=1000.0,
        live_trading_threshold=float(
            os.environ.get("LIVE_TRADING_THRESHOLD", "100000")
        ),
        hard_stop_pct=-0.04,
        hard_take_profit_pct=0.10,
        soft_stop_pct=-0.02,
        asset_universe=[
            "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD",
            "ADA/USD", "AVAX/USD", "DOT/USD", "LINK/USD",
        ],
    )

    # -- System health (placeholders until probes are added) ----------------
    db_size_mb = 0.0
    try:
        db_size_mb = round(os.path.getsize(DB_PATH) / (1024 * 1024), 2)
    except OSError:
        pass

    health = SystemHealth(
        claude_cli="unknown",
        alpaca_api="unknown",
        db_size_mb=db_size_mb,
    )

    # -- Paper trading progress (computed from alpaca_trades) ---------------
    with get_db() as conn:
        total_trades = conn.execute(
            "SELECT COUNT(*) FROM alpaca_trades"
        ).fetchone()[0]

        closed_rows = conn.execute(
            """
            SELECT pnl FROM alpaca_trades
            WHERE status IN ('closed', 'stopped', 'target_hit')
            """
        ).fetchall()

        resolved = len(closed_rows)
        wins = sum(1 for r in closed_rows if (r["pnl"] or 0) > 0)
        total_pnl = sum(r["pnl"] or 0.0 for r in closed_rows)
        win_rate = wins / resolved if resolved > 0 else 0.0
        equity = config.starting_bankroll + total_pnl

        ready = (
            total_trades >= config.min_paper_trades
            and win_rate >= config.min_win_rate
            and equity >= config.live_trading_threshold
        )

    progress = PaperProgress(
        total_trades=total_trades,
        target_trades=config.min_paper_trades,
        win_rate=win_rate,
        target_win_rate=config.min_win_rate,
        equity=equity,
        target_equity=config.live_trading_threshold,
        ready_for_live=ready,
    )

    data = SettingsData(
        config=config,
        health=health,
        paper_progress=progress,
    )
    return Envelope(data=data, meta=Meta(count=1))
