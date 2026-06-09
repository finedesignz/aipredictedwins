---
phase: 05-mirofish-removal-from-alpaca-path
plan: 01
subsystem: alpaca-trading-path
tags: [removal, deterministic-exits, llm-free, EXIT-01, EXIT-04]
requires: [04-deterministic-atr-exits]
provides: ["Alpaca path with zero LLM calls (no ExitAdvisor, no Claude-auth)"]
affects: [src/alpaca_orchestrator.py, src/bot_thread.py, tests/test_atr_exits.py]
key-files:
  modified:
    - src/alpaca_orchestrator.py
    - src/bot_thread.py
    - tests/test_atr_exits.py
decisions:
  - "Updated test_atr_exits.py constructor calls to the new 3-arg PositionMonitor signature (API change follow-through, not a regression paper-over). LLM-free assertion preserved."
metrics:
  duration: ~10m
  tasks: 3
  files: 3
  completed: 2026-06-08
---

# Phase 5 Plan 01: MiroFish Removal from Alpaca Path Summary

Stripped every MiroFish/LLM dependency out of the live Alpaca trading path — `ExitAdvisor` and the Claude-CLI auth plumbing — leaving deterministic ATR exits + `RulesGate`. Removal-only diff; Kalshi/MiroFish files retained on disk.

## EXIT-01 (ExitAdvisor removal) — DONE
- `alpaca_orchestrator.py`: trimmed L34 import to `TrailingStop, HARD_STOP_PCT, SOFT_STOP_PCT, SOFT_TAKE_PROFIT_PCT` (dropped `ExitAdvisor` + unused `check_position_thresholds`); removed `exit_advisor: ExitAdvisor` ctor param, `self.exit_advisor` attr, `exit_advisor = ExitAdvisor()`, and updated `PositionMonitor(alpaca, logger, PROFILE)`.
- `bot_thread.py`: trimmed import to pct constants only; removed `exit_advisor = ExitAdvisor()` and the advisor arg from `PositionMonitor(alpaca, logger, _monitor_profile)`.

## EXIT-04 (Claude-auth removal) — DONE
- Removed startup `ClaudeLLM` verify block (`is_available()`/`call("Reply with OK")` + both `send_alert` lines), the `_last_auth_check` init, and the daily auth health-check block. Preserved `daily_pnl = 0.0` / `daily_start = today` reset.
- `bot_thread.py` had no Claude-auth mirror — untouched for EXIT-04 (confirmed).

## Kept (untouched / retained)
- `TrailingStop` + `HARD_STOP_PCT`/`SOFT_STOP_PCT`/`SOFT_TAKE_PROFIT_PCT` imports in both files.
- `RulesGate` deterministic entry gate.
- Files on disk: `exit_advisor.py`, `risk_gate.py`, `mirofish_client.py`, `claude_llm.py` (verified present).

## Discretion tidy (minimal, no behavior change)
- Module docstring, PositionMonitor docstring, banner title/`risk_mode`, monitor-start print, final-report header, argparse description, and the exit-ladder inline comment in `alpaca_orchestrator.py` reworded from "MiroFish-as-Guardian"/"MiroFish exit advisor" to deterministic ATR exits + RulesGate.
- `bot_thread.py` docstring `ExitAdvisor` -> `RulesGate`.

## Test results
- `python -m pytest tests/ -q`: **208 passed, 2 skipped** (GREEN).
- 8 `test_atr_exits.py` failures (old `PositionMonitor(..., mock_advisor, ...)` 4-arg calls) were the expected fallout of the ctor signature change. Fixed by dropping the `mock_advisor` arg from the 3 constructor sites; `test_no_llm_call`'s `should_exit` assertion preserved (now trivially true — no advisor reaches the monitor).
- Smoke: `import src.alpaca_orchestrator, src.bot_thread` OK.
- grep (non-comment code): no `ExitAdvisor` / `ClaudeLLM` / `should_exit` in either trading-path file; `TrailingStop` + `HARD_STOP_PCT` retained.

## Deviations from Plan
None beyond the documented test-fixture update (Rule 3 — blocking ctor-signature mismatch in tests; fixed inline, no expectation weakening).

## Commits
- `f011569` refactor(05-01): remove ExitAdvisor + Claude-auth from alpaca_orchestrator (EXIT-01, EXIT-04)
- `0398a96` refactor(05-01): remove ExitAdvisor from bot_thread (EXIT-01)
- `8f054f0` test(05-01): drop exit_advisor arg from PositionMonitor calls (EXIT-01)

## Self-Check: PASSED
- src/alpaca_orchestrator.py — FOUND
- src/bot_thread.py — FOUND
- tests/test_atr_exits.py — FOUND
- commits f011569, 0398a96, 8f054f0 — FOUND
