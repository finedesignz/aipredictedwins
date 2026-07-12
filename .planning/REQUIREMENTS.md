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
- [ ] **PNL-01**: Every submitted order transitions to a terminal state (filled→closed, or
      canceled/rejected/expired) and is recorded — no order is silently dropped from the trade log.
- [ ] **PNL-02**: Each closed trade records realized P&L computed from actual fill prices and
      quantities, net of fees/slippage (not target/estimated prices).
- [ ] **PNL-03**: A reconciliation check compares summed trade-log P&L against Alpaca account
      realized P&L per bot; discrepancy beyond a tolerance is surfaced (logged + dashboard flag).
- [ ] **PNL-04**: The root cause of unresolved trades (orders never re-checked / partial fills /
      monitor-thread gaps) is identified and fixed so resolution rate approaches ~100% going forward.
- [ ] **PNL-05**: A backfill/repair pass resolves existing open-but-stale trades to their true
      terminal state where Alpaca history allows.

### Universe Enforcement (UNIV)
- [ ] **UNIV-01**: Entry is hard-gated to the configured per-bot allowlist; any symbol outside it
      (e.g. TRUMP, FIL) is rejected before order submission and the rejection is logged.
- [ ] **UNIV-02**: Chronically unprofitable symbols (BTC, 0-for-12) are droppable/quarantinable via
      config without a code change.
- [ ] **UNIV-03**: The dashboard exposes the effective live universe per bot so a leak is visible.

### Profitable Retune (TUNE)
- [ ] **TUNE-01**: Confluence entry threshold and quarter-Kelly sizing are retuned using the real
      resolved-trade dataset + backtest harness, targeting win rate ≥40% and halted drawdown.
- [ ] **TUNE-02**: Per-symbol / per-bot performance analysis drives the retune (winners: UNI, ADA,
      SOL, XRP, CRV; losers: BTC, AVAX, TRUMP, FIL) rather than uniform thresholds.
- [ ] **TUNE-03**: Retuned parameters are validated against the existing backtest before going live
      on paper; the change is reversible via config/env.

### Reliable Runtime & Honest Monitoring (RUN)
- [ ] **RUN-01**: Bots restart/stay running reliably; an unexpected stop (thread death) is detected
      and alerted (existing notifier path).
- [ ] **RUN-02**: The dashboard's headline P&L / win-rate reflects reconciled (PNL-03) numbers, not
      the overstated trade-log sum.

### Verification (VERIFY)
- [ ] **VERIFY-01**: Unit/integration tests cover order-state resolution, realized-P&L math (with
      fees), universe rejection, and the reconciliation check.
- [ ] **VERIFY-02**: An end-to-end check on live/paper data shows resolution rate and P&L
      reconciliation within tolerance after the fix.

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
| UNIV-01 | Phase 15 — Universe Hard-Gate Enforcement | Pending |
| UNIV-02 | Phase 15 — Universe Hard-Gate Enforcement | Pending |
| UNIV-03 | Phase 16 — Effective-Universe Dashboard Visibility | Pending |
| TUNE-02 | Phase 17 — Per-Symbol Performance Analysis | Pending |
| TUNE-01 | Phase 18 — Profitable Retune (Confluence + Kelly) | Pending |
| TUNE-03 | Phase 18 — Profitable Retune (Confluence + Kelly) | Pending |
| RUN-01 | Phase 19 — Reliable Runtime & Honest Monitoring | Pending |
| RUN-02 | Phase 19 — Reliable Runtime & Honest Monitoring | Pending |
| VERIFY-01 | Phase 20 — Verification & E2E Reconciliation | Pending |
| VERIFY-02 | Phase 20 — Verification & E2E Reconciliation | Pending |

**Coverage:** 15/15 requirements mapped to exactly one phase — no orphans, no duplicates.
