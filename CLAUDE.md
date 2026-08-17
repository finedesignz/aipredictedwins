<!-- template-version: 1 -->
<!-- repo-align-template: dev v1 -->

# CLAUDE.md

## Purpose

Automated crypto swing-trading system on Alpaca. Technical indicators
(EMA, ADX, RSI, Volume, VWAP) are the primary signal engine; MiroFish
(LLM swarm intelligence) acts as a risk gate before entry and an exit
advisor after. A Kalshi prediction-markets orchestrator also exists in
the codebase but is currently PAUSED -- do not run it.

## Stack

- Python: trading orchestrators, signal engine, risk/exit advisors
  (`src/`), SQLite trade logger (`data/trades.db`).
- Dashboard: Next.js + FastAPI + BotManager in one container (Coolify).
- `gateway/` -- Claude Code CLI bridge on Coolify, OpenAI-compatible API
  backed by the Claude Max plan (OAuth via `claude login`, not an API
  key -- see Gotchas).
- `vendor/TradingAgents/` -- third-party vendored trading-agent framework,
  NOT code we wrote or maintain.

## Commands

```bash
# Alpaca crypto (v2 -- technical + MiroFish guardian)
python -m src.alpaca_orchestrator --mode paper --max-trades 50

# Evaluate signals only (no trading)
python -m src.alpaca_orchestrator --mode evaluate

# Dashboard
streamlit run dashboard/app.py

# Kalshi -- PAUSED, do not run
# python -m src.orchestrator --mode paper --max-trades 200
```

## Deploy target

- Coolify project "AI Predicted Wins" (UUID `u7x0xw0y4qvcgeh8vyidsgyi`).
  Dashboard is served at https://app.aipredictedwins.com.
- DNS: Cloudflare zone `aipredictedwins.com`.
- **CI is GitHub Actions ONLY** -- `.github/workflows/docs-drift.yml` and
  `docs-drift.yaml`, plus open Dependabot branches. No `.woodpecker/`
  directory exists in this repo (verified on `origin/main`, 2026-08-16).
  This corrects an earlier claim that GHA and Woodpecker were both
  present mid-migration -- that is not the case as of this check.
- Each trading bot (A/B/C/D) runs as its own Coolify orchestrator service
  against its own dedicated Alpaca paper account -- see the one-account-
  per-bot rule below before touching bot provisioning.

## Repo conventions

- Live trading is BLOCKED until: 50+ paper trades, win rate > 40%, and
  equity reaches the $100,000 breakeven target. Do not bypass this gate.
- Risk rules are HARDCODED and never overridden: max 5% bankroll per
  position, min 15% gap to trade, quarter-Kelly sizing, 20% drawdown
  stop, limit orders only, max 3 correlated positions per event, max 10
  simulations per cycle.
- **One Alpaca account per bot, hard rule.** Bot A/B/C/D each read their
  own suffixed keys (`ALPACA_API_KEY_A`..`_D`) on the dashboard service
  for attribution, but each bot's own orchestrator service reads BARE
  `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` -- one orchestrator process per
  bot, one account per process, no A/B fallback. Sharing an account
  between bots corrupts equity curves and P&L attribution.

## GSD state

No `.planning/` directory in this repo as of this check -- not currently
GSD-managed. `docs/deployment/bot-d-coolify-recipe.md` documents the Bot D
provisioning recipe as a standalone doc.

## Gotchas

- **Rule 22c: API-key references in this repo are all vendored, not
  ours.** Grepping the repo for `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`
  (2026-08-16) turns up hits ONLY inside `vendor/TradingAgents/` (a
  third-party library we vendor but do not own or maintain) and inside
  `.claude/skills/skill-creator/scripts/improve_description.py`, which
  documents that it uses "the session's Claude Code auth, no separate
  ANTHROPIC_API_KEY needed" -- i.e. it explicitly avoids the key, it does
  not use one. No rule-22c violation was found in code we own. If
  `vendor/TradingAgents` is ever forked/modified rather than pulled
  as-is, re-audit its own key handling at that point.
- **Gateway auth expires.** The Claude Code CLI bridge in `gateway/`
  needs `claude login` re-run via the Coolify terminal when it expires;
  use a persistent volume at `/root/.claude` so login survives rebuilds.
- **MiroFish port coupling:** `FLASK_PORT` must be `5001` to match
  `VITE_BACKEND_URL=http://localhost:5001` -- a mismatch here is the most
  common cause of MiroFish 500 errors.
- **Probability-extraction bias:** the `extract_probability` prompt must
  ask for AGENT CONSENSUS, not the LLM's own estimate, or it defaults to
  systematic skepticism (1-5% on everything).
- Kalshi orchestrator (`src/orchestrator.py`) is PAUSED -- present in the
  codebase but must not be run.
