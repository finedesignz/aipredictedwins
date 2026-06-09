# Phase 7: Close the Self-Learning Loop (Entry + Sizing) - Context

**Gathered:** 2026-06-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Make the existing self-learning system actually DRIVE decisions (the loop is currently open:
`TradeMemory.record_trade_context()` + `LearningLoop.run_cycle()` are called, but
`get_advice()` and `get_dynamic_thresholds()` are not consumed to change entries/sizing).

- **LEARN-01:** Before sizing each candidate, call `memory.get_advice(symbol, signal_type, …)`;
  if `should_trade == False` (historical win-rate < 30% over ≥3 trades) → VETO the candidate
  (skip, logged as `learn_veto`).
- **LEARN-02:** Use `advice["confidence_adjustment"]` to SCALE the position size
  (multiply the Kelly dollar amount / fraction by the adjustment, within existing caps).
- **LEARN-03:** Feed `memory.get_dynamic_thresholds()` into Kelly sizing — its
  `min_position_pct` / `max_position_pct` (and confluence thresholds where applicable) override
  the static defaults so sizing adapts to overall win-rate.

**Does NOT deliver:** the new intraday learning dimensions (time-of-day/hold/vol) or shadow-mode
gating — those are Phase 8. Phase 7 wires the CONSUMPTION; Phase 8 adds dimensions + the
shadow→auto safety gate. (Sequencing note: Phase 8 will wrap these consumption calls in shadow
mode; Phase 7 should wire them in a way Phase 8 can gate cleanly.)
</domain>

<decisions>
## Implementation Decisions

### Wiring (LEARN-01/02/03)
- **D-01:** RESEARCH must first map the CURRENT state of learning wiring in BOTH
  `bot_thread.py` (the live runtime — appears to already have a "memory advisory" call) and
  `alpaca_orchestrator.py`. Identify exactly what is already called vs missing, so we ADD only
  the missing consumption and don't double-wire.
- **D-02:** `signal_type` passed to `get_advice` must match what `record_trade_context` stores
  (e.g. `technical_confluence_{score}` / `short_technical_{score}`) so advice keys align with
  recorded outcomes. RESEARCH: confirm the exact signal_type strings used at record time.
- **D-03:** VETO and SCALE apply in BOTH long and short entry paths, in BOTH bot_thread and
  orchestrator (keep them behaviorally identical). Live runtime (bot_thread) is the priority.
- **D-04:** Sizing precedence: dynamic thresholds set the min/max position caps; Kelly computes
  within them; then confidence_adjustment scales the result; existing MAX_POSITION_PCT /
  exposure caps remain hard ceilings (never exceeded).
- **D-05:** Insertion point: AFTER the fee gate (Phase 6) and risk-gate, integrated with the
  `_kelly_technical` call so advice/thresholds feed sizing. Veto happens before sizing.

### Claude's Discretion
- Whether to extend `_kelly_technical`'s signature to accept thresholds/adjustment vs apply the
  scaling around it — planner's call, but keep hard caps inviolate and the wiring shadow-gateable
  for Phase 8.
</decisions>

<canonical_refs>
## Canonical References

- `docs/superpowers/specs/2026-06-08-day-trading-upgrade-design.md` §3 (close the learning loop).
- `.planning/REQUIREMENTS.md` — LEARN-01, LEARN-02, LEARN-03.
- `src/trade_memory.py` — `get_advice()` (returns should_trade/confidence_adjustment/…),
  `get_dynamic_thresholds()` (min/max_position_pct, confluence, signal_scores), `record_trade_context()`.
- `src/learning_loop.py` — `LearningLoop.run_cycle()` (already called).
- `src/bot_thread.py` — live entry/sizing path (the existing memory advisory call + `_kelly_technical`).
- `src/alpaca_orchestrator.py` — `_kelly_technical`, entry loops, existing `memory.record_trade_context`.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TradeMemory.get_advice()` and `get_dynamic_thresholds()` already implemented and tested —
  this phase CONSUMES them, doesn't build them.
- `_kelly_technical` is the sizing function to feed.

### Established Patterns
- `memory` is constructed when learning is available; entries already record context. Hard caps
  (MAX_POSITION_PCT, MAX_TOTAL_EXPOSURE_PCT) already enforced — keep as ceilings.

### Integration Points
- Phase 8 wraps these consumption calls in shadow mode — wire so a single gate can flip
  veto/scale from "log-only" to "enforced".
</code_context>

<specifics>
## Specific Ideas
Tests: get_advice should_trade=False → candidate vetoed (not sized/ordered); confidence_adjustment
scales dollar amount; dynamic thresholds change min/max caps; hard MAX_POSITION_PCT never exceeded
even with adjustment>1; signal_type alignment with record_trade_context. Full suite green (217+).
</specifics>

<deferred>
## Deferred Ideas
- Intraday learning dimensions (time-of-day, hold, volatility) — Phase 8.
- Shadow→auto-apply gate (LEARNING_SHADOW_UNTIL_TRADES) — Phase 8.

None outside phase scope.
</deferred>

---

*Phase: 7-Close the Self-Learning Loop (Entry + Sizing)*
*Context gathered: 2026-06-08*
