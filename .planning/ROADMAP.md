# Roadmap — AI Predicted Wins

## Shipped Milestones

- **v1.0 Day-Trading Upgrade** ✅ (2026-06-15) — StrategyProfile abstraction + self-learning
  intraday Bot D, deterministic ATR exits, MiroFish removed from the trading path, closed
  learning loop, fee gate, 5-min backtest. 10/10 phases verified. Archive:
  [`milestones/v1.0-ROADMAP.md`](milestones/v1.0-ROADMAP.md).

## Backlog / Next

- Provision Bot D live infra (Alpaca paper account + Coolify service) — recipe in
  `docs/deployment/bot-d-coolify-recipe.md` (BOT-02 / live BOT-01).
- Retune daytrade confluence/sizing thresholds after real paper data.
- Full P&L backtest (fills + slippage).
- Options v3 (calls/puts/spreads) — separate milestone.

Start the next milestone with `/gsd-new-milestone`.
