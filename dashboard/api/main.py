"""
FastAPI application for the AI Predicted Wins trading dashboard.

Read-only API that serves portfolio data, positions, trades, signals,
risk gate decisions, settings, and a live SSE activity stream. All data
is read from the shared SQLite database written by the trading bot.

Run locally:
    uvicorn dashboard.api.main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import (
    activity,
    portfolio,
    positions,
    risk_gate,
    settings,
    signals,
    trades,
)

app = FastAPI(
    title="AI Predicted Wins Dashboard API",
    description="Read-only trading dashboard API for the Alpaca crypto bot.",
    version="1.0.0",
)

# -- CORS (allow all origins for development) --------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- Mount route modules ------------------------------------------------------
app.include_router(portfolio.router)
app.include_router(positions.router)
app.include_router(trades.router)
app.include_router(signals.router)
app.include_router(risk_gate.router)
app.include_router(settings.router)
app.include_router(activity.router)


@app.get("/api/health")
def health_check():
    """Simple health check endpoint."""
    return {"status": "ok"}
