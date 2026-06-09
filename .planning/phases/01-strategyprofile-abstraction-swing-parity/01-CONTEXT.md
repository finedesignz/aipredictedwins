# Phase 1: StrategyProfile Abstraction + SWING Parity - Context

**Gathered:** 2026-06-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Introduce a `StrategyProfile` abstraction that bundles every parameter differing
between trading styles (timeframe, scan cadence, indicator periods, exit params,
max-hold, sizing, confluence thresholds), and a `SWING` preset that reproduces the
**current** swing-bot behavior byte-for-byte. The orchestrator reads its profile and
sources today's scattered module-level constants from the profile instead.

**Delivers:** PROFILE-01 (profile object), PROFILE-02 (SWING parity).
**Does NOT deliver:** the DAYTRADE preset or env selection (Phase 2), any behavior
change, MiroFish removal, signal-engine edits. This phase is a pure, behavior-preserving
refactor — the regression-safety foundation everything else builds on.
</domain>

<decisions>
## Implementation Decisions

### Profile object
- **D-01:** New module `src/strategy_profile.py`. `StrategyProfile` is a frozen
  `@dataclass` (immutable — presets are constants, not mutated at runtime).
- **D-02:** Fields (from design spec): `name`, `timeframe`, `scan_interval_s`,
  `bar_count`, `htf_filter_timeframe`, `ema_fast`, `ema_slow`, `rsi_period`,
  `adx_period`, `atr_period`, `atr_mult_stop`, `atr_mult_trail`, `hard_stop_pct`,
  `max_hold_hours` (`None` ⇒ overnight allowed), `kelly_fraction`,
  `max_position_pct`, `min_confluence`, `min_short_confluence`.
- **D-03:** Presets exposed as module constants `SWING` (and a `PROFILES` dict keyed
  by name for Phase 2 selection). DAYTRADE is added in Phase 2 — do not define it here.

### SWING parity (the hard constraint)
- **D-04:** SWING preset values MUST equal the current effective defaults in
  `alpaca_orchestrator.py` / `technical_signals.py`: timeframe `1Hour`,
  scan_interval 1800s (`CYCLE_SLEEP_SECONDS`), bar_count 50, HTF `4Hour`,
  EMA 9/21, RSI 14, ADX 14, hard_stop = `HARD_STOP_PCT`, max_hold `None`,
  kelly from config, max_position 0.05, min_confluence 4, min_short_confluence 3.
- **D-05:** Env overrides that exist today (e.g. `MIN_CONFLUENCE`, `CYCLE_SLEEP_SECONDS`)
  must continue to win — the profile supplies the **default**, env still overrides, so
  running bots A/B with their current Coolify env produces identical behavior.
- **D-06:** Refactor is mechanical: replace constant reads with `profile.<field>`
  reads; do NOT change any control flow, thresholds, or ordering this phase.

### Claude's Discretion
- Exact wiring style (pass `profile` through `main()` vs module-level resolved profile)
  is the planner's call, provided env-override precedence (D-05) holds and the diff stays
  minimal (Karpathy: smallest diff, no drive-by refactors).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design
- `docs/superpowers/specs/2026-06-08-day-trading-upgrade-design.md` — authoritative design;
  §"StrategyProfile abstraction" defines the field set and the SWING-parity requirement.

### Requirements
- `.planning/REQUIREMENTS.md` — PROFILE-01, PROFILE-02.

### Code being refactored
- `src/alpaca_orchestrator.py` — module-level constants (lines ~52–81) and their use sites.
- `src/technical_signals.py` — hardcoded indicator periods in `analyze()`/`scan_assets()`.
- `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/CONVENTIONS.md` — house style.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- Existing module-level constants block in `alpaca_orchestrator.py` is the source of truth
  for SWING values — copy them verbatim into the SWING preset.
- `src/config.py` `load_config()` already supplies `kelly_fraction`/`starting_bankroll`.

### Established Patterns
- Env-var-with-default pattern (`_os.environ.get(...)`) is pervasive — preserve it as the
  override layer on top of profile defaults.
- Pure-function indicator math in `technical_signals.py` (no external TA lib) — periods are
  the only thing parameterized; keep the math untouched.

### Integration Points
- `main()` in `alpaca_orchestrator.py` is where the profile gets resolved and threaded into
  `scan_assets`, `_kelly_technical`, and `PositionMonitor` construction (consumed by later phases).
</code_context>

<specifics>
## Specific Ideas

Parity is verifiable: a unit test asserting `SWING` field values equal the current constants,
plus a test that with no env overrides the resolved swing config matches today's literals.
</specifics>

<deferred>
## Deferred Ideas

- DAYTRADE preset + `BOT_PROFILE` selection — Phase 2.
- ATR fields are present on the profile now but only *consumed* in Phase 4 (exits) — defining
  them here is fine; wiring them is later.

None outside phase scope.
</deferred>

---

*Phase: 1-StrategyProfile Abstraction + SWING Parity*
*Context gathered: 2026-06-08*
