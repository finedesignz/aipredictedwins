# VERIFY-01 Coverage Map

**Phase:** 10 — Verification + Backtest
**Generated:** 2026-06-15
**Purpose:** Audit existing unit coverage of the milestone's critical surfaces (D-01),
identify the one known gap (the Phase-7 `_advice_consume` MIRROR), and confirm it is
closed by `tests/test_learning_realloop.py`. Documentation only — no green tests duplicated.

## Surface → Test mapping

| # | Critical surface | Existing test(s) | Verdict |
|---|------------------|------------------|---------|
| 1 | Profile presets / SWING parity | `tests/test_strategy_profile.py` (SWING field-for-field parity, DAYTRADE preset, PROFILES registry) | GREEN keep |
| 2 | ATR exit math | `tests/test_atr_exits.py`, `tests/test_exit_advisor.py`, `tests/conftest.py::test_make_bars_for_atr_matches_atr` | GREEN keep |
| 3 | Fee gate | `tests/test_fee_gate.py` (`clears_fee_hurdle` hurdle math) | GREEN keep |
| 4 | Session VWAP | `tests/test_technical_signals.py` — `test_session_anchor_excludes_prior_day`, `test_session_anchor_below_current_day_vwap`, `test_session_anchor_false_unchanged`, `test_daytrade_uses_session_anchor` (drive `_vwap_bullish(..., session_anchor=True)`) | GREEN keep |
| 5 | Learning sizing math (Kelly + scale + floor/ceiling + hard cap) | `tests/test_learning_wiring.py` — `test_adjustment_scales_size`, `test_hard_cap_inviolate`, `test_dynamic_thresholds_applied`, `test_min_floor_not_applied_to_zero`, `test_defaults_unchanged` (pure `_kelly_technical`) | GREEN keep |
| 6 | Learning veto wiring | `tests/test_learning_wiring.py::test_veto_skips_candidate` | **MIRROR** — asserts `_advice_consume` re-implementation, NOT the real `_run_cycle`. Closed by `tests/test_learning_realloop.py::test_realloop_veto_enforce`. |
| 7 | Learning scale wiring | `tests/test_learning_wiring.py::test_adjustment_scales_size_in_path` | **MIRROR** — asserts `_advice_consume`, NOT the real loop. Closed by `tests/test_learning_realloop.py::test_realloop_scale_enforce`. |
| 8 | Shadow-mode wiring | `tests/test_learning_wiring.py::test_shadow_mode_no_effect` | **MIRROR** — asserts `_advice_consume`, NOT the real loop. Closed by `tests/test_learning_realloop.py::test_realloop_veto_shadow` + `test_realloop_scale_shadow`. |
| 9 | signal_type alignment (long/short canonical) | `tests/test_learning_wiring.py::test_signal_type_alignment` | GREEN keep |
| 10 | Shadow gate count (`should_enforce_learning`) | `tests/test_shadow_gate.py`, `tests/test_learning_wiring.py` (`test_*_imports_shadow_gate`, `test_explicit_zero_forces_shadow_both_runtimes`) | GREEN keep |
| 11 | Learning dimensions | `tests/test_learning_dimensions.py` | GREEN keep |
| 12 | Orchestrator/bot_thread sizing parity | `tests/test_learning_wiring.py::test_orchestrator_bot_thread_parity`, `test_memory_none_no_op` | GREEN keep |

## The gap (rows 6–8) and how it is closed

Rows 6, 7, 8 are flagged **MIRROR**: the Phase-7 verifier found the veto / scale /
shadow path tests assert against `_advice_consume` (a contract re-implementation in
`tests/test_learning_wiring.py`, lines 82–97), **not** the production entry loop in
`src/bot_thread.py::BotThread._run_cycle` (lines 522–577). A regression that dropped the
real `if not advice["should_trade"]` veto or the `adj = advice.get("confidence_adjustment")`
scale would NOT have been caught.

**Closed by** `tests/test_learning_realloop.py` (Phase 10, plan 01, Task 3), which drives the
REAL `BotThread._run_cycle` with stubbed alpaca/logger/`_db`/`scan_assets` (no network, no DB)
and a seeded `FakeTradeMemory`, asserting:

- `test_realloop_veto_enforce` — `should_trade=False` + enforce → `place_market_order` NOT called (call-count 0).
- `test_realloop_veto_shadow` — same advice + `LEARNING_ENFORCE=0` → order IS placed (call-count 1).
- `test_realloop_scale_enforce` — `confidence_adjustment=0.5` + enforce → captured `qty` ≈ 0.5 × the adj=1.0 baseline (compared pre-cap).
- `test_realloop_scale_shadow` — `confidence_adjustment=0.5` + `LEARNING_ENFORCE=0` → `qty` unscaled (equals baseline).

No existing green test was modified or duplicated.
