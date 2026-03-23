# AI Predicted Wins

Automated trading system powered by MiroFish swarm intelligence. Runs 1,000 AI agents to simulate crowd behavior, compares predictions to live market prices, and trades when it finds mispricing.

## Platforms

- **Kalshi** — CFTC-regulated prediction markets (political events, economic indicators)
- **Alpaca** — Stocks and crypto day trading (coming soon)

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env  # Edit with your API keys

# Evaluate markets (no trading)
python -m src.orchestrator --mode evaluate --top 30

# Start paper trading
python -m src.orchestrator --mode paper --max-trades 200

# Start crypto trading (requires Alpaca keys)
python -m src.alpaca_orchestrator --mode paper --asset-class crypto

# Launch dashboard
streamlit run dashboard/app.py
```

## How It Works

1. **Scan** — Pulls active markets from Kalshi, filters by volume and time horizon
2. **Evaluate** — Ranks markets by MiroFish simulation fit (political > tech > weather)
3. **Simulate** — Feeds event descriptions into MiroFish as seed material, runs 1,000 AI agents debating the outcome across simulated Twitter and Reddit
4. **Extract** — Uses Claude to extract the crowd consensus probability from the simulation report
5. **Compare** — Detects gaps between MiroFish prediction and market price
6. **Trade** — Places limit orders sized with Kelly Criterion when gaps exceed 15%
7. **Track** — Logs everything to SQLite, monitors P&L, stops on 20% drawdown

## Project Structure

```
src/
  orchestrator.py          # Kalshi trading loop
  alpaca_orchestrator.py   # Crypto/stock trading loop
  kalshi_client.py         # Kalshi API wrapper
  alpaca_client.py         # Alpaca API wrapper
  mirofish_client.py       # MiroFish simulation client
  market_evaluator.py      # Market tier ranking
  alpaca_evaluator.py      # Crypto/stock ranking
  event_formatter.py       # Seed text generator
  gap_detector.py          # Probability comparison
  position_sizer.py        # Kelly Criterion sizing
  trade_logger.py          # SQLite trade logging
  config.py                # Environment configuration
gateway/                   # Claude Code Bridge (Coolify)
dashboard/                 # Streamlit monitoring UI
tests/                     # 49 unit tests
data/                      # SQLite DB + logs
```

## Infrastructure

| Service | URL |
|---------|-----|
| MiroFish UI | https://app.aipredictedwins.com |
| LLM Gateway | https://gateway.aipredictedwins.com |
| Dashboard | http://localhost:8501 (local) |

## Risk Management

All rules are hardcoded and cannot be overridden:

- 5% max bankroll per position
- 15% minimum gap to trade
- Quarter-Kelly position sizing
- 20% drawdown stop
- Limit orders only
- 50 paper trades before live mode

## Disclaimer

This is for educational/personal research only. Not financial advice. All trading involves risk of loss. Never trade money you cannot afford to lose.
