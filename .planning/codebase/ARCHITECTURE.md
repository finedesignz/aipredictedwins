<!-- refreshed: 2026-05-31 -->
# Architecture

**Analysis Date:** 2026-05-31

## System Overview

```text
┌──────────────────────────────────────────────────────────────────────────┐
│        Dashboard Container (Coolify) — app.aipredictedwins.com              │
│        supervisord: [api] uvicorn :8000 + [web] node server.js :3000        │
│                     + [bot_c_shim] uvicorn 127.0.0.1:8765                    │
├───────────────────────────────┬────────────────────────────────────────────┤
│  Next.js UI  `dashboard/web/` │  FastAPI  `dashboard/api/main.py`            │
│  app/ pages (page-routed):    │  Bearer auth (DASHBOARD_TOKEN), CORS         │
│   bots, positions, trades,    │  routers: alpaca, benchmark, bots, chat,     │
│   signals, risk-gate,         │  equity, portfolio, positions, trades,       │
│   settings, login             │  signals, risk_gate, settings, activity      │
│  components/, useSSE.ts       │  /api/health (no auth), /api/auth/*          │
└───────────────┬───────────────┴───────────────┬────────────────────────────┘
                │ fetch + SSE (useSSE)           │ FastAPI lifespan owns
                ▼                                ▼
                                   ┌──────────────────────────────┐
                                   │  BotManager  `src/bot_manager`│
                                   │  reads `bots` table → spawns  │
                                   │  one thread per ENABLED bot   │
                                   │  + watchdog (revive + silence)│
                                   └──────────────┬───────────────┘
                                                  │ strategy dispatch
                         ┌────────────────────────┴────────────────────────┐
                         ▼                                                  ▼
        ┌────────────────────────────────────┐         ┌──────────────────────────────┐
        │ BotThread `src/bot_thread.py`       │         │ CopyTraderThread             │
        │ confluence / trend_btc strategies   │         │ `src/copytrade_thread.py`    │
        │  per-bot AlpacaClient + RulesGate   │         │ Bot E: polls ai4trade feed,  │
        │  + ExitAdvisor + PositionMonitor    │         │ mirrors leader trades        │
        │  reuses alpaca_orchestrator helpers │         │ (no scan / no gate)          │
        └──────────────┬─────────────────────┘         └──────────┬───────────────────┘
                       │ 3-layer pipeline                          │
                       ▼                                           ▼
   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    ┌────────────────┐
   │ Alpaca API   │  │ Claude CLI   │  │ Postgres     │    │ ai4trade.ai     │
   │ (per-bot acct│  │ gateway      │  │ (Coolify)    │    │ signals feed    │
   │  in bots row)│  │ gateway/main │  │ src/db.py    │    │ ai4trade_client │
   └──────────────┘  └──────────────┘  └──────────────┘    └────────────────┘
```

> PERSISTENCE NOTE: despite `data/trades.db` mentions in CLAUDE.md, `src/trade_logger.py` is a thin shim over `src/db.py`, which uses **Postgres** (`DATABASE_URL`, psycopg3 `ConnectionPool`, schema bootstrapped from `src/db_schema.sql`). The `db_path` arg is ignored; SQLite is legacy.

> BOT MODEL NOTE: bots are NOT separate OS processes. BotManager runs inside the FastAPI process (lifespan) and spawns one **thread** per enabled `bots` row. Single-bot CLI (`python -m src.alpaca_orchestrator`) still exists for manual runs.

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| BotManager | Reads `bots` table, spawns one thread per enabled bot, watchdog revives dead threads + trade-silence alerts, hot-swaps config | `src/bot_manager.py` |
| BotThread | Per-bot scan→gate→size→enter loop + own PositionMonitor; strategies `confluence` / `trend_btc`; atomic config swap | `src/bot_thread.py` |
| CopyTraderThread | Bot E (`strategy=copytrade`): polls ai4trade leaders, mirrors trades proportionally | `src/copytrade_thread.py`, `src/claude_copytrade.py` |
| AlpacaCryptoOrchestrator | Reference v2 pipeline + shared helpers (`_kelly_technical`, `_select_cycle_candidates`, `PositionMonitor`); CLI entry | `src/alpaca_orchestrator.py` |
| PositionMonitor | Daemon thread: trailing/hard stops + LLM exit advisor on 60s cadence | `src/alpaca_orchestrator.py` (class) |
| TechnicalSignalEngine | EMA(9/21)/ADX(14)/RSI(14)/Volume/VWAP → `Signal` (confluence, short_score, trend_4h) | `src/technical_signals.py` |
| RulesGate | Deterministic pre-entry gate (default in BotThread) | `src/rules_gate.py` |
| RiskGate | MiroFish/Claude 5-analyst LLM veto panel (optional, `skip_risk_gate`) | `src/risk_gate.py` |
| ExitAdvisor + TrailingStop | LLM HOLD/TIGHTEN/EXIT on soft thresholds; trailing-stop tracker | `src/exit_advisor.py` |
| TradingAgentsGate / bot_c shim | Bot C alternate LLM gate; local shim at 127.0.0.1:8765 | `src/tradingagents_gate.py`, `src/bot_c/` |
| MiroFishClient | 7-step swarm pipeline + OpenAI-compatible LLM client | `src/mirofish_client.py` |
| ClaudeLLM | Calls the Claude CLI gateway (OAuth) | `src/claude_llm.py` |
| db / TradeLogger | Postgres DAL, bot_id-scoped; shim preserves old API | `src/db.py`, `src/trade_logger.py` |
| Notifier / Alerter | Email alerts via emails4agents | `src/notifier.py`, `src/alerter.py` |
| BotConfig / Config | Per-bot snapshot from `bots` row; global env config | `src/bot_config.py`, `src/config.py` |
| Dashboard API | FastAPI: bot CRUD + reads + SSE; owns BotManager via lifespan | `dashboard/api/main.py`, `dashboard/api/routes/*.py` |
| Dashboard UI | Next.js page-routed; recharts; SSE live updates | `dashboard/web/` |
| Gateway | Spawns `claude -p` subprocess per request; OpenAI-compatible | `gateway/main.py` |
| Kalshi orchestrator | PAUSED — prediction-market flow (v1) | `src/orchestrator.py` |

## Pattern Overview

**Overall:** Technical-first trading pipeline with LLM-as-guardian (v2). Multiple bots (A/B/C/E) run as worker threads inside the dashboard's FastAPI process, each configured by a row in the `bots` Postgres table and bound to its own Alpaca account for head-to-head comparison.

**Key Characteristics:**
- Technical confluence is the PRIMARY entry signal; LLM only gates entries and advises exits.
- Bots are DB-driven threads, not processes. BotManager spawns/revives them; config is hot-swappable (`update_config`) without restart.
- Strategy is polymorphic per bot: `confluence` (default scalper) and `trend_btc` use `BotThread`; `copytrade` uses `CopyTraderThread`.
- Each BotThread owns a daemon `PositionMonitor` running on a 60s cadence, independent of the scan cycle.

## Layers

**Signal layer** — `src/technical_signals.py`: bars → `Signal` (confluence 0–5, short_score, trend_4h). Pure math, no LLM.

**Guardian layer** — `src/rules_gate.py` (deterministic, default) and `src/risk_gate.py` (LLM veto via `claude_llm.py` → gateway). `skip_risk_gate` bypasses.

**Execution layer** — `_kelly_technical` sizing + order placement via `src/alpaca_client.py`. Quarter-Kelly by confluence (3=.55,4=.60,5=.65 win-prob), capped at `max_position_pct` (5%), bounded by `MAX_TOTAL_EXPOSURE_PCT` (80%).

**Exit layer** — `PositionMonitor` + `ExitAdvisor`/`TrailingStop`. Hard stop -15% / trailing → immediate close; soft stop -8% / soft TP +15% → LLM consult.

**Persistence/UI** — `src/db.py` (Postgres) ← `trade_logger.py`; FastAPI reads same DB; Next.js renders with SSE.

## Data Flow

### Bot lifecycle (BotManager)

1. FastAPI lifespan → `BotManager(db_url).start_all()`.
2. `SELECT * FROM bots WHERE enabled AND alpaca_api_key != ''` → `BotConfig.from_row`.
3. `_spawn` dispatches on `cfg.strategy`: `copytrade` → `CopyTraderThread`, else `BotThread`.
4. Watchdog (60s): revive dead threads (`_revive_dead_bots`, max 1 death-alert/hr/bot), trade-silence alert (no trades in `TRADE_SILENCE_ALERT_HOURS`).
5. `bots` row CRUD via `dashboard/api/routes/bots.py` → `mgr.add/update/stop_bot/enable_bot`; `_on_status_change` writes status back to DB.

### Entry Path (BotThread / orchestrator cycle)

1. Refresh dynamic universe (top-N by volume), strip `_ALPACA_UNTRADEABLE`.
2. Exposure + BTC-regime guard (skip if ≥80% exposed or BTC OVERHEATED).
3. `scan_assets` → volume-context filter → long/short candidates (EMA hard-gate, confluence ≥ `min_confluence`, 4H-trend filter, RSI ceiling, dedup vs open).
4. `_select_cycle_candidates` caps to `MAX_ENTRIES_PER_CYCLE` (3) by confluence then RSI.
5. Guardian: RulesGate/RiskGate → PROCEED/VETO.
6. `_kelly_technical` → `place_market_order` → `log_alpaca_trade` → notify.

### Exit Path (PositionMonitor, 60s)

1. Reconcile DB-open trades vs live Alpaca positions (mark externally-closed).
2. Side-aware `pnl_pct`; trailing stop for longs.
3. hard_stop / trailing_stop / tightened_stop → immediate `close_position`.
4. soft_stop / soft_take_profit → `ExitAdvisor.should_exit` → EXIT closes, TIGHTEN→breakeven, HOLD no-op.

**State Management:**
- Durable state in Postgres (`bots`, `alpaca_trades`, `copytrade_state`/`copytrade_signals`), scoped by `bot_id`.
- Live positions/equity fetched from Alpaca on demand; in-memory `_tightened` set + `TrailingStop` per monitor.

## Key Abstractions

- **BotConfig** (`bot_config.py`) — frozen per-bot snapshot from a `bots` row; `symbols` property by asset_class.
- **Signal** (`technical_signals.py`) — ema_bullish, adx, rsi, volume_spike, vwap_bullish, confluence_score, short_score, trend_4h.
- **PipelineState** (`pipeline_state.py`) — approved candidate carried signal→sizing.
- **RiskVerdict** / **ExitAdvice** — gate + exit decisions.

## Entry Points

- `dashboard/api/main.py` — FastAPI `app`; lifespan launches BotManager (primary runtime).
- `dashboard/supervisord.conf` / `dashboard/entrypoint.sh` — container launch (api + web + bot_c_shim); entrypoint bootstraps Claude creds + runs migrations/seed.
- `python -m src.alpaca_orchestrator --mode {paper|live|evaluate}` — single-bot CLI.
- `gateway/main.py` — standalone LLM bridge (`/v1/chat/completions`, `/v1/models`, `/health`).
- `src/orchestrator.py` — Kalshi (PAUSED).

## Architectural Constraints

- **One Alpaca account per bot (HARD RULE).** Creds live in each `bots` row (`alpaca_api_key`/`_secret_key`), never exposed by the API. Sharing breaks dedup, P&L attribution, equity overlay.
- **Threading model:** BotManager (in FastAPI process) + N bot threads + watchdog; each bot thread spawns a `PositionMonitor` daemon. Postgres via pooled connections (`src/db.py` max_size=10; BotManager pool max_size=5).
- **Guardian + chat LLM depend on Claude CLI auth.** `entrypoint.sh` prefers a valid token on the persistent `/root/.claude` volume, falls back to `CLAUDE_CREDENTIALS` env; CLI refreshes on first call. Startup/daily auth health checks alert on failure.
- **API auth:** all routers require Bearer `DASHBOARD_TOKEN` (cookie or header); `/api/health` exempt; auth disabled when token unset (dev).
- **Live trading gated:** ≥50 paper trades, win-rate ≥40%, equity ≥ `LIVE_TRADING_THRESHOLD` ($100k) + interactive CONFIRM (CLI only).

## Anti-Patterns

### LLM as entry signal
**What happens:** Using MiroFish/LLM probability as the buy trigger (v1 Kalshi model).
**Why it's wrong:** Systematic skepticism bias (1–5%); risk gate measured counterproductive (~$2K monitor P&L gap, per memory).
**Do this instead:** Technical confluence drives entries (`technical_signals.py`); LLM only vetoes/advises; default guardian is deterministic `RulesGate`.

### Two bots, one Alpaca account
**What happens:** Two `bots` rows with the same Alpaca key.
**Why it's wrong:** Corrupts dedup + attribution; equity curves overlay.
**Do this instead:** One dedicated paper account per bot row.

### Assuming bots are separate processes / SQLite store
**What happens:** Looking for a per-bot process or `data/trades.db`.
**Why it's wrong:** Bots are threads under BotManager; persistence is Postgres via `src/db.py`.
**Do this instead:** Inspect the `bots` table + `mgr.status()`; treat `DATABASE_URL` Postgres as source of truth.

## Error Handling

**Strategy:** Defensive try/except in every long-running loop; per-iteration failures logged and skipped. BotManager survives bad rows (logs + continues) and revives dead threads. Order/close failures logged + emailed (`alert_*`), never crash a thread. CLI `main()` catches crashes → `alert_bot_crash`. FastAPI lifespan degrades to read-only if BotManager can't start.

## Cross-Cutting Concerns

**Logging:** stdout INFO (api/web/bot_c via supervisord to /dev/stdout) + Rich console + Postgres rows; `data/bot_output.log`.
**Validation:** confluence ≥ threshold + EMA hard-gate + RSI ceiling + guardian veto + hard/soft thresholds + exposure/regime guards.
**Notifications:** `Notifier`/`Alerter` via emails4agents (crash, bot death, drawdown, monitor error, position closed, trade silence, auth failure).
**Realtime:** SSE (`dashboard/web/hooks/useSSE.ts` ← `dashboard/api/routes/activity.py`, `chat.py`).
**Auth/secrets:** Alpaca keys in `bots` rows (API never returns them); Claude creds on persistent volume; `DASHBOARD_TOKEN` Bearer.

---

*Architecture analysis: 2026-05-31*
