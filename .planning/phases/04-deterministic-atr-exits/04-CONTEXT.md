# Phase 4: Deterministic ATR Exits - Context

**Gathered:** 2026-06-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace the soft-threshold exit decisions in the position monitor with **deterministic,
volatility-scaled (ATR) exits**, and add absolute overrides. The MiroFish `ExitAdvisor`
LLM consult is REPLACED by ATR logic for soft thresholds. ATR exits land in BOTH the
orchestrator `PositionMonitor` and the live `bot_thread.py` monitor.

- **EXIT-02:** ATR-scaled stop = entry − (`profile.atr_mult_stop` × ATR); ATR-scaled trailing
  stop ratchets up from the high-water mark by (`profile.atr_mult_trail` × ATR). Side-aware
  (longs and shorts). Uses `Signal.atr_value` / a fresh ATR from monitor bars.
- **EXIT-03:** `profile.hard_stop_pct` and `profile.max_hold_hours` auto-close are ABSOLUTE
  overrides (fire regardless of ATR state). Max-hold: if a position has been open longer than
  `max_hold_hours`, close it (true day-trade discipline). `max_hold_hours=None` (swing) ⇒ no
  time-based close — swing exit behavior preserved.

**Does NOT deliver:** removal of the ExitAdvisor module/import (Phase 5 — this phase makes
the monitor stop CALLING it for decisions, replacing with ATR; Phase 5 deletes the wiring +
Claude-CLI auth). Fee gate (Phase 6), learning (7/8). The exit path must never be gapped:
ATR exits must be live before Phase 5 strips MiroFish.
</domain>

<decisions>
## Implementation Decisions

### ATR stop + trail (EXIT-02)
- **D-01:** Replace the soft_stop/soft_take_profit branch that calls `exit_advisor.should_exit()`
  with deterministic ATR logic. Compute ATR from the monitor's existing bar fetch
  (reuse `technical_signals._atr` from Phase 3) over `profile.atr_period`.
- **D-02:** Long: hard stop level = entry − atr_mult_stop×ATR; trail = highwater − atr_mult_trail×ATR,
  only ratchets up. Short: mirror (entry + atr_mult_stop×ATR; trail from low-water). Reuse the
  existing `TrailingStop` tracker where it fits; extend for ATR distance + shorts.
- **D-03:** Keep the existing absolute hard-threshold behavior but source the level from
  `profile.hard_stop_pct` (already wired). Existing trailing-stop and tightened-stop machinery
  stays; ATR augments/replaces the LLM-advisor branch only.

### Absolute overrides (EXIT-03)
- **D-04:** Max-hold: compute hours-held from the trade's entry timestamp (the monitor already
  parses `timestamp`); if `profile.max_hold_hours` is not None and exceeded → immediate close
  (reason `max_hold`). `None` ⇒ skip (swing unaffected).
- **D-05:** Override ordering (first match wins): hard_stop_pct → max_hold → ATR trailing stop →
  ATR stop. Document the precedence explicitly.

### Profile threading
- **D-06:** `PositionMonitor` (orchestrator) and the `bot_thread.py` monitor must know the active
  profile to read atr_mult_*/hard_stop_pct/max_hold_hours/atr_period. Thread the profile into the
  monitor constructor (orchestrator passes `PROFILE`; bot_thread resolves `PROFILES.get(BOT_PROFILE,SWING)`).

### Claude's Discretion
- Whether to keep `ExitAdvisor` import present-but-unused this phase (removed Phase 5) or guard it —
  planner's call, but the monitor must NOT make exit decisions via the LLM after this phase.
</decisions>

<canonical_refs>
## Canonical References

- `docs/superpowers/specs/2026-06-08-day-trading-upgrade-design.md` §2 (deterministic ATR exits).
- `.planning/REQUIREMENTS.md` — EXIT-02, EXIT-03.
- `src/alpaca_orchestrator.py` — `PositionMonitor` (soft/hard threshold logic, `TrailingStop`, `_tightened`).
- `src/bot_thread.py` — the live runtime monitor (mirror the changes here — this is what actually runs in prod).
- `src/exit_advisor.py` — `ExitAdvisor`, `TrailingStop`, `check_position_thresholds`, HARD/SOFT consts (what's being replaced).
- `src/technical_signals.py` — `_atr` (Phase 3) to reuse.
- `src/strategy_profile.py` — atr_mult_stop/atr_mult_trail/atr_period/hard_stop_pct/max_hold_hours.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_atr()` (Phase 3). `TrailingStop` class in exit_advisor.py. Monitor already fetches bars,
  parses entry timestamp, computes pnl_pct side-aware, and closes positions.

### Established Patterns
- Monitor loop: threshold detection → should_close decision → close_position + log + alert.
  ATR logic plugs into the threshold-decision step.

### Integration Points
- Two monitors (orchestrator + bot_thread) — keep them behaviorally identical. bot_thread is prod.
- Phase 5 removes the now-unused ExitAdvisor + Claude-CLI auth that supported it.
</code_context>

<specifics>
## Specific Ideas
Tests: ATR stop level math (long/short), trailing ratchet (up-only), max-hold close fires after
N hours, swing (max_hold None) never time-closes, override precedence order, ATR exit triggers
without any LLM call (mock/assert exit_advisor.should_exit not invoked for the decision).
</specifics>

<deferred>
## Deferred Ideas
- Delete ExitAdvisor import + mirofish_client + Claude-CLI auth — Phase 5.
- Fee gate — Phase 6.

None outside phase scope.
</deferred>

---

*Phase: 4-Deterministic ATR Exits*
*Context gathered: 2026-06-08*
