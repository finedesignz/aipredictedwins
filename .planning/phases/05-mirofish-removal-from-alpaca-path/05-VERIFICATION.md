---
phase: 05-mirofish-removal-from-alpaca-path
verified: 2026-06-08T00:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: none
---

# Phase 5: MiroFish Removal from Alpaca Path Verification Report

**Phase Goal:** Strip every MiroFish/LLM dependency out of the live Alpaca trading path; deterministic exits + RulesGate retained, Kalshi files kept on disk. Closes EXIT-01, EXIT-04.
**Verified:** 2026-06-08
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Alpaca path makes zero LLM/Claude calls (startup, daily, monitoring) | VERIFIED | No `ClaudeLLM`, `is_available`, `Reply with OK`, `_last_auth_check` in non-comment code of alpaca_orchestrator.py. No startup verify / daily auth block. |
| 2 | PositionMonitor constructs without ExitAdvisor; exits deterministic (TrailingStop + pct constants) | VERIFIED | `def __init__(self, alpaca, logger, profile=SWING)` (L109, 3-arg). `self._trailing = TrailingStop()` (L120). `self.exit_advisor` absent. |
| 3 | Both orchestrator main() and BotThread instantiate PositionMonitor without exit_advisor | VERIFIED | alpaca L598 `PositionMonitor(alpaca, logger, PROFILE)`; bot_thread L226 `PositionMonitor(alpaca, logger, _monitor_profile)`. No `exit_advisor =` in either. |
| 4 | exit_advisor.py, risk_gate.py, mirofish_client.py, claude_llm.py still exist | VERIFIED | All four present on disk (ls confirmed). |
| 5 | Full test suite green; both modules import | VERIFIED | `pytest tests/ -q` → 208 passed, 2 skipped. `ast.parse` OK on both files. |

**Score:** 5/5 truths verified

### EXIT-01 — PASS
- alpaca_orchestrator L34 import trimmed to `TrailingStop, HARD_STOP_PCT, SOFT_STOP_PCT, SOFT_TAKE_PROFIT_PCT` — `ExitAdvisor` AND `check_position_thresholds` dropped.
- No ExitAdvisor import / ctor param / `self.exit_advisor` attr / `ExitAdvisor()` instantiation in non-comment code (both files).
- `TrailingStop` + the three pct constants retained (alpaca); pct constants retained (bot_thread — TrailingStop not needed there, per plan interfaces).
- PositionMonitor is 3-arg; both call sites updated.
- `check_position_thresholds` dropped (no remaining reference).

### EXIT-04 — PASS
- ClaudeLLM startup verify block removed (no `from src.claude_llm`, no `is_available`, no `Reply with OK`).
- Daily auth re-check removed (no `_last_auth_check`).
- `daily_pnl = 0.0` (L613/627) and `daily_start` (L616/628) reset preserved.
- RulesGate untouched: `from src.rules_gate import RulesGate` (L32), `risk_gate = RulesGate()` (L566).

### Key Link Verification

| From | To | Via | Status |
|------|-----|-----|--------|
| alpaca_orchestrator.py | exit_advisor.TrailingStop | kept import | WIRED — L34 import + L120 `TrailingStop()` + L244/294 usage |
| PositionMonitor.run | trailing stop + pct constants | deterministic, no should_exit | WIRED — `self._trailing.update_atr`/`.remove`; no `should_exit` |

### Probe Execution

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| Task 1/2 grep+parse | non-comment scan both files | no ExitAdvisor/ClaudeLLM/should_exit; TrailingStop+HARD retained; parse OK | PASS |
| Task 3 suite | `python -m pytest tests/ -q` | 208 passed, 2 skipped | PASS |
| Files intact | ls four files | all present | PASS |

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
|-------------|-------------|--------|----------|
| EXIT-01 | 05-01 | SATISFIED | ExitAdvisor fully removed from both trading-path files; deterministic exits retained |
| EXIT-04 | 05-01 | SATISFIED | Claude-auth startup + daily blocks removed; daily reset preserved; RulesGate untouched |

### Anti-Patterns Found

None blocking.

### Behavioral Spot-Checks / Info

- `test_no_llm_call` (tests/test_atr_exits.py L154) still passes but is now a **trivial guard** — it asserts `mock_advisor.should_exit.assert_not_called()` while the advisor is never wired into the 3-arg PositionMonitor, so it cannot fail by construction. SUMMARY discloses this honestly. INFO only: the architectural removal (no advisor reaches the monitor) IS the real guarantee, and that is independently verified above. Not a regression, not a blocker.

### Gaps Summary

No gaps. Both requirements closed, all truths verified against actual code, suite green, no MiroFish/Claude file deleted.

---

_Verified: 2026-06-08_
_Verifier: Claude (gsd-verifier)_
