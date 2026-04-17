# AI Predicted Wins

Automated swing trading system for crypto and stocks. Uses a technical signal engine (EMA, ADX, RSI, Volume, VWAP) to score assets, gates trades with a deterministic rules engine, and supports long and short positions across multiple isolated bots.

## Live Dashboard

**https://app.aipredictedwins.com**

## Bots

| Bot | Asset Class | Strategy |
|-----|-------------|----------|
| Bot A | Crypto | Kelly 0.25, min confluence 3, MiroFish risk gate on |
| Bot B | Crypto | Kelly 0.50, min confluence 2, risk gate off (speed test) |
| Bot C | Stocks | Kelly 0.25, min confluence 3, market-hours gated |

Each bot has its own isolated Alpaca paper account. Bots run in parallel threads managed by the dashboard's BotManager.

## How It Works

1. **Scan** — Fetch OHLCV bars for the asset universe (crypto: dynamic top-N by volume; stocks: static watchlist)
2. **Score** — Compute 5 indicators: EMA(9/21) trend, ADX(14) momentum, RSI(14) level, volume spike, VWAP confluence
3. **Filter** — Only assets with 3+ bullish (long) or 3+ bearish (short) signals become candidates
4. **Gate** — RulesGate vetoes trades: gap >5% since last close, or ADX <12 (flat market)
5. **Size** — Quarter-Kelly based on confluence score (3/5 → 55% win rate estimate, etc.)
6. **Trade** — Limit orders only; short selling via Alpaca's margin accounts
7. **Monitor** — Background thread checks every 60s; soft thresholds trigger exit advisor, hard thresholds force immediate exit
8. **Learn** — TradeMemory logs every decision with full context; LearningLoop adjusts parameters over time

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env  # add Alpaca keys

# Run a single bot (evaluate mode — no trades placed)
python -m src.alpaca_orchestrator --mode evaluate

# Run a single bot (paper trading)
python -m src.alpaca_orchestrator --mode paper --max-trades 50

# Full multi-bot dashboard
cd dashboard && docker compose up
```

## Signal Engine

| Indicator | Bullish condition | Bearish condition |
|-----------|-------------------|-------------------|
| EMA 9/21 | 9 > 21 | 9 < 21 |
| ADX 14 | ADX > 20 | ADX > 20 |
| RSI 14 | 40–65 | 35–60 |
| Volume | Spike > 1.5× avg | Spike > 1.5× avg |
| VWAP | Price > VWAP | Price < VWAP |

4H MTF confirmation is applied on crypto (no 4H data for stocks).

## Risk Rules (hardcoded — no override)

- 5% max bankroll per position
- 80% max total portfolio exposure
- Quarter-Kelly sizing
- Hard stop −5% / take profit +10% (immediate exit)
- Soft stop −3% / soft profit +5% (exit advisor consulted)
- 20% portfolio drawdown stop
- Limit orders only
- 50 paper trades before live mode unlocks

## Infrastructure

| Service | Details |
|---------|---------|
| Dashboard | https://app.aipredictedwins.com (Coolify, Next.js + FastAPI) |
| Broker | Alpaca paper trading |
| DB | Postgres (Coolify-managed) |
| DNS | Cloudflare — aipredictedwins.com |

## Disclaimer

Educational/personal research only. Not financial advice. All trading involves risk of loss.
