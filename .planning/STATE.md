---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: — Trustworthy P&L + Profitable Retune
status: executing
last_updated: "2026-07-21T06:21:47.322Z"
last_activity: 2026-07-21 -- Phase 21 execution started
progress:
  total_phases: 1
  completed_phases: 0
  total_plans: 3
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

**Core value:** Compounding, self-improving automated trading edge — the bot gets measurably better as it accumulates trade outcomes, without manual retuning.
**Current focus:** Phase 21 — Exit-Stack Backtest Fidelity + Real Retune

## Current Position

Phase: 21 (Exit-Stack Backtest Fidelity + Real Retune) — EXECUTING
Plan: 1 of 3
Status: Executing Phase 21
Last activity: 2026-07-21 -- Phase 21 execution started

## Accumulated Context

**Decisions:**

- Phase 1 locks SWING-preset byte-for-byte parity before any behavior change (bots A/B must not regress).
- ATR exits (Phase 4) land before MiroFish removal (Phase 5) so exits never have a gap.
- Self-learning loop split: entry+sizing wiring (Phase 7) then intraday dimensions + shadow mode (Phase 8).
- Migrations are numbered SQL (`dashboard/api/migrations/NNN_*.sql`), NOT alembic — any schema change uses `NNN_day_<slug>.sql`.
- Live trading path is `BotThread` + its `PositionMonitor`; the shared `alpaca_orchestrator.py` helpers are the reference. Both must be updated where a phase touches "the orchestrator".

**Phase 20 (VERIFY-01 + VERIFY-02):**

- **The backfill's slash bug is FIXED, but the tool stays UNARMED and was NOT run.** Run with `--apply` before this fix, `src/backfill.py` resolved a genuinely-HELD `BTC/USD` position as `('resolved', {'status':'closed','exit_price':80.0,'pnl':-20.45,'fees':0.45})` — a live position closed with a fabricated loss. Both compare sites (`:72`, `:155`) now normalize via `src.universe.normalize`; the `get_positions() -> None` sentinel is preserved with `counts["error"] = "positions_unavailable"` so an Alpaca outage is distinguishable from "nothing to recover".
- **FINDING — the gun already had a trigger.** `scripts/backfill_trades.py` has been an armed `--apply` CLI since Phase 14 (PNL-05); the Phase-20 plan wrongly assumed no entrypoint existed. The trigger is **human-only** (no CI workflow, Dockerfile, compose file or cron references it). Fence 38 freezes the trigger set at that one file. **The 395-row repair remains a blocking human authorization (20-07).**
- **The paper gate now counts RESOLVED trades, not raw rows. It READS WORSE by design and is NOT to be tuned back.** `paper_trades_target=50`, `win_rate_target=40.0`, `mode="paper"` are byte-unchanged. The live before/after magnitude is **MEASURED** by `scripts/e2e_verify.py`, never predicted — RESEARCH R1 refuted the "655 → 260" projection (different bot sets AND different status filters).
- **`reconciliation_anchor` (T0) is written `ON CONFLICT (bot_id) DO NOTHING`.** An UPSERT would re-anchor T0 on every run and make the windowed check vacuously green. `reconcile_window` **calls** `reconcile_bot` (two calls, one formula — no second copy of the subtraction). **`INSUFFICIENT_SAMPLE` and `NO_ANCHOR` both exit non-zero and are NOT passes**; the sample gate is evaluated first so a zero delta on 19 trades cannot reach PASS.
- **`scripts/e2e_verify.py` refuses to grade against a tampered ruler.** Any `RECONCILIATION_TOLERANCE_*` env override emits `TOLERANCE_OVERRIDE`, suppresses every PASS, and exits 2 **before querying prod**. The committed $25 all-time tolerance stays and **keeps breaching — THE BREACH IS THE FINDING.**
- **Both LIVE exit writers now record NET realized P&L with fees.** `trend_strategy.py` and `bot_c/strategy.py` were writing GROSS, long-only-signed P&L (a profitable short booked as a **-$10,000 loss**), poisoning the post-T0 window that is VERIFY-02's only evidence. Fixed forward-only; no historical row repaired.

**Todos:** —
**Blockers:** —

## Session Continuity

Next: `/gsd-plan-phase 1` (StrategyProfile Abstraction + SWING Parity).
