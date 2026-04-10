"""
FastAPI application for the AI Predicted Wins trading dashboard.

Read-only API that serves portfolio data, positions, trades, signals,
risk gate decisions, settings, and a live SSE activity stream. All data
is read from the shared SQLite database written by the trading bot.

Authentication: Set DASHBOARD_TOKEN env var. The frontend sends it as
a Bearer token. Without it, all API routes return 401.
"""

import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from routes import (
    activity,
    alpaca,
    benchmark,
    benchmark_btc,
    bots,
    equity,
    portfolio,
    positions,
    risk_gate,
    settings,
    signals,
    trades,
)

DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN", "")

app = FastAPI(
    title="AI Predicted Wins Dashboard API",
    description="Read-only trading dashboard API for the Alpaca crypto bot.",
    version="1.0.0",
)

# -- CORS --------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- Auth middleware ----------------------------------------------------------
security = HTTPBearer(auto_error=False)


async def verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    """Verify the Bearer token matches DASHBOARD_TOKEN.

    If DASHBOARD_TOKEN is not set, auth is disabled (dev mode).
    """
    if not DASHBOARD_TOKEN:
        return  # no token configured = auth disabled

    # Allow health check without auth
    if request.url.path == "/api/health":
        return

    # Check cookie first (set by login page)
    token_cookie = request.cookies.get("dashboard_token")
    if token_cookie == DASHBOARD_TOKEN:
        return

    # Check Bearer header (for API clients)
    if credentials and credentials.credentials == DASHBOARD_TOKEN:
        return

    raise HTTPException(status_code=401, detail="Unauthorized")


# -- Login / logout endpoints (no auth required) ------------------------------
@app.post("/api/auth/login")
async def login(request: Request):
    """Validate token and set auth cookie."""
    body = await request.json()
    token = body.get("token", "")

    if not DASHBOARD_TOKEN:
        return {"success": True, "message": "Auth disabled"}

    if token != DASHBOARD_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    from fastapi.responses import JSONResponse
    response = JSONResponse({"success": True})
    response.set_cookie(
        key="dashboard_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=60 * 60 * 24 * 30,  # 30 days
    )
    return response


@app.get("/api/auth/check")
async def check_auth(request: Request):
    """Check if the current session is authenticated."""
    if not DASHBOARD_TOKEN:
        return {"authenticated": True}

    token_cookie = request.cookies.get("dashboard_token")
    if token_cookie == DASHBOARD_TOKEN:
        return {"authenticated": True}

    return {"authenticated": False}


@app.post("/api/auth/logout")
async def logout():
    """Clear the auth cookie."""
    from fastapi.responses import JSONResponse
    response = JSONResponse({"success": True})
    response.delete_cookie("dashboard_token")
    return response


# -- Mount route modules (all require auth) -----------------------------------
app.include_router(alpaca.router, dependencies=[Depends(verify_token)])
app.include_router(benchmark.router, dependencies=[Depends(verify_token)])
app.include_router(benchmark_btc.router, dependencies=[Depends(verify_token)])
app.include_router(bots.router, dependencies=[Depends(verify_token)])
app.include_router(equity.router, dependencies=[Depends(verify_token)])
app.include_router(portfolio.router, dependencies=[Depends(verify_token)])
app.include_router(positions.router, dependencies=[Depends(verify_token)])
app.include_router(trades.router, dependencies=[Depends(verify_token)])
app.include_router(signals.router, dependencies=[Depends(verify_token)])
app.include_router(risk_gate.router, dependencies=[Depends(verify_token)])
app.include_router(settings.router, dependencies=[Depends(verify_token)])
app.include_router(activity.router, dependencies=[Depends(verify_token)])


@app.get("/api/health")
def health_check():
    """Simple health check endpoint (no auth required)."""
    try:
        from db import get_db
        with get_db() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "database": "postgres"}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}
