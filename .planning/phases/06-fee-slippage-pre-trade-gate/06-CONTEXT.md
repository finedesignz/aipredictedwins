# Phase 6: Fee/Slippage Pre-Trade Gate - Context

**Gathered:** 2026-06-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a deterministic pre-trade **fee/slippage gate** (FEE-01): before placing an entry,
skip the candidate when the expected move to its soft take-profit target does not clear
round-trip cost `2 × taker_fee + slippage_buffer`. Prevents intraday churn where the 5-min
cadence produces trades too small to overcome fees.

**Does NOT deliver:** learning loop (Phase 7/8), Bot D deployment (Phase 9). This is a single
guard inserted into the entry path.
</domain>

<decisions>
## Implementation Decisions

### The gate (FEE-01)
- **D-01:** New pure helper (e.g. `src/fee_gate.py` or a function in an existing module —
  planner's call) `clears_fee_hurdle(expected_move_pct, taker_fee, slippage_buffer) -> bool`
  returning `expected_move_pct >= 2*taker_fee + slippage_buffer`.
- **D-02:** "Expected move" = the candidate's distance to its soft take-profit target as a
  fraction (the entry path already computes a soft take-profit ~8% for swing). For intraday
  the relevant target is smaller; use the same soft-target basis the sizing/exit uses so the
  gate is consistent with how the trade is actually managed.
- **D-03:** Fee params are config knobs with sane defaults: `TAKER_FEE` default ~0.0025 (0.25%,
  Alpaca crypto taker ballpark) and `SLIPPAGE_BUFFER` default ~0.0010 (0.10%), both env-overridable.
  Consider putting them on `StrategyProfile` later, but env defaults are sufficient this phase.
- **D-04:** Apply the gate in the entry candidate loop in BOTH the orchestrator and the live
  `bot_thread.py` entry path (wherever orders are placed), AFTER confluence/risk-gate and
  BEFORE sizing/order placement. Log skips clearly (`fee_gate_skip`).

### Claude's Discretion
- Whether to compute expected_move from soft-target pct constant vs ATR-based target — use the
  soft-target the trade is managed against (consistency over cleverness). Helper location.
</decisions>

<canonical_refs>
## Canonical References

- `docs/superpowers/specs/2026-06-08-day-trading-upgrade-design.md` §5 (fee/slippage gate).
- `.planning/REQUIREMENTS.md` — FEE-01.
- `src/alpaca_orchestrator.py` — entry candidate loop / order placement (soft take-profit at +8%, stop_loss).
- `src/bot_thread.py` — its entry/order-placement path (mirror the gate).
- `src/strategy_profile.py` — for any future fee fields.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- Entry loop already computes target_price = price*(1+0.08) (soft TP) and stop_loss — reuse that
  target to derive expected_move_pct.

### Established Patterns
- Env-var-with-default knobs everywhere; deterministic guards (untradeable lists, exposure caps).

### Integration Points
- Gate sits between risk-gate approval and order placement in both the orchestrator and bot_thread.
</code_context>

<specifics>
## Specific Ideas
Tests: clears_fee_hurdle boundary cases (just-above/just-below threshold); a candidate whose
expected move < hurdle is skipped (logged), one above is allowed; default fee/slippage values;
env override of TAKER_FEE/SLIPPAGE_BUFFER. Full suite stays green.
</specifics>

<deferred>
## Deferred Ideas
- Moving fee params onto StrategyProfile per-style — later.
- Maker/limit-order fee modeling nuance — later; taker round-trip is the conservative default.

None outside phase scope.
</deferred>

---

*Phase: 6-Fee/Slippage Pre-Trade Gate*
*Context gathered: 2026-06-08*
