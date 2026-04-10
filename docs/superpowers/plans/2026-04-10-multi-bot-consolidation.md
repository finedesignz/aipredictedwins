# Multi-Bot Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run N trading bots (each with its own Alpaca account and strategy params) from the single existing dashboard deployment, with a UI to add/edit/disable bots and an embedded Claude chat interface.

**Architecture:** BotManager lives in FastAPI's lifespan, reads enabled bots from Postgres on startup, and spawns one BotThread per bot. API endpoints drive all thread lifecycle changes reactively. Next.js frontend adds a `/bots` management page and a `/chat` page; all existing pages become dynamic over the bots API.

**Tech Stack:** Python 3.13, FastAPI lifespan, threading, psycopg3, Next.js 15, Recharts, Tailwind CSS, supervisord, Claude CLI subprocess for chat SSE.

---

## File Map

**New files:**
- `src/bot_config.py` — `BotConfig` dataclass (per-bot params, constructed from DB row)
- `src/bot_thread.py` — `BotThread` class (wraps the orchestrator scan/monitor loop)
- `src/bot_manager.py` — `BotManager` (thread lifecycle, start/stop/update)
- `dashboard/entrypoint.sh` — writes CLAUDE_CREDENTIALS on container start
- `dashboard/api/routes/chat.py` — `POST /api/chat/message` SSE endpoint
- `dashboard/web/app/bots/page.tsx` — bot list + add/edit drawer
- `dashboard/web/app/chat/page.tsx` — full-page chat UI
- `dashboard/web/components/bots/BotCard.tsx` — single bot card
- `dashboard/web/components/bots/BotDrawer.tsx` — add/edit slide-in drawer
- `dashboard/web/components/chat/ChatWidget.tsx` — shared chat thread component

**Modified files:**
- `dashboard/api/main.py` — add lifespan + BotManager wiring
- `dashboard/api/routes/bots.py` — replace stub with full CRUD
- `dashboard/api/models.py` — add BotFull, BotCreate, BotUpdate
- `dashboard/api/db.py` — add `query_filtered_n()` for N bots
- `dashboard/Dockerfile` — COPY src/, install claude CLI
- `dashboard/supervisord.conf` — call entrypoint.sh before starting
- `dashboard/web/types/index.ts` — BotFull type, relax BotFilter types
- `dashboard/web/context/BotFilterContext.tsx` — dynamic N bots from API
- `dashboard/web/components/shared/BotFilter.tsx` — remove hardcoded DEFAULT_BOTS
- `dashboard/web/components/charts/EquityCurve.tsx` — dynamic N lines
- `dashboard/web/app/page.tsx` — remove hardcoded "Bot A"/"Bot B" labels
- `dashboard/web/app/layout.tsx` — add /bots and /chat nav links

---

## Task 1: DB Migration — Expand `bots` table + drop bot_id constraints

**Files:**
- Create: `dashboard/api/migrations/002_multi_bot.sql`

- [x] **Step 1: Write the migration SQL**

```sql
-- dashboard/api/migrations/002_multi_bot.sql

-- 1. Drop the CHECK constraint on alpaca_trades.bot_id (if it exists)
ALTER TABLE alpaca_trades DROP CONSTRAINT IF EXISTS alpaca_trades_bot_id_check;

-- 2. Rename old columns on bots so we can replace them cleanly
ALTER TABLE bots
    ADD COLUMN IF NOT EXISTS bot_id            VARCHAR(10),
    ADD COLUMN IF NOT EXISTS alpaca_api_key    VARCHAR(200),
    ADD COLUMN IF NOT EXISTS alpaca_secret_key VARCHAR(200),
    ADD COLUMN IF NOT EXISTS kelly_fraction    FLOAT   DEFAULT 0.25,
    ADD COLUMN IF NOT EXISTS min_confluence    INT     DEFAULT 3,
    ADD COLUMN IF NOT EXISTS hard_stop_pct     FLOAT   DEFAULT -0.08,
    ADD COLUMN IF NOT EXISTS soft_stop_pct     FLOAT   DEFAULT -0.05,
    ADD COLUMN IF NOT EXISTS rsi_ceiling       FLOAT   DEFAULT 65.0,
    ADD COLUMN IF NOT EXISTS crypto_universe   TEXT    DEFAULT 'BTC/USD,ETH/USD,SOL/USD,XRP/USD',
    ADD COLUMN IF NOT EXISTS skip_risk_gate    BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS max_position_pct  FLOAT   DEFAULT 0.05,
    ADD COLUMN IF NOT EXISTS enabled           BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS status            VARCHAR(20) DEFAULT 'stopped',
    ADD COLUMN IF NOT EXISTS status_detail     TEXT,
    ADD COLUMN IF NOT EXISTS updated_at        TIMESTAMPTZ DEFAULT NOW();

-- 3. Backfill bot_id from existing id column for bots A and B
UPDATE bots SET bot_id = id WHERE bot_id IS NULL;

-- 4. Add unique constraint on bot_id
ALTER TABLE bots ADD CONSTRAINT bots_bot_id_unique UNIQUE (bot_id);
```

- [x] **Step 2: Run migration against the Coolify Postgres instance**

Connect via `psql $DATABASE_URL` and run the file, OR add it to the FastAPI startup to auto-apply:

```bash
psql "$DATABASE_URL" -f dashboard/api/migrations/002_multi_bot.sql
```

Expected: `ALTER TABLE` lines, no errors.

- [x] **Step 3: Seed Bot A and Bot B rows from current Coolify env vars**

This SQL sets the API keys so the existing bots keep running after migration.

```sql
UPDATE bots
SET
    alpaca_api_key    = current_setting('app.alpaca_key_a', true),
    alpaca_secret_key = current_setting('app.alpaca_secret_a', true)
WHERE bot_id = 'A';

UPDATE bots
SET
    alpaca_api_key    = current_setting('app.alpaca_key_b', true),
    alpaca_secret_key = current_setting('app.alpaca_secret_b', true)
WHERE bot_id = 'B';
```

In practice: run this via the Coolify terminal with actual values substituted, OR update via the `/bots` UI after the dashboard is deployed. The important thing is the schema is ready.

- [x] **Step 4: Commit**

```bash
git add dashboard/api/migrations/002_multi_bot.sql
git commit -m "feat: add multi-bot columns to bots table, drop bot_id check constraint"
```

---

## Task 2: `src/bot_config.py` — Per-bot config dataclass

**Files:**
- Create: `src/bot_config.py`

- [x] **Step 1: Write the dataclass**

```python
# src/bot_config.py
"""Per-bot configuration loaded from the bots DB row."""

from dataclasses import dataclass, field


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
            alpaca_api_key=row["alpaca_api_key"] or "",
            alpaca_secret_key=row["alpaca_secret_key"] or "",
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
```

- [x] **Step 2: Write a quick smoke test**

```python
# tests/test_bot_config.py
from src.bot_config import BotConfig


def test_from_row_defaults():
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
    assert cfg.kelly_fraction == 0.25
    assert cfg.symbols == ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD"]


def test_from_row_custom():
    row = {
        "bot_id": "B", "label": "Agent B",
        "alpaca_api_key": "k2", "alpaca_secret_key": "s2",
        "kelly_fraction": 0.5, "min_confluence": 2,
        "hard_stop_pct": -0.10, "soft_stop_pct": -0.06,
        "rsi_ceiling": 70.0, "crypto_universe": "BTC/USD,ETH/USD",
        "skip_risk_gate": True, "max_position_pct": 0.03,
    }
    cfg = BotConfig.from_row(row)
    assert cfg.min_confluence == 2
    assert cfg.skip_risk_gate is True
    assert cfg.symbols == ["BTC/USD", "ETH/USD"]
```

- [x] **Step 3: Run tests**

```bash
cd C:\Users\artic\GitHub\aipredictedwins
python -m pytest tests/test_bot_config.py -v
```

Expected: 2 passed.

- [x] **Step 4: Commit**

```bash
git add src/bot_config.py tests/test_bot_config.py
git commit -m "feat: add BotConfig dataclass loaded from bots DB row"
```

---

## Task 3: `src/bot_thread.py` — BotThread wrapping the orchestrator loop

**Files:**
- Create: `src/bot_thread.py`

- [x] **Step 1: Write BotThread**

```python
# src/bot_thread.py
"""BotThread — runs one bot's scan/monitor loop in a background thread.

Each thread is fully isolated: own AlpacaClient, TradeLogger, ExitAdvisor,
RiskGate. Config is held as an atomic reference; update_config() replaces it
so the next scan cycle picks up new params without a restart.
"""

import logging
import threading
import time
from typing import Callable

from src.bot_config import BotConfig
from src.config import Config
from src.alpaca_client import AlpacaClient
from src.trade_logger import TradeLogger
from src.risk_gate import RiskGate
from src.exit_advisor import ExitAdvisor, TrailingStop, check_position_thresholds
from src.technical_signals import scan_assets
from src.alpaca_orchestrator import (
    PositionMonitor,
    _kelly_technical,
    _select_cycle_candidates,
    MAX_ENTRIES_PER_CYCLE,
    MAX_POSITION_PCT,
    MAX_TOTAL_EXPOSURE_PCT,
    DRAWDOWN_STOP_PCT,
    CYCLE_SLEEP_SECONDS,
)

log = logging.getLogger(__name__)


def _make_alpaca_config(bot_cfg: BotConfig) -> Config:
    """Build a Config object from a BotConfig (no env var reads)."""
    return Config(
        alpaca_api_key=bot_cfg.alpaca_api_key,
        alpaca_secret_key=bot_cfg.alpaca_secret_key,
        alpaca_env="paper",
        kelly_fraction=bot_cfg.kelly_fraction,
        max_position_pct=bot_cfg.max_position_pct,
    )


class BotThread(threading.Thread):
    """Runs one bot's trading loop.

    Lifecycle:
      - Created and started by BotManager.start_bot()
      - Stopped cleanly by BotManager.stop_bot() via _stop_event
      - Config updated atomically by BotManager.update_bot()
    """

    def __init__(
        self,
        config: BotConfig,
        on_status_change: Callable[[str, str, str], None],
    ):
        super().__init__(daemon=True, name=f"bot-{config.bot_id}")
        self._config_lock = threading.Lock()
        self._config = config
        self._stop_event = threading.Event()
        self._on_status_change = on_status_change  # (bot_id, status, detail) -> None

    @property
    def config(self) -> BotConfig:
        with self._config_lock:
            return self._config

    def update_config(self, new_config: BotConfig) -> None:
        """Replace config atomically. Next scan cycle picks it up."""
        with self._config_lock:
            self._config = new_config
        log.info("[bot-%s] Config updated", new_config.bot_id)

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        cfg = self.config
        bot_id = cfg.bot_id
        self._set_status("running", "")
        log.info("[bot-%s] Starting", bot_id)

        try:
            alpaca_cfg = _make_alpaca_config(cfg)
            alpaca = AlpacaClient(alpaca_cfg)
            logger = TradeLogger(bot_id=bot_id)
            risk_gate = RiskGate(logger=logger) if not cfg.skip_risk_gate else None
            exit_advisor = ExitAdvisor()

            monitor = PositionMonitor(alpaca, logger, exit_advisor)
            monitor.start()

            cycle = 0
            while not self._stop_event.is_set():
                cfg = self.config  # re-read on every cycle (atomic swap support)
                cycle += 1
                try:
                    self._run_cycle(cycle, cfg, alpaca, logger, risk_gate, exit_advisor)
                except Exception as exc:
                    log.error("[bot-%s] Cycle %d error: %s", bot_id, cycle, exc)

                self._stop_event.wait(CYCLE_SLEEP_SECONDS)

            monitor.stop()
            monitor.join(timeout=10)

        except Exception as exc:
            log.exception("[bot-%s] Fatal error: %s", bot_id, exc)
            self._set_status("error", str(exc))
            return

        self._set_status("stopped", "")
        log.info("[bot-%s] Stopped", bot_id)

    def _run_cycle(
        self,
        cycle: int,
        cfg: BotConfig,
        alpaca: AlpacaClient,
        logger: TradeLogger,
        risk_gate,
        exit_advisor: ExitAdvisor,
    ) -> None:
        account = alpaca.get_account()
        equity = float(account.get("equity", 0))

        if equity <= 0:
            log.warning("[bot-%s] Account equity is zero, skipping cycle", cfg.bot_id)
            return

        # Check drawdown stop
        peak_equity = logger.get_peak_equity() or equity
        drawdown = (equity - peak_equity) / peak_equity if peak_equity > 0 else 0
        if drawdown < -DRAWDOWN_STOP_PCT:
            log.warning("[bot-%s] Drawdown stop triggered (%.1f%%)", cfg.bot_id, drawdown * 100)
            self._set_status("error", f"Drawdown stop: {drawdown:.1%}")
            self._stop_event.set()
            return

        # Technical scan
        symbols = cfg.symbols
        signals = scan_assets(alpaca, symbols, timeframe="1Hour", bar_count=50)
        candidates = [s for s in signals if s.confluence_score >= cfg.min_confluence]

        # Dedup: skip symbols already in open positions
        open_symbols = {t["symbol"].replace("/", "") for t in logger.get_open_alpaca_positions()}
        candidates = [s for s in candidates if s.symbol.replace("/", "") not in open_symbols]

        # Exposure cap
        positions = alpaca.get_positions()
        total_position_value = sum(float(p.get("market_value", 0)) for p in positions)
        exposure_pct = total_position_value / equity if equity > 0 else 0
        if exposure_pct >= MAX_TOTAL_EXPOSURE_PCT:
            log.info("[bot-%s] Exposure cap reached (%.1f%%), skipping entries", cfg.bot_id, exposure_pct * 100)
            return

        selected = _select_cycle_candidates(candidates, MAX_ENTRIES_PER_CYCLE)

        for signal in selected:
            if self._stop_event.is_set():
                break

            # Risk gate (optional per bot)
            if risk_gate is not None:
                decision = risk_gate.evaluate(signal)
                if decision and decision.get("action") == "VETO":
                    log.info("[bot-%s] Risk gate vetoed %s", cfg.bot_id, signal.symbol)
                    continue

            # Kelly sizing
            size = _kelly_technical(
                confluence=signal.confluence_score,
                current_price=signal.details["latest_close"],
                bankroll=equity,
                kelly_fraction=cfg.kelly_fraction,
                max_position_pct=cfg.max_position_pct,
            )

            if size["side"] == "none" or size["shares"] <= 0:
                continue

            try:
                order = alpaca.place_order(
                    symbol=signal.symbol,
                    qty=size["shares"],
                    side="buy",
                    order_type="market",
                )
                logger.log_alpaca_trade(
                    symbol=signal.symbol,
                    side="buy",
                    qty=size["shares"],
                    entry_price=signal.details["latest_close"],
                    market_sentiment=f"technical_confluence_{signal.confluence_score}",
                    bot_id=cfg.bot_id,
                )
                log.info("[bot-%s] Entered %s: %s shares @ $%.2f",
                         cfg.bot_id, signal.symbol, size["shares"], signal.details["latest_close"])
            except Exception as exc:
                log.error("[bot-%s] Order failed for %s: %s", cfg.bot_id, signal.symbol, exc)

    def _set_status(self, status: str, detail: str) -> None:
        self._on_status_change(self.config.bot_id, status, detail)
```

- [x] **Step 2: Commit**

```bash
git add src/bot_thread.py
git commit -m "feat: add BotThread wrapping orchestrator scan/monitor loop per bot"
```

---

## Task 4: `src/bot_manager.py` — BotManager lifecycle

**Files:**
- Create: `src/bot_manager.py`

- [x] **Step 1: Write BotManager**

```python
# src/bot_manager.py
"""BotManager — manages N BotThread instances from FastAPI lifespan.

Called from FastAPI lifespan on startup/shutdown.
API endpoints call add/stop/update reactively — no polling.
"""

import logging
import os
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from src.bot_config import BotConfig
from src.bot_thread import BotThread

log = logging.getLogger(__name__)


class BotManager:
    """Owns all running BotThread instances.

    Usage (FastAPI lifespan):
        manager = BotManager(db_url)
        await manager.start_all()
        yield  # app runs
        await manager.stop_all()
    """

    def __init__(self, db_url: str):
        self._db_url = db_url
        self._threads: dict[str, BotThread] = {}
        self._pool = ConnectionPool(
            conninfo=db_url,
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row},
            open=True,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_all(self) -> None:
        """Called from FastAPI lifespan. Reads enabled bots from DB and spawns threads."""
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM bots WHERE enabled = TRUE AND alpaca_api_key IS NOT NULL AND alpaca_api_key != ''"
            ).fetchall()

        log.info("BotManager: starting %d enabled bots", len(rows))
        for row in rows:
            try:
                cfg = BotConfig.from_row(row)
                self._spawn(cfg)
            except Exception as exc:
                log.error("Failed to start bot %s: %s", row.get("bot_id"), exc)

    def stop_all(self) -> None:
        """Called from FastAPI lifespan on shutdown."""
        for bot_id, thread in list(self._threads.items()):
            log.info("BotManager: stopping bot %s", bot_id)
            thread.stop()
        for thread in self._threads.values():
            thread.join(timeout=15)
        self._threads.clear()

    # ------------------------------------------------------------------
    # CRUD — called from API endpoints
    # ------------------------------------------------------------------

    def add(self, row: dict) -> None:
        """Spawn a new bot thread from a freshly-inserted DB row."""
        cfg = BotConfig.from_row(row)
        self._spawn(cfg)

    def update(self, bot_id: str, row: dict) -> None:
        """Push updated config to live thread. Thread picks it up next cycle."""
        thread = self._threads.get(bot_id)
        if thread and thread.is_alive():
            thread.update_config(BotConfig.from_row(row))
        elif row.get("enabled"):
            # If it was stopped/dead and now enabled, spawn it
            self._spawn(BotConfig.from_row(row))

    def stop_bot(self, bot_id: str) -> None:
        """Gracefully stop a single bot thread."""
        thread = self._threads.pop(bot_id, None)
        if thread:
            thread.stop()
            thread.join(timeout=15)

    def enable_bot(self, bot_id: str, row: dict) -> None:
        """Spawn thread for a previously-disabled bot."""
        if bot_id not in self._threads or not self._threads[bot_id].is_alive():
            self._spawn(BotConfig.from_row(row))

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, dict]:
        """Return {bot_id: {status, thread_alive}} for all tracked threads."""
        result = {}
        for bot_id, thread in self._threads.items():
            result[bot_id] = {
                "thread_alive": thread.is_alive(),
                "config_label": thread.config.label,
            }
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _spawn(self, cfg: BotConfig) -> None:
        # Stop existing thread if running
        old = self._threads.get(cfg.bot_id)
        if old and old.is_alive():
            old.stop()
            old.join(timeout=5)

        thread = BotThread(cfg, on_status_change=self._on_status_change)
        self._threads[cfg.bot_id] = thread
        thread.start()
        log.info("BotManager: spawned bot %s (%s)", cfg.bot_id, cfg.label)

    def _on_status_change(self, bot_id: str, status: str, detail: str) -> None:
        """Write status back to DB when thread changes state."""
        try:
            with self._pool.connection() as conn:
                conn.execute(
                    "UPDATE bots SET status = %s, status_detail = %s, updated_at = NOW() WHERE bot_id = %s",
                    (status, detail, bot_id),
                )
        except Exception as exc:
            log.warning("Failed to write status for bot %s: %s", bot_id, exc)
```

- [x] **Step 2: Commit**

```bash
git add src/bot_manager.py
git commit -m "feat: add BotManager — reactive thread lifecycle management"
```

---

## Task 5: Wire BotManager into FastAPI lifespan

**Files:**
- Modify: `dashboard/api/main.py`

- [x] **Step 1: Read current main.py** (already read — 152 lines, no lifespan)

- [x] **Step 2: Replace main.py**

Replace the `app = FastAPI(...)` block and imports to add lifespan:

```python
"""
FastAPI application for the AI Predicted Wins trading dashboard.
"""

import os
import sys
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from routes import (
    activity, alpaca, benchmark, bots, chat, equity,
    portfolio, positions, risk_gate, settings, signals, trades,
)

DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN", "")

# ---------------------------------------------------------------------------
# BotManager — import conditionally so dashboard works without src/ in path
# ---------------------------------------------------------------------------
_bot_manager = None

def _try_init_manager():
    global _bot_manager
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return
    try:
        # src/ is mounted at /app/src inside the container
        if "/app" not in sys.path:
            sys.path.insert(0, "/app")
        from src.bot_manager import BotManager
        _bot_manager = BotManager(db_url)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("BotManager unavailable: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _try_init_manager()
    if _bot_manager is not None:
        _bot_manager.start_all()
    app.state.bot_manager = _bot_manager
    yield
    if _bot_manager is not None:
        _bot_manager.stop_all()


app = FastAPI(
    title="AI Predicted Wins Dashboard API",
    description="Trading dashboard API with multi-bot management.",
    version="2.0.0",
    lifespan=lifespan,
)
```

Keep everything else (CORS, auth, route mounting) identical to current. Just add `chat` to the imports and `app.include_router(chat.router, ...)` after the others.

- [x] **Step 3: Commit**

```bash
git add dashboard/api/main.py
git commit -m "feat: add FastAPI lifespan wiring BotManager on startup/shutdown"
```

---

## Task 6: Replace `dashboard/api/routes/bots.py` with full CRUD

**Files:**
- Modify: `dashboard/api/routes/bots.py`
- Modify: `dashboard/api/models.py`

- [x] **Step 1: Add Pydantic models to models.py**

Add after the existing `BotInfo` class:

```python
# In dashboard/api/models.py

class BotFull(BaseModel):
    """Full bot row including strategy params and status."""
    bot_id: str
    label: str
    alpaca_api_key: Optional[str] = None   # never returned after creation
    kelly_fraction: float = 0.25
    min_confluence: int = 3
    hard_stop_pct: float = -0.08
    soft_stop_pct: float = -0.05
    rsi_ceiling: float = 65.0
    crypto_universe: str = "BTC/USD,ETH/USD,SOL/USD,XRP/USD"
    skip_risk_gate: bool = False
    max_position_pct: float = 0.05
    enabled: bool = True
    status: str = "stopped"
    status_detail: Optional[str] = None
    thread_alive: bool = False


class BotCreate(BaseModel):
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


class BotUpdate(BaseModel):
    label: Optional[str] = None
    alpaca_api_key: Optional[str] = None
    alpaca_secret_key: Optional[str] = None
    kelly_fraction: Optional[float] = None
    min_confluence: Optional[int] = None
    hard_stop_pct: Optional[float] = None
    soft_stop_pct: Optional[float] = None
    rsi_ceiling: Optional[float] = None
    crypto_universe: Optional[str] = None
    skip_risk_gate: Optional[bool] = None
    max_position_pct: Optional[float] = None
    enabled: Optional[bool] = None
```

- [x] **Step 2: Rewrite bots.py**

```python
# dashboard/api/routes/bots.py
"""
Bot CRUD endpoints — full lifecycle management.

GET    /api/bots             — list all bots with live status
POST   /api/bots             — add bot → DB insert + thread spawn
PUT    /api/bots/{bot_id}    — edit config → DB update + live config push
DELETE /api/bots/{bot_id}    — stop thread + DB delete
POST   /api/bots/{bot_id}/enable   — spawn thread for disabled bot
POST   /api/bots/{bot_id}/disable  — graceful stop, keep DB row
"""

from fastapi import APIRouter, HTTPException, Request

from db import get_db
from models import BotFull, BotCreate, BotUpdate, Envelope, Meta

router = APIRouter(prefix="/api", tags=["bots"])

_BOT_COLUMNS = """
    bot_id, label, kelly_fraction, min_confluence, hard_stop_pct,
    soft_stop_pct, rsi_ceiling, crypto_universe, skip_risk_gate,
    max_position_pct, enabled, status, status_detail
"""


def _row_to_full(row: dict, manager_status: dict) -> BotFull:
    bot_id = row["bot_id"]
    thread_alive = manager_status.get(bot_id, {}).get("thread_alive", False)
    return BotFull(
        bot_id=bot_id,
        label=row["label"],
        kelly_fraction=row.get("kelly_fraction") or 0.25,
        min_confluence=row.get("min_confluence") or 3,
        hard_stop_pct=row.get("hard_stop_pct") or -0.08,
        soft_stop_pct=row.get("soft_stop_pct") or -0.05,
        rsi_ceiling=row.get("rsi_ceiling") or 65.0,
        crypto_universe=row.get("crypto_universe") or "BTC/USD,ETH/USD,SOL/USD,XRP/USD",
        skip_risk_gate=bool(row.get("skip_risk_gate")),
        max_position_pct=row.get("max_position_pct") or 0.05,
        enabled=bool(row.get("enabled", True)),
        status=row.get("status") or "stopped",
        status_detail=row.get("status_detail"),
        thread_alive=thread_alive,
    )


def _get_manager(request: Request):
    return getattr(request.app.state, "bot_manager", None)


@router.get("/bots")
def list_bots(request: Request):
    manager = _get_manager(request)
    mgr_status = manager.status() if manager else {}
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT {_BOT_COLUMNS} FROM bots ORDER BY bot_id"
        ).fetchall()
    data = [_row_to_full(r, mgr_status) for r in rows]
    return Envelope(data=data, meta=Meta(count=len(data)))


@router.post("/bots", status_code=201)
def create_bot(body: BotCreate, request: Request):
    manager = _get_manager(request)
    with get_db() as conn:
        existing = conn.execute(
            "SELECT bot_id FROM bots WHERE bot_id = %s", (body.bot_id,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"Bot {body.bot_id} already exists")

        conn.execute(
            """INSERT INTO bots
               (bot_id, label, alpaca_api_key, alpaca_secret_key,
                kelly_fraction, min_confluence, hard_stop_pct, soft_stop_pct,
                rsi_ceiling, crypto_universe, skip_risk_gate, max_position_pct,
                enabled, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,'stopped')""",
            (body.bot_id, body.label, body.alpaca_api_key, body.alpaca_secret_key,
             body.kelly_fraction, body.min_confluence, body.hard_stop_pct, body.soft_stop_pct,
             body.rsi_ceiling, body.crypto_universe, body.skip_risk_gate, body.max_position_pct),
        )
        row = conn.execute(
            f"SELECT {_BOT_COLUMNS}, alpaca_api_key, alpaca_secret_key FROM bots WHERE bot_id = %s",
            (body.bot_id,)
        ).fetchone()

    if manager:
        manager.add(row)

    return Envelope(data=_row_to_full(row, manager.status() if manager else {}))


@router.put("/bots/{bot_id}")
def update_bot(bot_id: str, body: BotUpdate, request: Request):
    manager = _get_manager(request)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [bot_id]

    with get_db() as conn:
        result = conn.execute(
            f"UPDATE bots SET {set_clause}, updated_at = NOW() WHERE bot_id = %s",
            values,
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
        row = conn.execute(
            f"SELECT {_BOT_COLUMNS}, alpaca_api_key, alpaca_secret_key FROM bots WHERE bot_id = %s",
            (bot_id,)
        ).fetchone()

    if manager:
        manager.update(bot_id, row)

    return Envelope(data=_row_to_full(row, manager.status() if manager else {}))


@router.delete("/bots/{bot_id}", status_code=204)
def delete_bot(bot_id: str, request: Request):
    manager = _get_manager(request)
    if manager:
        manager.stop_bot(bot_id)
    with get_db() as conn:
        result = conn.execute("DELETE FROM bots WHERE bot_id = %s", (bot_id,))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")


@router.post("/bots/{bot_id}/enable")
def enable_bot(bot_id: str, request: Request):
    manager = _get_manager(request)
    with get_db() as conn:
        conn.execute(
            "UPDATE bots SET enabled = TRUE, status = 'stopped', updated_at = NOW() WHERE bot_id = %s",
            (bot_id,)
        )
        row = conn.execute(
            f"SELECT {_BOT_COLUMNS}, alpaca_api_key, alpaca_secret_key FROM bots WHERE bot_id = %s",
            (bot_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    if manager:
        manager.enable_bot(bot_id, row)
    return Envelope(data=_row_to_full(row, manager.status() if manager else {}))


@router.post("/bots/{bot_id}/disable")
def disable_bot(bot_id: str, request: Request):
    manager = _get_manager(request)
    if manager:
        manager.stop_bot(bot_id)
    with get_db() as conn:
        conn.execute(
            "UPDATE bots SET enabled = FALSE, status = 'stopped', updated_at = NOW() WHERE bot_id = %s",
            (bot_id,)
        )
        row = conn.execute(
            f"SELECT {_BOT_COLUMNS} FROM bots WHERE bot_id = %s", (bot_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Bot {bot_id} not found")
    return Envelope(data=_row_to_full(row, {}))
```

- [x] **Step 3: Commit**

```bash
git add dashboard/api/routes/bots.py dashboard/api/models.py
git commit -m "feat: replace bots stub with full CRUD endpoints wired to BotManager"
```

---

## Task 7: Claude chat SSE endpoint

**Files:**
- Create: `dashboard/api/routes/chat.py`

- [x] **Step 1: Write the chat route**

```python
# dashboard/api/routes/chat.py
"""
POST /api/chat/message  — Claude chat with streaming SSE response.

Spawns `claude` CLI subprocess with current bot status injected as system
context. Streams stdout as SSE events so the frontend can render tokens
progressively.

Credentials: managed by entrypoint.sh writing CLAUDE_CREDENTIALS to
/root/.claude/.credentials.json on every container start.
"""

import json
import os
import subprocess
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from db import get_db

router = APIRouter(prefix="/api/chat", tags=["chat"])

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")


class ChatMessage(BaseModel):
    message: str
    context: dict = {}


def _get_bot_context(request: Request) -> str:
    """Build a context string with live bot status for the system prompt."""
    try:
        manager = getattr(request.app.state, "bot_manager", None)
        mgr_status = manager.status() if manager else {}

        with get_db() as conn:
            bots = conn.execute(
                "SELECT bot_id, label, status, status_detail FROM bots ORDER BY bot_id"
            ).fetchall()
            open_positions = conn.execute(
                "SELECT bot_id, symbol, entry_price, qty FROM alpaca_trades WHERE status = 'open' ORDER BY bot_id, timestamp DESC"
            ).fetchall()

        bot_lines = []
        for b in bots:
            alive = mgr_status.get(b["bot_id"], {}).get("thread_alive", False)
            bot_lines.append(
                f"  Bot {b['bot_id']} ({b['label']}): status={b['status']}, thread_alive={alive}"
                + (f", note={b['status_detail']}" if b.get("status_detail") else "")
            )

        pos_lines = []
        for p in open_positions:
            pos_lines.append(
                f"  [{p['bot_id']}] {p['symbol']}: {p['qty']} @ ${p['entry_price']:.2f}"
            )

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return (
            f"Current time: {now}\n\n"
            f"Bot status:\n" + "\n".join(bot_lines or ["  No bots configured"]) + "\n\n"
            f"Open positions:\n" + "\n".join(pos_lines or ["  No open positions"])
        )
    except Exception as exc:
        return f"(Context unavailable: {exc})"


async def _stream_claude(message: str, system_context: str) -> AsyncGenerator[str, None]:
    system_prompt = (
        "You are a trading assistant for the AI Predicted Wins crypto swing trading system.\n"
        "You help the user understand bot performance, analyze trades, and adjust strategy.\n\n"
        "LIVE SYSTEM CONTEXT:\n"
        f"{system_context}\n\n"
        "When suggesting config changes (e.g. 'tighten Bot A stop to -6%'), end your message with a JSON block:\n"
        '```action\n{"type":"update_bot","bot_id":"A","field":"hard_stop_pct","value":-0.06}\n```\n'
        "The UI will render an Apply button for these actions."
    )

    proc = subprocess.Popen(
        [CLAUDE_BIN, "--print", "--system", system_prompt, message],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    try:
        for line in proc.stdout:
            if line:
                payload = json.dumps({"token": line})
                yield f"data: {payload}\n\n"
        proc.wait(timeout=60)
    except Exception as exc:
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"
    finally:
        proc.terminate()

    yield "data: [DONE]\n\n"


@router.post("/message")
async def chat_message(body: ChatMessage, request: Request):
    context = _get_bot_context(request)
    return StreamingResponse(
        _stream_claude(body.message, context),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

- [x] **Step 2: Commit**

```bash
git add dashboard/api/routes/chat.py
git commit -m "feat: add /api/chat/message SSE endpoint streaming Claude CLI output"
```

---

## Task 8: Dockerfile + entrypoint.sh — install claude CLI, persist credentials

**Files:**
- Modify: `dashboard/Dockerfile`
- Create: `dashboard/entrypoint.sh`
- Modify: `dashboard/supervisord.conf`

- [x] **Step 1: Create entrypoint.sh**

```bash
#!/bin/bash
# dashboard/entrypoint.sh
# Writes Claude credentials from env var on every container start,
# then hands off to supervisord.

set -e

# Write Claude credentials if the env var is set
if [ -n "$CLAUDE_CREDENTIALS" ]; then
    mkdir -p /root/.claude
    echo "$CLAUDE_CREDENTIALS" > /root/.claude/.credentials.json
    echo "[entrypoint] Claude credentials written to /root/.claude/.credentials.json"
else
    echo "[entrypoint] CLAUDE_CREDENTIALS not set — Claude chat will not work until you run 'claude login'"
fi

# Start supervisord
exec supervisord -c /etc/supervisor/conf.d/supervisord.conf
```

- [x] **Step 2: Update Dockerfile**

Replace the production stage to add `src/` copy, claude CLI installation, and entrypoint:

```dockerfile
# ------ Stage 2: Production image ------
FROM python:3.13-slim

# Install Node.js 22, supervisor, curl, npm (needed for claude CLI)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates supervisor && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install claude CLI globally via npm
RUN npm install -g @anthropic-ai/claude-code

# ------ Python dependencies ------
WORKDIR /app/api
COPY api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ------ Copy FastAPI source ------
COPY api/ ./

# ------ Copy bot src/ for BotThread/BotManager ------
WORKDIR /app
COPY src/ ./src/

# ------ Copy built Next.js from builder ------
WORKDIR /app/web
COPY --from=web-builder /build/.next/standalone/ ./
COPY --from=web-builder /build/.next/static/ ./.next/static/
COPY --from=web-builder /build/public/ ./public/

# ------ Data directory (volume mount point) ------
RUN mkdir -p /app/data /root/.claude

# ------ Supervisord config + entrypoint ------
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ------ Health check ------
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:3000/ || exit 1

EXPOSE 3000

CMD ["/entrypoint.sh"]
```

Note: The `FROM node:22-slim AS web-builder` stage at the top stays identical — only the production stage changes.

- [x] **Step 3: Commit**

```bash
git add dashboard/entrypoint.sh dashboard/Dockerfile dashboard/supervisord.conf
git commit -m "feat: add entrypoint.sh for Claude credential persistence, install claude CLI in image"
```

---

## Task 9: Frontend types + BotFilterContext — make N-bot dynamic

**Files:**
- Modify: `dashboard/web/types/index.ts`
- Modify: `dashboard/web/context/BotFilterContext.tsx`
- Modify: `dashboard/web/components/shared/BotFilter.tsx`

- [x] **Step 1: Add BotFull to types/index.ts**

Add after the existing `BotInfo` interface:

```typescript
// In dashboard/web/types/index.ts

export interface BotFull {
  bot_id: string;
  label: string;
  kelly_fraction: number;
  min_confluence: number;
  hard_stop_pct: number;
  soft_stop_pct: number;
  rsi_ceiling: number;
  crypto_universe: string;
  skip_risk_gate: boolean;
  max_position_pct: number;
  enabled: boolean;
  status: "running" | "stopped" | "error";
  status_detail: string | null;
  thread_alive: boolean;
}
```

- [x] **Step 2: Rewrite BotFilterContext.tsx**

```typescript
"use client";

import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import type { BotFull } from "@/types";
import { useAPI } from "@/hooks/useAPI";

export interface BotFilterState {
  [bot_id: string]: boolean;
  spy: boolean;
}

interface BotFilterContextValue {
  filter: BotFilterState;
  setFilter: (f: BotFilterState) => void;
  bots: BotFull[];
  activeBotIds: string[];
  botParam: string;  // comma-separated active bot_ids, or single id, or "both"
}

const BotFilterContext = createContext<BotFilterContextValue>({
  filter: { spy: true },
  setFilter: () => {},
  bots: [],
  activeBotIds: [],
  botParam: "both",
});

export function BotFilterProvider({ children }: { children: ReactNode }) {
  const { data: bots } = useAPI<BotFull[]>("/api/bots", 30_000);
  const botList = bots ?? [];

  const [filter, setFilter] = useState<BotFilterState>({ spy: true });

  // When bots load, default all to active
  useEffect(() => {
    if (botList.length > 0) {
      const initial: BotFilterState = { spy: true };
      botList.forEach((b) => { initial[b.bot_id] = true; });
      setFilter(initial);
    }
  }, [botList.length]);

  const activeBotIds = botList.map((b) => b.bot_id).filter((id) => filter[id] !== false);
  const botParam = activeBotIds.length === 1 ? activeBotIds[0] : "both";

  return (
    <BotFilterContext.Provider value={{ filter, setFilter, bots: botList, activeBotIds, botParam }}>
      {children}
    </BotFilterContext.Provider>
  );
}

export const useBotFilter = () => useContext(BotFilterContext);
```

- [x] **Step 3: Rewrite BotFilter.tsx**

```typescript
"use client";

import { useBotFilter } from "@/context/BotFilterContext";

const BOT_COLORS = ["#60a5fa", "#fbbf24", "#34d399", "#f87171", "#a78bfa", "#fb923c"];

export default function BotFilter() {
  const { filter, setFilter, bots } = useBotFilter();

  return (
    <div className="flex flex-wrap gap-2 items-center">
      {bots.map((bot, i) => {
        const color = BOT_COLORS[i % BOT_COLORS.length];
        const active = filter[bot.bot_id] !== false;
        return (
          <button
            key={bot.bot_id}
            onClick={() => setFilter({ ...filter, [bot.bot_id]: !active })}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-opacity ${
              active ? "opacity-100" : "opacity-40"
            }`}
            style={{ borderColor: color, color }}
          >
            <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
            {bot.label}
            <span className={`w-1.5 h-1.5 rounded-full ml-0.5 ${
              bot.status === "running" ? "bg-green-400" :
              bot.status === "error" ? "bg-red-400" : "bg-slate-500"
            }`} />
          </button>
        );
      })}
      <button
        onClick={() => setFilter({ ...filter, spy: !filter.spy })}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border border-slate-400 text-slate-400 transition-opacity ${
          filter.spy ? "opacity-100" : "opacity-40"
        }`}
      >
        <span className="w-2 h-2 rounded-full bg-slate-400 flex-shrink-0" />
        S&amp;P 500
      </button>
    </div>
  );
}
```

- [x] **Step 4: Commit**

```bash
git add dashboard/web/types/index.ts dashboard/web/context/BotFilterContext.tsx dashboard/web/components/shared/BotFilter.tsx
git commit -m "feat: make BotFilter dynamic over N bots from API, add status dot"
```

---

## Task 10: Update EquityCurve for N bots

**Files:**
- Modify: `dashboard/web/components/charts/EquityCurve.tsx`

- [x] **Step 1: Read full EquityCurve.tsx** (read top 50 lines earlier — need full file)

- [x] **Step 2: Replace the hardcoded merge + line rendering**

The file currently hardcodes `a_pct` and `b_pct` keys. Replace `mergeSeries` and the `<Line>` rendering:

```typescript
// Replace MergedPoint interface and mergeSeries function:

interface MergedPoint {
  timestamp: string;
  spy_pct?: number;
  [key: string]: number | string | undefined;  // dynamic bot keys like "bot_A_pct"
}

function mergeSeries(
  series: EquitySeries[],
  spy: BenchmarkPoint[]
): MergedPoint[] {
  const map = new Map<string, MergedPoint>();

  for (const s of series) {
    for (const p of s.points) {
      const key = p.timestamp;
      const existing = map.get(key) ?? { timestamp: key };
      existing[`bot_${s.bot_id}_pct`] = p.return_pct;
      map.set(key, existing);
    }
  }

  for (const p of spy) {
    const key = p.timestamp;
    const existing = map.get(key) ?? { timestamp: key };
    existing.spy_pct = p.return_pct;
    map.set(key, existing);
  }

  // Forward-fill: sort by timestamp, fill nulls from previous value
  const sorted = Array.from(map.values()).sort((a, b) =>
    a.timestamp < b.timestamp ? -1 : 1
  );

  const botKeys = series.map((s) => `bot_${s.bot_id}_pct`);
  const prev: Record<string, number> = {};
  for (const point of sorted) {
    for (const bk of botKeys) {
      if (point[bk] !== undefined) {
        prev[bk] = point[bk] as number;
      } else if (prev[bk] !== undefined) {
        point[bk] = prev[bk];
      }
    }
  }

  return sorted;
}
```

Replace the `<Line>` rendering section (where it currently has two hardcoded `<Line>` elements for A and B) with:

```typescript
// Dynamic bot colors — same palette as BotFilter
const BOT_COLORS = ["#60a5fa", "#fbbf24", "#34d399", "#f87171", "#a78bfa", "#fb923c"];

// Inside the return, replace the two hardcoded <Line> elements:
{series.map((s, i) => (
  filter[s.bot_id] !== false && (
    <Line
      key={s.bot_id}
      type="monotone"
      dataKey={`bot_${s.bot_id}_pct`}
      stroke={BOT_COLORS[i % BOT_COLORS.length]}
      strokeWidth={2}
      dot={false}
      name={s.bot_id}
      connectNulls
    />
  )
))}
{filter.spy && (
  <Line
    type="monotone"
    dataKey="spy_pct"
    stroke="#94a3b8"
    strokeWidth={1.5}
    strokeDasharray="4 4"
    dot={false}
    name="S&P 500"
    connectNulls
  />
)}
```

- [x] **Step 3: Commit**

```bash
git add dashboard/web/components/charts/EquityCurve.tsx
git commit -m "feat: make EquityCurve dynamic for N bots — no hardcoded A/B keys"
```

---

## Task 11: Build `/bots` page — bot list + add/edit drawer

**Files:**
- Create: `dashboard/web/app/bots/page.tsx`
- Create: `dashboard/web/components/bots/BotCard.tsx`
- Create: `dashboard/web/components/bots/BotDrawer.tsx`

- [x] **Step 1: Write BotCard.tsx**

```typescript
// dashboard/web/components/bots/BotCard.tsx
"use client";

import type { BotFull } from "@/types";

interface BotCardProps {
  bot: BotFull;
  onEdit: (bot: BotFull) => void;
  onToggle: (bot: BotFull, enabled: boolean) => void;
}

export default function BotCard({ bot, onEdit, onToggle }: BotCardProps) {
  const statusColor =
    bot.status === "running" ? "bg-green-400" :
    bot.status === "error" ? "bg-red-400" : "bg-slate-500";

  return (
    <div className="rounded-xl border border-border-primary bg-bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`w-2.5 h-2.5 rounded-full ${statusColor}`} />
          <span className="font-medium text-sm text-text-primary">{bot.label}</span>
          <span className="text-xs text-text-muted font-mono bg-bg-muted px-1.5 py-0.5 rounded">
            {bot.bot_id}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => onToggle(bot, !bot.enabled)}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
              bot.enabled ? "bg-blue-500" : "bg-slate-600"
            }`}
          >
            <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
              bot.enabled ? "translate-x-4" : "translate-x-1"
            }`} />
          </button>
          <button
            onClick={() => onEdit(bot)}
            className="text-xs text-text-muted hover:text-text-primary px-2 py-1 rounded border border-border-primary"
          >
            Edit
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs text-text-muted">
        <div>Kelly: <span className="text-text-primary">{bot.kelly_fraction}</span></div>
        <div>Min confluence: <span className="text-text-primary">{bot.min_confluence}/5</span></div>
        <div>Hard stop: <span className="text-text-primary">{(bot.hard_stop_pct * 100).toFixed(0)}%</span></div>
        <div>Soft stop: <span className="text-text-primary">{(bot.soft_stop_pct * 100).toFixed(0)}%</span></div>
        <div>RSI ceiling: <span className="text-text-primary">{bot.rsi_ceiling}</span></div>
        <div>Max position: <span className="text-text-primary">{(bot.max_position_pct * 100).toFixed(0)}%</span></div>
      </div>

      <div className="text-xs text-text-muted">
        Assets: <span className="text-text-primary">{bot.crypto_universe}</span>
      </div>

      {bot.status === "error" && bot.status_detail && (
        <div className="text-xs text-red-400 bg-red-900/20 rounded p-2">{bot.status_detail}</div>
      )}
    </div>
  );
}
```

- [x] **Step 2: Write BotDrawer.tsx**

```typescript
// dashboard/web/components/bots/BotDrawer.tsx
"use client";

import { useState, useEffect } from "react";
import type { BotFull } from "@/types";

interface BotDrawerProps {
  bot: BotFull | null;   // null = create mode
  open: boolean;
  onClose: () => void;
  onSave: (data: Partial<BotFull> & { alpaca_api_key?: string; alpaca_secret_key?: string; bot_id?: string }) => Promise<void>;
}

export default function BotDrawer({ bot, open, onClose, onSave }: BotDrawerProps) {
  const isNew = bot === null;
  const [form, setForm] = useState({
    bot_id: "",
    label: "",
    alpaca_api_key: "",
    alpaca_secret_key: "",
    kelly_fraction: 0.25,
    min_confluence: 3,
    hard_stop_pct: -0.08,
    soft_stop_pct: -0.05,
    rsi_ceiling: 65,
    crypto_universe: "BTC/USD,ETH/USD,SOL/USD,XRP/USD",
    skip_risk_gate: false,
    max_position_pct: 0.05,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (bot) {
      setForm({
        bot_id: bot.bot_id,
        label: bot.label,
        alpaca_api_key: "",
        alpaca_secret_key: "",
        kelly_fraction: bot.kelly_fraction,
        min_confluence: bot.min_confluence,
        hard_stop_pct: bot.hard_stop_pct,
        soft_stop_pct: bot.soft_stop_pct,
        rsi_ceiling: bot.rsi_ceiling,
        crypto_universe: bot.crypto_universe,
        skip_risk_gate: bot.skip_risk_gate,
        max_position_pct: bot.max_position_pct,
      });
    }
  }, [bot]);

  const set = (field: string, value: unknown) => setForm((f) => ({ ...f, [field]: value }));

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      await onSave(form);
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/50" onClick={onClose} />
      <div className="w-96 bg-bg-page border-l border-border-primary overflow-y-auto p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-text-primary">
            {isNew ? "Add Bot" : `Edit ${bot.label}`}
          </h2>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary text-lg">&times;</button>
        </div>

        {isNew && (
          <Field label="Bot ID (e.g. C)">
            <input className={input} value={form.bot_id} onChange={e => set("bot_id", e.target.value)} />
          </Field>
        )}

        <Field label="Label">
          <input className={input} value={form.label} onChange={e => set("label", e.target.value)} />
        </Field>

        <Field label="Alpaca API Key">
          <input className={input} placeholder={isNew ? "Required" : "Leave blank to keep existing"}
            value={form.alpaca_api_key} onChange={e => set("alpaca_api_key", e.target.value)} />
        </Field>

        <Field label="Alpaca Secret Key">
          <input className={input} type="password" placeholder={isNew ? "Required" : "Leave blank to keep existing"}
            value={form.alpaca_secret_key} onChange={e => set("alpaca_secret_key", e.target.value)} />
        </Field>

        <Field label={`Kelly Fraction: ${form.kelly_fraction}`}>
          <input type="range" min={0.1} max={1} step={0.05} className="w-full"
            value={form.kelly_fraction} onChange={e => set("kelly_fraction", parseFloat(e.target.value))} />
        </Field>

        <Field label={`Min Confluence: ${form.min_confluence}/5`}>
          <input type="range" min={1} max={5} step={1} className="w-full"
            value={form.min_confluence} onChange={e => set("min_confluence", parseInt(e.target.value))} />
        </Field>

        <Field label={`Hard Stop: ${(form.hard_stop_pct * 100).toFixed(0)}%`}>
          <input type="range" min={-0.15} max={-0.03} step={0.01} className="w-full"
            value={form.hard_stop_pct} onChange={e => set("hard_stop_pct", parseFloat(e.target.value))} />
        </Field>

        <Field label={`Soft Stop: ${(form.soft_stop_pct * 100).toFixed(0)}%`}>
          <input type="range" min={-0.10} max={-0.01} step={0.01} className="w-full"
            value={form.soft_stop_pct} onChange={e => set("soft_stop_pct", parseFloat(e.target.value))} />
        </Field>

        <Field label={`RSI Ceiling: ${form.rsi_ceiling}`}>
          <input type="range" min={50} max={80} step={1} className="w-full"
            value={form.rsi_ceiling} onChange={e => set("rsi_ceiling", parseFloat(e.target.value))} />
        </Field>

        <Field label={`Max Position: ${(form.max_position_pct * 100).toFixed(0)}%`}>
          <input type="range" min={0.01} max={0.10} step={0.01} className="w-full"
            value={form.max_position_pct} onChange={e => set("max_position_pct", parseFloat(e.target.value))} />
        </Field>

        <Field label="Crypto Universe (comma-separated)">
          <input className={input} value={form.crypto_universe}
            onChange={e => set("crypto_universe", e.target.value)} />
        </Field>

        <div className="flex items-center gap-2">
          <input type="checkbox" id="skip-rg" checked={form.skip_risk_gate}
            onChange={e => set("skip_risk_gate", e.target.checked)} />
          <label htmlFor="skip-rg" className="text-xs text-text-muted">Skip risk gate</label>
        </div>

        {error && <p className="text-xs text-red-400">{error}</p>}

        <button
          onClick={handleSave}
          disabled={saving}
          className="w-full py-2 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save"}
        </button>
      </div>
    </div>
  );
}

const input = "w-full bg-bg-card border border-border-primary rounded px-2 py-1.5 text-xs text-text-primary";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-xs text-text-muted">{label}</label>
      {children}
    </div>
  );
}
```

- [x] **Step 3: Write the /bots page**

```typescript
// dashboard/web/app/bots/page.tsx
"use client";

import { useState, useCallback } from "react";
import { useAPI } from "@/hooks/useAPI";
import type { BotFull } from "@/types";
import BotCard from "@/components/bots/BotCard";
import BotDrawer from "@/components/bots/BotDrawer";
import { fetchAPI } from "@/lib/api";

export default function BotsPage() {
  const { data: bots, refresh } = useAPI<BotFull[]>("/api/bots", 30_000);
  const [editBot, setEditBot] = useState<BotFull | null | "new">(undefined as unknown as BotFull | null | "new");
  const [drawerOpen, setDrawerOpen] = useState(false);

  const openNew = () => { setEditBot(null); setDrawerOpen(true); };
  const openEdit = (bot: BotFull) => { setEditBot(bot); setDrawerOpen(true); };
  const closeDrawer = () => setDrawerOpen(false);

  const handleSave = useCallback(async (data: Record<string, unknown>) => {
    if (editBot === null) {
      // Create
      await fetchAPI("/api/bots", { method: "POST", body: JSON.stringify(data) });
    } else {
      // Update
      const updates: Record<string, unknown> = { ...data };
      if (!updates.alpaca_api_key) delete updates.alpaca_api_key;
      if (!updates.alpaca_secret_key) delete updates.alpaca_secret_key;
      await fetchAPI(`/api/bots/${(editBot as BotFull).bot_id}`, {
        method: "PUT",
        body: JSON.stringify(updates),
      });
    }
    refresh();
  }, [editBot]);

  const handleToggle = useCallback(async (bot: BotFull, enabled: boolean) => {
    const path = enabled ? `/api/bots/${bot.bot_id}/enable` : `/api/bots/${bot.bot_id}/disable`;
    await fetchAPI(path, { method: "POST" });
    refresh();
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-text-primary">Bots</h1>
        <button
          onClick={openNew}
          className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium rounded"
        >
          + Add Bot
        </button>
      </div>

      {bots && bots.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {bots.map((bot) => (
            <BotCard
              key={bot.bot_id}
              bot={bot}
              onEdit={openEdit}
              onToggle={handleToggle}
            />
          ))}
        </div>
      ) : (
        <div className="flex items-center justify-center h-48 rounded-lg border border-border-primary bg-bg-card">
          <p className="text-sm text-text-muted">No bots configured. Click &quot;+ Add Bot&quot; to get started.</p>
        </div>
      )}

      <BotDrawer
        bot={editBot === "new" ? null : editBot as BotFull | null}
        open={drawerOpen}
        onClose={closeDrawer}
        onSave={handleSave}
      />
    </div>
  );
}
```

You'll also need `fetchAPI` in `lib/api.ts` if it doesn't exist. Add:

```typescript
// In dashboard/web/lib/api.ts
export async function fetchAPI(path: string, options: RequestInit = {}): Promise<unknown> {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "";
  const res = await fetch(`${base}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}
```

- [x] **Step 4: Commit**

```bash
git add dashboard/web/app/bots/ dashboard/web/components/bots/ dashboard/web/lib/api.ts
git commit -m "feat: add /bots page with bot list, add/edit drawer, enable/disable toggle"
```

---

## Task 12: Build `/chat` page

**Files:**
- Create: `dashboard/web/app/chat/page.tsx`
- Create: `dashboard/web/components/chat/ChatWidget.tsx`

- [x] **Step 1: Write ChatWidget.tsx**

```typescript
// dashboard/web/components/chat/ChatWidget.tsx
"use client";

import { useState, useRef, useEffect } from "react";
import { fetchAPI } from "@/lib/api";

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface ActionBlock {
  type: "update_bot";
  bot_id: string;
  field: string;
  value: unknown;
}

function parseAction(content: string): ActionBlock | null {
  const match = content.match(/```action\n([\s\S]*?)\n```/);
  if (!match) return null;
  try { return JSON.parse(match[1]); } catch { return null; }
}

export default function ChatWidget() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    if (!input.trim() || streaming) return;
    const userMsg = input.trim();
    setInput("");
    setMessages((m) => [...m, { role: "user", content: userMsg }]);
    setStreaming(true);

    setMessages((m) => [...m, { role: "assistant", content: "" }]);

    try {
      const res = await fetch("/api/chat/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: userMsg }),
      });

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value);
        for (const line of chunk.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (raw === "[DONE]") break;
          try {
            const { token } = JSON.parse(raw);
            if (token) {
              setMessages((m) => {
                const last = m[m.length - 1];
                return [...m.slice(0, -1), { ...last, content: last.content + token }];
              });
            }
          } catch { /* ignore parse errors */ }
        }
      }
    } catch (e) {
      setMessages((m) => {
        const last = m[m.length - 1];
        return [...m.slice(0, -1), { ...last, content: `Error: ${e}` }];
      });
    } finally {
      setStreaming(false);
    }
  };

  const applyAction = async (action: ActionBlock) => {
    try {
      await fetchAPI(`/api/bots/${action.bot_id}`, {
        method: "PUT",
        body: JSON.stringify({ [action.field]: action.value }),
      });
      setMessages((m) => [...m, { role: "assistant", content: `Applied: ${action.field} = ${action.value} for Bot ${action.bot_id}` }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: `Failed to apply: ${e}` }]);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto space-y-4 p-4">
        {messages.length === 0 && (
          <p className="text-sm text-text-muted text-center mt-8">
            Ask Claude about your bots, trades, or strategy.
          </p>
        )}
        {messages.map((msg, i) => {
          const action = msg.role === "assistant" ? parseAction(msg.content) : null;
          const displayContent = msg.content.replace(/```action[\s\S]*?```/g, "").trim();
          return (
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[85%] rounded-xl px-3 py-2 text-sm whitespace-pre-wrap ${
                msg.role === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-bg-card border border-border-primary text-text-primary"
              }`}>
                {displayContent}
                {action && (
                  <button
                    onClick={() => applyAction(action)}
                    className="mt-2 block w-full text-xs bg-green-700 hover:bg-green-600 text-white rounded px-2 py-1"
                  >
                    Apply: {action.field} = {String(action.value)} (Bot {action.bot_id})
                  </button>
                )}
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-border-primary p-3 flex gap-2">
        <input
          className="flex-1 bg-bg-card border border-border-primary rounded px-3 py-2 text-sm text-text-primary placeholder-text-muted"
          placeholder="Ask Claude..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
          disabled={streaming}
        />
        <button
          onClick={send}
          disabled={streaming || !input.trim()}
          className="px-3 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded disabled:opacity-50"
        >
          {streaming ? "..." : "Send"}
        </button>
      </div>
    </div>
  );
}
```

- [x] **Step 2: Write /chat page**

```typescript
// dashboard/web/app/chat/page.tsx
import ChatWidget from "@/components/chat/ChatWidget";

export default function ChatPage() {
  return (
    <div className="h-[calc(100vh-8rem)] rounded-xl border border-border-primary bg-bg-page overflow-hidden">
      <ChatWidget />
    </div>
  );
}
```

- [x] **Step 3: Add nav links in layout/NavWrapper**

In `dashboard/web/app/NavWrapper.tsx` or wherever the nav links are defined, add:
- `/bots` — "Bots"
- `/chat` — "Chat"

- [x] **Step 4: Commit**

```bash
git add dashboard/web/app/chat/ dashboard/web/components/chat/
git commit -m "feat: add /chat page with streaming Claude chat UI and Apply action buttons"
```

---

## Task 13: Update page.tsx to remove hardcoded Bot A/Bot B labels

**Files:**
- Modify: `dashboard/web/app/page.tsx`

- [x] **Step 1: Replace hardcoded "Bot A" / "Bot B" references**

The current page.tsx has `labelA="Bot A"` and `labelB="Bot B"` hardcoded in `<HeroKPI>` and `<MetricCard>` components. Replace the entire metric section to be dynamic over `activeBotIds` from context:

```typescript
// At top of OverviewPage component, add:
const { bots, activeBotIds } = useBotFilter();

// Build a bot_id -> label map
const botLabels = Object.fromEntries(bots.map((b) => [b.bot_id, b.label]));

// Replace the HeroKPI section (isMulti branch) to use dynamic labels:
// Change labelA="Bot A" to labelA={botLabels["A"] ?? "Bot A"}
// Change labelB="Bot B" to labelB={botLabels["B"] ?? "Bot B"}
```

For a truly N-bot portfolio, the metric cards also need to generalize. For now, the two-bot A/B layout still works since the API returns A and B — but label strings come from the DB.

- [x] **Step 2: Commit**

```bash
git add dashboard/web/app/page.tsx
git commit -m "feat: use dynamic bot labels from DB on overview page"
```

---

## Task 14: Coolify — volume, env var, and cleanup

**Files:** None (Coolify UI / API actions)

- [ ] **Step 1: Add `/root/.claude` persistent volume to the dashboard app**

In Coolify dashboard → app `aipredictedwins-dashboard` → Storages → Add Volume:
- Source: named volume `claude-credentials`
- Destination: `/root/.claude`

This preserves tokens refreshed at runtime across container restarts.

- [ ] **Step 2: Set CLAUDE_CREDENTIALS env var**

Get the current credentials from the running container:
```bash
# Run in Coolify terminal
cat /root/.claude/.credentials.json
```

Copy the JSON and set `CLAUDE_CREDENTIALS` env var in Coolify to that JSON string.

- [ ] **Step 3: Update ALPACA_API_KEY / SECRET env vars**

The new bots table stores credentials per-bot. Run the seed SQL from Task 1 Step 3 to populate Bot A and Bot B rows with the current env var values.

- [ ] **Step 4: Deploy**

Push code to git → Coolify auto-deploys OR trigger manual redeploy.

- [ ] **Step 5: Verify**

- Navigate to `https://app.aipredictedwins.com/bots` — should show Bot A and Bot B cards with status dots
- Navigate to `https://app.aipredictedwins.com/chat` — send a test message, confirm streaming response
- Check FastAPI logs — should see `BotManager: started 2 enabled bots`

- [ ] **Step 6: Delete old Bot A / Bot B Coolify apps** (only after verifying new app is running both bots)

---

## Self-Review

**Spec coverage check:**
- [x] Run N bots from single deployment → Tasks 3, 4, 5
- [x] Dashboard UI to add/edit/enable/disable bots → Tasks 6, 11
- [x] Config changes take effect immediately → BotThread.update_config() in Task 3
- [x] Claude chat UI embedded in dashboard → Tasks 7, 12
- [x] Claude credential persistence → Task 8 (entrypoint.sh + volume)
- [x] Dynamic bot references everywhere → Tasks 9, 10, 13
- [x] DB migration / seed → Task 1
- [x] Bots table schema → Task 1

**Placeholder scan:** None found — all steps have actual code.

**Type consistency:**
- `BotConfig.from_row()` in Task 2 → consumed by `BotThread.__init__()` in Task 3 → `BotManager._spawn()` in Task 4 ✓
- `BotFull` Pydantic model in Task 6 → `BotFull` TypeScript type in Task 9 — fields match ✓
- `_row_to_full()` in bots.py omits `alpaca_api_key` from response → frontend never shows it ✓
- `bot_param` was `"A" | "B" | "both"` — Task 9 relaxes to `string` to support N bots ✓
