---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Trustworthy P&L + Profitable Retune
status: planning
last_updated: "2026-07-09T07:19:52.788Z"
last_activity: 2026-07-09
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

**Core value:** Compounding, self-improving automated trading edge — the bot gets measurably better as it accumulates trade outcomes, without manual retuning.
**Current focus:** Milestone complete

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-07-09 — Milestone v1.1 started

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
