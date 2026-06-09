---
phase: 4
slug: deterministic-atr-exits
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-08
---

# Phase 4 — Validation Strategy

## Test Infrastructure
| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Quick run command** | `python -m pytest tests/test_atr_exits.py -q` |
| **Full suite command** | `python -m pytest tests/ -q` |
| **Estimated runtime** | ~20s |

## Sampling Rate
- After every task commit: `python -m pytest tests/test_atr_exits.py -q`
- Before `/gsd-verify-work`: `python -m pytest tests/ -q` green (200+ baseline maintained)
- Max latency: 30s

## Validation Architecture (from RESEARCH.md)
- **EXIT-02:** ATR stop level math long & short (entry ∓ atr_mult_stop×ATR); trailing ratchets up-only (long) / down-only (short) at atr_mult_trail×ATR from water-mark. ATR computed at `profile.timeframe`.
- **EXIT-03:** max_hold close fires after `profile.max_hold_hours`; `max_hold_hours=None` (swing) never time-closes; hard_stop_pct absolute override.
- **Precedence:** first-match ladder hard_stop_pct → max_hold → ATR trail → ATR stop.
- **No-LLM:** the soft-threshold decision no longer calls `ExitAdvisor.should_exit()` — test mocks ExitAdvisor and asserts it is NOT called for the exit decision.
- **Swing parity:** SWING hard_stop_pct=-0.15 == old HARD_STOP_PCT; swing exit behavior unchanged; full suite stays green.

Nyquist floor — phase cannot pass until all green and the no-LLM assertion holds.
