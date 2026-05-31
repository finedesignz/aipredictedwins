# Technology Stack

**Analysis Date:** 2026-05-31

## Languages

**Primary:**
- Python 3.13 - Trading bots (`src/*.py`), bot manager, signal engine, MiroFish/gateway clients, dashboard API (`dashboard/api/`), Claude Code Bridge (`gateway/`)
- TypeScript - Next.js 15 dashboard frontend (`dashboard/web/`)

**Secondary:**
- SQL (Postgres dialect) - schema + numbered migrations in `dashboard/api/migrations/*.sql`, `src/db_schema.sql`

## Runtime

**Environment:**
- CPython 3.13 (`.cpython-313` artifacts) for all backend/bot code
- Node.js for Next.js 15 frontend (built standalone, run via `node server.js`)
- Production: single Coolify container running `supervisord` (`dashboard/supervisord.conf`) with 3 programs — `api` (uvicorn `main:app` :8000), `web` (`node server.js` :3000), `bot_c_shim` (uvicorn `src.bot_c.llm_shim:app` :8765). **The trading bots are NOT a separate supervisord program** — `BotManager` is started inside the FastAPI `lifespan` of the `api` process (`dashboard/api/main.py` → `src/bot_manager.py`), spawning one thread per active bot from the `bots` DB table.

**Package Manager:**
- Python: `pip` via three `requirements.txt` (root bots, `dashboard/api/`, `gateway/`)
- Node: npm — `dashboard/web/package.json` + committed `package-lock.json`
- Version pins: Python uses `>=` floors (not fully pinned)

## Frameworks

**Bots / Core (Python, root `requirements.txt`):**
- `alpaca-py` >=0.21.0 (installed 0.43.2) - trading + market data; crypto symbols `BTC/USD`
- `kalshi-python` >=2.1.0 - Kalshi SDK. **Kalshi PAUSED** (CLAUDE.md references `kalshi-python-sync`; root requirements lists `kalshi-python`)
- `pandas` >=2.0.0 - technical indicators (`src/technical_signals.py`)
- `openai` >=1.0.0 - OpenAI-compatible client pointed at the Claude Code Bridge gateway (`src/mirofish_client.py`, `src/claude_llm.py`)
- `requests` >=2.31.0 - HTTP for MiroFish, ai4.trade
- `psycopg[binary]` >=3.2 + `psycopg-pool` >=3.2 - Postgres access (sync pool in `src/db.py`)
- `boto3` >=1.34.0 - AWS SES email (`src/notifier.py`, `src/alerter.py`)
- `schedule` >=1.2.0 - periodic loops; `rich` >=13 - console output; `pytz` - tz handling

**Dashboard API (`dashboard/api/requirements.txt`):**
- `fastapi` + `uvicorn[standard]` - API backend, routes under `/api/*`, exposes `/health`
- `psycopg[binary]`/`psycopg-pool` - sync pool (`dashboard/api/db.py`)
- `sse-starlette` - Server-Sent Events (activity feed, Claude chat stream) — aligns with "SSE over WebSockets"
- `pydantic` - models (`dashboard/api/models.py`)
- `httpx` - outbound HTTP; `yfinance` >=0.2.0 - stock/benchmark quotes; `boto3` - AWS; `rich`

**Dashboard Web (`dashboard/web/package.json`):**
- `next` ^15.1.0, `react`/`react-dom` ^19.0.0
- `@tanstack/react-table` ^8.20, `recharts` ^2.15 (charts), `lucide-react` (icons)
- `tailwindcss` ^4.0 + `@tailwindcss/postcss`, `typescript` ^5.7
- App Router (`app/`), standalone output (`server.js`)

**Gateway (`gateway/requirements.txt`):**
- `fastapi` >=0.115 + `uvicorn[standard]` >=0.32 - OpenAI-compatible "Claude Code Bridge" v2.0.0 (`gateway/main.py`); spawns `claude -p --output-format json` per request, routes CLAUDE.md context via `X-Project` header

**Legacy/local:**
- `streamlit` >=1.30.0 - legacy local dashboard (`dashboard/app.py`)

**Vendored:**
- `vendor/TradingAgents/` - multi-agent debate framework powering Bot C (its own `requirements.txt`, Dockerfile)

## Key Dependencies

**Critical:**
- `alpaca-py` - executes all paper trades; ONE Alpaca account per bot (hard rule)
- `psycopg`/`psycopg-pool` - shared Coolify Postgres is the single source of truth for bots + dashboard
- `openai` - all LLM calls route through the Claude Code Bridge (never Anthropic API keys)

**Infrastructure:**
- `supervisord` - multi-process container orchestration
- `boto3` - AWS SES notifications

## Configuration

**Environment:**
- All secrets/config in root `.env` (gitignored); loaded via `python-dotenv` in `src/config.py`
- `DATABASE_URL` (Coolify Postgres) required by `src/db.py` and `dashboard/api/db.py`
- Heavy env-var-driven tuning in `src/alpaca_orchestrator.py` (MAX_POSITION_PCT, MAX_TOTAL_EXPOSURE_PCT=0.80, DRAWDOWN_STOP_PCT, MIN_CONFLUENCE, CYCLE_SLEEP_SECONDS=1800, POSITION_CHECK_INTERVAL=60, SKIP_RISK_GATE, BOT_LABEL, SHORT_ENABLED, etc.) and `src/exit_advisor.py` (stop/take-profit/trailing thresholds)
- Per-bot config is the DB `bots` table row (`src/bot_config.py` `BotConfig.from_row`): Alpaca keys, kelly_fraction, min_confluence, stops, RSI ceiling, crypto/stock universe, asset_class, strategy (`confluence` | `trend_btc`), skip_risk_gate, short_enabled, tradingagents_enabled — editable live via `PUT /api/bots/{bot_id}`
- `DASHBOARD_TOKEN` — dashboard API bearer auth (all routes 401 without it)
- `private_key.pem` (gitignored) - Kalshi RSA (paused)
- `check_envs.py` helper validates env

**Build/Deploy:**
- `Dockerfile.alpaca` (bots image), `dashboard/Dockerfile` (combined api+web+bot_c_shim via supervisord), `gateway/Dockerfile`
- `docker-compose.dev.yml` for local dev
- Coolify project "AI Predicted Wins" (UUID `u7x0xw0y4qvcgeh8vyidsgyi`); gateway is a separate Coolify service with persistent volume `/root/.claude`

## Source Modules (`src/`)

| File | Responsibility |
|------|----------------|
| `bot_manager.py` | Started in FastAPI lifespan — loads `bots` table, spawns one `BotThread`/`CopyTraderThread` per active bot, watchdog restarts dead threads, liveness/silence alerts |
| `bot_thread.py` / `copytrade_thread.py` | Per-bot run loops |
| `bot_config.py` | `BotConfig` dataclass loaded from DB `bots` row |
| `alpaca_orchestrator.py` | v2 pipeline: technical signals → rules/risk gate → trade (env-tunable) |
| `technical_signals.py` | EMA/ADX/RSI/Volume/VWAP confluence (0-5) |
| `rules_gate.py` | Deterministic gate (gap>5%, ADX<12 veto) |
| `risk_gate.py` / `exit_advisor.py` | MiroFish entry veto / exit advice |
| `mirofish_client.py` | 8-step MiroFish pipeline + probability extraction (uses `openai` client) |
| `claude_llm.py` | LLM helper over gateway |
| `claude_copytrade.py` / `ai4trade_client.py` | Bot E copytrade from ai4trade.ai leaderboard |
| `bot_c/` | Bot C TradingAgents integration + `llm_shim.py` (cached LLM proxy :8765) |
| `tradingagents_gate.py` | Bot C gate wiring |
| `trend_strategy.py` | `trend_btc` strategy (50DMA trend follower on BITX) |
| `position_sizer.py` | Quarter-Kelly sizing |
| `db.py` | Sync Postgres pool + trade/sim/signal persistence |
| `trade_logger.py` / `trade_memory.py` | Trade persistence + history (Postgres) |
| `notifier.py` / `alerter.py` | AWS SES email alerts (rate-limited) |
| `learning_loop.py` / `signal_validator.py` | Signal QC + parameter learning |
| `orchestrator.py` / `kalshi_client.py` / `gap_detector.py` / `market_evaluator.py` / `quick_simulator.py` / `event_formatter.py` | Kalshi path — **PAUSED** |
| `backtester/` | Backtesting harness (bar cache `data/bar_cache`) |
| `config.py` | Env/config loader (`Config` dataclass) |

## Dashboard API Modules (`dashboard/api/`)

- `main.py` (FastAPI app, CORS, Bearer auth via `DASHBOARD_TOKEN`, BotManager lifespan, mounts routes, `/health`)
- `routes/` — activity, alpaca, benchmark, bots, chat, equity, portfolio, positions, risk_gate, settings, signals, trades
- `db.py` (sync pool, `KNOWN_BOTS=("A","B","C")`, `query_filtered`), `models.py` (pydantic), `migrations/` (numbered `.sql` + `run_migrations.py`), `seed_bots.py`, `alpaca_health.py`

## Bots (from README)

| Bot | Asset | Strategy |
|-----|-------|----------|
| Bot A | Crypto | Kelly 0.25, min confluence 3, MiroFish risk gate ON |
| Bot B | Crypto | Kelly 0.50, min confluence 2, risk gate OFF (speed test) |
| Bot C | Stocks | Kelly 0.25, min confluence 3, market-hours gated, TradingAgents |
| Bot E | (copytrade) | ai4trade.ai leaderboard copytrader |

## Platform Requirements

**Development:**
- Python 3.13 + `pip install -r requirements.txt` (and `dashboard/api/requirements.txt`)
- Node.js for `dashboard/web`
- A reachable Postgres (`DATABASE_URL`)

**Production:**
- Coolify (https://coolify.titaniumlabs.us, server 46.224.61.233)
- Alpaca paper mode only (live BLOCKED until 50+ paper trades, win rate >40%, $100k equity)

## How the App Is Started

```bash
# Prod (Coolify container): supervisord runs all three —
uvicorn main:app --host 0.0.0.0 --port 8000   # api; BotManager starts in lifespan
node server.js                                # Next.js web :3000
uvicorn src.bot_c.llm_shim:app --port 8765    # Bot C TradingAgents LLM shim
# (trading bots are threads inside the api process, not a standalone command)

# Single bot, manual / dev
python -m src.alpaca_orchestrator --mode paper --max-trades 50
python -m src.alpaca_orchestrator --mode evaluate    # signals only

# Local full stack
cd dashboard && docker compose up

# Legacy local dashboard
streamlit run dashboard/app.py

# Kalshi — PAUSED (do not run):
# python -m src.orchestrator --mode paper --max-trades 200
```

---

*Stack analysis: 2026-05-31*
