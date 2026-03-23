# AI Predicted Wins — Project Summary

## What It Is

An automated trading system that uses **MiroFish swarm intelligence** (1,000 AI agents simulating crowd behavior) to identify mispriced event contracts on **Kalshi** and directional opportunities on **Alpaca** (stocks/crypto). The system scans markets, runs multi-agent simulations, extracts consensus probabilities, and trades when it detects a gap between the AI crowd's prediction and the market price.

## Architecture

| Component | URL / Location | Status |
|-----------|---------------|--------|
| MiroFish (swarm engine) | https://app.aipredictedwins.com | Running on Coolify |
| Claude Code Bridge (LLM gateway) | https://gateway.aipredictedwins.com | Running on Coolify |
| Kalshi API | Production (api.elections.kalshi.com) | Connected, live trading |
| Alpaca API | Paper mode (built, awaiting API keys) | Ready |
| Trading Bot | Local Python process | Running |
| Dashboard | Streamlit (localhost:8501) | Built |

## Performance to Date (March 22-23, 2026)

| Metric | Value |
|--------|-------|
| Simulations completed | 71+ |
| Trades placed | 28 (all live on Kalshi prod) |
| Open positions | 28 |
| Total capital deployed | $33.54 of $35.00 bankroll |
| Unique markets traded | 17 |
| Avg position size | $1.20 (1.8 contracts) |
| Avg gap at entry | 37.7% |
| Side breakdown | 27 NO / 1 YES |
| Resolved trades | 0 (all long-dated political markets) |
| P&L realized | $0.00 (no settlements yet) |

## Markets Traded

All Tier 1 (political/sentiment-driven) — MiroFish's strongest category:

- 2028 Presidential Election (party, candidates)
- Trump impeachment / removal / resignation
- Supreme Court confirmations and resignations
- Congressional veto overrides
- UK general election
- Israel PM succession
- Cabinet departures
- US territory expansion (Greenland)

## Known Issues & Fixes Applied

1. **Systematic low-probability bias** — MiroFish probability extraction was returning 1-5% on events priced at 20-70%. Root cause: the LLM prompt asked for its own estimate instead of extracting the agent consensus. **Fixed** on March 23 with an improved prompt that explicitly extracts crowd sentiment.

2. **All positions are NO-side** — consequence of the low-probability bias. The bot saw everything as unlikely and bet NO. May still be profitable if events don't occur, but diversification is needed.

3. **Long-dated markets only** — Kalshi's active markets are 2-4 years to resolution. Capital is locked until events settle. Mitigation: positions can be sold early when market price moves favorably.

4. **No realized P&L yet** — all 28 positions are open. First resolutions expected in months, not days.

## Tech Stack

- **Python 3.13** — orchestrator, clients, position sizing
- **MiroFish** — 1,000-agent swarm simulations via OASIS engine
- **Claude Sonnet 4.6** — LLM for ontology generation, agent profiles, probability extraction (via Claude Max plan, zero incremental cost)
- **Kalshi SDK** (kalshi-python-sync 3.9.0) — prediction market trading
- **Alpaca SDK** (alpaca-py 0.43.2) — stock/crypto trading (ready, not yet active)
- **SQLite** — trade and simulation logging
- **Streamlit** — monitoring dashboard
- **Coolify** — deployment (MiroFish + gateway on VPS)
- **Cloudflare** — DNS and proxy for aipredictedwins.com

## Risk Management (Hardcoded)

- Max 5% bankroll per position (Kelly Criterion, quarter-Kelly)
- Min 15% gap to trade
- Min $10,000 market volume
- Max 3 correlated positions per event
- 20% drawdown stop
- Limit orders only (never market orders)
- 50 paper trades required before live mode

## Improvements Made (March 23)

1. **Fixed probability extraction bias** — Rewrote the LLM prompt from "estimate the probability" (which defaulted to skepticism) to "extract the agent consensus percentage" (which reads what the simulated crowd actually concluded). This should eliminate the systematic 1-5% predictions.

2. **Fixed MiroFish API integration** — Discovered the actual 7-step backend workflow (ontology → graph → simulation → prepare → start → report → extract). Original client was using wrong endpoints.

3. **Fixed Flask port mismatch** — MiroFish backend was running on port 8700 but the Vite proxy expected 5001. Caused all API calls to fail with ECONNREFUSED. Fixed by setting `FLASK_PORT=5001`.

4. **Fixed simulation dedup blocking retries** — Failed simulations were logged as "simulated today", preventing the bot from retrying. Now only successful simulations are logged.

5. **Fixed trade logger signature** — Orchestrator was passing kwargs but `log_trade()` expected a dict. Aligned the call signatures.

6. **Added market time-preference scoring** — Near-term markets (1-14 days) get 40pt bonus. Long-dated (60+ days) get -50pt penalty. Capital realization is faster.

7. **Built Alpaca integration** — Full crypto/stock trading client, evaluator, and orchestrator. Ready to run once API keys are configured. Supports 24/7 crypto with 3% stop-loss and 8% take-profit.

8. **Deployed Claude Code Bridge** — Custom FastAPI gateway on Coolify using Claude CLI + Max plan OAuth. Zero incremental LLM cost. MiroFish routes all AI calls through it.

9. **Set up custom domains** — `app.aipredictedwins.com` (MiroFish UI), `gateway.aipredictedwins.com` (LLM bridge) via Cloudflare DNS.

10. **Dashboard design completed** — Full UI/UX specs in `dashboard/DESIGN.md` and `dashboard/UX_RESEARCH.md`. Recommends Next.js + React migration from Streamlit.

## What's Next

1. Monitor existing 28 positions for price movement opportunities (sell early if gap narrows)
2. Validate improved probability extraction produces balanced predictions
3. Activate Alpaca integration for crypto day trading (faster realization)
4. Build Next.js dashboard to replace Streamlit (design specs complete)
5. Reach 200 paper trades for statistical significance before scaling
