# Postgres A/B Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace dual-SQLite architecture with a single shared Postgres database so both bots write to the same store and the dashboard can show live data for both, with SPY benchmark overlay and real Alpaca health checks.

**Architecture:** Both bots tag every row with `bot_id TEXT CHECK (bot_id IN ('A','B'))`. Dashboard reads from one psycopg3 pool with `?bot=A|B|both` query params. Frontend BotFilter context toggles per-bot + SPY series on/off.

**Tech Stack:** psycopg[binary]>=3.2, psycopg-pool>=3.2, Recharts (already installed), React Context, FastAPI, Alpaca-py

**Spec:** `docs/superpowers/specs/2026-04-09-postgres-ab-dashboard-design.md`

---

### Task 1: Postgres Schema SQL

**Files:**
- Create: `src/db_schema.sql`

- [ ] Write `src/db_schema.sql` with all `CREATE TABLE IF NOT EXISTS` statements. Every table gets: `bot_id TEXT NOT NULL CHECK (bot_id IN ('A','B'))`, `source_id BIGINT` (nullable, for migration idempotency), composite `(bot_id, timestamp)` index, and `UNIQUE INDEX ... WHERE source_id IS NOT NULL` on `(bot_id, source_id)`.

Tables to define:
- `bots` — `id TEXT PK, label TEXT, starting_equity DOUBLE PRECISION DEFAULT 100000, alpaca_key_prefix TEXT, config_flags JSONB, created_at TIMESTAMPTZ DEFAULT NOW()`
- `alpaca_trades` — `id BIGSERIAL PK, source_id BIGINT, bot_id, timestamp TEXT, symbol TEXT, asset_class TEXT, side TEXT, qty DOUBLE PRECISION, entry_price DOUBLE PRECISION, mirofish_prob DOUBLE PRECISION, market_sentiment TEXT, target_price DOUBLE PRECISION, stop_loss DOUBLE PRECISION, status TEXT DEFAULT 'open', exit_price DOUBLE PRECISION, pnl DOUBLE PRECISION, closed_at TEXT, simulation_id TEXT, notes TEXT`
- `validations` — mirror of existing SQLite schema + bot_id/source_id
- `screenings` — mirror + bot_id/source_id
- `simulations` — `PRIMARY KEY (bot_id, id)` (id is TEXT), + source_id
- `daily_stats` — `PRIMARY KEY (bot_id, date)`, no autoincrement id
- `trades` — `id BIGSERIAL PK` + bot_id/source_id

End the file with idempotent seed rows:
```sql
INSERT INTO bots (id, label, starting_equity, config_flags)
VALUES
  ('A', 'Bot A — Conservative', 100000.0, '{"kelly_fraction":0.25,"min_confluence":3,"skip_risk_gate":false}'),
  ('B', 'Bot B — Aggressive',   100000.0, '{"kelly_fraction":0.50,"min_confluence":2,"skip_risk_gate":true}')
ON CONFLICT (id) DO NOTHING;
```

- [ ] Verify the SQL is valid by running it against a local Postgres (or noting it will be tested in Task 2).

- [ ] Commit: `git add src/db_schema.sql && git commit -m "feat: postgres schema with bot_id and source_id columns"`

---

### Task 2: src/db.py — Postgres Pool + Core Functions

**Files:**
- Create: `src/db.py`

- [ ] Write `src/db.py`. This module owns the connection pool and exposes the same public functions that `trade_logger.py` currently does internally.

Key structure:
```python
import os, time
import psycopg
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

def _create_pool() -> ConnectionPool:
    url = os.environ["DATABASE_URL"]
    for attempt in range(3):
        try:
            pool = ConnectionPool(conninfo=url, min_size=2, max_size=10,
                                  kwargs={"row_factory": dict_row}, open=True)
            return pool
        except Exception:
            if attempt == 2: raise
            time.sleep(2 ** attempt)

_pool: ConnectionPool | None = None

def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = _create_pool()
        _bootstrap_schema()
    return _pool

def _bootstrap_schema():
    schema_path = os.path.join(os.path.dirname(__file__), "db_schema.sql")
    with open(schema_path) as f:
        sql = f.read()
    with get_pool().connection() as conn:
        conn.execute(sql)
```

Then implement every function the shim will need:
- `log_alpaca_trade(bot_id, trade_data) -> int`
- `update_alpaca_trade(bot_id, trade_id, status, exit_price, pnl)`
- `get_open_alpaca_positions(bot_id) -> list[dict]`
- `log_validation(bot_id, data) -> int`
- `log_screening(bot_id, data) -> int`
- `log_simulation(bot_id, sim_id, market, mirofish_prob, kalshi_price, estimated_cost)`
- `log_trade(bot_id, trade_data) -> int`
- `update_trade(bot_id, trade_id, status, exit_price_cents, pnl)`
- `get_accuracy(bot_id, last_n=None) -> dict`
- `get_alpaca_accuracy(bot_id, last_n=None) -> dict`
- `get_daily_summary(bot_id) -> dict`
- `get_simulated_tickers_today(bot_id) -> set[str]`
- `get_veto_history(bot_id, last_n=20) -> list[dict]`

All queries use `%s` placeholders. Use `conn.execute(sql, params).fetchone()["id"]` pattern. Use `RETURNING id` for inserts.

- [ ] Write a smoke test `tests/test_db.py` that skips when `DATABASE_URL` is not set, otherwise:
  - Bootstraps schema
  - Calls `log_alpaca_trade("A", {...})` and asserts returned id is an int
  - Calls `get_open_alpaca_positions("A")` and asserts 1 row
  - Calls `update_alpaca_trade("A", id, "closed", 85000, 150.0)`
  - Calls `get_alpaca_accuracy("A")` and asserts `resolved == 1, wins == 1`

- [ ] Run: `DATABASE_URL=postgresql://... pytest tests/test_db.py -v` — PASS

- [ ] Commit: `git add src/db.py tests/test_db.py && git commit -m "feat: psycopg3 connection pool and core db functions"`

---

### Task 3: src/trade_logger.py Shim + requirements.txt

**Files:**
- Modify: `src/trade_logger.py`
- Modify: `requirements.txt`

- [ ] Add to `requirements.txt`:
```
psycopg[binary]>=3.2
psycopg-pool>=3.2
```

- [ ] Rewrite `TradeLogger.__init__` to:
  1. Read `self.bot_id = os.environ.get("BOT_ID", "")` 
  2. Validate: `if self.bot_id not in ("A", "B"): raise ValueError(f"BOT_ID env var must be 'A' or 'B', got {self.bot_id!r}")`
  3. Remove all SQLite `self.db_path` / `_init_db` / `_get_conn` logic.

- [ ] Rewrite every method as a one-line delegation to `src.db`:
```python
def log_alpaca_trade(self, trade_data: dict) -> int:
    from src import db
    return db.log_alpaca_trade(self.bot_id, trade_data)

def update_alpaca_trade(self, trade_id, status, exit_price=None, pnl=None):
    from src import db
    db.update_alpaca_trade(self.bot_id, trade_id, status, exit_price, pnl)

# ... same pattern for all methods
```

- [ ] Keep `log_veto` and `export_csv` as-is (they call other methods, not SQLite directly).

- [ ] Verify no remaining `sqlite3` imports in `src/trade_logger.py`.

- [ ] Write test `tests/test_trade_logger_shim.py`:
  - Without `BOT_ID` env var: `TradeLogger()` raises `ValueError`
  - With `BOT_ID=X`: raises `ValueError`  
  - With `BOT_ID=A` and valid `DATABASE_URL`: `log_alpaca_trade({...})` returns int (skip if no DB)

- [ ] Run: `pytest tests/test_trade_logger_shim.py -v` — PASS

- [ ] Commit: `git add src/trade_logger.py requirements.txt tests/test_trade_logger_shim.py && git commit -m "feat: trade_logger shim delegates to src.db via BOT_ID env var"`

---

### Task 4: src/trade_memory.py Shim

**Files:**
- Modify: `src/trade_memory.py`

- [ ] Read `src/trade_memory.py` to understand its current structure (SQLite tables: `trade_lessons`, `trade_context`, `strategy_scores`).

- [ ] Add these tables to `src/db_schema.sql` (amend Task 1 commit or add to schema):
```sql
CREATE TABLE IF NOT EXISTS trade_lessons (
    id          BIGSERIAL PRIMARY KEY,
    bot_id      TEXT NOT NULL CHECK (bot_id IN ('A','B')),
    timestamp   TEXT NOT NULL,
    symbol      TEXT,
    lesson      TEXT NOT NULL,
    outcome     TEXT,
    pnl         DOUBLE PRECISION
);
CREATE TABLE IF NOT EXISTS trade_context (
    id          BIGSERIAL PRIMARY KEY,
    bot_id      TEXT NOT NULL CHECK (bot_id IN ('A','B')),
    timestamp   TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    context     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS strategy_scores (
    bot_id      TEXT NOT NULL CHECK (bot_id IN ('A','B')),
    strategy    TEXT NOT NULL,
    score       DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (bot_id, strategy)
);
```

- [ ] Rewrite `TradeMemory` to:
  - Read `self.bot_id` from `os.environ["BOT_ID"]` (same pattern as TradeLogger)
  - Replace all `sqlite3` queries with psycopg3 via `src.db.get_pool().connection()`
  - Use `%s` placeholders throughout

- [ ] Run existing tests (if any) or a quick smoke: `pytest tests/ -k trade_memory -v`

- [ ] Commit: `git add src/trade_memory.py src/db_schema.sql && git commit -m "feat: trade_memory migrated to postgres"`

---

### Task 5: Migration Script

**Files:**
- Create: `scripts/migrate_sqlite_to_postgres.py`

- [ ] Write the migration script. It must:
  1. Accept `--bot-a-db path` and `--bot-b-db path` CLI args
  2. For each source db, copy it to `backups/trades-{A|B}-{timestamp}.db` before touching anything. Exit if backup fails.
  3. Open each SQLite file read-only with `sqlite3.connect("file:path?mode=ro", uri=True)`
  4. For each table (`alpaca_trades`, `validations`, `screenings`, `simulations`, `daily_stats`, `trades`), run `SELECT rowid AS source_id, * FROM table` and insert into Postgres with `INSERT ... ON CONFLICT (bot_id, source_id) DO NOTHING`
  5. After each table, assert `SELECT COUNT(*) FROM table WHERE bot_id = %s` == SQLite row count. Print PASS/FAIL.
  6. Print summary: total rows migrated per table per bot.

Key column mappings:
- Add `bot_id = 'A'` or `'B'` to every row
- Set `source_id = rowid`
- `daily_stats` has no `rowid` (TEXT PK on `date`) — use `ON CONFLICT (bot_id, date) DO NOTHING`
- `simulations` PK is `(bot_id, id)` — use `ON CONFLICT (bot_id, id) DO NOTHING`

- [ ] Manual test: run against fixture SQLite files in `tests/backtester/fixtures/` (or create a tiny test db)

- [ ] Commit: `git add scripts/migrate_sqlite_to_postgres.py && git commit -m "feat: idempotent sqlite→postgres migration script"`

---

### Task 6: docker-compose.dev.yml

**Files:**
- Create: `docker-compose.dev.yml`

- [ ] Write `docker-compose.dev.yml` at repo root:
```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: aipw
      POSTGRES_USER: aipw
      POSTGRES_PASSWORD: aipw
    ports: ["5432:5432"]
    volumes: [postgres_data:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U aipw"]
      interval: 5s
      retries: 5

  bot-a:
    build: {context: ., dockerfile: Dockerfile.alpaca}
    environment:
      BOT_ID: "A"
      DATABASE_URL: postgresql://aipw:aipw@postgres:5432/aipw
    env_file: [.env]
    volumes: [./src:/app/src]
    depends_on:
      postgres: {condition: service_healthy}

  bot-b:
    build: {context: ., dockerfile: Dockerfile.alpaca}
    environment:
      BOT_ID: "B"
      DATABASE_URL: postgresql://aipw:aipw@postgres:5432/aipw
    env_file: [.env]
    volumes: [./src:/app/src]
    depends_on:
      postgres: {condition: service_healthy}

  dashboard-api:
    build: {context: dashboard/api}
    environment:
      DATABASE_URL: postgresql://aipw:aipw@postgres:5432/aipw
    ports: ["8080:8080"]
    volumes: [./dashboard/api:/app]
    depends_on:
      postgres: {condition: service_healthy}

volumes:
  postgres_data:
```

- [ ] Verify `docker compose -f docker-compose.dev.yml config` runs without error.

- [ ] Commit: `git add docker-compose.dev.yml && git commit -m "feat: docker-compose.dev.yml for local postgres dev"`

---

### Task 7: dashboard/api/db.py — Replace SQLite with psycopg3

**Files:**
- Modify: `dashboard/api/db.py`
- Modify: `dashboard/api/requirements.txt`

- [ ] Add to `dashboard/api/requirements.txt`:
```
psycopg[binary]>=3.2
psycopg-pool>=3.2
```

- [ ] Rewrite `dashboard/api/db.py`:

```python
import os
from contextlib import contextmanager
from typing import Generator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=os.environ["DATABASE_URL"],
            min_size=2, max_size=10,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _pool


@contextmanager
def get_db() -> Generator[psycopg.Connection, None, None]:
    with _get_pool().connection() as conn:
        yield conn


def query_filtered(sql: str, params: tuple, bot: str) -> list[dict]:
    """Run a query with optional bot_id filter. bot='both' returns all rows."""
    if bot in ("A", "B"):
        # Inject bot_id filter — caller's WHERE clause must be present
        # Wrap in subquery to add filter cleanly
        wrapped = f"SELECT * FROM ({sql}) _q WHERE bot_id = %s"
        final_params = params + (bot,)
    else:
        wrapped = sql
        final_params = params
    with get_db() as conn:
        return conn.execute(wrapped, final_params).fetchall()


def rows_to_list(rows) -> list[dict]:
    """psycopg3 dict_row already returns dicts — just return as list."""
    return list(rows)
```

- [ ] Update `dashboard/api/main.py` health check: remove `from db import DB_PATH` and the `db_exists` check. Replace with:
```python
@app.get("/api/health")
def health_check():
    try:
        from db import get_db
        with get_db() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "database": "postgres"}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}
```

- [ ] Write test `dashboard/api/tests/test_db.py` (skip without `DATABASE_URL`):
  - `get_db()` yields a connection
  - `query_filtered("SELECT bot_id FROM bots", (), "A")` returns only A rows
  - `query_filtered("SELECT bot_id FROM bots", (), "both")` returns both A and B rows

- [ ] Run: `DATABASE_URL=postgresql://... pytest dashboard/api/tests/test_db.py -v` — PASS

- [ ] Commit: `git add dashboard/api/db.py dashboard/api/requirements.txt dashboard/api/main.py dashboard/api/tests/ && git commit -m "feat: dashboard api db layer migrated to psycopg3"`

---

### Task 8: dashboard/api/models.py Additions

**Files:**
- Modify: `dashboard/api/models.py`

- [ ] Add to `models.py`:

```python
class EquityPoint(BaseModel):
    timestamp: str
    equity: float
    return_pct: float
    bot_id: Optional[str] = None

class EquitySeries(BaseModel):
    bot_id: str
    points: list[EquityPoint]

class BotInfo(BaseModel):
    id: str
    label: str
    starting_equity: float
    alpaca_key_prefix: Optional[str] = None
    config_flags: Optional[dict] = None

class MultiBotPortfolio(BaseModel):
    """Used when bot=both — keyed by bot_id."""
    A: Optional[PortfolioData] = None
    B: Optional[PortfolioData] = None

class BenchmarkPoint(BaseModel):
    timestamp: str
    return_pct: float
```

- [ ] Also update `HealthStatus`: change `sqlite_db: bool` → `database: bool` (and update `settings.py` to match).

- [ ] Run: `python -c "from models import EquitySeries, BotInfo, MultiBotPortfolio, BenchmarkPoint; print('OK')"` — PASS

- [ ] Commit: `git add dashboard/api/models.py && git commit -m "feat: add EquitySeries, BotInfo, MultiBotPortfolio, BenchmarkPoint models"`

---

### Task 9: Portfolio + Equity Routes — bot= param

**Files:**
- Modify: `dashboard/api/routes/portfolio.py`
- Modify: `dashboard/api/routes/equity.py`

**portfolio.py:**

- [ ] Replace the entire route with:
```python
from typing import Literal
from fastapi import APIRouter, Query
from db import get_db
from models import Envelope, Meta, PortfolioData, MultiBotPortfolio

router = APIRouter(prefix="/api", tags=["portfolio"])

def _portfolio_for_bot(conn, bot_id: str) -> PortfolioData:
    starting = conn.execute(
        "SELECT starting_equity FROM bots WHERE id = %s", (bot_id,)
    ).fetchone()
    starting_equity = (starting["starting_equity"] if starting else 100_000.0)

    closed = conn.execute(
        """SELECT pnl FROM alpaca_trades
           WHERE bot_id = %s AND status IN ('closed','stopped','target_hit')""",
        (bot_id,)
    ).fetchall()
    total_pnl = sum(r["pnl"] or 0.0 for r in closed)
    wins = sum(1 for r in closed if (r["pnl"] or 0) > 0)
    losses = len(closed) - wins
    equity = starting_equity + total_pnl

    total_trades = conn.execute(
        "SELECT COUNT(*) AS n FROM alpaca_trades WHERE bot_id = %s", (bot_id,)
    ).fetchone()["n"]
    open_count = conn.execute(
        "SELECT COUNT(*) AS n FROM alpaca_trades WHERE bot_id = %s AND status='open'",
        (bot_id,)
    ).fetchone()["n"]

    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_rows = conn.execute(
        """SELECT pnl FROM alpaca_trades
           WHERE bot_id = %s AND status IN ('closed','stopped','target_hit')
             AND closed_at LIKE %s""",
        (bot_id, f"{today}%")
    ).fetchall()
    daily_pnl = sum(r["pnl"] or 0.0 for r in daily_rows)

    resolved = len(closed)
    win_rate = round(wins / resolved * 100, 1) if resolved > 0 else 0.0
    return PortfolioData(
        equity=equity,
        total_pnl=total_pnl,
        total_pnl_percent=round(total_pnl / starting_equity * 100, 2),
        win_rate=win_rate,
        open_positions=open_count,
        daily_pnl=daily_pnl,
        daily_pnl_percent=round(daily_pnl / starting_equity * 100, 2),
        mode="paper",
        trades_resolved=resolved,
        total_trades=total_trades,
        wins=wins,
        losses=losses,
    )

@router.get("/portfolio")
def get_portfolio(bot: Literal["A", "B", "both"] = "both"):
    with get_db() as conn:
        if bot == "both":
            data = MultiBotPortfolio(
                A=_portfolio_for_bot(conn, "A"),
                B=_portfolio_for_bot(conn, "B"),
            )
        else:
            data = _portfolio_for_bot(conn, bot)
    return Envelope(data=data, meta=Meta(count=1))
```

**equity.py:**

- [ ] Rewrite to query from single Postgres pool:
```python
from typing import Literal
from fastapi import APIRouter, Query
from db import get_db
from models import Envelope, EquityPoint, EquitySeries, Meta
from datetime import datetime, timezone

router = APIRouter()

def _build_series(conn, bot_id: str) -> EquitySeries:
    starting = conn.execute(
        "SELECT starting_equity FROM bots WHERE id = %s", (bot_id,)
    ).fetchone()
    starting_equity = starting["starting_equity"] if starting else 100_000.0

    rows = conn.execute(
        """SELECT closed_at, pnl FROM alpaca_trades
           WHERE bot_id = %s AND status IN ('closed','stopped','target_hit')
             AND closed_at IS NOT NULL
           ORDER BY closed_at ASC""",
        (bot_id,)
    ).fetchall()

    points = []
    cumulative = starting_equity
    for r in rows:
        cumulative += r["pnl"] or 0
        return_pct = round((cumulative - starting_equity) / starting_equity * 100, 4)
        points.append(EquityPoint(
            timestamp=r["closed_at"],
            equity=round(cumulative, 2),
            return_pct=return_pct,
            bot_id=bot_id,
        ))

    if not points:
        points.append(EquityPoint(
            timestamp=datetime.now(timezone.utc).isoformat(),
            equity=starting_equity,
            return_pct=0.0,
            bot_id=bot_id,
        ))
    return EquitySeries(bot_id=bot_id, points=points)

@router.get("/api/equity")
def get_equity(bot: Literal["A", "B", "both"] = "both"):
    with get_db() as conn:
        if bot == "both":
            data = {"series": [
                _build_series(conn, "A").model_dump(),
                _build_series(conn, "B").model_dump(),
            ]}
        else:
            data = {"series": [_build_series(conn, bot).model_dump()]}
    return Envelope(data=data, meta=Meta())
```

- [ ] Run: `pytest dashboard/api/tests/ -v` — PASS (tests from Task 7)

- [ ] Commit: `git add dashboard/api/routes/portfolio.py dashboard/api/routes/equity.py && git commit -m "feat: portfolio and equity routes support bot=A|B|both with postgres"`

---

### Task 10: Remaining Routes — positions, trades, risk_gate, activity

**Files:**
- Modify: `dashboard/api/routes/positions.py`
- Modify: `dashboard/api/routes/trades.py`
- Modify: `dashboard/api/routes/risk_gate.py`
- Modify: `dashboard/api/routes/activity.py`

**positions.py:**
- [ ] Remove `from db import query_both`. Add `from db import get_db`.
- [ ] Add `bot: Literal["A","B","both"] = "both"` param to both endpoints.
- [ ] Replace `query_both(sql)` calls with:
```python
with get_db() as conn:
    if bot == "both":
        rows = conn.execute(sql_with_no_bot_filter).fetchall()
    else:
        rows = conn.execute(sql + " AND bot_id = %s", (bot,)).fetchall()
```
- [ ] Add `bot` field to `OpenPosition` responses using `r["bot_id"]`.

**trades.py:**
- [ ] Same pattern: `query_both` → `get_db()` + `bot_id` WHERE clause.
- [ ] Change all `?` placeholders to `%s`.
- [ ] Add `bot: Literal["A","B","both"] = "both"` param.

**risk_gate.py:**
- [ ] Read the file to see its current structure.
- [ ] Replace `get_db()` SQLite pattern with psycopg3 pool. Change `?` → `%s`.
- [ ] Add `bot: Literal["A","B","both"] = "both"` param.

**activity.py:**
- [ ] Replace SQLite-specific code with psycopg3:
  - Remove `import sqlite3`, `from db import DB_PATH`
  - Add `from db import get_db`
  - Replace `_get_readonly_conn()` with async-safe pattern using `asyncio.to_thread`:
```python
async def _fetch_activity(since: str) -> dict:
    def _sync():
        with get_db() as conn:
            trades = conn.execute(
                "SELECT id, timestamp, symbol, side, qty, entry_price, status, bot_id "
                "FROM alpaca_trades WHERE timestamp > %s ORDER BY timestamp ASC",
                (since,)
            ).fetchall()
            closed = conn.execute(
                "SELECT id, symbol, side, qty, entry_price, exit_price, pnl, status, closed_at, bot_id "
                "FROM alpaca_trades WHERE closed_at > %s "
                "AND status IN ('closed','stopped','target_hit') ORDER BY closed_at ASC",
                (since,)
            ).fetchall()
            vals = conn.execute(
                "SELECT id, timestamp, kalshi_ticker, decision, veto_reason, risk_assessment, confidence, bot_id "
                "FROM validations WHERE timestamp > %s ORDER BY timestamp ASC",
                (since,)
            ).fetchall()
        return {"trades": trades, "closed": closed, "validations": vals}
    return await asyncio.to_thread(_sync)
```

- [ ] Run: `pytest dashboard/api/tests/ -v` — PASS

- [ ] Commit: `git add dashboard/api/routes/ && git commit -m "feat: positions/trades/risk_gate/activity routes migrated to postgres"`

---

### Task 11: dashboard/api/alpaca.py + Settings Health Check

**Files:**
- Create: `dashboard/api/alpaca.py`
- Modify: `dashboard/api/routes/settings.py`

**alpaca.py:**
- [ ] Create `dashboard/api/alpaca.py`:
```python
import os, time
from functools import lru_cache
from alpaca.trading.client import TradingClient

_ALPACA_KEY = os.environ.get("DASH_ALPACA_API_KEY", "")
_ALPACA_SECRET = os.environ.get("DASH_ALPACA_SECRET_KEY", "")

_health_cache: dict = {"value": "unknown", "ts": 0.0}
_CACHE_TTL = 30.0

def get_account_health() -> str:
    now = time.time()
    if now - _health_cache["ts"] < _CACHE_TTL:
        return _health_cache["value"]
    if not _ALPACA_KEY or not _ALPACA_SECRET:
        _health_cache.update({"value": "unknown", "ts": now})
        return "unknown"
    try:
        client = TradingClient(_ALPACA_KEY, _ALPACA_SECRET, paper=True)
        client.get_account()
        _health_cache.update({"value": "ok", "ts": now})
        return "ok"
    except Exception:
        _health_cache.update({"value": "down", "ts": now})
        return "down"
```

**settings.py:**
- [ ] Replace the SQLite `get_db()` import with psycopg3 `get_db()`.
- [ ] Change `?` → `%s` in all queries.
- [ ] Replace `db_exists = os.path.exists(DB_PATH)` health check with:
```python
from alpaca import get_account_health
alpaca_status = get_account_health()
try:
    with get_db() as conn:
        conn.execute("SELECT 1")
    db_ok = True
except Exception:
    db_ok = False

health = HealthStatus(
    claude_cli=True,
    alpaca_api=(alpaca_status == "ok"),
    database=db_ok,
    db_size_mb=0.0,
)
```
- [ ] Update `HealthStatus` in models.py: remove `sqlite_db`, add `database: bool = True`.
- [ ] Add `bot: Literal["A","B","both"] = "both"` param. When `bot=both` aggregate stats across both bots. When single, filter by `bot_id`.

- [ ] Test: `curl http://localhost:8080/api/settings` returns `health.database: true`

- [ ] Commit: `git add dashboard/api/alpaca.py dashboard/api/routes/settings.py dashboard/api/models.py && git commit -m "feat: real alpaca health check and postgres health in settings route"`

---

### Task 12: benchmark.py + bots.py Routes + main.py Registration

**Files:**
- Create: `dashboard/api/routes/benchmark.py`
- Create: `dashboard/api/routes/bots.py`
- Modify: `dashboard/api/main.py`

**benchmark.py:**
- [ ] Create `dashboard/api/routes/benchmark.py`:
```python
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Query
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
import os

from models import BenchmarkPoint, Envelope, Meta

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])

_ALPACA_KEY = os.environ.get("DASH_ALPACA_API_KEY", "")
_ALPACA_SECRET = os.environ.get("DASH_ALPACA_SECRET_KEY", "")

_spy_cache: dict = {"data": [], "ts": 0.0}
_CACHE_TTL = 300.0  # 5 minutes

@router.get("/spy")
def get_spy_benchmark(
    since: Optional[str] = Query(None, description="ISO date. Defaults to 90 days ago."),
):
    now = time.time()
    if now - _spy_cache["ts"] < _CACHE_TTL:
        return Envelope(data=_spy_cache["data"], meta=Meta())

    if not _ALPACA_KEY or not _ALPACA_SECRET:
        return Envelope(data=[], meta=Meta())

    start = datetime.fromisoformat(since) if since else (datetime.now(timezone.utc) - timedelta(days=90))
    try:
        client = StockHistoricalDataClient(_ALPACA_KEY, _ALPACA_SECRET)
        req = StockBarsRequest(symbol_or_symbols="SPY", timeframe=TimeFrame.Day, start=start)
        bars = client.get_stock_bars(req).data.get("SPY", [])
    except Exception:
        return Envelope(data=[], meta=Meta())

    if not bars:
        return Envelope(data=[], meta=Meta())

    base_close = bars[0].close
    points = []
    for bar in bars:
        return_pct = round((bar.close - base_close) / base_close * 100, 4)
        points.append(BenchmarkPoint(
            timestamp=bar.timestamp.isoformat(),
            return_pct=return_pct,
        ).model_dump())

    _spy_cache.update({"data": points, "ts": now})
    return Envelope(data=points, meta=Meta(count=len(points)))
```

**bots.py:**
- [ ] Create `dashboard/api/routes/bots.py`:
```python
from fastapi import APIRouter
from db import get_db
from models import BotInfo, Envelope, Meta

router = APIRouter(prefix="/api", tags=["bots"])

@router.get("/bots")
def get_bots():
    with get_db() as conn:
        rows = conn.execute("SELECT id, label, starting_equity, alpaca_key_prefix, config_flags FROM bots ORDER BY id").fetchall()
    data = [BotInfo(**r) for r in rows]
    return Envelope(data=data, meta=Meta(count=len(data)))
```

**main.py:**
- [ ] Add imports and router registrations:
```python
from routes import benchmark, bots
# ...
app.include_router(benchmark.router, dependencies=[Depends(verify_token)])
app.include_router(bots.router, dependencies=[Depends(verify_token)])
```

- [ ] Test: `curl http://localhost:8080/api/bots` returns 2 bots. `curl http://localhost:8080/api/benchmark/spy` returns SPY points.

- [ ] Commit: `git add dashboard/api/routes/benchmark.py dashboard/api/routes/bots.py dashboard/api/main.py && git commit -m "feat: benchmark/spy and bots registry routes"`

---

### Task 13: Frontend Types

**Files:**
- Modify: `dashboard/web/types/index.ts`

- [ ] Add to `dashboard/web/types/index.ts`:
```typescript
export interface EquitySeriesPoint {
  timestamp: string;
  equity: number;
  return_pct: number;
  bot_id?: string;
}

export interface EquitySeries {
  bot_id: string;
  points: EquitySeriesPoint[];
}

export interface EquityResponse {
  series: EquitySeries[];
}

export interface BenchmarkPoint {
  timestamp: string;
  return_pct: number;
}

export interface BotInfo {
  id: string;
  label: string;
  starting_equity: number;
  alpaca_key_prefix?: string;
  config_flags?: Record<string, string | number | boolean>;
}

export interface MultiBotPortfolio {
  A?: Portfolio;
  B?: Portfolio;
}
```

- [ ] Update `EquityData` interface to match new shape:
```typescript
// Replace old EquityData with:
export interface EquityData {
  series: EquitySeries[];
}
```

- [ ] Run: `cd dashboard/web && npx tsc --noEmit` — no type errors from these additions

- [ ] Commit: `git add dashboard/web/types/index.ts && git commit -m "feat: add frontend types for multi-bot equity, benchmark, bots"`

---

### Task 14: BotFilterContext + layout.tsx

**Files:**
- Create: `dashboard/web/context/BotFilterContext.tsx`
- Modify: `dashboard/web/app/layout.tsx`

**BotFilterContext.tsx:**
- [ ] Create `dashboard/web/context/BotFilterContext.tsx`:
```typescript
"use client";
import { createContext, useContext, useState, ReactNode } from "react";

export interface BotFilter {
  A: boolean;
  B: boolean;
  spy: boolean;
}

interface BotFilterContextValue {
  filter: BotFilter;
  setFilter: (f: BotFilter) => void;
  activeBots: ("A" | "B")[];
  botParam: "A" | "B" | "both";
}

const BotFilterContext = createContext<BotFilterContextValue>({
  filter: { A: true, B: true, spy: true },
  setFilter: () => {},
  activeBots: ["A", "B"],
  botParam: "both",
});

export function BotFilterProvider({ children }: { children: ReactNode }) {
  const [filter, setFilter] = useState<BotFilter>({ A: true, B: true, spy: true });
  const activeBots = (["A", "B"] as const).filter(b => filter[b]);
  const botParam = activeBots.length === 1 ? activeBots[0] : "both";
  return (
    <BotFilterContext.Provider value={{ filter, setFilter, activeBots, botParam }}>
      {children}
    </BotFilterContext.Provider>
  );
}

export const useBotFilter = () => useContext(BotFilterContext);
```

- [ ] In `dashboard/web/app/layout.tsx`, wrap children in `<BotFilterProvider>`:
```typescript
import { BotFilterProvider } from "@/context/BotFilterContext";
// ...
<BotFilterProvider>
  {children}
</BotFilterProvider>
```

- [ ] Run: `cd dashboard/web && npx tsc --noEmit` — PASS

- [ ] Commit: `git add dashboard/web/context/BotFilterContext.tsx dashboard/web/app/layout.tsx && git commit -m "feat: BotFilterContext for persistent per-bot and SPY toggle state"`

---

### Task 15: BotFilter Component

**Files:**
- Create: `dashboard/web/components/shared/BotFilter.tsx`

- [ ] Create `dashboard/web/components/shared/BotFilter.tsx`:
```typescript
"use client";
import { useBotFilter } from "@/context/BotFilterContext";
import { useAPI } from "@/hooks/useAPI";
import type { BotInfo } from "@/types";

const BOT_COLORS: Record<string, string> = {
  A: "#60a5fa",
  B: "#fbbf24",
};

export default function BotFilter() {
  const { filter, setFilter } = useBotFilter();
  const { data: bots } = useAPI<BotInfo[]>("/api/bots", 0);

  const toggle = (key: "A" | "B" | "spy") =>
    setFilter({ ...filter, [key]: !filter[key] });

  return (
    <div className="flex flex-wrap gap-2 items-center">
      {(bots ?? [{ id: "A", label: "Bot A" }, { id: "B", label: "Bot B" }]).map(bot => (
        <button
          key={bot.id}
          onClick={() => toggle(bot.id as "A" | "B")}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-opacity ${
            filter[bot.id as "A" | "B"] ? "opacity-100" : "opacity-40"
          }`}
          style={{ borderColor: BOT_COLORS[bot.id], color: BOT_COLORS[bot.id] }}
        >
          <span className="w-2 h-2 rounded-full" style={{ background: BOT_COLORS[bot.id] }} />
          {bot.label}
        </button>
      ))}
      <button
        onClick={() => toggle("spy")}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border border-slate-400 text-slate-400 transition-opacity ${
          filter.spy ? "opacity-100" : "opacity-40"
        }`}
      >
        <span className="w-2 h-2 rounded-full bg-slate-400" />
        S&P 500
      </button>
    </div>
  );
}
```

- [ ] Run: `cd dashboard/web && npx tsc --noEmit` — PASS

- [ ] Commit: `git add dashboard/web/components/shared/BotFilter.tsx && git commit -m "feat: BotFilter chip bar component with dynamic bot labels"`

---

### Task 16: EquityCurve.tsx Multi-Series Rewrite

**Files:**
- Modify: `dashboard/web/components/charts/EquityCurve.tsx`

- [ ] Rewrite `EquityCurve.tsx` to accept `series: EquitySeries[]` and optional `spy: BenchmarkPoint[]`:

Key changes from current implementation:
- Props: `{ series: EquitySeries[], spy?: BenchmarkPoint[] }` (remove `agentA`, `agentB`)
- Y-axis: `return_pct` (percentage), not absolute equity. Label: `%`.
- Y-axis formatter: `v => v >= 0 ? `+${v.toFixed(1)}%` : `${v.toFixed(1)}%``
- `ReferenceLine y={0}` (not 100_000)
- Merge function: align series by timestamp, fields named `a_pct`, `b_pct`, `spy_pct`
- Render `<Area>` for Bot A (blue `#60a5fa`), `<Area>` for Bot B (amber `#fbbf24`), `<Line>` dashed for SPY (gray `#94a3b8`)
- Only render series where corresponding `BotFilterContext` flag is true
- Read filter state: `const { filter } = useBotFilter()`
- `BotStat` component: show `return_pct` from last point (not absolute equity minus 100k)
- Custom tooltip: show `%` values, format as `+1.23%`
- Empty state: same as before

- [ ] Run: `cd dashboard/web && npx tsc --noEmit` — PASS

- [ ] Commit: `git add dashboard/web/components/charts/EquityCurve.tsx && git commit -m "feat: equity curve rewritten for multi-series return_pct with SPY overlay"`

---

### Task 17: HeroKPI + MetricCard + PositionCard Dual-Value

**Files:**
- Modify: `dashboard/web/components/kpi/HeroKPI.tsx`
- Modify: `dashboard/web/components/kpi/MetricCard.tsx`
- Modify: `dashboard/web/components/positions/PositionCard.tsx`

**HeroKPI.tsx:**
- [ ] Read current `HeroKPI.tsx` to understand its props.
- [ ] Add optional `valueB?: number`, `labelB?: string`, `deltaB?: number`, `deltaBPercent?: number` props.
- [ ] When `valueB` is present, render two stacked rows:
```
Bot A: $98,380   -1.62%
Bot B: $101,200  +1.20%
```
Otherwise render single value as before.

**MetricCard.tsx:**
- [ ] Read current `MetricCard.tsx`.
- [ ] Add optional `valueB?: string`, `deltaB?: string`, `colorB?: "green"|"red"|"blue"|"default"` props.
- [ ] When `valueB` present, render `A: val / B: val` with independent color coding per half.

**PositionCard.tsx:**
- [ ] Read current `PositionCard.tsx`.
- [ ] Add small badge in top-right showing `bot` field from position: `A` in blue, `B` in amber.

- [ ] Run: `cd dashboard/web && npx tsc --noEmit` — PASS

- [ ] Commit: `git add dashboard/web/components/ && git commit -m "feat: HeroKPI/MetricCard dual-value, PositionCard bot badge"`

---

### Task 18: page.tsx Wiring

**Files:**
- Modify: `dashboard/web/app/page.tsx`

- [ ] Update `page.tsx` to:
1. Read `botParam` from `useBotFilter()`
2. Pass `bot=${botParam}` to all `useAPI` calls:
```typescript
const { data: rawPortfolio } = useAPI<Portfolio | MultiBotPortfolio>(
  `/api/portfolio?bot=${botParam}`, 10000
);
const { data: equityData } = useAPI<EquityData>(`/api/equity?bot=${botParam}`);
```
3. Derive per-bot values for MetricCard and HeroKPI:
```typescript
const isMulti = botParam === "both";
const portA = isMulti ? (rawPortfolio as MultiBotPortfolio)?.A : (rawPortfolio as Portfolio);
const portB = isMulti ? (rawPortfolio as MultiBotPortfolio)?.B : undefined;
```
4. Add `<BotFilter />` above the metric cards.
5. Pass `series={equityData?.series ?? []}` to `<EquityCurve />` instead of agentA/agentB.
6. Pass SPY data: `const { data: spyData } = useAPI<BenchmarkPoint[]>("/api/benchmark/spy");` → pass to EquityCurve as `spy={spyData ?? []}`.
7. Pass dual values to HeroKPI and MetricCard when `isMulti`.

- [ ] Run: `cd dashboard/web && npx tsc --noEmit` — PASS

- [ ] Commit: `git add dashboard/web/app/page.tsx && git commit -m "feat: overview page wired to multi-bot filter context and new API shapes"`

---

### Task 19: Backend Unit Tests

**Files:**
- Create: `dashboard/api/tests/test_routes.py`

- [ ] Write `dashboard/api/tests/test_routes.py` using pytest + `httpx` (async TestClient) and a real Postgres instance (skip if `TEST_DATABASE_URL` not set):

```python
import os, pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set"
)

@pytest.fixture(scope="session")
def client():
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    from main import app
    # Seed test data
    from db import get_db
    with get_db() as conn:
        conn.execute("INSERT INTO alpaca_trades (bot_id, timestamp, symbol, asset_class, side, qty, entry_price, mirofish_prob, status, pnl, closed_at) VALUES ('A', '2026-01-01T00:00:00', 'BTC/USD', 'crypto', 'buy', 0.01, 80000, 0.6, 'closed', 500.0, '2026-01-02T00:00:00')")
        conn.execute("INSERT INTO alpaca_trades (bot_id, timestamp, symbol, asset_class, side, qty, entry_price, mirofish_prob, status, pnl, closed_at) VALUES ('B', '2026-01-01T00:00:00', 'ETH/USD', 'crypto', 'buy', 0.1, 3000, 0.7, 'closed', -100.0, '2026-01-02T00:00:00')")
    return TestClient(app)

def test_portfolio_flat_shape(client):
    r = client.get("/api/portfolio?bot=A", headers={"Authorization": "Bearer test"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert "equity" in d
    assert "A" not in d  # flat shape for single bot

def test_portfolio_keyed_shape(client):
    r = client.get("/api/portfolio?bot=both", headers={"Authorization": "Bearer test"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert "A" in d and "B" in d

def test_equity_both_returns_two_series(client):
    r = client.get("/api/equity?bot=both", headers={"Authorization": "Bearer test"})
    assert r.status_code == 200
    series = r.json()["data"]["series"]
    assert len(series) == 2
    bot_ids = {s["bot_id"] for s in series}
    assert bot_ids == {"A", "B"}

def test_equity_return_pct_field_present(client):
    r = client.get("/api/equity?bot=A", headers={"Authorization": "Bearer test"})
    series = r.json()["data"]["series"]
    assert len(series) == 1
    point = series[0]["points"][0]
    assert "return_pct" in point

def test_bots_endpoint(client):
    r = client.get("/api/bots", headers={"Authorization": "Bearer test"})
    assert r.status_code == 200
    bots = r.json()["data"]
    assert len(bots) == 2
    ids = {b["id"] for b in bots}
    assert ids == {"A", "B"}
```

- [ ] Run: `TEST_DATABASE_URL=postgresql://... pytest dashboard/api/tests/test_routes.py -v` — all PASS

- [ ] Commit: `git add dashboard/api/tests/test_routes.py && git commit -m "test: dashboard route unit tests against real postgres"`

---

## Execution Checklist (post all tasks)

- [ ] All 19 tasks committed
- [ ] `pytest tests/ -v` — PASS (bot-side tests)
- [ ] `pytest dashboard/api/tests/ -v` — PASS (dashboard tests)
- [ ] `cd dashboard/web && npx tsc --noEmit` — PASS (frontend types)
- [ ] Push to main
- [ ] Coolify: provision Postgres in AI Predicted Wins project, note DATABASE_URL
- [ ] Run `python scripts/migrate_sqlite_to_postgres.py --bot-a-db ... --bot-b-db ...`
- [ ] Coolify: add DATABASE_URL + BOT_ID to Bot A + Bot B, redeploy, tail logs
- [ ] Coolify: add DATABASE_URL + DASH_ALPACA_API_KEY + DASH_ALPACA_SECRET_KEY to Dashboard, redeploy
- [ ] Check `https://app.aipredictedwins.com` — non-zero equity, two series visible, SPY line rendering
