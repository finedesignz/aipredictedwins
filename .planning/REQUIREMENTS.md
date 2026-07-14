# Requirements — Milestone v1.1 Trustworthy P&L + Profitable Retune

**Goal:** Make bot performance measurable, then profitable. Fix trade-resolution / P&L logging so
the dashboard reconciles to real Alpaca equity, enforce the asset universe, and retune entry &
sizing on real paper data to stop the drawdown and clear the 40% win-rate gate.

Derived from the 2026-07-06 live audit (see `.planning/PROJECT.md` → Current Milestone).

## Audit baseline (facts this milestone must fix)

- Only ~30 of ~300 submitted orders per bot resolve into the P&L log.
- Logged closed-trade P&L (+$1,296 A / +$112 B) contradicts real Alpaca equity ($85,655 / −14.34%;
  $96,178 / −3.82%).
- 33% win rate (20W/36L) across 60 resolved trades — below the 40% live gate.
- BTC 0-for-12 (−$479); off-universe TRUMP (−$295) and FIL (−$66) traded despite the 8-asset universe.
- Both A/B bots currently stopped.

## v1.1 Requirements

### Trade Resolution & P&L Integrity (PNL)
- [x] **PNL-01**: Every submitted order transitions to a terminal state (filled→closed, or
      canceled/rejected/expired) and is recorded — no order is silently dropped from the trade log.
- [x] **PNL-02**: Each closed trade records realized P&L computed from actual fill prices and
      quantities, net of fees/slippage (not target/estimated prices).
- [x] **PNL-03**: A reconciliation check compares summed trade-log P&L against Alpaca account
      realized P&L per bot; discrepancy beyond a tolerance is surfaced (logged + dashboard flag).
- [x] **PNL-04**: The root cause of unresolved trades (orders never re-checked / partial fills /
      monitor-thread gaps) is identified and fixed so resolution rate approaches ~100% going forward.
- [x] **PNL-05**: A backfill/repair pass resolves existing open-but-stale trades to their true
      terminal state where Alpaca history allows.

### Universe Enforcement (UNIV)
- [x] **UNIV-01**: Entry is hard-gated to the configured per-bot allowlist; any symbol outside it
      (e.g. TRUMP, FIL) is rejected before order submission and the rejection is logged.
- [x] **UNIV-02**: Chronically unprofitable symbols (BTC, 0-for-12) are droppable/quarantinable via
      config without a code change.
- [x] **UNIV-03**: The dashboard exposes the effective live universe per bot so a leak is visible.

### Profitable Retune (TUNE)
- [~] **TUNE-01** (PARTIAL — do not tick without reading this): Confluence entry threshold and
      quarter-Kelly sizing are retuned using the real resolved-trade dataset + backtest harness,
      targeting win rate ≥40% and halted drawdown.
      **What shipped:** the per-symbol quarantine (BTC/ETH/TRUMP/FIL/ARB), justified independently by
      Phase-17 real-trade evidence (BTC 2-for-23, −$1,207), plus Bot B's Kelly 0.50→0.25 and
      max_position 0.10→0.05 (both were hardcoded-risk-rule breaches, not tuning results).
      **What did NOT ship, and why:** no `min_confluence` / `kelly_fraction` change. The 12-cell sweep
      returned a NEGATIVE result that the harness could not have falsified — the backtest engine models
      exits as a flat −15%/+30% barrier while the live bot runs −8% plus an ATR trailing stop and an ATR
      fixed stop. Kelly cannot move win rate, so criterion 2 (win_rate ≥40%) produced exactly two
      distinct values across all 12 live cells (3.23%, 0.00%) — unreachable by construction, 12 FAILs
      and zero information. Phase 17 located the actual losses on the EXIT side, precisely the dimension
      the harness does not model. Tuning entry knobs was aiming at the wrong half of the system.
      **To close this properly:** a new phase that models the live exit stack in the backtester, then
      re-runs the sweep. Tracked in ROADMAP. See `.planning/phases/18-profitable-retune/18-BACKTEST.md`.
- [x] **TUNE-02**: Per-symbol / per-bot performance analysis drives the retune (winners: UNI, ADA,
      SOL, XRP, CRV; losers: BTC, AVAX, TRUMP, FIL) rather than uniform thresholds.
- [x] **TUNE-03**: Retuned parameters are validated against the existing backtest before going live
      on paper; the change is reversible via config/env.

### Reliable Runtime & Honest Monitoring (RUN)
- [ ] **RUN-01**: Bots restart/stay running reliably; an unexpected stop (thread death) is detected
      and alerted (existing notifier path).
- [ ] **RUN-02**: The dashboard's headline P&L / win-rate reflects reconciled (PNL-03) numbers, not
      the overstated trade-log sum.

### Verification (VERIFY)
- [x] **VERIFY-01**: Unit/integration tests cover order-state resolution, realized-P&L math (with
      fees), universe rejection, and the reconciliation check.
      All four clauses covered, plus the four Phase-20 seams (G1 e2e reconciliation, G2 paper gate,
      G3 backfill, G4 windowed reconciliation), plus the two live GROSS-P&L writers now recording fees
      (`tests/test_gross_pnl_writers.py`) — which is this requirement's own "with fees" clause. Suite:
      541 passed / 29 skipped (no new skips). Traceability matrix:
      `.planning/phases/20-verification-e2e/20-EVIDENCE.md` §3.
- [~] **VERIFY-02** (PARTIAL — scoped; do not tick without reading this): An end-to-end check on
      live/paper data shows resolution rate and P&L reconciliation within tolerance after the fix.
      **Measured against prod 2026-07-14** (`scripts/e2e_verify.py`, SELECT-only, tolerance $25 /
      0.005 both from `default`, `tolerance_override: false`). Evidence: `20-EVIDENCE.md`.

      **The ALL-TIME window is NOT achieved and is provably NOT achievable.** Both sides of
      `reconcile_bot` are cumulative-since-inception. The 395 fabricated-zero rows contribute **exactly
      zero** to `trade_log_pnl`, while Alpaca's `equity − starting_equity` **already contains their real
      outcomes**. The delta is therefore a **FIXED LEVEL OFFSET** — every future perfectly-recorded trade
      adds the same amount to *both* sides and leaves it intact. Measured: **Bot A $8,720.31, Bot B
      $1,610.22, Bot C $9,497.07** (all breaching the unchanged $25 tolerance). Bot A's figure is
      consistent with the original audit — the log said +$1,296 while the account was −14.34%.
      `abs(delta) <= $25` all-time is **unreachable forever** unless those rows are repaired.
      **And the shipped backfill cannot repair them:** all 395 are `status='closed'` with
      `order_id IS NULL`, while the backfill only selects `open`/`submitted` rows *with* an `order_id`
      — dry-run recovery ceiling **0 of 395 for every bot** (Alpaca answered; no `positions_unavailable`,
      so these are real zeros). Closing the offset would need a new `(symbol, qty, timestamp)`-matching
      mechanism that does not exist. **The backfill was NOT run; the historical rows are untouched.**

      **The ANCHORED POST-T0 WINDOW is the honest path — and it OPENED TODAY.** `T0` was written by the
      manager's reconcile tick at **2026-07-14 07:18 UTC**, in the same deploy that fixed the two live
      gross-P&L writers, so the window is fee-clean and sentinel-free **by construction**. Every bot
      currently reports **`INSUFFICIENT_SAMPLE` (0 resolved post-T0 trades; `MIN_WINDOW_SAMPLE` = 20)**.
      **`INSUFFICIENT_SAMPLE` IS NOT A PASS.** The window has not earned a verdict, and none is claimed.
      Nothing was widened and no retry was run to manufacture a sample.
      **VERIFY-02 stays OPEN on the windowed clause** until a dated follow-up run returns PASS — not
      before **2026-07-28** (≥20 resolved trades per bot):
      `python scripts/e2e_verify.py --json`   (exit 0 == every enabled bot's window reconciles)

      **What IS measured today:** the all-time reconciliation (breaching, `legacy: true`), the legacy
      offset per bot, the recovery ceiling (0/395), and the paper gate — which now reads
      **655 total rows → 260 resolved** (delta exactly −395, the sentinel count), `win_rate 34.6`
      (below the 40% gate). **The gate reads worse because it is now counting the truth. It is NOT to be
      tuned back.**

## Out of Scope
- Kalshi prediction markets (paused).
- Options v3 (calls/puts/spreads — separate milestone).
- Promotion to live trading (stays paper-gated: 50+ trades, >40% win rate, equity target).
- Net-new strategies or assets beyond the existing universe.

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| PNL-01 | Phase 11 — Order-State Resolution Engine | Validated |
| PNL-04 | Phase 11 — Order-State Resolution Engine | Validated |
| PNL-02 | Phase 12 — Realized P&L From Fills | Validated |
| PNL-03 | Phase 13 — Alpaca Reconciliation Check | Validated |
| PNL-05 | Phase 14 — Stale-Trade Backfill & Repair | Validated |
| UNIV-01 | Phase 15 — Universe Hard-Gate Enforcement | Validated |
| UNIV-02 | Phase 15 — Universe Hard-Gate Enforcement | Validated |
| UNIV-03 | Phase 16 — Effective-Universe Dashboard Visibility | Validated |
| TUNE-02 | Phase 17 — Per-Symbol Performance Analysis | Validated |
| TUNE-01 | Phase 18 — Profitable Retune (Confluence + Kelly) | **PARTIAL** — quarantine + risk-rule fixes shipped; entry-knob retune blocked by backtest exit-model fidelity gap (see requirement text) |
| TUNE-03 | Phase 18 — Profitable Retune (Confluence + Kelly) | Validated |
| RUN-01 | Phase 19 — Reliable Runtime & Honest Monitoring | Pending |
| RUN-02 | Phase 19 — Reliable Runtime & Honest Monitoring | Pending |
| VERIFY-01 | Phase 20 — Verification & E2E Reconciliation | Validated |
| VERIFY-02 | Phase 20 — Verification & E2E Reconciliation | **PARTIAL (scoped)** — all-time reconciliation provably unachievable (fixed level offset from 395 unrepairable rows); anchored post-T0 window opened 2026-07-14 07:18 UTC and reports INSUFFICIENT_SAMPLE (0/20 per bot) — NOT a pass. Open until a dated follow-up `e2e_verify` run passes (see requirement text) |

**Coverage:** 15/15 requirements mapped to exactly one phase — no orphans, no duplicates.
