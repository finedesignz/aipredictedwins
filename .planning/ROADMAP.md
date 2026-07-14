# Roadmap — AI Predicted Wins

## Shipped Milestones

- **v1.0 Day-Trading Upgrade** ✅ (2026-06-15) — StrategyProfile abstraction + self-learning
  intraday Bot D, deterministic ATR exits, MiroFish removed from the trading path, closed
  learning loop, fee gate, 5-min backtest. 10/10 phases verified. Archive:
  [`milestones/v1.0-ROADMAP.md`](milestones/v1.0-ROADMAP.md).

- **v1.1 Trustworthy P&L + Profitable Retune** ✅ (2026-07-14) — Phases 11–20, 44 plans, tests 279 → 541.
  Order-state resolution + fill-derived realized P&L net of fees, Alpaca reconciliation + backfill,
  universe hard-gate + quarantine, runtime alerting that actually fires, prod risk-rule breaches
  remediated. Found the root cause of the "+$1,296 logged vs −14% real equity" contradiction: 395 of 655
  position-closed rows were `pnl=0.0` external-exit sentinels the dashboard booked as losses.
  **13/15 requirements Validated; TUNE-01 and VERIFY-02 shipped PARTIAL — they were not ticked.**
  Archive: [`milestones/v1.1-ROADMAP.md`](milestones/v1.1-ROADMAP.md) ·
  [`milestones/v1.1-REQUIREMENTS.md`](milestones/v1.1-REQUIREMENTS.md).

---

## Upcoming

### Phase 21: Exit-Stack Backtest Fidelity + Real Retune (OPEN — opened by Phase 18, NOT part of v1.1)

**Why:** Phase 18's entry-knob sweep returned a negative result its own harness could not have
falsified. The backtest engine models exits as a flat −15%/+30% barrier; the live bot runs −8% plus
an ATR trailing stop and an ATR fixed stop. Kelly cannot move win rate, so the ≥40% criterion had
exactly two possible values across all 12 live cells and was unreachable by construction. Phase 17
located the actual losses on the EXIT side — the one dimension the harness does not model. Tuning
entry thresholds was aiming at the wrong half of the system.

**Goal:** Model the live exit stack (soft/hard stops, ATR trailing, ATR fixed, max-hold, exit
advisor) in `src/backtester/engine.py` so the harness measures the strategy the bot actually runs,
then re-run the sweep over BOTH entry and exit knobs. Only then can TUNE-01 be honestly closed.

**Depends on**: Phase 18, Phase 20
**Closes**: TUNE-01 (currently PARTIAL)

## Backlog / Next

- **395-row repair** — needs a NEW mechanism (a `(symbol, qty, timestamp)` matcher against Alpaca
  history). The existing backfill selects `status IN ('open','submitted') AND order_id IS NOT NULL`
  while the 395 rows are `status='closed', order_id IS NULL` → **recovery ceiling 0/395**.
  **Blocker:** the `scripts/backfill.py:153` `TradeLogger(bot_id)` positional-arg attribution bug must
  be fixed first.
- **VERIFY-02 dated follow-up** — not before **2026-07-28**: `python scripts/e2e_verify.py --json`
  against the post-T0 window (T0 = 2026-07-14 07:18 UTC); needs ≥20 resolved trades per bot.
- Provision Bot D live infra (Alpaca paper account + Coolify service) — recipe in
  `docs/deployment/bot-d-coolify-recipe.md`.
- Options v3 (calls/puts/spreads) — separate milestone.

Start the next milestone with `/gsd-new-milestone`.
