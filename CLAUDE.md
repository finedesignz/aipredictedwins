# AI Predicted Wins

## Project Overview

Automated trading system for crypto swing trading on Alpaca. Uses technical indicators (EMA, ADX, RSI, Volume, VWAP) as the primary signal engine, with MiroFish swarm intelligence as a risk gate and exit advisor.

**Kalshi prediction markets are PAUSED** — do not run the Kalshi orchestrator.

## Architecture (v2 — Technical-First, MiroFish-as-Guardian)

- **Alpaca orchestrator** (`src/alpaca_orchestrator.py`) — three-layer pipeline: technical signals → risk gate → trade
- **Technical Signal Engine** (`src/technical_signals.py`) — EMA(9/21), ADX(14), RSI(14), Volume spike, VWAP confluence scoring (0-5)
- **MiroFish Risk Gate** (`src/risk_gate.py`) — LLM risk panel (5 analysts) vetoes bad trades before entry
- **MiroFish Exit Advisor** (`src/exit_advisor.py`) — smart stop-loss/take-profit (HOLD/TIGHTEN/EXIT)
- **Kalshi orchestrator** (`src/orchestrator.py`) — PAUSED. Scans prediction markets, runs MiroFish simulations, trades gaps > 15%
- **MiroFish client** (`src/mirofish_client.py`) — 7-step pipeline: project → graph → simulation → prepare → start → report → extract probability
- **Gateway** (`gateway/`) — Claude Code CLI bridge on Coolify, OpenAI-compatible API backed by Claude Max plan. Exposes OpenAPI 3.1 at `/openapi.json` + Scalar at `/docs` per repo docs convention; see `gateway/README.md`.
- **Trade logger** (`src/trade_logger.py`) — SQLite at `data/trades.db`

## Infrastructure

- Dashboard: https://app.aipredictedwins.com (Coolify, Next.js + FastAPI + BotManager in one container)
- Alpaca: paper mode — **Bot A and Bot B each have their own separate Alpaca paper account**
- DNS: Cloudflare zone `aipredictedwins.com`
- Coolify project: "AI Predicted Wins" (UUID: `u7x0xw0y4qvcgeh8vyidsgyi`)

## Alpaca Accounts — ONE ACCOUNT PER BOT (HARD RULE)

**NEVER point two bots at the same Alpaca account.** Each bot must have its own dedicated paper (and eventually live) account:

| Bot | Env var (Coolify) | Account |
|-----|-------------------|---------|
| Bot A | `ALPACA_API_KEY_A` / `ALPACA_SECRET_KEY_A` | Bot A's paper account |
| Bot B | `ALPACA_API_KEY_B` / `ALPACA_SECRET_KEY_B` | Bot B's paper account |

Sharing one account between bots will:
- Make their equity curves identical (overlay on chart — one becomes invisible)
- Cause position deduplication to block one bot's trades
- Corrupt P&L attribution (can't tell which bot made money)

If you need to add a new bot, create a new Alpaca paper account first.

## Key Files

- `.env` — all API keys and config (gitignored)
- `private_key.pem` — Kalshi RSA key (gitignored)
- `data/trades.db` — SQLite trade/simulation database
- `data/bot_output.log` — live bot output

## Running

```bash
# Alpaca crypto (v2 — technical + MiroFish guardian)
python -m src.alpaca_orchestrator --mode paper --max-trades 50

# Evaluate signals only (no trading)
python -m src.alpaca_orchestrator --mode evaluate

# Dashboard
streamlit run dashboard/app.py

# Kalshi — PAUSED (do not run)
# python -m src.orchestrator --mode paper --max-trades 200
```

## Paper-Only Gate

Live trading is BLOCKED until:
1. 50+ paper trades completed
2. Win rate > 40%
3. Equity reaches $100,000 breakeven target

## Trading Pipeline (v2)

1. **Technical Scan** — fetch 1-hour bars for 8 crypto assets, compute 5 indicators
2. **Confluence Filter** — only assets with 3+ bullish indicators become candidates
3. **Deduplication** — skip symbols already in open positions
4. **Risk Gate** — MiroFish 5-analyst panel brainstorms risk scenarios, vetoes if needed
5. **Kelly Sizing** — quarter-Kelly based on confluence score (3/5=55%, 4/5=60%, 5/5=65%)
6. **Position Monitor** — background thread checks every 60s:
   - Soft thresholds (-2%, +5%) → MiroFish exit advisor (HOLD/TIGHTEN/EXIT)
   - Hard thresholds (-4%, +10%) → immediate exit (no override)

## Asset Universe

Top 8 crypto by market cap: BTC, ETH, SOL, XRP, ADA, AVAX, DOT, LINK.
No meme coins (DOGE, SHIB, PEPE removed).

## Risk Rules (HARDCODED — never override)

- Max 5% bankroll per position
- Min 15% gap to trade
- Quarter-Kelly sizing (kelly_fraction=0.25)
- 20% drawdown stop
- Limit orders only
- 50 paper trades before live mode
- Max 3 correlated positions per event
- Max 10 simulations per cycle

## MiroFish API Workflow

The correct endpoint sequence (discovered from source code):
1. `POST /api/graph/ontology/generate` — upload seed material (multipart/form-data)
2. `POST /api/graph/build` — build knowledge graph from project
3. `POST /api/simulation/create` — create simulation
4. `POST /api/simulation/prepare` — generate agent profiles
5. `POST /api/simulation/start` — launch OASIS subprocess
6. `GET /api/simulation/{id}/run-status` — poll status
7. `POST /api/report/generate` — generate prediction report
8. `GET /api/report/{id}` — retrieve markdown report

MiroFish backend runs on port 5001 inside the container. The Vite frontend proxies `/api/*` to it. `FLASK_PORT` must be `5001` to match `VITE_BACKEND_URL=http://localhost:5001`.

## Probability Extraction

The `extract_probability` prompt must ask for the AGENT CONSENSUS, not the LLM's own estimate. Otherwise it defaults to skepticism (1-5% on everything). The prompt anchors on "what percentage of simulated agents believed YES" to avoid systematic low bias.

## SDK Notes

- Kalshi: `kalshi-python-sync` 3.9.0 (imports as `kalshi_python_sync`). Uses dollar-string fields (`volume_fp`, `last_price_dollars`) not integer cents.
- Alpaca: `alpaca-py` 0.43.2. Crypto symbols use `BTC/USD` format.
- Gateway: Claude CLI via OAuth token. `claude login` in Coolify terminal. Add persistent volume at `/root/.claude` to survive rebuilds.

## Common Issues

- **MiroFish 500 errors**: Check `FLASK_PORT=5001` matches `VITE_BACKEND_URL`. Check `LLM_BASE_URL` points to working gateway.
- **All NO-side trades**: Probability extraction bias. Check the prompt in `mirofish_client.py`.
- **"0 after removing already-simulated"**: Failed simulations were logged. Only log successful ones (status=completed).
- **Gateway auth**: `claude login` expires. Re-login via Coolify terminal. Use persistent volume for `/root/.claude`.
