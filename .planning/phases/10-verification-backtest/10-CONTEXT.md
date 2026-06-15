# Phase 10: Verification + Backtest - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Final milestone validation.

- **VERIFY-01:** Ensure unit tests cover the milestone's critical surfaces: profile presets
  (SWING parity), ATR exit math, fee gate, learning veto/scale wiring, session VWAP. MOST of
  these already exist (Phases 1–8). This phase AUDITS coverage and fills the one known gap:
  the Phase-7 verifier flagged that the learning veto/scale path tests assert against a
  `_advice_consume` mirror helper rather than driving the real entry loop — add a real
  integration test that exercises the actual bot_thread/orchestrator entry path so a future
  regression in the live wiring is caught.
- **VERIFY-02:** A backtest harness over historical 5-minute bars that validates daytrade
  SIGNAL FREQUENCY (how often the daytrade profile produces candidates) before any live paper
  run — reuse `scan_assets(..., profile=DAYTRADE, fetch_4h=False)` on historical bars. Output a
  simple frequency/coverage report (candidates per N bars per symbol). This is a sanity check,
  NOT a full P&L backtest.

**Does NOT deliver:** live trading, P&L backtest with fills, the deferred Bot D infra (Phase 9 HALT).
</domain>

<decisions>
## Implementation Decisions

### Coverage audit + integration test (VERIFY-01)
- **D-01:** Audit existing tests and map them to the VERIFY-01 surfaces; document the mapping.
  Only ADD what's missing — do not duplicate existing green tests.
- **D-02:** Add a real-loop learning integration test: construct the entry path (or the smallest
  real slice of it) with a fake/seeded TradeMemory returning should_trade=False / adjustment<1,
  and assert the ACTUAL code path vetoes/scales (not the mirror helper). Cover both enforce and
  shadow modes. RESEARCH: find the cleanest seam to drive the real loop in a unit test.

### Backtest harness (VERIFY-02)
- **D-03:** New `scripts/backtest_signal_frequency.py` (or tests/ harness) that: fetches
  historical 5-min bars for the daytrade universe (RESEARCH: Alpaca historical bars API limits/
  params; or accept a fixture/CSV for offline determinism), runs `scan_assets(profile=DAYTRADE,
  fetch_4h=False)` across a rolling window, and reports candidate frequency per symbol + totals.
- **D-04:** Must run deterministically in CI/test without live API where possible — prefer a
  fixture-driven test plus an optional live-fetch mode. RESEARCH picks the approach.
- **D-05:** Output a short human-readable report (and assert a sane frequency range so it doubles
  as a regression guard — e.g. daytrade produces > 0 and not absurdly many candidates on the fixture).

### Claude's Discretion
- Backtest harness location (scripts/ vs tests/) and fixture vs live-fetch default — planner/
  researcher's call; prefer deterministic fixture for the committed test + documented live mode.
</decisions>

<canonical_refs>
## Canonical References

- `docs/superpowers/specs/2026-06-08-day-trading-upgrade-design.md` (Testing section).
- `.planning/REQUIREMENTS.md` — VERIFY-01, VERIFY-02.
- `.planning/phases/07-...-07-VERIFICATION.md` — the mirror-helper gap to close.
- `src/technical_signals.py` (scan_assets/analyze, profile param), `src/strategy_profile.py` (DAYTRADE).
- `src/bot_thread.py`, `src/alpaca_orchestrator.py` (entry loop seam for the integration test).
- `src/alpaca_client.py` (get_bars — historical fetch params/timeframe).
- `tests/conftest.py` (FakeTradeMemory), existing tests across tests/.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- ~272 tests already cover most surfaces; FakeTradeMemory fixture exists; scan_assets is profile-aware and has fetch_4h=False for offline use.

### Established Patterns
- Pure-function signal engine → easy to drive on fixture bars deterministically.

### Integration Points
- Backtest reuses the real scan_assets; integration test reuses the real entry seam.
</code_context>

<specifics>
## Specific Ideas
Tests: coverage-map doc; real-loop veto + scale integration test (enforce + shadow); backtest
harness produces a frequency report on a fixture and asserts a sane range. Full suite green (272+).
</specifics>

<deferred>
## Deferred Ideas
- Full P&L backtest with fills/slippage — future.
- Live Bot D paper run — after the Phase 9 infra HALT is resolved.

None outside phase scope.
</deferred>

---

*Phase: 10-Verification + Backtest*
*Context gathered: 2026-06-09*
