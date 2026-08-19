# Phase 21: Exit-Stack Backtest Fidelity + Real Retune - Context

**Gathered:** 2026-07-20
**Status:** Ready for planning
**Mode:** --auto (decisions auto-selected on recommended defaults; audit trail below)

<domain>
## Phase Boundary

Make the backtest harness model the exit strategy the live bot actually runs, then re-run the
retune sweep over BOTH entry and exit knobs so TUNE-01 can be honestly closed.

**In scope:**
- Extend `src/backtester/engine.py` to model the full live exit precedence:
  `hard_stop_pct -> max_hold_hours -> ATR trailing stop -> ATR fixed stop`, plus soft stop /
  soft take-profit behavior — matching `alpaca_orchestrator.py:317-331`.
- Source exit parameters from `StrategyProfile` so the sweep can vary them (not hardcoded).
- Re-run the entry+exit knob sweep; measure win rate / expectancy against the REAL exit model.
- Close TUNE-01 honestly on the result (validated on the Phase 18 holdout).

**Out of scope (deferred / other phases):**
- Changing the live exit logic itself (this phase measures it, does not redesign it).
- New indicators or entry signals beyond the existing confluence/Kelly knobs.
- Live-mode promotion (paper-only gate still applies).
</domain>

<decisions>
## Implementation Decisions

### Exit-model fidelity
- **D-01:** Model the full live exit precedence in the backtester exactly as
  `alpaca_orchestrator.py:317-331`: `hard_stop -> max_hold -> ATR trailing -> ATR fixed`, plus
  soft stop/take. `[auto] recommended — fidelity to live is the entire point of the phase.`
- **D-02:** Reuse the SINGLE source of truth — import constants + the `TrailingStop` class and any
  exit-decision helpers from `src/exit_advisor.py`; do NOT fork/duplicate the exit logic into the
  backtester. Extract shared exit-decision logic into a reusable function if needed so live and
  backtest call the same code. `[auto] recommended — prevents live/backtest drift.`

### Parameterization
- **D-03:** Exit knobs (`hard_stop_pct`, `soft_stop_pct`, ATR trailing multiplier, ATR fixed-stop
  multiplier, `max_hold_hours`) come from `StrategyProfile` (`src/strategy_profile.py` /
  `src/bot_config.py`), so the sweep varies them the same way it varies entry knobs.
  `[auto] recommended — matches existing StrategyProfile abstraction from v1.0.`

### Sweep + closure
- **D-04:** Sweep the grid over BOTH entry knobs (confluence threshold, Kelly fraction) AND exit
  knobs (D-03 list). Report the best train cell, then validate on the Phase 18 holdout under
  `18-HOLDOUT.lock` discipline — no holdout peeking during selection.
  `[auto] recommended — required to legitimately close TUNE-01.`
- **D-05:** TUNE-01 closes only if the retune produces a validated, non-degenerate result against
  the real exit model (win-rate / expectancy criterion measured on the true strategy, not the flat
  barrier). If the sweep still cannot beat the criterion, record the honest negative and the reason
  rather than force-ticking. `[auto] recommended — honesty over a forced green.`

### Claude's Discretion
- Exact grid resolution / knob ranges, ATR window length, and any parallelization of the sweep.
- Whether to refactor exit logic into a shared helper vs import-in-place (D-02 intent preserved
  either way).
- Backtest data window and bar granularity (subject to matching prior phases' harness).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase spec / roadmap
- `.planning/ROADMAP.md` §"Phase 21" — goal, why, deps, "Closes TUNE-01".
- `.planning/milestones/v1.1-REQUIREMENTS.md` §TUNE-01 (line ~47, ~135) — the PARTIAL requirement
  text and WHY the entry-only sweep was unfalsifiable.
- `.planning/PROJECT.md` (lines ~48, ~63, ~122) — TUNE-01 context + the exit-fidelity gap.

### Prior phases (deps)
- `.planning/phases/18-profitable-retune/18-BACKTEST.md`, `18-VALIDATION.md`, `18-HOLDOUT.lock`,
  `18-RESEARCH.md` — the entry-knob sweep, holdout discipline, harness conventions.
- `.planning/phases/20-verification-e2e/VERIFICATION.md`, `20-VALIDATION.md` — P&L trust baseline.

### Code — exit stack (single source of truth)
- `src/backtester/engine.py` — CURRENT exit model (hard thresholds only, lines ~89-104). Target.
- `src/alpaca_orchestrator.py:292-396` — LIVE exit precedence to mirror.
- `src/exit_advisor.py` — `TrailingStop`, `HARD_STOP_PCT`, `SOFT_STOP_PCT`, `SOFT_TAKE_PROFIT_PCT`,
  `HARD_TAKE_PROFIT_PCT`. Reuse; do not duplicate.
- `src/strategy_profile.py`, `src/bot_config.py` — exit knob defaults (`hard_stop_pct=-0.08`,
  `soft_stop_pct=-0.05`, `max_hold_hours`).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/exit_advisor.py`: `TrailingStop` class + all stop/take-profit constants — the exact live
  exit primitives; the backtester should consume these.
- `StrategyProfile` (`src/strategy_profile.py`): existing v1.0 abstraction for per-bot knobs —
  extend/consume for exit-knob sweeping.
- Existing sweep harness from Phase 18 (`18-BACKTEST.md`) — extend rather than rebuild.

### Established Patterns
- Live exit precedence is explicit and ordered (`alpaca_orchestrator.py:317-331`). The backtester
  must reproduce the SAME precedence, not an approximation.
- Holdout discipline via a lock file (`18-HOLDOUT.lock`) — carry forward.

### Integration Points
- `src/backtester/engine.py` position-close loop is where the new exit precedence slots in.
- Sweep reads knob grid; each cell instantiates a `StrategyProfile` with entry+exit knobs.
</code_context>

<specifics>
## Specific Ideas

The failure this phase fixes: the flat -15%/+30% barrier made the >=40% win-rate criterion take
only two possible values across all 12 live cells — unfalsifiable by construction. Modeling the
real exit stack restores a continuous, falsifiable objective.
</specifics>

<deferred>
## Deferred Ideas

- Redesigning the live exit logic (only measured here).
- Live-mode promotion / paper-gate changes.

None else — discussion stayed within phase scope.
</deferred>

---

*Phase: 21-Exit-Stack Backtest Fidelity + Real Retune*
*Context gathered: 2026-07-20*
