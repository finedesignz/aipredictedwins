---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: Day-Trading Upgrade
status: ready_to_plan
last_updated: 2026-06-15T16:31:52.690Z
last_activity: 2026-06-09
progress:
  total_phases: 10
  completed_phases: 0
  total_plans: 0
  completed_plans: 13
  percent: 0
stopped_at: Phase 9 complete (1/3) — ready to discuss Phase 10
---

# Project State

## Project Reference

**Core value:** Compounding, self-improving automated trading edge — the bot gets measurably better as it accumulates trade outcomes, without manual retuning.
**Current focus:** Phase 10 — verification + backtest

## Current Position

Phase: 10
Plan: Not started
Status: Ready to plan
Progress: [          ] 0/10 phases
Last activity: 2026-06-15

## Accumulated Context

**Decisions:**
- Phase 1 locks SWING-preset byte-for-byte parity before any behavior change (bots A/B must not regress).
- ATR exits (Phase 4) land before MiroFish removal (Phase 5) so exits never have a gap.
- Self-learning loop split: entry+sizing wiring (Phase 7) then intraday dimensions + shadow mode (Phase 8).
- Migrations are numbered SQL (`dashboard/api/migrations/NNN_*.sql`), NOT alembic — any schema change uses `NNN_day_<slug>.sql`.
- Live trading path is `BotThread` + its `PositionMonitor`; the shared `alpaca_orchestrator.py` helpers are the reference. Both must be updated where a phase touches "the orchestrator".

**Todos:** —
**Blockers:** —

## Session Continuity

Next: `/gsd-plan-phase 1` (StrategyProfile Abstraction + SWING Parity).
