# Phase 3: Parameterized Signal Engine + ATR + Session VWAP - Context

**Gathered:** 2026-06-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Make `src/technical_signals.py` profile-aware and intraday-correct:
- **SIGNAL-01:** `analyze()` / `scan_assets()` take indicator periods from the active
  `StrategyProfile` instead of hardcoded 9/21/14.
- **SIGNAL-02:** `Signal` carries an `atr_value` (ATR over `profile.atr_period`),
  computed from bar data (reuse the true-range math already in `_adx`).
- **SIGNAL-03:** VWAP becomes **session-anchored** for the daytrade profile (rolling
  intraday window / daily reset) instead of rolling-20, while swing behavior is preserved.

**Also in scope (remediation):** the 11 pre-existing failing tests in
`tests/test_technical_signals.py` (and any in `tests/test_exit_advisor.py` rooted in the
signal module) — they are stale-threshold expectations from the earlier trend-rider
overhaul. Since this phase rewrites the signal surface, bring these tests green
(fix the test expectations to match intended current behavior, or fix a genuine bug if
one is found — decide per case, document which).

**Does NOT deliver:** ATR-based exit logic (Phase 4 consumes `atr_value`), fee gate (Phase 6),
learning (Phase 7/8).
</domain>

<decisions>
## Implementation Decisions

### Period parameterization (SIGNAL-01)
- **D-01:** `analyze(symbol, bars, bars_4h=None, profile=SWING)` — periods sourced from
  `profile.ema_fast/ema_slow/rsi_period/adx_period`. Default param = `SWING` so existing
  callers and swing behavior are unchanged (defaults equal today's 9/21/14).
- **D-02:** `scan_assets(...)` gains a `profile` param and threads it + `profile.timeframe`
  / `profile.bar_count` / `profile.htf_filter_timeframe` through. Orchestrator passes the
  active profile (selection from Phase 2). Keep swing call-site behavior identical.

### ATR (SIGNAL-02)
- **D-03:** Add `_atr(highs, lows, closes, period)` reusing the true-range computation
  pattern from `_adx` (Wilder smoothing). Add `atr_value: float` to the `Signal` dataclass
  (default 0.0 for safety). Compute it in `analyze()`. Do NOT wire it into exits (Phase 4).

### Session VWAP (SIGNAL-03)
- **D-04:** VWAP anchored to the current intraday session. Crypto trades 24/7 → "session" =
  a rolling/daily-reset window keyed off bar timestamps (e.g. UTC-day anchor). For swing
  (1H bars) preserve current VWAP semantics; the session anchor applies to the intraday
  (daytrade) path. Researcher: confirm the cleanest anchor given Alpaca bar timestamps and
  that bars carry a usable timestamp field.
- **D-05:** Confluence/short-score scoring logic and thresholds are UNCHANGED this phase —
  only the inputs (periods, VWAP basis) are parameterized. No strategy retuning here.

### Claude's Discretion
- Exact VWAP session-anchor implementation and whether ATR helper returns a series or scalar
  — planner/researcher's call, minimal-diff, math correctness verified by tests.
</decisions>

<canonical_refs>
## Canonical References

- `docs/superpowers/specs/2026-06-08-day-trading-upgrade-design.md` §4 (Signal engine changes).
- `.planning/REQUIREMENTS.md` — SIGNAL-01, SIGNAL-02, SIGNAL-03.
- `src/technical_signals.py` — `analyze`, `scan_assets`, `_adx` (TR math to reuse), `_vwap_bullish`.
- `src/strategy_profile.py` — period/atr_period/timeframe fields.
- `src/alpaca_orchestrator.py` — `scan_assets` call-sites (thread profile through).
- `tests/test_technical_signals.py` — the failing tests to bring green.
- `.planning/codebase/TESTING.md`.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_adx()` already computes true range — factor/reuse for `_atr()`.
- `_vwap_bullish()` already has a rolling-window fallback — extend with session anchor.
- Bars are dicts with open/high/low/close/volume and (optionally) vwap + timestamp.

### Established Patterns
- Pure-function indicator math, no external TA lib — keep that style.
- `analyze()` returns None when both scores are 0 — preserve.

### Integration Points
- `atr_value` on `Signal` is consumed by Phase 4 exits; session VWAP feeds confluence now.
- `scan_assets` profile param is set by the orchestrator's selected profile (Phase 2).
</code_context>

<specifics>
## Specific Ideas
Tests: period-param wiring (swing defaults == old behavior), ATR correctness vs a hand-computed
fixture, session-VWAP reset across a day boundary, and the previously-failing technical_signals
tests now green. Add a regression test asserting swing `analyze()` output unchanged for a fixed bar fixture.
</specifics>

<deferred>
## Deferred Ideas
- ATR consumption in exits — Phase 4.
- Strategy/threshold retuning for daytrade — later, post-paper-data.

None outside phase scope.
</deferred>

---

*Phase: 3-Parameterized Signal Engine + ATR + Session VWAP*
*Context gathered: 2026-06-08*
