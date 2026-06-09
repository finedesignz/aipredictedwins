# Phase 8: Intraday Learning Dimensions + Shadow Mode - Context

**Gathered:** 2026-06-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Enrich the (now-closed) learning loop with intraday signal and add the safety gate:

- **LEARN-04:** `trade_context` records three new dimensions at entry: `time_of_day_bucket`
  (e.g. UTC 4-hour buckets / session label), `hold_minutes` (filled at close from entry→exit),
  and `volatility_regime` (derived from ATR-vs-price or recent range at entry; e.g. low/med/high).
- **LEARN-05:** `generate_lessons()` / strategy scoring incorporate the new dimensions so lessons
  can be conditioned on them (e.g. "5/5 SOL, US-afternoon, low-vol → 70% WR").
- **LEARN-06:** Shadow mode — until `LEARNING_SHADOW_UNTIL_TRADES` (default 30) CLOSED trades
  exist (per bot), the learning veto/scale runs in LOG-ONLY mode ("WOULD veto / WOULD scale
  ×N"); once the threshold is crossed, it auto-applies. This supersedes the static
  `LEARNING_ENFORCE` flag from Phase 7 (env still available as a manual override).

**Does NOT deliver:** Bot D deployment (Phase 9), backtest (Phase 10).
</domain>

<decisions>
## Implementation Decisions

### Schema + recording (LEARN-04)
- **D-01:** RESEARCH must locate where `trade_context` is defined/created (Postgres via `src.db`;
  migrations location — numbered SQL under dashboard/api/migrations per project convention, or
  wherever trade_context DDL lives) and add the 3 columns with safe defaults / nullable, plus a
  backward-compatible migration. Existing rows get NULLs — handle gracefully in lessons.
- **D-02:** `time_of_day_bucket` + `volatility_regime` computed at entry (record_trade_context);
  `hold_minutes` computed at close (the learning loop's outcome sync has entry+exit timestamps).
  Compute volatility_regime from data already available at entry (ATR/price or recent range) —
  RESEARCH picks the cleanest source (Signal.atr_value from Phase 3 is a candidate).
- **D-03:** Wire the new fields through both runtimes' record_trade_context calls (long+short,
  bot_thread + orchestrator), reusing the canonical signal_type from Phase 7.

### Lessons (LEARN-05)
- **D-04:** Extend `generate_lessons()` / `update_strategy_scores()` to group/condition on the
  new dimensions where sample size supports it (respect existing min_sample gates). Keep it
  additive — don't break existing per-signal/per-symbol lessons.

### Shadow gate (LEARN-06)
- **D-05:** Add a helper that returns whether learning should ENFORCE: count closed trades for
  the bot; if `< LEARNING_SHADOW_UNTIL_TRADES` (default 30) → shadow (log-only); else enforce.
  Replace/augment the Phase-7 `LEARNING_ENFORCE` check at the veto/scale seams so the gate is the
  single source of truth. In shadow mode, log `learn_shadow: WOULD veto/scale ×N` and DO NOT act.
- **D-06:** Manual override: explicit `LEARNING_ENFORCE=0` forces shadow regardless of count;
  `LEARNING_ENFORCE=1` is the default count-based behavior. (Decide precedence: explicit 0 wins.)

### Claude's Discretion
- Exact bucket boundaries / volatility thresholds and lesson grouping granularity — planner/
  researcher's call, kept additive and tested.
</decisions>

<canonical_refs>
## Canonical References

- `docs/superpowers/specs/2026-06-08-day-trading-upgrade-design.md` §3 (intraday dimensions + shadow).
- `.planning/REQUIREMENTS.md` — LEARN-04, LEARN-05, LEARN-06.
- `src/trade_memory.py` — record_trade_context, generate_lessons, update_strategy_scores, get_dynamic_thresholds, the schema/columns.
- `src/learning_loop.py` — outcome sync (entry/exit timestamps → hold_minutes).
- `src/db.py` — connection + where DDL/migrations live.
- `src/bot_thread.py`, `src/alpaca_orchestrator.py` — record_trade_context call sites (Phase 7) + the LEARNING_ENFORCE seams.
- `.planning/phases/07-...-07-RESEARCH.md` — the wiring map + shadow seam.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- Phase 7 LEARNING_ENFORCE seam — Phase 8 swaps the static check for the count-based gate.
- Signal.atr_value (Phase 3) for volatility_regime; entry timestamp already recorded.

### Established Patterns
- trade_context is per-bot (bot_id). generate_lessons groups by signal_type/symbol with min_sample.

### Integration Points
- New columns must not break existing inserts/queries (nullable + defaults); shadow gate is the
  single decision point feeding both veto and scale in both runtimes.
</code_context>

<specifics>
## Specific Ideas
Tests: new columns persisted on insert (long+short, both runtimes); hold_minutes filled at close;
volatility_regime/time_of_day_bucket computed correctly; lessons can condition on a dimension;
shadow gate log-only below threshold + enforce above (mock closed-trade count); explicit
LEARNING_ENFORCE=0 forces shadow; migration applies cleanly + existing rows tolerated. Suite green (230+).
</specifics>

<deferred>
## Deferred Ideas
- Bot D deployment — Phase 9. Backtest — Phase 10.

None outside phase scope.
</deferred>

---

*Phase: 8-Intraday Learning Dimensions + Shadow Mode*
*Context gathered: 2026-06-08*
