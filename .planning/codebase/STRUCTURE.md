# Codebase Structure

**Analysis Date:** 2026-05-31

## Directory Layout

```
aipredictedwins/
├── src/                          # Trading engine (Python package, run via `python -m src.*`)
│   ├── bot_manager.py            # BotManager: spawns/revives one thread per enabled bot [309]
│   ├── bot_thread.py             # BotThread: per-bot scan/monitor loop (confluence/trend_btc) [727]
│   ├── copytrade_thread.py       # CopyTraderThread: Bot E ai4trade copy loop [510]
│   ├── bot_config.py             # BotConfig frozen dataclass (from bots DB row) [71]
│   ├── alpaca_orchestrator.py    # v2 pipeline + PositionMonitor + shared helpers + CLI [1200]
│   ├── technical_signals.py      # EMA/ADX/RSI/Volume/VWAP confluence + short_score + 4H trend [472]
│   ├── rules_gate.py             # Deterministic pre-entry gate (DEFAULT guardian) [133]
│   ├── risk_gate.py              # MiroFish/Claude 5-analyst LLM veto panel (optional) [201]
│   ├── exit_advisor.py           # ExitAdvisor + TrailingStop (HOLD/TIGHTEN/EXIT) [252]
│   ├── tradingagents_gate.py     # Bot C alternate LLM gate [393]
│   ├── trend_strategy.py         # trend_btc 50DMA strategy helpers [170]
│   ├── claude_copytrade.py       # Copytrade leader selection [120]
│   ├── ai4trade_client.py        # ai4trade.ai signals client [160]
│   ├── mirofish_client.py        # 7-step swarm pipeline + OpenAI-compatible client [448]
│   ├── claude_llm.py             # Claude CLI gateway client (OAuth) [338]
│   ├── db.py                     # Postgres DAL (DATABASE_URL, psycopg3 pool) [443]
│   ├── db_schema.sql             # Schema DDL (bootstrapped on first pool use)
│   ├── trade_logger.py           # Thin shim → src/db.py, bot_id-scoped [137]
│   ├── config.py / position_sizer.py / signal_validator.py / pipeline_state.py
│   ├── alpaca_client.py          # Alpaca trading/data wrapper (per-bot) [434]
│   ├── alpaca_evaluator.py       # Universe selection (TOP_CRYPTO_TICKERS, MEME_CRYPTO, dynamic) [370]
│   ├── trade_memory.py / learning_loop.py   # Optional trade-learning system
│   ├── notifier.py / alerter.py  # Email alerts (emails4agents)
│   ├── market_evaluator.py / gap_detector.py / event_formatter.py / quick_simulator.py / market_*
│   ├── kalshi_client.py / orchestrator.py   # Kalshi (PAUSED)
│   ├── backtester/               # Backtesting package
│   └── bot_c/                    # Bot C TradingAgents specifics (incl. llm_shim:app @ :8765)
├── dashboard/                    # Next.js + FastAPI, one Coolify container (supervisord)
│   ├── api/                      # FastAPI backend (uvicorn main:app :8000)
│   │   ├── main.py               # FastAPI app; lifespan owns BotManager; Bearer auth + CORS
│   │   ├── routes/               # activity, alpaca, benchmark, bots, chat, equity,
│   │   │                         #   portfolio, positions, risk_gate, settings, signals, trades
│   │   ├── db.py                 # Dashboard DB access (get_db)
│   │   ├── models.py             # Pydantic models (BotCreate/BotFull/BotUpdate, Envelope, Meta)
│   │   ├── alpaca_client.py / alpaca_health.py / seed_bots.py
│   │   ├── migrations/           # 002–013 *.sql + run_migrations.py
│   │   └── tests/                # test_db.py, test_routes.py
│   ├── web/                      # Next.js App Router frontend (node server.js :3000)
│   │   ├── app/                  # page-routed: bots/, positions/, trades/, signals/,
│   │   │                         #   risk-gate/, settings/, login/; page.tsx, layout.tsx, NavWrapper.tsx
│   │   ├── components/           # activity, auth, bots, charts, chat, kpi, nav, positions,
│   │   │                         #   risk-gate, settings, shared, signals, trades
│   │   ├── context/              # BotFilterContext.tsx, ChatContext.tsx
│   │   ├── hooks/                # useAPI.ts, useSSE.ts
│   │   ├── lib/                  # api.ts, format.ts
│   │   ├── next.config.ts / tailwind.config.ts / package.json (recharts)
│   │   └── public/
│   ├── app.py                    # Legacy Streamlit dashboard (superseded)
│   ├── supervisord.conf          # programs: api, web, bot_c_shim
│   ├── entrypoint.sh             # Claude creds bootstrap + migrations + seed → supervisord
│   └── Dockerfile
├── gateway/                      # Claude CLI → OpenAI-compatible bridge (standalone Coolify)
│   ├── main.py                   # FastAPI; spawns `claude -p` subprocess per request
│   ├── projects/                 # X-Project context dirs (default: mirofish)
│   └── entrypoint.sh / Dockerfile / requirements.txt
├── scripts/                      # Ops: daily_audit, check_*, seed_bot_e, migrate_sqlite_to_postgres, playwright_audit
├── tests/                        # pytest (test_technical_signals, test_exit_advisor, test_trade_logger_shim, ...)
├── data/                         # bot_output.log + legacy trades.db (runtime, gitignored)
├── vendor/                       # Vendored deps (incl. TradingAgents for bot_c)
├── Dockerfile.alpaca / docker-compose.dev.yml / requirements.txt
├── README.md / PROJECT_SUMMARY.md / CLAUDE.md
└── private_key.pem               # Kalshi RSA key (gitignored, paused)
```

## Directory Purposes

**`src/`** — Trading engine, importable as `src` package. Multi-bot orchestration (`bot_manager`/`bot_thread`/`copytrade_thread`), signals, guardians, Postgres DAL. Runs inside the dashboard FastAPI process (BotManager) or standalone via `python -m src.alpaca_orchestrator`.

**`dashboard/api/`** — FastAPI backend. `main.py` mounts `routes/*.py`, requires Bearer `DASHBOARD_TOKEN`, and OWNS BotManager via lifespan. Migrations under `api/migrations/`.

**`dashboard/web/`** — Next.js App Router UI, page-routed (one folder per top-level view under `app/`). Components grouped by feature; live data via `hooks/useSSE.ts` + `lib/api.ts`.

**`gateway/`** — Independent FastAPI service that spawns `claude -p --output-format json` per request (OAuth/Claude Max, no Anthropic API key). Consumed by `claude_llm.py`, risk gate, exit advisor, MiroFish, dashboard chat.

**`scripts/`** — One-off ops/diagnostics (audits, env setup, SQLite→Postgres migration, Playwright UI audit).

**`data/`** — Runtime logs + legacy SQLite. Source of truth is now Postgres (`src/db.py`).

## Key File Locations

**Entry Points:**
- `dashboard/api/main.py` — FastAPI `app` (primary runtime; BotManager via lifespan).
- `dashboard/supervisord.conf` / `dashboard/entrypoint.sh` — container launch (api/web/bot_c_shim).
- `src/bot_manager.py` — multi-bot supervisor.
- `src/alpaca_orchestrator.py` — `main()`/`evaluate()` single-bot CLI.
- `gateway/main.py` — gateway `app`.

**Configuration:**
- `bots` Postgres table — per-bot config (label, alpaca keys, kelly_fraction, min_confluence, stops, universe, asset_class, strategy, enabled). Read via `BotConfig.from_row` (`src/bot_config.py`).
- `.env` / Coolify env — `DATABASE_URL`, `DASHBOARD_TOKEN`, `CLAUDE_CREDENTIALS`, `LLM_BASE_URL`, `LIVE_TRADING_THRESHOLD`, `TRADE_SILENCE_ALERT_HOURS`, per-bot `ALPACA_API_KEY_*` (seed), thresholds.
- `src/config.py` (`load_config` → `Config`); runtime env tunables in `alpaca_orchestrator.py` and `exit_advisor.py`.

**Core Logic:** orchestration `src/bot_manager.py` + `src/bot_thread.py`; signals `src/technical_signals.py`; guardians `src/rules_gate.py` + `src/risk_gate.py`; exits `src/exit_advisor.py`.

**Persistence:** `src/db.py` (Postgres) via `src/trade_logger.py`; schema `src/db_schema.sql` + `dashboard/api/migrations/*.sql` (run via `run_migrations.py`).

**Testing:** `tests/` (engine), `dashboard/api/tests/` (API).

## Naming Conventions

- **Python modules:** snake_case (`bot_manager.py`).
- **Classes:** PascalCase (`BotManager`, `BotThread`, `CopyTraderThread`, `BotConfig`, `PositionMonitor`).
- **Value objects:** frozen dataclasses (`BotConfig`, `Signal`, `PipelineState`).
- **React:** PascalCase `.tsx` components under `dashboard/web/components/<feature>/`; routes are folders under `dashboard/web/app/`.
- **Bots:** short ids (`A`, `B`, `C`, `E`) as `bots.bot_id`; strategy ∈ {`confluence`, `trend_btc`, `copytrade`}.
- **Migrations:** numbered `NNN_description.sql`.

## Where to Add New Code

**New indicator / signal:** extend `src/technical_signals.py` (`Signal` fields + analysis); orchestrator/BotThread recompute confluence downstream.

**New guardian rule:** deterministic → `src/rules_gate.py`; LLM → `src/risk_gate.py` (via `claude_llm.py`).

**New exit behavior:** `src/exit_advisor.py` (ExitAdvisor/TrailingStop); thresholds env-backed + per-bot (`hard_stop_pct`/`soft_stop_pct` in `bots`).

**New strategy:** add a `strategy` value, dispatch it in `BotManager._spawn` (`src/bot_manager.py`); implement a Thread (sibling to `BotThread`/`CopyTraderThread`) or branch inside `BotThread`. Add config fields to `BotConfig` + a migration.

**New bot:** create a dedicated Alpaca paper account FIRST (HARD RULE), insert a `bots` row (via `POST /api/bots` or `seed_bots.py`) with its keys + strategy; BotManager spawns the thread automatically. Bot E pattern = `copytrade`; Bot C = `tradingagents_enabled` + `bot_c/`.

**New API endpoint:** add a router in `dashboard/api/routes/`, include it in `dashboard/api/main.py` with `Depends(verify_token)`; add Pydantic models in `models.py`. Schema change → new `dashboard/api/migrations/NNN_*.sql`.

**New dashboard view:** add a folder under `dashboard/web/app/` (page-routed) + feature components in `dashboard/web/components/<feature>/`; live data via `hooks/useSSE.ts` + `lib/api.ts`.

**New persistence:** add query/table in `src/db.py` (+ migration); always scope by `bot_id`.

## Special Directories

- **`data/`** — runtime logs + legacy SQLite; NOT committed (Coolify volume). Postgres is authoritative.
- **`dashboard/api/migrations/`** — ordered SQL migrations, applied via `run_migrations.py` in `entrypoint.sh`.
- **`src/bot_c/`** — Bot C TradingAgents integration; `llm_shim:app` runs as supervisord `bot_c_shim` on 127.0.0.1:8765.
- **`vendor/TradingAgents`** — vendored dep for bot_c (on PYTHONPATH).
- **`dashboard/app.py`** — legacy Streamlit dashboard, superseded by `dashboard/web/` + `dashboard/api/`.
- **`src/orchestrator.py` / `src/kalshi_client.py` / `private_key.pem`** — Kalshi (PAUSED, do not run).

---

*Structure analysis: 2026-05-31*
