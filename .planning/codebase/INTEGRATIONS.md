# External Integrations

**Analysis Date:** 2026-05-31

## APIs & External Services

**Trading / Market Data:**
- **Alpaca** - executes paper crypto+stock trades + fetches bars (`src/alpaca_client.py`, `src/alpaca_orchestrator.py`, `dashboard/api/alpaca_client.py`)
  - SDK: `alpaca-py` 0.43.2; crypto symbols `BTC/USD`; stocks plain tickers; supports long + short (margin)
  - **ONE ACCOUNT PER BOT (hard rule)** — never share. Per-bot keys live in the `bots` DB row (`src/bot_config.py`), not just env
  - Hosts: paper `https://paper-api.alpaca.markets`, live `https://api.alpaca.markets` (live BLOCKED by paper gate)
  - Health: `dashboard/api/alpaca_health.py`

- **yfinance** - stock/benchmark quotes in the dashboard API (`yfinance>=0.2.0`); used by the benchmark route

- **Kalshi** - prediction markets — **PAUSED, do not run** (`src/orchestrator.py`, `src/kalshi_client.py`)
  - SDK: `kalshi-python` (root requirements); RSA-signed via `private_key.pem`
  - Demo `https://demo-api.kalshi.co/trade-api/v2`, prod `https://api.elections.kalshi.com/trade-api/v2` (`src/config.py`)

**Swarm Intelligence / LLM Risk:**
- **MiroFish** - swarm-simulation risk gate + exit advisor (guardian, not primary signal)
  - Client `src/mirofish_client.py` (`requests` + `openai`); used by `src/risk_gate.py` (5-analyst entry veto) and `src/exit_advisor.py`
  - Backend Flask on **port 5001**; `FLASK_PORT=5001` MUST match `VITE_BACKEND_URL=http://localhost:5001`
  - `MIROFISH_BACKEND_URL` env (default `http://localhost:5001`)
  - 8-step pipeline: graph/ontology/generate → graph/build → simulation/create → prepare → start → run-status → report/generate → report/{id}
  - Probability extraction asks AGENT CONSENSUS (not LLM self-estimate) to avoid 1-5% low bias

- **ai4trade.ai** - external swing-trade signal/leaderboard provider, copytraded by **Bot E** (`src/ai4trade_client.py`, `src/claude_copytrade.py`, `src/copytrade_thread.py`)
  - Base URL default `https://ai4trade.ai`; timeout default 90s (server takes 30-45s). Token/agent/followed-leaders/last-seen state persisted in the `copytrade_state` Postgres table (not env)
  - Endpoints (verified vs `https://ai4trade.ai/openapi.json`): `POST /api/claw/agents/selfRegister`, `GET /api/agents/top`, `POST /api/signals/follow|unfollow`, `GET /api/signals/feed`, `GET /api/signals/following` (Bearer)

- **TradingAgents** (vendored, `vendor/TradingAgents/`) - multi-agent debate framework powering **Bot C** (`src/bot_c/`, `src/tradingagents_gate.py`)
  - LLM via the Bot C shim `src/bot_c/llm_shim.py` (uvicorn :8765, supervisord program `bot_c_shim`); caches responses to `BOT_C_SHIM_CACHE` SQLite (default `/app/data/bot_c_llm_cache.db`)
  - Models: `claude-sonnet-4-6` deep/quick think (env-overridable `TRADINGAGENTS_DEEP_THINK_LLM` / `_QUICK_THINK_LLM`)

**LLM Gateway:**
- **Claude Code Bridge** (`gateway/main.py`, FastAPI + uvicorn, "v2.0.0") - OpenAI-compatible (`/v1/chat/completions`, `/v1/models`, `/health`); spawns `claude -p --output-format json` subprocess per request, backed by Claude Max OAuth (zero incremental cost)
  - Env: `PROJECTS_DIR` (default `./projects`), `CLI_TIMEOUT` (default 300s), `DEFAULT_PROJECT` (default `mirofish`); `X-Project` header routes to a project folder's CLAUDE.md context (`gateway/projects/mirofish/`)
  - Models advertised: `claude-sonnet-4-6`, `claude-opus-4-6`, `claude-haiku-4-5`
  - Auth: Claude CLI OAuth — `claude login` in Coolify terminal; persistent volume `/root/.claude`. **Never Anthropic API keys.**
  - Consumed by Python LLM code via `openai` client pointed at `LLM_BASE_URL` (`src/config.py`, `src/mirofish_client.py`, `src/claude_llm.py`); Bot C uses the separate in-container shim above

## Data Stores

**Primary Database — Postgres (Coolify):**
- Shared Postgres is the single source of truth; bots write, dashboard reads. `DATABASE_URL` required
- Bots: sync pool `src/db.py` (`psycopg` + `ConnectionPool`, min 2/max 10, `dict_row`); auto-bootstraps `src/db_schema.sql` on first use
- Dashboard: sync pool `dashboard/api/db.py` (`ConnectionPool`, `query_filtered(sql, params, bot)` with `KNOWN_BOTS=("A","B","C")`)
- Schema: `src/db_schema.sql` + numbered migrations `dashboard/api/migrations/00X_*.sql` run by `run_migrations.py`
- Tables seen: `alpaca_trades`, `trades` (legacy Kalshi), `simulations`, `validations`, `screenings`, `signals`, `bots`, `copytrade_state`, learning/risk-gate/tradingagents tables
- The `bots` table drives `src/bot_manager.py` (one thread per active bot) and per-bot config (`src/bot_config.py`)

**SQLite (local/auxiliary):**
- `data/trades.db` (gitignored) — legacy/local SQLite per CLAUDE.md; superseded by Postgres in prod. Migration helper `scripts/migrate_sqlite_to_postgres.py`
- Bot C LLM response cache: SQLite at `BOT_C_SHIM_CACHE`
- Backtester bar cache: `data/bar_cache`

**File Storage:**
- Local filesystem only — `data/bot_output.log`, `data/backtest_results/`, `data/screenshots/`, `private_key.pem`, `.env`

**Caching:**
- Bot C LLM shim cache (SQLite); no Redis detected

## Authentication & Identity

- **Trading:** Alpaca per-bot key/secret stored in the `bots` DB row (`src/bot_config.py`); Kalshi RSA signing via `private_key.pem` (paused)
- **LLM:** Claude CLI OAuth (no API keys)
- **Dashboard API:** `DASHBOARD_TOKEN` env — frontend sends as Bearer; all routes 401 without it (`dashboard/api/main.py`). Frontend gate: `login` page + `AuthGuard` (`dashboard/web/app/login/`, `components/auth/AuthGuard.tsx`). NOT wired to Titanium licensing.

## Monitoring & Observability

**Error Tracking:** None (no Sentry/etc.)

**Logs:**
- INFO logging enabled at app startup (commit 0b63724) to surface bot thread activity; `LOG_LEVEL` env in dashboard API
- `data/bot_output.log`; supervisord pipes all programs to stdout/stderr
- `src/daily_audit.py` + `scripts/daily_audit.py` daily audit; `scripts/get_deploy_logs.py`

**Health:**
- Dashboard `/health` (FastAPI); gateway `/health`; `src/gateway_health.py`; `dashboard/api/alpaca_health.py`

## Notifications (Email)

- **AWS SES via boto3** is the actual send path in code — `src/notifier.py` and `src/alerter.py` both call `boto3.client("ses", ...)`. Sender `alerts@emails4agents.com`, recipient `articulatedesigns@gmail.com`.
  - Creds: `~/.claude/secrets/services.json` (`aws` block) for local dev, else env `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_DEFAULT_REGION` (default `us-west-2`/`us-east-1`) in container
  - NOTE: global rule 7 prefers the emails4agents HTTP API; current code uses SES directly (emails4agents domain is only the verified sender identity). Flag if standardizing.
  - Failures logged, never raised — alerts can't crash the bot
  - Triggers: bot crash/thread death, drawdown stop, position-monitor failure, daily summary; rate-limited per event type
- Silent-bot alerts: `TRADE_SILENCE_ALERT_HOURS` (default 24, `src/bot_manager.py`)

## CI/CD & Deployment

**Hosting:** Coolify (https://coolify.titaniumlabs.us, server 46.224.61.233); project "AI Predicted Wins" UUID `u7x0xw0y4qvcgeh8vyidsgyi`
- Combined container (supervisord: api :8000 + web :3000 + bot_c_shim :8765) via `dashboard/Dockerfile` + `dashboard/supervisord.conf`; trading bots run as threads inside the api process (FastAPI lifespan → BotManager)
- Gateway = separate Coolify service (`gateway/Dockerfile`, volume `/root/.claude`)
- Bots-only image `Dockerfile.alpaca`

**DNS:** Cloudflare zone `aipredictedwins.com` → https://app.aipredictedwins.com

**CI Pipeline:** None detected in repo

## Environment Configuration

**Required / key env vars:**
- `DATABASE_URL` — Coolify Postgres (bots + dashboard) [REQUIRED]
- per-bot Alpaca keys primarily in DB `bots` row; env `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` (and `_A`/`_B` per CLAUDE.md) for single-process/dev
- `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL_NAME` — Claude Code Bridge gateway
- `DASHBOARD_TOKEN` — dashboard API bearer auth (401 without it)
- `PROJECTS_DIR` / `CLI_TIMEOUT` / `DEFAULT_PROJECT` — gateway service
- `FLASK_PORT=5001` + `VITE_BACKEND_URL=http://localhost:5001`, `MIROFISH_BACKEND_URL` — MiroFish
- ai4trade.ai base URL/token/timeout — Bot E (token in `copytrade_state` table, not env)
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_DEFAULT_REGION` — SES email
- Tuning: `MAX_POSITION_PCT`, `MAX_TOTAL_EXPOSURE_PCT`, `DRAWDOWN_STOP_PCT`, `MIN_CONFLUENCE`, `SKIP_RISK_GATE`, `BOT_LABEL`, `BOT_ID`, `SHORT_ENABLED`, `CYCLE_SLEEP_SECONDS`, `POSITION_CHECK_INTERVAL`, `TRADE_SILENCE_ALERT_HOURS`, plus exit-advisor stop/take/trail thresholds and `TRADINGAGENTS_*`

**Secrets location:** root `.env` (gitignored), `private_key.pem` (gitignored), `~/.claude/secrets/services.json` (local AWS); prod values in Coolify env. `.env.example` exists but is empty. `check_envs.py` validates at startup.

## Webhooks & Callbacks

**Incoming:** None detected (dashboard pushes via SSE, not inbound webhooks)
**Outgoing:** None (notifications are direct SES calls, not webhooks)

## Realtime

- **SSE** via `sse-starlette` in dashboard API (activity feed, Claude chat) consumed by `dashboard/web/hooks/useSSE.ts` — matches "SSE over WebSockets" preference

---

*Integration audit: 2026-05-31*
