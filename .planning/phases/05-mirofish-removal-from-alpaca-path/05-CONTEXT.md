# Phase 5: MiroFish Removal from Alpaca Path - Context

**Gathered:** 2026-06-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Remove MiroFish/LLM dependencies from the live Alpaca trading path now that deterministic
ATR exits (Phase 4) are in place.

- **EXIT-01:** `PositionMonitor` no longer imports or constructs the MiroFish `ExitAdvisor`.
  Remove the `exit_advisor` constructor param, the `self.exit_advisor` attribute, and the
  `ExitAdvisor` import from the orchestrator. Update both instantiation sites (orchestrator +
  bot_thread) to stop passing an advisor.
- **EXIT-04:** Remove the Claude-CLI auth checks that only served MiroFish — the startup
  `ClaudeLLM` verification and the daily auth health-check in the main loop (and the
  associated `send_alert` calls / banner text). The entry risk gate is the deterministic
  `RulesGate` and does not need Claude.

**Does NOT deliver:** deleting `exit_advisor.py` / `risk_gate.py` / `mirofish_client.py`
files. Per design, they REMAIN in the repo (Kalshi paused, not deleted) — only the Alpaca
path stops importing the MiroFish pieces.
</domain>

<decisions>
## Implementation Decisions

### Precise removal surface (EXIT-01)
- **D-01:** `TrailingStop` ALSO lives in `exit_advisor.py` and is deterministic — it is STILL
  USED by the monitor (Phase 4). KEEP the `TrailingStop` import. Remove ONLY `ExitAdvisor`
  (and `check_position_thresholds`/`HARD_STOP_PCT`-style constants if now unused — verify each).
- **D-02:** Remove `exit_advisor` from `PositionMonitor.__init__`, the `self.exit_advisor`
  assignment, and any remaining references. Both instantiation sites updated.
- **D-03:** After Phase 4, the soft-branch already does not call `should_exit()` — so this is a
  clean removal with no behavior change. Verify the monitor path has zero `ExitAdvisor` refs.

### Claude-CLI auth removal (EXIT-04)
- **D-04:** Remove the startup `ClaudeLLM` import + `is_available()`/`call("Reply with OK")`
  verification block and the daily auth re-check in the main loop, plus the related
  `send_alert("Claude ... ")` calls and banner lines referencing MiroFish/Claude guardian.
  Do this in BOTH alpaca_orchestrator.py main() and bot_thread.py if mirrored.
- **D-05:** Keep `RulesGate` (deterministic entry risk gate) untouched — it needs no Claude.
  Leave `risk_gate.py` / `exit_advisor.py` / `mirofish_client.py` files on disk.

### Claude's Discretion
- Whether to also tidy now-dead constants/banner strings — allowed if clearly unused and
  minimal-diff; do not refactor unrelated code.
</decisions>

<canonical_refs>
## Canonical References

- `docs/superpowers/specs/2026-06-08-day-trading-upgrade-design.md` §2 (drop MiroFish; files retained).
- `.planning/REQUIREMENTS.md` — EXIT-01, EXIT-04.
- `.planning/phases/04-deterministic-atr-exits/04-RESEARCH.md` — exit-path surface map (reuse).
- `src/alpaca_orchestrator.py` — PositionMonitor.__init__, main() Claude-auth blocks, banner, both monitor instantiations.
- `src/bot_thread.py` — its PositionMonitor instantiation + any Claude-auth mirror.
- `src/exit_advisor.py` — ExitAdvisor (remove from path) vs TrailingStop (KEEP).
- `src/claude_llm.py` — ClaudeLLM (import being removed from the path).
- `src/rules_gate.py` — RulesGate (deterministic, keep).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- Deterministic `RulesGate` already gates entries; `TrailingStop` (deterministic) stays.

### Established Patterns
- Removal-only diff; keep files for the paused Kalshi path.

### Integration Points
- After removal, the Alpaca path has zero LLM calls — verify with grep (no ClaudeLLM/ExitAdvisor/should_exit in the trading loop).
</code_context>

<specifics>
## Specific Ideas
Tests/checks: grep asserts no `ExitAdvisor`, no `ClaudeLLM`, no `should_exit` in alpaca_orchestrator.py + bot_thread.py trading path; full `pytest tests/ -q` stays green (208+); orchestrator + bot_thread still import (smoke). exit_advisor.py / risk_gate.py / mirofish_client.py files still exist.
</specifics>

<deferred>
## Deferred Ideas
- Fee gate — Phase 6. Learning loop — Phase 7/8.
- Eventual deletion of MiroFish files — out of scope (Kalshi paused, not killed).

None outside phase scope.
</deferred>

---

*Phase: 5-MiroFish Removal from Alpaca Path*
*Context gathered: 2026-06-08*
