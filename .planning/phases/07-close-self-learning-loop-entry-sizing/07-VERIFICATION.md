---
phase: 07-close-self-learning-loop-entry-sizing
verified: 2026-06-08T00:00:00Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: none
---

# Phase 7: Close the Self-Learning Loop — Entry + Sizing Verification Report

**Phase Goal:** Close trade-memory feedback loop into both runtimes — `_kelly_technical` consumes learned confidence/thresholds (LEARN-02/03) and both entry paths veto on losing patterns (LEARN-01), behind a `LEARNING_ENFORCE` shadow seam.
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | LEARN-01: `get_advice` should_trade=False vetoes (skip) in all 4 entry paths; LONG veto not duplicated | ✓ VERIFIED | bot_thread LONG 530-538 (existing veto, single, wrapped in LEARNING_ENFORCE), SHORT 723-731; orchestrator LONG 881-887, SHORT 1028-1034. All gate `continue` behind `if LEARNING_ENFORCE`. No second LONG veto added. |
| 2 | LEARN-02: confidence_adjustment scales Kelly before the cap clamp | ✓ VERIFIED | alpaca_orchestrator.py:418-421 — `adjusted_pct = kelly_pct*kelly_fraction; adjusted_pct *= confidence_adjustment` precedes floor (424) and cap (428-430). Order: scale → floor → cap. |
| 3 | LEARN-03: dynamic thresholds feed sizing; effective max = min(static, dynamic), adjustment>1 cannot breach static cap | ✓ VERIFIED | eff_max = min(MAX/cfg, dynamic) at all 4 call sites (bot 555/748, orch 902/1049). Cap clamp is LAST in `_kelly_technical` (428-430). `test_hard_cap_inviolate`: adjustment=1.5 → adjusted_pct==0.05, capped True. |
| 4 | Loop integrity: canonical signal_type in get_advice AND record_trade_context, both files; short paths record context; sentiment /4.0 | ✓ VERIFIED | LONG `technical_confluence_{score}` (bot 512, orch 869); SHORT `technical_short_{score}` (bot 702, orch 1016) — same local var passed to both get_advice and record_trade_context. SHORT record_trade_context added (bot 799, orch 1110). sentiment `/4.0` everywhere (bot 527/720, orch 878/1025). orch order-log `short_technical_` (1088) intentionally left in alpaca_trades, not context. |
| 5 | Shadow seam LEARNING_ENFORCE present (default enforce); memory=None no-op | ✓ VERIFIED | `LEARNING_ENFORCE = os.environ.get("LEARNING_ENFORCE","1")=="1"` (bot_thread:89, orch:67). All advisory reads guarded by `if memory is not None`; `adj=1.0` initialized first; eff_max/eff_min fall back to static/None. test_memory_none_no_op asserts res==legacy. |
| 6 | Test suite 0 failures (claimed 230/2 skip); test_hard_cap_inviolate + memory=None tests meaningful | ✓ VERIFIED | `python -m pytest tests/ -q` → **230 passed, 2 skipped** (run by verifier). Both named tests are substantive (real `_kelly_technical` calls with concrete assertions, not hollow). |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `tests/test_learning_wiring.py` | veto/scale/threshold/hardcap/shadow/signal_type tests | ✓ VERIFIED | 13 tests, 0 skips. Math tests + path-contract + parity + enforce-flag-reload. |
| `tests/conftest.py` FakeTradeMemory | in-memory advice/thresholds stub | ✓ VERIFIED | get_advice/get_dynamic_thresholds/record_trade_context, records calls for assertion. |
| `src/alpaca_orchestrator.py` | extended `_kelly_technical` + both paths wired | ✓ VERIFIED | sig has confidence_adjustment+min_position_pct; both LONG+SHORT advisory blocks + short record added. |
| `src/bot_thread.py` | both paths wired, LEARNING_ENFORCE | ✓ VERIFIED | LONG extended, SHORT full block + record added. |

### Key Link Verification

| From | To | Via | Status |
|------|----|----|--------|
| test_learning_wiring | `_kelly_technical` | direct import + adjustment kwargs | ✓ WIRED |
| bot_thread | `_kelly_technical` | confidence_adjustment= passed | ✓ WIRED (both sides) |
| orchestrator | memory.get_advice | fresh advisory both paths | ✓ WIRED |
| both files SHORT | record_trade_context | technical_short_ signal_type | ✓ WIRED |

### Probe / Behavioral

`python -m pytest tests/ -q` → 230 passed, 2 skipped (0 failures). Matches SUMMARY claim. The 2 skips are pre-existing/unrelated.

### Requirements Coverage

| Req | Description | Status | Evidence |
|-----|-------------|--------|----------|
| LEARN-01 | get_advice veto before sizing, should_trade=False vetoes | ✓ SATISFIED | All 4 paths, get_advice rule win_rate<0.30 & closed>=3 (trade_memory:480) |
| LEARN-02 | confidence_adjustment scales size | ✓ SATISFIED | _kelly_technical:421 before cap |
| LEARN-03 | dynamic thresholds feed min/max into Kelly | ✓ SATISFIED | eff_max=min(static,dynamic), floor at 424 |

### Anti-Patterns Found

None blocking. No TBD/FIXME/XXX in modified files. record blocks wrapped in try/except (defensive but justified — DB I/O boundary).

### Findings (WARNING, non-blocking)

⚠️ The path-level tests (`test_veto_skips_candidate`, `test_shadow_mode_no_effect`, `test_adjustment_scales_size_in_path`) exercise a `_advice_consume` **mirror helper defined in the test file**, not the actual candidate-loop code in bot_thread/orchestrator. They verify the contract logic is sound but do NOT execute the production wiring. The production wiring itself was verified by direct code reading (all 4 call sites confirmed correct above), so the goal IS achieved — but these tests would not catch a future regression in the real loop. Recommend a follow-up integration test driving the actual cycle with FakeTradeMemory. This does not block ship: code is correct and the math/parity/no-op/hard-cap tests (which DO call real code) are meaningful.

### Gaps Summary

No gaps. All 6 truths verified against actual code, all 3 LEARN requirements satisfied in both runtimes and both sides. Hard cap proven inviolate (clamp last + min(static,dynamic) at call sites). Shadow seam and memory=None no-op confirmed. Suite green (230/2).

---

_Verified: 2026-06-08_
_Verifier: Claude (gsd-verifier)_
