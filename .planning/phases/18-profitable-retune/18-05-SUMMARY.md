---
phase: 18
plan: 05
subsystem: backtester
requirements: [TUNE-01, TUNE-03]
key-files:
  modified: [src/backtester/config.py, src/backtester/engine.py, src/backtester/cli.py]
commits: [46af5e3, 656231d]
---

# Phase 18 Plan 05: backtester knobs + fidelity guards Summary

`PhaseConfig` (frozen) gains `symbols: tuple = ()`, `quarantined: tuple = ()`,
`rsi_ceiling: float = 65.0`. The engine gains two guards around the existing confluence gate:

- `entry_allowed(sym, config.symbols, config.quarantined)` — **imported from `src.universe`**,
  the literal live gate (`bot_thread.py:146`). Not re-implemented; no `in exclude`, no
  `.replace("/","")` anywhere in `engine.py`. Without it the sweep's quarantine arm measured
  nothing.
- `signal.rsi_value >= config.rsi_ceiling → skip` — mirrors `bot_thread.py:147`'s strict `<`
  accept. Without it the backtest entered overbought setups the live bot refuses, inflating
  trade counts at exactly the confluence levels being swept.

CLI: `--min-confluence`, `--kelly-fraction`, `--symbols`, `--exclude-symbols`, applied through
the existing `dataclasses.replace` idiom; the bar-load loop now iterates `config.symbols`.

**`--kelly-fraction > 0.25` is a `parser.error` (exit 2).** Quarter-Kelly is a hardcoded ceiling
and may only go DOWN — the cell is UNRUNNABLE, not merely discouraged. Verified: `exit=2`.

The bit-identical pin (case 21, at `rsi_ceiling=inf`) passes — the plumbing changed nothing.
Case 20 passes with a strict inequality — the fidelity fix is real. `git diff` on
`src/technical_signals.py`, `src/bot_thread.py`, `src/backtester/metrics.py`,
`src/backtester/portfolio.py` is EMPTY. The confluence score was NOT "fixed" to reach 5.

## Deviations from Plan

None.

## Self-Check: PASSED — `tests/backtester/` 42 passed.
