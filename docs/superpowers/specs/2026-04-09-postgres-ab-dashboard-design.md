# Postgres-Backed A/B Dashboard with S&P 500 Benchmark — Design

**Date:** 2026-04-09
**Status:** Approved, ready for implementation plan
**Owner:** artic

---

## Problem

Bot A and Bot B run as separate Coolify applications, each writing trade data to its own containerized SQLite volume (`alpaca-paper-data:/app/data/trades.db`). The dashboard is a third separate Coolify application and has no access to either bot's database. As a result, `app.aipredictedwins.com` shows `$0.00` balance, empty equity curve, "no open positions", and "waiting for bot activity" — even though both bots are actively trading.

Additionally, the dashboard cannot show S&P 500 as a performance benchmark, which is critical for evaluating whether either bot is actually beating passive market exposure.

## Goals

1. Both Bot A and Bot B connected to the same dashboard, showing live trade data for each.
2. S&P 500 (SPY) overlaid as a benchmark line on the equity curve.
3. Users can toggle Bot A / Bot B / SPY independently via filter chips.
4. Historical SQLite data from both bots preserved in the migration.
5. The dashboard accurately reports Alpaca API health instead of the current `"unknown"` placeholder.

## Non-Goals

- Options/stocks trading support (separate spec: `project_options_v3_plan.md`).
- Re-enabling the Kalshi orchestrator (paused, still in schema but not exercised).
- Writing from the dashboard (dashboard remains read-only).
- ORM adoption — the codebase uses raw SQL and will continue to.
- Authentication / multi-tenant support beyond the A/B split.

---

## Architecture

### High-level shape

```
                         ┌─────────────────────┐
                         │  Postgres (Coolify) │
                         │   ai_predicted_wins │
                         └──────────┬──────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
      ┌───────▼──────┐      ┌───────▼──────┐     ┌────────▼────────┐
      │   Bot A      │      │   Bot B      │     │   Dashboard     │
      │  BOT_ID=A    │      │  BOT_ID=B    │     │  reads only     │
      │  writes      │      │  writes      │     │  + Alpaca SPY   │
      └──────────────┘      └──────────────┘     └─────────────────┘
```

All three Coolify applications live in the existing `AI Predicted Wins` project and reach the Postgres service via the Coolify-internal hostname. Each bot tags every write with its own `BOT_ID` (`A` or `B`). The dashboard reads both via a single connection pool and fans out queries with a `?bot=A|B|both` filter.

### Postgres service

- **Hosting:** Coolify-managed Postgres, provisioned inside the same `AI Predicted Wins` project (UUID `u7x0xw0y4qvcgeh8vyidsgyi`). Same server (`46.224.61.233`), no egress, automatic backups via Coolify.
- **Database name:** `aipw`
- **Connection:** `DATABASE_URL` env var injected by Coolify into each linked application. Hostname is the Coolify-internal service name (e.g. `ai-predicted-wins-db`), port 5432.
- **Driver:** `psycopg[binary]==3.2.*` with `psycopg_pool==3.2.*`. Rationale: the codebase uses raw SQL throughout; an ORM would add unnecessary abstraction. Psycopg3 is a modern, typed, async-capable thin driver that mirrors the existing `trade_logger.py` call style.

### Schema

Every existing SQLite table gains a non-nullable `bot_id TEXT` column (`'A'` or `'B'`), a check constraint (`bot_id IN ('A', 'B')`), and a composite index on `(bot_id, timestamp)` for fast filtered time-series reads.

New `bots` registry table:

```sql
CREATE TABLE bots (
    id              TEXT PRIMARY KEY CHECK (id IN ('A', 'B')),
    label           TEXT NOT NULL,                -- "Bot A — Conservative"
    starting_equity DOUBLE PRECISION NOT NULL,    -- for % return normalization
    alpaca_key_prefix TEXT,                        -- display only
    config_flags    JSONB,                         -- { kelly_fraction, min_confluence, skip_risk_gate, ... }
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Seed rows for this table are inserted as part of the schema bootstrap.

**Tables migrated from SQLite** (each receives `bot_id` column + composite index):
- `alpaca_trades` — the critical one, drives the overview page
- `validations` — TradingAgents / risk-gate decisions
- `screenings` — quick screener results
- `simulations` — MiroFish sim records (legacy Kalshi, kept for historical reads)
- `daily_stats` — primary key becomes `(bot_id, date)` composite
- `trades` — legacy Kalshi trades (kept for read-only historical access)

**Type mapping:**
- `INTEGER` → `INTEGER` (or `BIGINT` for `id` columns)
- `REAL` → `DOUBLE PRECISION`
- `TEXT` → `TEXT`
- `BOOLEAN` → `BOOLEAN`
- Timestamps remain ISO strings in `TEXT` columns (no behavior change) — we are deliberately NOT migrating to `TIMESTAMPTZ` in this pass to keep the blast radius small.

**Schema bootstrap:** `src/db_schema.sql` contains all `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` statements. Runs on bot startup. Idempotent. No migration framework for v1 — when the schema needs to change later, we will add a `schema_migrations` table and `scripts/migrate.py` runner.

### Data migration

One-time script: `scripts/migrate_sqlite_to_postgres.py`.

**Execution:** dumps each bot's `trades.db` file off its Coolify volume (via `docker cp` or `coolify exec` tar-streamed over SSH) to a local working directory, then streams rows into Postgres.

**Idempotency strategy:** every migrated table gains a permanent `source_id BIGINT` column (nullable — new rows written post-migration will have `NULL`) and a unique index on `(bot_id, source_id) WHERE source_id IS NOT NULL`. This preserves each row's original SQLite `rowid` / autoincrement ID, makes re-running the migration a safe `INSERT … ON CONFLICT (bot_id, source_id) DO NOTHING`, and doesn't leak into post-migration writes.

**Per-row handling:**
1. Open each SQLite file read-only.
2. For each table, `SELECT rowid AS source_id, * FROM <table>`.
3. Insert into Postgres with `bot_id` set to the source file's bot and `source_id` set to the SQLite rowid. Use `INSERT … ON CONFLICT (bot_id, source_id) DO NOTHING`.
4. After all tables are loaded, assert `SELECT COUNT(*) FROM <table> WHERE bot_id = ?` matches the source SQLite's row count. Fail loud if not.
5. Leave the `source_id` column in place permanently — it's a cheap audit trail and enables future re-runs if we ever need to re-import historical data.

**Backup before migration:** copy each `trades.db` file to `backups/trades-{bot_id}-{timestamp}.db` before touching anything. Migration script refuses to run without this backup in place.

---

## Bot Changes

### `src/db.py` (new)

New module that owns the Postgres connection pool and exposes the same functions `trade_logger.py` currently does: `log_alpaca_trade`, `update_alpaca_trade`, `get_open_alpaca_positions`, `log_validation`, `log_screening`, `log_simulation`, `log_trade`, `update_trade`, `get_accuracy`, `get_daily_summary`, `get_simulated_tickers_today`, `get_veto_history`, `export_csv`, etc.

**Pool initialization:** `psycopg_pool.ConnectionPool(conninfo=os.environ["DATABASE_URL"], min_size=2, max_size=10, timeout=30)`. Created at module import time. Retries on initial connection failure with exponential backoff (3 attempts, 1s/2s/4s) so a slow Postgres startup doesn't crash the bot.

**Schema bootstrap on startup:** `src/db.py` reads and executes `src/db_schema.sql` once on first use. Idempotent (`IF NOT EXISTS` throughout), safe to run from both bots simultaneously.

### `src/trade_logger.py` (thin shim)

`TradeLogger` keeps its public API but its methods become one-line wrappers that:
1. Read `bot_id = os.environ["BOT_ID"]` (validated at class init; crashes loud if missing or not in `{"A", "B"}`).
2. Delegate to `src.db` functions, passing `bot_id` as the first argument.

This keeps the diff in orchestrators / risk_gate / exit_advisor zero. No call sites change.

### `src/trade_memory.py`

Same treatment: shim through `src.db`, inject `bot_id` from env. The memory index notes this module exists for cross-session learning — keeping its interface stable is important.

### Env vars (new on each bot)

- `DATABASE_URL` — `postgresql://user:pass@ai-predicted-wins-db:5432/aipw` (Coolify auto-injects when you link the Postgres service to the bot application)
- `BOT_ID` — `A` or `B` (crash-on-missing, crash-on-invalid)

Bot A: `qjyla085qflghz7h0dpsk7mh` gets `BOT_ID=A`.
Bot B: `v147jk2s2sm0n7aov83ph8y2` gets `BOT_ID=B`.

### Dockerfile.alpaca

Add `psycopg[binary]==3.2.*` and `psycopg_pool==3.2.*` to `requirements.txt`. No other changes — bot is still a single process.

### Local dev

New `docker-compose.dev.yml` at the repo root spins up:
- `postgres:16-alpine` with a named volume and `POSTGRES_DB=aipw`
- Bot A (volume-mounted source, `BOT_ID=A`)
- Bot B (volume-mounted source, `BOT_ID=B`)
- Dashboard API + web (volume-mounted source, hot reload)

Existing `dashboard/docker-compose.dev.yml` is replaced or superseded by this root-level compose file. A local smoke script asserts all three apps can connect to Postgres.

---

## Dashboard Backend Changes

### `dashboard/api/db.py`

Replace the SQLite connection helper with a psycopg3 `ConnectionPool`. Same context-manager API so route files barely change:

```python
@contextmanager
def get_db() -> Generator[psycopg.Connection, None, None]:
    with _pool.connection() as conn:
        yield conn
```

Pool settings: `min_size=2, max_size=10, timeout=30`. Reads `DATABASE_URL` from env.

Because we are switching drivers, a few small query adjustments are required:
- `?` placeholders become `%s`.
- `sqlite3.Row` becomes `psycopg.rows.dict_row` factory for the same dict-style access.
- `LIKE 'prefix%'` with date string matching works identically in Postgres.

### Route-level changes

Every route file (`portfolio.py`, `positions.py`, `equity.py`, `trades.py`, `signals.py`, `risk_gate.py`, `settings.py`, `activity.py`) gains a `bot: Literal["A", "B", "both"] = "both"` query parameter.

**Time-series routes** (`equity.py`, `trades.py` history, signals history): when `bot="both"`, return a structure keyed by `bot_id`:

```json
{
  "data": {
    "series": [
      { "bot_id": "A", "points": [{"timestamp": "...", "equity": 98380.12, "return_pct": -1.62}, ...] },
      { "bot_id": "B", "points": [{"timestamp": "...", "equity": 101200.50, "return_pct": 1.20}, ...] }
    ]
  },
  "meta": { ... }
}
```

**Aggregate routes** (`portfolio.py`): when `bot="both"`, return a map:

```json
{
  "data": {
    "A": { "equity": 98380.12, "total_pnl": -1620.00, "win_rate": 0.42, ... },
    "B": { "equity": 101200.50, "total_pnl": 1200.50, "win_rate": 0.38, ... }
  }
}
```

When `bot="A"` or `bot="B"`, both endpoint shapes collapse to the current single-value shape for backwards compatibility.

### New: `dashboard/api/alpaca.py`

Read-only Alpaca client for the dashboard. Uses dedicated env vars:
- `DASH_ALPACA_API_KEY`
- `DASH_ALPACA_SECRET_KEY`

These are paper-account credentials with market-data access only — no trading scope needed. A separate set of keys keeps the dashboard's Alpaca calls isolated from either bot's trading state.

Exposes:
- `get_spy_bars(start: datetime, end: datetime, timeframe: str) -> list[Bar]` — fetches SPY daily closes from Alpaca's stock data client.
- `get_account_health() -> Literal["ok", "degraded", "down"]` — lightweight `get_account()` ping used by the settings endpoint's health check. Cached 30s.

### New: `dashboard/api/routes/benchmark.py`

`GET /api/benchmark/spy?since=<ISO>&timeframe=1Day`

Fetches SPY daily closes from Alpaca since the earliest bot trade timestamp, caches in memory for 5 minutes (one simple dict + TTL), returns the same `{ timestamp, equity, return_pct }` shape the frontend already understands.

**Normalization:** SPY's `return_pct` is computed from its first close in the response window, so the benchmark line starts at 0% at the same time as the bot equity curves. This makes the overlay visually comparable.

### New: `dashboard/api/routes/bots.py`

`GET /api/bots`

Returns the contents of the `bots` registry table:

```json
{
  "data": [
    {
      "id": "A",
      "label": "Bot A — Conservative",
      "starting_equity": 100000.0,
      "alpaca_key_prefix": "PKIZ5BFZ",
      "config_flags": {
        "kelly_fraction": 0.25,
        "min_confluence": 3,
        "skip_risk_gate": false
      }
    },
    {
      "id": "B",
      "label": "Bot B — Aggressive",
      "starting_equity": 100000.0,
      "alpaca_key_prefix": "PKVKN5V5",
      "config_flags": {
        "kelly_fraction": 0.50,
        "min_confluence": 2,
        "skip_risk_gate": true
      }
    }
  ]
}
```

Frontend uses this to render the bot filter toolbar dynamically and to display config comparison on a future `/bots` page. No hardcoded `A`/`B` in the UI code.

### Equity normalization logic (`equity.py`)

For each bot, compute:

```python
starting_equity = bots[bot_id].starting_equity  # from the bots registry
return_pct      = (equity - starting_equity) / starting_equity * 100.0
```

Return both absolute `equity` and `return_pct` in each point. The frontend chooses which axis to use (it uses `return_pct` for the overlay chart so SPY can share the same Y-axis).

### Settings health check

Replace `alpaca_api="unknown"` in `settings.py` with a real ping via `dashboard/api/alpaca.py:get_account_health()`. Return `"ok" | "degraded" | "down"` with 30s in-memory cache.

Optionally add a Postgres health check: `"ok"` if the pool yields a connection within 1s, `"degraded"` otherwise.

---

## Dashboard Frontend Changes

### `components/shared/BotFilter.tsx` (new)

Filter chip bar rendered at the top of the Overview page (and above charts on other pages):

```
┌─────────────────────────────────────────┐
│  [ ● Bot A ]  [ ● Bot B ]  [ ● S&P 500 ] │
└─────────────────────────────────────────┘
```

- Each chip is clickable and toggles visibility of the corresponding series.
- State lives in `BotFilterContext` (React Context) so it persists across page navigations within the same browser session.
- Defaults: all three visible.
- Chip colors match the chart line colors (blue / amber / gray).
- The chip labels pull from `/api/bots` so we never hardcode `A`/`B` strings in the UI.

### `EquityCurve.tsx` — multi-series rewrite

Takes `series: EquitySeries[]` instead of a flat `EquityPoint[]`.

Renders up to 3 Recharts components on the same chart:
- Bot A — `<Area>` with blue gradient (`#60a5fa`)
- Bot B — `<Area>` with amber gradient (`#fbbf24`)
- SPY — `<Line>`, dashed, gray (`#94a3b8`)

Only series enabled in `BotFilterContext` are rendered. Y-axis is `return_pct` (labelled as `%`), X-axis is `timestamp`. Custom tooltip shows all enabled series values at the hovered time. Legend is implicit — the `BotFilter` toolbar above the chart IS the legend.

Empty state unchanged when no data: "No equity data available yet. Trades will appear here once the bots place them."

### `HeroKPI.tsx`

When `both` is active, stacks two hero numbers vertically:

```
Bot A: $98,380     -1.62%
Bot B: $101,200    +1.20%
```

When only one bot is enabled via the filter, falls back to the existing single-value design.

### `MetricCard.tsx`

Becomes dual-value when both bots are enabled. Shows `A / B` inline for Total P&L, Win Rate, Open Positions, Daily P&L. Each half of the card gets its own color coding (green/red) independently.

### `PositionCard.tsx`

Gains a small `A` / `B` badge in the top-right corner, colored to match the chart line for that bot.

### Data-fetching hooks

Every `useAPI` call in `page.tsx`, `positions/page.tsx`, `trades/page.tsx`, `signals/page.tsx`, `risk-gate/page.tsx` reads the current `BotFilterContext` value and appends `?bot=A|B|both` to the URL.

When a single bot is enabled via the filter, the fetched endpoints return the flat single-value shape (backwards compatible). When multiple bots are enabled, they return the keyed shape. The hook/TypeScript types branch accordingly via a discriminated union.

### New page: `/bots` (P2, optional)

Side-by-side bot config comparison pulled from `/api/bots`. Shows Kelly fraction, min confluence, risk gate state, starting equity, Alpaca key prefix, etc. Useful context for interpreting A/B performance. Marked as P2 — ship after the core overlay works.

---

## Testing

Three layers, each a hard gate before shipping to production:

### Unit tests (backend)

Location: `dashboard/api/tests/test_routes.py`

A pytest fixture spins up a throwaway Postgres (testcontainers or local docker-compose), seeds it with synthetic Bot A and Bot B rows in every table, then asserts each endpoint returns the correct shape with `bot=A`, `bot=B`, and `bot=both`. Specific assertions:
- `/api/portfolio?bot=A` returns flat shape with Bot A's totals.
- `/api/portfolio?bot=both` returns keyed shape with both bots.
- `/api/equity?bot=both` returns two series with correctly computed `return_pct`.
- `/api/benchmark/spy` returns non-empty points with `return_pct` starting at 0%.
- `/api/settings` returns `alpaca_api: "ok"` when Alpaca is reachable, `"down"` when keys are wrong.

### Integration tests (local docker-compose)

`docker-compose.dev.yml` spins up Postgres + Bot A + Bot B + Dashboard. Smoke script (`scripts/smoke.sh`):
1. Wait for Postgres healthcheck.
2. Insert fake trades directly into Postgres tagged for each bot.
3. Hit `/api/portfolio?bot=both` and assert both bots show non-zero values.
4. Hit `/api/equity?bot=both` and assert two series come back.
5. Hit `/api/benchmark/spy` and assert SPY points are present.
6. Hit `/api/settings` and assert `alpaca_api == "ok"`.
7. Kill Postgres container, hit `/api/portfolio`, assert 503 with a clean error payload.
8. Bring Postgres back, assert the next request recovers.

### Visual smoke test (Playwright)

`scripts/visual-smoke.ts`:
1. Navigate to the deployed dashboard (or localhost during dev).
2. Wait for the overview page to render.
3. Assert the equity chart has 3 SVG paths (Bot A area, Bot B area, SPY line).
4. Click each filter chip, assert the corresponding path disappears/reappears.
5. Assert `HeroKPI` renders two stacked values when `both` is active.
6. Assert no `$0.00` balance and no "waiting for bot activity" messages appear.
7. Take a screenshot and save as `artifacts/dashboard-smoke-{timestamp}.png` for manual review.

---

## Migration Runbook

Ordered steps. Each is a hard gate — do not proceed if the prior step failed.

1. **Backup both bots' SQLite files** to local disk and a separate S3-like location. Refuse to continue without verification.
2. **Provision Coolify Postgres** inside the `AI Predicted Wins` project. Note the `DATABASE_URL`.
3. **Deploy the bot image with schema bootstrap** to a staging Coolify app (not Bot A or Bot B yet) — this creates the schema safely.
4. **Run `scripts/migrate_sqlite_to_postgres.py`** against both backup files. Verify row counts match. Verify `SELECT COUNT(*) FROM alpaca_trades WHERE bot_id = 'A'` matches source. Same for B.
5. **Add `DATABASE_URL` and `BOT_ID` env vars** to Bot A's Coolify app. Redeploy Bot A. Tail logs, assert it connects to Postgres and writes a fresh row.
6. **Repeat step 5 for Bot B.**
7. **Add `DATABASE_URL` and `DASH_ALPACA_*` env vars** to the Dashboard app. Redeploy. Load `https://app.aipredictedwins.com`. Assert the overview page shows non-zero data for both bots and the SPY line renders.
8. **Rollback plan:** if any step fails, redeploy the last known-good image tag for the failing application in Coolify (Bot A, Bot B, or Dashboard). The previous image still uses the SQLite code path and will continue writing to its `/app/data/trades.db` on its existing volume — which we deliberately leave untouched during the migration. The `alpaca-paper-data` volumes are NOT deleted until post-deployment verification passes.

---

## Open Questions

None remaining — the brainstorming round clarified all architectural decisions (Postgres hosting, data migration, UI layout, SPY normalization). Any edge cases discovered during plan-writing will be surfaced as sub-questions in the implementation plan.

## Risks

- **Coolify Postgres backup cadence** — verify it's actually running before trusting it. Add a manual pg_dump to the daily audit until confirmed.
- **Schema drift between bots** — both bots run the same `db_schema.sql` on startup, but there's a race window on first deploy. Mitigation: deploy the schema via a standalone one-shot job (step 3 above) before either bot starts writing.
- **SPY data cost** — Alpaca's stock market data is free for paper accounts, but if this changes the 5-minute cache keeps request volume low.
- **Migration idempotency** — the `(bot_id, source_id)` unique index approach is new to this codebase; verify on staging by running the migration twice against the same backup files and asserting no duplicates appear.

---

## Implementation Priority

The implementation plan (generated next via writing-plans) will break this into sequenced tasks roughly matching:

1. **P0 — Unblock the dashboard** (schema + migration + bot shim + dashboard backend + single-bot view)
2. **P0 — Multi-bot overlay** (BotFilter, EquityCurve rewrite, dual HeroKPI/MetricCard)
3. **P0 — SPY benchmark** (Alpaca client, benchmark route, chart integration)
4. **P0 — Health checks** (replace `alpaca_api="unknown"`)
5. **P1 — Testing harness** (unit, integration, visual smoke)
6. **P2 — `/bots` comparison page**
