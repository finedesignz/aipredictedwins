---
phase: 04-deterministic-atr-exits
verified: 2026-06-08T00:00:00Z
status: passed
score: 8/8 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: none
---

# Phase 4: Deterministic ATR Exits — Verification Report

**Phase Goal:** Replace the MiroFish LLM soft-exit branch with a deterministic, side-aware ATR exit ladder plus absolute overrides (EXIT-02/EXIT-03), LLM-free before Phase 5.
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Monitor decides exits with deterministic ATR math; `should_exit()` never called for decision | ✓ VERIFIED | `alpaca_orchestrator.py` L233-262 ladder; only `should_exit` occurrence is comment L235; `test_no_llm_call` PASS asserts `should_exit.assert_not_called()` across atr_stop long/short + hard_stop |
| 2 | Soft-zone crossings close on ATR stop / ATR trailing stop (no run-to-hard-stop gap) | ✓ VERIFIED | `soft_stop/soft_take_profit` LLM branch deleted; rungs 3 (trailing) + 4 (atr_stop) L244-258 fill the soft zone |
| 3 | TrailingStop side-aware ATR trailing (high-water longs / low-water shorts) | ✓ VERIFIED | `exit_advisor.py` `update_atr` L234-278; `_peaks`/`_troughs`; `test_atr_trail_ratchet` PASS (long+short) |
| 4 | hard_stop_pct + max_hold_hours absolute overrides; SWING (None) never time-closes | ✓ VERIFIED | L239-243 with `max_hold_hours is not None` guard; `test_swing_no_time_close` + `test_max_hold_fires` PASS |
| 5 | First-match precedence: hard_stop → max_hold → trailing → atr_stop | ✓ VERIFIED | if/elif ladder L239-258; `test_override_precedence` PASS (hard wins) |
| 6 | ATR computed live at `profile.timeframe`, not hardcoded 1Hour; ATR<=0 → overrides only | ✓ VERIFIED | L222-223 `get_bars(timeframe=self.profile.timeframe, limit=atr_period+5)`; `_atr` L229; rungs 3/4 gated `atr > 0`; `test_zero_atr_safe` PASS |
| 7 | Both consumers pass active profile to shared PositionMonitor | ✓ VERIFIED | `alpaca_orchestrator.py` L614 `PROFILE`; `bot_thread.py` L227 `_monitor_profile` from `PROFILES.get(BOT_PROFILE, SWING)` L226 |
| 8 | RED→GREEN test suite exists for all behaviors | ✓ VERIFIED | `tests/test_atr_exits.py` 8 tests, substantive assertions on close reasons |

**Score:** 8/8 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `tests/test_atr_exits.py` | 8 behavioral tests | ✓ VERIFIED | Real assertions, not stubs |
| `tests/conftest.py` | mock fixtures | ✓ VERIFIED | mock_alpaca/logger/advisor consumed by tests |
| `src/exit_advisor.py` | `update_atr` + shorts | ✓ VERIFIED | `_troughs`, side-aware, atr<=0→None; pct `update()` untouched |
| `src/alpaca_orchestrator.py` | profile param + ladder | ✓ VERIFIED | `__init__(... profile=SWING)` L109; ladder L233-262 |
| `src/bot_thread.py` | profile threaded | ✓ VERIFIED | L227 |

### Key Link Verification

| From | To | Via | Status |
|------|----|----|--------|
| `_check_all_positions` | `_atr` at profile.timeframe | live bar fetch | ✓ WIRED L222-229 |
| `_check_all_positions` | `TrailingStop.update_atr` | trailing rung | ✓ WIRED L245-247 |
| `bot_thread` monitor | `PROFILES.get(BOT_PROFILE, SWING)` | constructor arg | ✓ WIRED L226-227 |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full suite | `python -m pytest tests/ -q` | 208 passed, 2 skipped | ✓ PASS |
| No-LLM | `pytest tests/test_atr_exits.py::test_no_llm_call` | 1 passed | ✓ PASS |
| ATR spec | `pytest tests/test_atr_exits.py -q` | 8 passed | ✓ PASS |

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| EXIT-02 (side-aware ATR stop + trailing at profile.timeframe) | ✓ SATISFIED | Truths 2,3,6; tests pass |
| EXIT-03 (hard_stop_pct + max_hold overrides, swing-safe, precedence) | ✓ SATISFIED | Truths 4,5; tests pass |

### Anti-Patterns Found

None. `should_exit` retained only as unused attribute (intentional, Phase 5 removes). No TODO/FIXME/stub in modified decision path.

### Human Verification Required

None — fully verifiable via tests and grep.

### Gaps Summary

No gaps. SUMMARY claims independently confirmed: 208 passed/2 skipped exactly matches; `test_no_llm_call` passes; only two `PositionMonitor(` sites, both profile-passing; no `should_exit()` decision call (grep shows comment only); ATR uses `self.profile.timeframe` not literal `1Hour`; SWING `max_hold_hours is not None` guard prevents time-close; first-match if/elif ladder correct order. ExitAdvisor module retained for Phase 5.

**Ship verdict: PASS.**

---

_Verified: 2026-06-08_
_Verifier: Claude (gsd-verifier)_
