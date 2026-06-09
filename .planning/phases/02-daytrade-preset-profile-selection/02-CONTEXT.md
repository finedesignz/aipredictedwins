# Phase 2: DAYTRADE Preset + Profile Selection - Context

**Gathered:** 2026-06-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Add the `DAYTRADE` preset to `src/strategy_profile.py` and make the orchestrator
**select** its active profile from the `BOT_PROFILE` env var (default `swing`).
Delivers PROFILE-03 (DAYTRADE preset) + PROFILE-04 (env selection).

**Does NOT deliver:** signal-engine rewiring to use the periods (Phase 3), ATR exits
(Phase 4), or any consumption of daytrade-only fields beyond selection. Selecting
`daytrade` must not crash — but behavior changes land in later phases. Bots A/B
(no `BOT_PROFILE` or `BOT_PROFILE=swing`) keep identical behavior.
</domain>

<decisions>
## Implementation Decisions

### DAYTRADE preset values (from design spec)
- **D-01:** `timeframe="5Min"`, `scan_interval_s=120`, `bar_count` sized for 5-min
  indicators (≥ ema_slow*2+adx_period; use 100), `htf_filter_timeframe="1Hour"`.
- **D-02:** indicator periods same as swing (ema 9/21, rsi 14, adx 14) — they now
  measure 5-min bars. `atr_period=14`, `atr_mult_stop≈1.5`, `atr_mult_trail≈2.0`
  (placeholders refined/consumed in Phase 4), `hard_stop_pct` tighter than swing
  (intraday) — use -0.04. `max_hold_hours=6.0` (4–8h band midpoint).
- **D-03:** `kelly_fraction` / `max_position_pct` same risk caps as swing initially
  (0.25 / 0.05); `min_confluence`/`min_short_confluence` same as swing (4/3) for now —
  tuning is a later concern, not this phase.
- **D-04:** Register in `PROFILES = {"swing": SWING, "daytrade": DAYTRADE}`.

### Profile selection
- **D-05:** Orchestrator resolves `profile = PROFILES[os.environ.get("BOT_PROFILE","swing").lower()]`
  at startup; unknown value → clear error (fail fast, not silent fallback). The
  env-var-default wiring from Phase 1 stays — `BOT_PROFILE` chooses which preset
  supplies the defaults; per-field env overrides still win on top.
- **D-06:** Banner prints the active profile name. No control-flow changes beyond selection.

### Claude's Discretion
- Exact `bar_count` for daytrade and whether selection happens in `main()` vs a small
  `resolve_profile()` helper — planner's call, keep minimal-diff.
</decisions>

<canonical_refs>
## Canonical References

- `docs/superpowers/specs/2026-06-08-day-trading-upgrade-design.md` §StrategyProfile / §6.
- `.planning/REQUIREMENTS.md` — PROFILE-03, PROFILE-04.
- `src/strategy_profile.py` — Phase 1 output; extend with DAYTRADE + registry entry.
- `src/alpaca_orchestrator.py` — startup/`main()` where profile resolves; banner.
- `.planning/phases/01-.../01-CONTEXT.md` + `01-RESEARCH.md` — env-override precedence pattern (reuse).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `StrategyProfile` + `SWING` + `PROFILES` from Phase 1 — extend, don't rewrite.
- Phase 1 env-override wiring — `BOT_PROFILE` slots in front of it as the default source.

### Established Patterns
- Fail-fast on bad config mirrors how the bot already validates (e.g. untradeable lists).

### Integration Points
- Profile selection at orchestrator startup feeds `scan_assets` timeframe, `PositionMonitor`,
  Kelly sizing in later phases — this phase only sets the selected profile object.
</code_context>

<specifics>
## Specific Ideas
Test: `BOT_PROFILE=daytrade` resolves to DAYTRADE; unset/`swing` resolves to SWING (parity);
unknown raises; selecting daytrade does not crash startup (smoke).
</specifics>

<deferred>
## Deferred Ideas
- Using the daytrade periods in technical_signals — Phase 3.
- ATR exit consumption + max_hold enforcement — Phase 4.
- Tuning daytrade confluence/sizing — later, post-paper-data.

None outside phase scope.
</deferred>

---

*Phase: 2-DAYTRADE Preset + Profile Selection*
*Context gathered: 2026-06-08*
