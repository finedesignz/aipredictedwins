---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: Day-Trading Upgrade
status: roadmapped
last_updated: "2026-06-09T00:41:29.331Z"
last_activity: 2026-06-09
progress:
  total_phases: 10
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

**Core value:** Compounding, self-improving automated trading edge — the bot gets measurably better as it accumulates trade outcomes, without manual retuning.
**Current focus:** v1.0 Day-Trading Upgrade — add self-learning intraday Bot D via a StrategyProfile abstraction, drop MiroFish from the Alpaca path, replace LLM exits with deterministic ATR logic, and close the self-learning loop.

## Current Position

Phase: Not started — roadmap created (10 phases, FINE granularity)
Plan: —
Status: Roadmapped, awaiting phase planning
Progress: [          ] 0/10 phases
Last activity: 2026-06-09 — ROADMAP.md created, 21/21 requirements mapped

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
