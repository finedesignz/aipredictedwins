# AI Predicted Wins

## Project Overview

Automated trading system using MiroFish swarm intelligence (1,000+ AI agents) to find mispriced prediction markets on Kalshi and directional opportunities on Alpaca (stocks/crypto).

## Architecture

- **Kalshi orchestrator** (`src/orchestrator.py`) — scans prediction markets, runs MiroFish simulations, trades gaps > 15%
- **Alpaca orchestrator** (`src/alpaca_orchestrator.py`) — scans crypto/stocks, runs sentiment simulations, trades divergences
- **MiroFish client** (`src/mirofish_client.py`) — 7-step pipeline: project → graph → simulation → prepare → start → report → extract probability
- **Gateway** (`gateway/`) — Claude Code CLI bridge on Coolify, OpenAI-compatible API backed by Claude Max plan
- **Trade logger** (`src/trade_logger.py`) — SQLite at `data/trades.db`

## Infrastructure

- MiroFish: https://app.aipredictedwins.com (Coolify, docker-compose)
- Gateway: https://gateway.aipredictedwins.com (Coolify, Dockerfile)
- Kalshi: production API (api.elections.kalshi.com)
- Alpaca: paper mode (awaiting API keys)
- DNS: Cloudflare zone `aipredictedwins.com`
- Coolify project: "AI Predicted Wins"

## Key Files

- `.env` — all API keys and config (gitignored)
- `private_key.pem` — Kalshi RSA key (gitignored)
- `data/trades.db` — SQLite trade/simulation database
- `data/bot_output.log` — live bot output

## Running

```bash
# Kalshi prediction markets
python -m src.orchestrator --mode paper --max-trades 200

# Alpaca crypto (when keys are set)
python -m src.alpaca_orchestrator --mode paper --asset-class crypto

# Dashboard
streamlit run dashboard/app.py

# Evaluate markets only
python -m src.orchestrator --mode evaluate --top 30
```

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
