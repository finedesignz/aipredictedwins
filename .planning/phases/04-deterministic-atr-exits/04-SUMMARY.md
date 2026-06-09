# Phase 4: Deterministic ATR Exits — Summary

Replaced the MiroFish LLM exit consultation with a deterministic, side-aware ATR exit ladder plus absolute overrides, so the exit path is LLM-free before Phase 5 strips MiroFish. EXIT-02 and EXIT-03 delivered across two waves on `main`.

## Built
- **Wave 1 (04-01)** — test foundation + tracker:
  - `tests/conftest.py`: deterministic ATR bar generator (flat closes + constant high-low => Wilder ATR == high-low, verified against `_atr`), mock alpaca/logger/advisor fixtures.
  - `tests/test_atr_exits.py`: 8 behavioral tests (RED at authoring).
  - `src/exit_advisor.py`: `TrailingStop.update_atr` — high-water longs / low-water shorts, ATR-distance trail, arms only in profit, `atr<=0 -> None`; `remove()` clears `_peaks` + `_troughs`; pct `update()` untouched.
- **Wave 2 (04-02)** — monitor rewrite + wiring:
  - `PositionMonitor(profile=SWING)`; ATR computed live at `self.profile.timeframe` (`limit=atr_period+5`), not literal `1Hour`.
  - First-match ladder: `hard_stop_pct -> max_hold -> ATR trailing stop -> ATR stop`. `atr<=0` falls back to hard_stop/max_hold only. SWING (`max_hold_hours=None`) never time-closes.
  - Deleted the `soft_stop/soft_take_profit` MiroFish branch (the only `should_exit()` call). Hard/trailing/tightened close mechanics + side-aware pnl preserved.
  - Profile threaded into both instantiation sites (orchestrator `main()` -> `PROFILE`; `bot_thread` -> `PROFILES.get(BOT_PROFILE, SWING)`).

## Files
- Created: `tests/conftest.py`, `tests/test_atr_exits.py`
- Modified: `src/exit_advisor.py`, `src/alpaca_orchestrator.py`, `src/bot_thread.py`

## Test Results
- `python -m pytest tests/ -q` — **208 passed, 2 skipped** (200-test baseline maintained + 8 new ATR tests).
- `tests/test_atr_exits.py` — 8/8 passed (ATR stop long/short, trail ratchet long+short, zero-ATR safe, max-hold fires DAYTRADE, swing-None skip, precedence hard_stop-wins).
- **No-LLM assertion result: PASS** — `test_no_llm_call` asserts `ExitAdvisor.should_exit` is never called for the exit decision (verified across atr_stop long/short and hard_stop). Grep confirms no `should_exit` call in the monitor decision path; exactly 2 `PositionMonitor(` sites, both profile-passing.

## Status
- **EXIT-02 (side-aware ATR stop + ATR trailing stop at profile.timeframe): COMPLETE.**
- **EXIT-03 (hard_stop_pct + max_hold_hours absolute overrides, swing-safe, first-match precedence): COMPLETE.**
- ExitAdvisor import/module/Claude-CLI auth retained for Phase 5. Swing parity preserved (SWING hard_stop_pct=-0.15 == old HARD_STOP_PCT, no time-close).

## Commits
- 8a03a09 test(04-01): ATR-exit fixtures + deterministic ATR generator
- 2b66939 test(04-01): add failing ATR-exit + no-LLM spec
- c2e094c feat(04-01): TrailingStop ATR-distance + short trailing
- 73dedfa feat(04-02): deterministic ATR exit ladder + overrides in PositionMonitor
- eb76c42 feat(04-02): thread active profile into both PositionMonitor sites
