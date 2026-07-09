---
phase: 11
slug: order-state-resolution-engine
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-09
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml / pytest.ini (existing suite, 279 tests green) |
| **Quick run command** | `python -m pytest tests/test_order_resolution.py -q` |
| **Full suite command** | `python -m pytest -q` |
| **Estimated runtime** | ~30–60s quick; full suite minutes |

---

## Sampling Rate

- **After every task commit:** Run the quick command.
- **After every plan wave:** Run the full suite.
- **Before `/gsd-verify-work`:** Full suite must be green.
- **Max feedback latency:** ~60 seconds.

---

## Validation Architecture (from 11-RESEARCH.md)

Order-state machine to prove (PNL-01, PNL-04). All cases live in
`tests/test_order_resolution.py` (Wave 0 creates the file):

| # | Case | Requirement | Proves |
|---|------|-------------|--------|
| 1 | submit → row created `status='submitted'` with `order_id` persisted | PNL-01 | order_id captured at submit |
| 2 | poll order `filled` → row becomes held position (`status='open'`) | PNL-04 | fill → position |
| 3 | poll order `canceled` (0 filled) → terminal `canceled`, pnl=0, not `open`, not `closed` | PNL-01 | unfilled resolves, no stat pollution |
| 4 | poll order `rejected` → terminal `rejected`, pnl=0 | PNL-01 | rejection recorded, not dropped |
| 5 | poll order `expired` → terminal `expired`, pnl=0 | PNL-01 | expiry resolves |
| 6 | partial-fill-then-`canceled` (filled_qty>0) → kept as `open` position | PNL-04 | partial fill is a real position |
| 7 | unfilled limit past timeout → cancel_order called + row terminalized | PNL-04 | timeout path frees capital + resolves |
| 8 | resolution is idempotent — re-poll an already-terminal row is a no-op | PNL-04 | crash-safe/restart re-poll |
| 9 | restart re-poll: pending `submitted` rows re-resolved from DB on startup | PNL-04 | no orphan on process restart |

Wave 0 gap: `tests/test_order_resolution.py` does not exist yet — created before implementation tasks.

---

## Nyquist Compliance

- Every requirement (PNL-01, PNL-04) maps to ≥1 automated case above.
- `nyquist_compliant` flips to true when all 9 cases exist and pass.
