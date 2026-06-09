---
phase: 1
slug: strategyprofile-abstraction-swing-parity
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-08
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | none — repo-root discovery (tests/ dir) |
| **Quick run command** | `python -m pytest tests/test_strategy_profile.py -q` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_strategy_profile.py -q`
- **After every plan wave:** Run `python -m pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| (filled by planner) | — | — | PROFILE-01/02 | n/a | n/a | unit | `python -m pytest tests/test_strategy_profile.py -q` | — | pending |

---

## Validation Architecture (from RESEARCH.md)

- **SWING parity test**: assert every `SWING` field equals the current source constant/env-default.
- **Frozen test**: assert `StrategyProfile` instances are immutable (`dataclasses.FrozenInstanceError`).
- **Registry test**: `PROFILES["swing"] is SWING`.
- **Env-override-wins test**: with `MIN_CONFLUENCE`/`CYCLE_SLEEP_SECONDS` set via `monkeypatch` + module reload, the orchestrator's resolved values come from env, not the profile default — proving bots A/B are unaffected.

These four assertions are the Nyquist feedback floor: the phase cannot pass verification until all are green.
