# Multi-Bot Consolidation Design

**Date:** 2026-04-10  
**Status:** Approved  

---

## Problem

Two separate Coolify apps (Bot A, Bot B) run the same `alpaca_orchestrator.py` binary with different env vars. Adding a third strategy means a third Coolify app, manual env var management, and no way to adjust config without redeploying. There is no in-app way to add bots or interact with the system.

---

## Goals

1. Run N bots (each with its own Alpaca account and strategy params) from a single deployment
2. Dashboard UI to add, edit, enable/disable bots without touching Coolify
3. Config changes take effect immediately — no restart required
4. Claude Code chat UI embedded in the dashboard for natural-language trade interaction

---

## Architecture

Single Coolify app (`aipredictedwins-dashboard`) — supervisord manages two processes:

```
aipredictedwins-dashboard
└── supervisord
    ├── nextjs    — Next.js frontend (port 3000)
    └── fastapi   — FastAPI backend (port 8000)
                    └── lifespan: BotManager
                        ├── BotThread(bot_id="A") ──► Alpaca account A
                        ├── BotThread(bot_id="B") ──► Alpaca account B
                        └── BotThread(bot_id="N") ──► Alpaca account N
```

The `BotManager` lives in FastAPI's app state. On startup it reads all `enabled=true` bots from Postgres and spawns threads. API endpoints drive all thread lifecycle changes reactively — no polling loop.

The two existing Bot A and Bot B Coolify apps are deleted after migration.

---

## Database Schema

### New table: `bots`

```sql
CREATE TABLE bots (
    id                SERIAL PRIMARY KEY,
    bot_id            VARCHAR(10) UNIQUE NOT NULL,   -- "A", "B", "C"
    label             VARCHAR(100) NOT NULL,          -- "Agent A"
    alpaca_api_key    VARCHAR(200) NOT NULL,
    alpaca_secret_key VARCHAR(200) NOT NULL,
    kelly_fraction    FLOAT   DEFAULT 0.25,
    min_confluence    INT     DEFAULT 3,
    hard_stop_pct     FLOAT   DEFAULT -0.08,
    soft_stop_pct     FLOAT   DEFAULT -0.05,
    rsi_ceiling       FLOAT   DEFAULT 65.0,
    crypto_universe   TEXT    DEFAULT 'BTC/USD,ETH/USD,SOL/USD,XRP/USD',
    skip_risk_gate    BOOLEAN DEFAULT FALSE,
    max_position_pct  FLOAT   DEFAULT 0.05,
    enabled           BOOLEAN DEFAULT TRUE,
    status            VARCHAR(20) DEFAULT 'stopped', -- 'running'|'stopped'|'error'
    status_detail     TEXT,                          -- last error message if any
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);
```

### Existing table: `alpaca_trades`
No schema change — already has `bot_id` column. All queries scoped by `bot_id`.

### Migration seed
On first run, seed Bot A and Bot B rows from current Coolify env vars so no trade history or config is lost.

---

## Bot Runner (`src/bot_manager.py`)

```
BotManager
├── _threads: dict[str, BotThread]
├── start_all()       — called from FastAPI lifespan, reads DB, spawns all enabled bots
├── add(config)       — insert DB row + spawn thread immediately
├── update(bot_id, config) — update DB row + push new config to live thread
├── stop(bot_id)      — signal thread to stop cleanly + update DB status
└── status()          — return dict of bot_id → {status, equity, thread_alive}
```

```
BotThread(config: BotConfig)
├── owns: AlpacaClient, TradeLogger, ExitAdvisor, RiskGate
├── runs: standard orchestrator scan/monitor loop
├── config: held as a threading.Event-safe reference
│   └── update_config(new_config) replaces config atomically
│       next scan cycle picks it up — no restart needed
└── writes status back to bots.status column on state changes
```

Each thread is fully isolated — its own Alpaca credentials, its own DB writes scoped to `bot_id`. A thread crash is caught, logged, and written to `bots.status_detail`; the BotManager can restart it without affecting other threads.

---

## API Endpoints

| Method | Path | Action |
|--------|------|--------|
| GET | `/api/bots` | List all bots with live status + equity |
| POST | `/api/bots` | Add bot → DB insert + thread spawn |
| PUT | `/api/bots/{bot_id}` | Edit config → DB update + live thread config push |
| DELETE | `/api/bots/{bot_id}` | Remove bot → thread stop + DB delete |
| POST | `/api/bots/{bot_id}/enable` | Enable disabled bot → spawn thread |
| POST | `/api/bots/{bot_id}/disable` | Graceful stop, keep DB row |

---

## Dashboard UI

### `/bots` page

**Bot list** — dynamically fetches all bots from `GET /api/bots` on page load and polls every 30s for status updates. The list reflects exactly what is in the DB — no hardcoded Bot A/Bot B references anywhere in the frontend. Every existing component that currently references "Agent A" / "Agent B" by name is updated to iterate over the bots array from the API.

One card per bot:
- Label + bot_id badge
- Status dot (green=running, red=error, grey=stopped)
- Live equity + daily P&L (fetched from Alpaca on each card render)
- Enable/disable toggle
- Edit button → opens drawer

**Add/Edit drawer** (slide-in panel):
- Label
- Alpaca API Key + Secret Key (masked, never shown after save)
- Kelly fraction (slider 0.1–1.0)
- Min confluence (1–5)
- Hard stop % (slider -3% to -15%)
- Soft stop % (slider -1% to -10%)
- RSI ceiling (50–80)
- Asset universe (checkbox: BTC ETH SOL XRP ADA AVAX DOT LINK)
- Skip risk gate (toggle)
- Max position % (slider 1%–10%)

Save is optimistic — updates UI immediately, rolls back on API error.

---

## Claude Chat UI

### Claude Credential Persistence

The `claude` CLI authenticates via OAuth tokens stored in `/root/.claude/.credentials.json`. These must survive container rebuilds and never expire during normal operation.

**Mechanism:**
1. Coolify stores `CLAUDE_CREDENTIALS` env var (JSON blob of the credentials file)
2. `entrypoint.sh` writes it to `/root/.claude/.credentials.json` on every container start — this refreshes the file even after a rebuild
3. A persistent Coolify volume mounts `/root/.claude` — so tokens refreshed by the CLI at runtime are also preserved between restarts
4. A background health-check task in FastAPI runs `claude --version` every 6 hours; if it fails (token expired), it rewrites credentials from `CLAUDE_CREDENTIALS` env var and alerts via the notifier

This means credentials never expire silently — the dashboard itself monitors and self-heals the Claude auth state.

### Backend: `POST /api/chat/message` (SSE response)

Accepts `{ message: string, context?: object }`. Spawns `claude` CLI subprocess with:
- System prompt injected with current bot statuses, open positions, recent P&L
- User message appended
- Streams stdout back as SSE events

Uses `/root/.claude` credentials maintained by the persistence mechanism above.

### Frontend: `/chat` page + sidebar widget

- Chat thread UI (messages + streaming response)
- Context panel showing current portfolio state (so Claude sees what the user sees)
- Suggested actions rendered as buttons when Claude's response includes actionable items (e.g. "tighten Bot B stop to -6%" → **Apply** button calls `PUT /api/bots/B`)
- Available from `/chat` page and as a collapsible sidebar on all dashboard pages

---

## Migration Plan

1. Add `bots` table to Postgres schema
2. Seed Bot A and Bot B rows from current Coolify env vars
3. Implement `BotManager` + `BotThread` in `src/bot_manager.py`
4. Wire `BotManager` into FastAPI lifespan
5. Add `/api/bots` CRUD endpoints
6. Add `/api/chat/message` SSE endpoint
7. Build `/bots` page in Next.js dashboard
8. Build `/chat` UI
9. Add `/root/.claude` persistent volume to dashboard Coolify app + set `CLAUDE_CREDENTIALS` env var
10. Update `entrypoint.sh` to write credentials on startup + add FastAPI health-check task
11. Deploy dashboard update
12. Verify both bots running via new manager
13. Verify Claude chat working with fresh credentials
14. Delete old Bot A + Bot B Coolify apps

---

## Dynamic Bot References

Every part of the UI that currently hardcodes "Agent A" / "Agent B" is replaced with dynamic rendering from the `bots` API:

- **Equity chart** — renders one line per bot returned from DB; color assigned by index; legend labels use `bot.label`
- **Portfolio header stats** — one stat pill per bot, not hardcoded two
- **Positions page** — bot badge uses `bot.label` from DB
- **Trades table** — bot column populated from `bot_id` → `label` lookup
- **Activity feed** — bot label resolved from DB, not hardcoded

Adding a third bot in the `/bots` UI automatically makes it appear everywhere with no frontend code changes.

---

## What Does NOT Change

- Existing orchestrator logic (`src/alpaca_orchestrator.py`) — untouched, just instantiated per-thread
- Alpaca account separation — each bot still has its own paper account
- Postgres `alpaca_trades` schema — `bot_id` column already exists
