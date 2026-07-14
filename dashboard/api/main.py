"""
FastAPI application for the AI Predicted Wins trading dashboard.

Serves portfolio data, positions, trades, signals, risk gate decisions,
settings, a live SSE activity stream, full bot CRUD, and a Claude chat
SSE endpoint. All persistent data lives in Postgres.

Authentication: Set DASHBOARD_TOKEN env var. The frontend sends it as
a Bearer token. Without it, all API routes return 401.
"""

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from routes import (
    activity,
    alpaca,
    benchmark,
    bots,
    chat,
    equity,
    portfolio,
    positions,
    risk_gate,
    settings,
    signals,
    trades,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    force=True,
)
_log = logging.getLogger(__name__)

DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN", "")


def _alert_manager_never_started(reason: str) -> None:
    """Email that NO BOTS ARE RUNNING. Never raises — an alert failure must not take the
    API down, and the dashboard still serves read-only."""
    try:
        from src.notifier import alert_manager_never_started  # noqa: PLC0415
        alert_manager_never_started(reason)
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("Failed to send manager-never-started alert: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start BotManager on startup, stop on shutdown.

    Defensive — if BotManager can't be imported or DATABASE_URL is missing
    the dashboard still starts in read-only mode.
    """
    manager = None
    db_url = os.environ.get("DATABASE_URL", "")
    # src/ is at /app/src in container, or project root in dev. This insert (plus
    # PYTHONPATH=/app, dashboard/Dockerfile:64) is what makes `src.*` importable here —
    # which is why every `src.*` import below is FUNCTION-LOCAL.
    for p in ["/app", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]:
        if p not in sys.path:
            sys.path.insert(0, p)

    if db_url:
        try:
            from src.bot_manager import BotManager  # noqa: PLC0415
            manager = BotManager(db_url)
            manager.start_all()
            _log.info("BotManager started")
        except Exception as exc:
            _log.warning("BotManager unavailable: %s", exc)
            _alert_manager_never_started(str(exc))
    else:
        # Research N10: BotManager cannot report its own non-existence — its watchdog
        # (bot_manager.py:79) starts AFTER the start_all query that can throw (:67-70).
        # This branch used to be COMPLETELY SILENT: no DATABASE_URL meant no bots ran at
        # all, and nothing said a word.
        _log.warning("BotManager not started: DATABASE_URL not set")
        _alert_manager_never_started("DATABASE_URL not set")

    app.state.bot_manager = manager
    yield
    if manager is not None:
        manager.stop_all()
        _log.info("BotManager stopped")


app = FastAPI(
    title="AI Predicted Wins Dashboard API",
    description="Trading dashboard API for the Alpaca crypto bot.",
    version="2.0.0",
    lifespan=lifespan,
)

# -- CORS --------------------------------------------------------------------
_ALLOWED_ORIGINS = [
    "https://app.aipredictedwins.com",
    # Allow localhost for local dev
    "http://localhost:3000",
    "http://localhost:3001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
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
app.include_router(bots.router, dependencies=[Depends(verify_token)])
app.include_router(chat.router, dependencies=[Depends(verify_token)])
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
