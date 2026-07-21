---
phase: 21
slug: exit-stack-backtest-fidelity-real-retune
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-20
---

# Phase 21 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> See `21-RESEARCH.md` §"Validation Architecture" for the full behavioral test matrix.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml / pytest.ini (existing) |
| **Quick run command** | `python -m pytest tests/backtester -q` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | ~90 seconds (full), ~10s (backtester subset) |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/backtester -q`
- **After every plan wave:** Run `python -m pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green (baseline 541 passed / 29 skipped)
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 21-01-01 | 01 | 1 | TUNE-01 | — | N/A (paper-only, no live path change) | unit | `python -m pytest tests/backtester/test_exit_model.py -q` | ❌ W0 | ⬜ pending |
| 21-02-01 | 02 | 2 | TUNE-01 | — | N/A | unit | `python -m pytest tests/backtester/test_exit_parity.py -q` | ❌ W0 | ⬜ pending |
| 21-03-01 | 03 | 3 | TUNE-01 | — | N/A | integration | `python -m pytest tests/backtester/test_sweep.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky. Concrete task IDs are finalized by the planner; this map is the sampling contract.*

---

## Wave 0 Requirements

- [ ] `tests/backtester/test_exit_model.py` — the 4-rung ATR ladder fires in correct precedence (hard_stop → max_hold → ATR trailing → ATR fixed), side-aware.
- [ ] `tests/backtester/test_exit_parity.py` — shared `evaluate_exit` returns identical decisions for live and backtest given the same inputs (drift guard, D-02).
- [ ] `tests/backtester/test_sweep.py` — sweep enumerates entry×exit grid, records per-cell metrics, respects holdout lock (no peeking).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| TUNE-01 closure verdict | TUNE-01 | Requires judgment on whether a validated non-degenerate result beats the criterion on holdout | Read sweep report; confirm best train cell validated on `21-HOLDOUT.lock` set; tick TUNE-01 only if criterion met on the REAL exit model, else record honest negative. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
