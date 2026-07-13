# Roadmap — AI Predicted Wins

## Shipped Milestones

- **v1.0 Day-Trading Upgrade** ✅ (2026-06-15) — StrategyProfile abstraction + self-learning
  intraday Bot D, deterministic ATR exits, MiroFish removed from the trading path, closed
  learning loop, fee gate, 5-min backtest. 10/10 phases verified. Archive:
  [`milestones/v1.0-ROADMAP.md`](milestones/v1.0-ROADMAP.md).

## Backlog / Next

- Provision Bot D live infra (Alpaca paper account + Coolify service) — recipe in
  `docs/deployment/bot-d-coolify-recipe.md`.
- Options v3 (calls/puts/spreads) — separate milestone.

Start the next milestone with `/gsd-new-milestone`.

---

## Milestone v1.1 — Trustworthy P&L + Profitable Retune

**Goal:** Make bot performance measurable, then profitable. Fix trade-resolution / P&L logging so
the dashboard reconciles to real Alpaca equity, enforce the asset universe, and retune entry &
sizing on real paper data to lift win rate ≥40% and halt drawdown.

**Sequencing principle — measurement before edge.** The P&L log is untrustworthy (~10% of
submitted orders resolve), so trade-resolution + realized-P&L (Phases 11–13) come first, then
reconciliation/backfill (14), universe enforcement (15–16, parallelizable), the retune (17–18,
gated on trustworthy resolved data), reliable runtime/honest monitoring (19), and verification
(20).

**Granularity:** Fine · **Execution:** Parallel · **Verifier:** yes · **Nyquist:** yes

**Phase numbering:** continues from v1.0 (ended at Phase 10). Migrations are numbered SQL files
`dashboard/api/migrations/NNN_*.sql` (next free = `015`), NOT alembic. Live trading path is
`BotThread` + `PositionMonitor` (threads under `BotManager` in the FastAPI process); persistence
is Postgres via `src/db.py`. One Alpaca account per bot — never share.

### Phases

- [ ] **Phase 11: Order-State Resolution Engine** - Every submitted order reaches a recorded terminal state; fix the root cause of unresolved trades.
- [x] **Phase 12: Realized P&L From Fills** - Closed trades record P&L from actual fills, net of fees/slippage.
- [ ] **Phase 13: Alpaca Reconciliation Check** - Trade-log P&L is reconciled per bot against real Alpaca account P&L with a tolerance flag.
- [ ] **Phase 14: Stale-Trade Backfill & Repair** - Existing open-but-stale trades are resolved to their true terminal state from Alpaca history.
- [ ] **Phase 15: Universe Hard-Gate Enforcement** - Off-universe symbols are rejected before submission; chronic losers are quarantinable via config.
- [x] **Phase 16: Effective-Universe Dashboard Visibility** - The dashboard shows each bot's effective live universe so a leak is visible.
- [ ] **Phase 17: Per-Symbol Performance Analysis** - Resolved-trade dataset yields per-symbol/per-bot win-rate & P&L to drive the retune.
- [ ] **Phase 18: Profitable Retune (Confluence + Kelly)** - Entry threshold and quarter-Kelly sizing retuned on real data, backtest-validated, reversible via config.
- [ ] **Phase 19: Reliable Runtime & Honest Monitoring** - Thread-death detection alerts; dashboard headline reflects reconciled numbers.
- [ ] **Phase 20: Verification & E2E Reconciliation** - Test suite covers resolution/P&L/universe/reconciliation; live-data check confirms resolution rate + reconciliation within tolerance.

### Phase Details

### Phase 11: Order-State Resolution Engine
**Goal**: Every submitted order deterministically reaches and records a terminal state, and the root cause of the ~90% unresolved rate is fixed so resolution approaches ~100% going forward.
**Depends on**: Nothing (first phase of milestone)
**Requirements**: PNL-01, PNL-04
**Success Criteria** (what must be TRUE):
  1. Every submitted order transitions to a recorded terminal state — `filled`→`open` position, or `canceled`/`rejected`/`expired` — with no order silently dropped from the trade log.
  2. The root cause of unresolved trades (`order_id` discarded at submit; `PositionMonitor` only resolves against live positions) is documented and fixed in code.
  3. A run over a representative order set shows resolution rate ≈100%: `python -m pytest tests/test_order_resolution.py -q` green, and no submitted order is left non-terminal after its resolver cycle.
**Plans**: 2 plans
  - [ ] 11-01-PLAN.md — Schema migration 015 + db.py persistence (order_id/fills/pending) + AlpacaClient.get_order (foundation)
  - [ ] 11-02-PLAN.md — Wave-0 test suite + _resolve_pending_orders resolver + submission wiring (order_id/submitted, exception→rejected, dedup)

### Phase 12: Realized P&L From Fills
**Goal**: Each closed trade records realized P&L from actual fill prices and quantities, net of fees/slippage — never target/estimated prices.
**Depends on**: Phase 11
**Requirements**: PNL-02
**Success Criteria** (what must be TRUE):
  1. Closed-trade P&L in `alpaca_trades` is computed from Alpaca fill prices × filled qty minus fees, not the intended/limit price.
  2. A unit test feeds a known fill (entry, exit, fee) and asserts the stored `pnl` matches the hand-computed net figure to the cent.
  3. Migration `dashboard/api/migrations/016_realized_pnl_fees.sql` adds the `fees` column and applies cleanly via `run_migrations.py`.
**Plans**: 3 plans
- [ ] 12-01-PLAN.md — Wave 0 RED tests: test_pnl.py + test_close_pnl.py (all 10 PNL-02 cases)
- [ ] 12-02-PLAN.md — Foundation: src/pnl.py helper, migration 016 + schema mirror, fees kwarg thread
- [ ] 12-03-PLAN.md — Monitor close wiring to fills + realized_pnl + fees (GREEN cases 6-10)

### Phase 13: Alpaca Reconciliation Check
**Goal**: Summed trade-log P&L is compared per bot against Alpaca account realized P&L, and any discrepancy beyond tolerance is surfaced.
**Depends on**: Phase 12
**Requirements**: PNL-03
**Success Criteria** (what must be TRUE):
  1. A reconciliation routine computes `sum(trade-log realized P&L)` vs Alpaca account realized P&L per bot and returns the delta.
  2. When the delta exceeds a configured tolerance it is logged and a reconciliation flag is written (consumed by the dashboard in Phase 19).
  3. Running the check against the two live paper accounts prints a per-bot delta and pass/fail against tolerance.
**Plans**: 3 plans
- [ ] 13-01-PLAN.md — RED tests: tests/test_reconciliation.py, all 10 VALIDATION cases
- [ ] 13-02-PLAN.md — foundation: reconcile_bot helper + db accessors + migration 017 + schema mirror
- [ ] 13-03-PLAN.md — driver + notifier breach wrapper + scripts/reconcile.py entrypoint

### Phase 14: Stale-Trade Backfill & Repair
**Goal**: Existing open-but-stale trades are resolved to their true terminal state wherever Alpaca history allows, so the historical log becomes trustworthy.
**Depends on**: Phase 11, Phase 12
**Requirements**: PNL-05
**Success Criteria** (what must be TRUE):
  1. A one-shot backfill script walks open/stale `alpaca_trades` rows and resolves each against Alpaca order/position history, writing realized P&L via the Phase 12 path.
  2. The script is idempotent (re-running changes nothing) and reports counts: resolved / unresolvable / unchanged.
  3. After the backfill, the count of non-terminal legacy trades drops to the irreducible set (no Alpaca history) and that residue is reported.
**Plans**: 3 plans
- [ ] 14-01-PLAN.md — Wave 0 RED tests (tests/test_backfill.py, 14 PNL-05 cases) + A1-A3 alpaca-py smoke
- [ ] 14-02-PLAN.md — foundation: pure classify_order extraction + db stale-candidate/residue queries + AlpacaClient.get_closed_orders
- [ ] 14-03-PLAN.md — resolver: resolve_stale_row + backfill(apply) driver + scripts/backfill_trades.py entrypoint

### Phase 15: Universe Hard-Gate Enforcement
**Goal**: Entry is hard-gated to each bot's configured allowlist; off-universe symbols are rejected before submission and chronic losers are quarantinable without code change.
**Depends on**: Nothing (independent — parallelizable with 11–14)
**Requirements**: UNIV-01, UNIV-02
**Success Criteria** (what must be TRUE):
  1. Any symbol outside the per-bot allowlist (e.g. TRUMP, FIL) is rejected before order submission in `BotThread`, and the rejection is logged.
  2. A configurable quarantine/drop list (e.g. BTC) removes a symbol from entry consideration via `bots`-row / env config with no code change.
  3. A unit test asserts an off-universe and a quarantined symbol both fail the entry gate while an allowlisted symbol passes.
**Plans**: 3 plans (3 waves)
- [ ] 15-01-PLAN.md — RED suite: tests/test_universe.py, all 16 VALIDATION cases (UNIV-01, UNIV-02)
- [ ] 15-02-PLAN.md — src/universe.py pure gate + migration 018 quarantine column + BotConfig/API/seed plumbing (UNIV-02)
- [ ] 15-03-PLAN.md — wire the gate into all 5 entry sites; exits never gated (UNIV-01)

### Phase 16: Effective-Universe Dashboard Visibility
**Goal**: The dashboard exposes each bot's effective live universe (allowlist minus quarantine) so a leak is immediately visible.
**Depends on**: Phase 15
**Requirements**: UNIV-03
**Success Criteria** (what must be TRUE):
  1. A FastAPI route returns the effective per-bot universe (allowlist minus quarantined symbols).
  2. The dashboard renders each bot's effective universe on a bot/settings view.
  3. `curl` of the route with a Bearer token returns the correct symbol set for a bot with a quarantined symbol excluded.
**Plans**: 4 plans
- [ ] 16-01-PLAN.md — RED suite: tests/test_effective_universe.py (all 17 VALIDATION cases)
- [ ] 16-02-PLAN.md — src/effective_universe.py: pure resolver delegating to src.universe.entry_allowed
- [ ] 16-03-PLAN.md — GET /api/bots/{bot_id}/universe on bots.router + exposure/leak query
- [ ] 16-04-PLAN.md — UniversePanel.tsx in BotCard + types realignment (npm run build gate)
**UI hint**: yes

### Phase 17: Per-Symbol Performance Analysis
**Goal**: The now-trustworthy resolved-trade dataset yields per-symbol and per-bot win-rate + P&L, identifying winners and losers to drive the retune (not uniform thresholds).
**Depends on**: Phase 13, Phase 14
**Requirements**: TUNE-02
**Success Criteria** (what must be TRUE):
  1. An analysis produces per-symbol/per-bot win rate and net realized P&L from the reconciled dataset.
  2. It surfaces the winner/loser split (winners e.g. UNI, ADA, SOL, XRP, CRV; losers e.g. BTC, AVAX, TRUMP, FIL) as concrete numbers.
  3. Output is a reproducible report/command whose figures reconcile with Phase 13 totals.
**Plans**: 4 plans (3 waves)
- [ ] 17-01-PLAN.md — Wave 0: RED suite, all 18 VALIDATION cases (tests/test_symbol_stats.py)
- [ ] 17-02-PLAN.md — Wave 1: db.get_resolved_trades, one read-only parameterized SELECT
- [ ] 17-03-PLAN.md — Wave 1: src/symbol_stats.py::aggregate, pure zero-I/O aggregator
- [ ] 17-04-PLAN.md — Wave 2: scripts/symbol_report.py (no --apply) + EVIDENCE.md

### Phase 18: Profitable Retune (Confluence + Kelly)
**Goal**: Confluence entry threshold and quarter-Kelly sizing are retuned on the real resolved dataset + backtest harness, targeting win rate ≥40% and halted drawdown, and validated before going live on paper.
**Depends on**: Phase 17
**Requirements**: TUNE-01, TUNE-03
**Success Criteria** (what must be TRUE):
  1. Retuned confluence + sizing parameters are derived from the Phase 17 analysis (per-symbol informed, not uniform).
  2. The existing backtest harness run on the retuned parameters shows improved win rate (target ≥40%) and reduced drawdown vs the current config, with results recorded.
  3. The parameter change is expressed in config/env (reversible), not hardcoded; hardcoded risk invariants (max 5%/pos, quarter-Kelly 0.25, 20% DD stop) are untouched.
**Plans**: TBD

### Phase 19: Reliable Runtime & Honest Monitoring
**Goal**: Bots stay running reliably with unexpected-stop detection, and the dashboard headline P&L / win-rate reflects reconciled numbers, not the overstated trade-log sum.
**Depends on**: Phase 13
**Requirements**: RUN-01, RUN-02
**Success Criteria** (what must be TRUE):
  1. A bot thread death is detected and alerted via the existing notifier path (`BotManager` watchdog), verified by killing a thread in a test run and observing the alert.
  2. The dashboard headline P&L and win-rate read from the reconciled (Phase 13) numbers, not the raw trade-log sum.
  3. A reconciliation-flag indicator is visible on the dashboard when a bot is out of tolerance.
**Plans**: TBD
**UI hint**: yes

### Phase 20: Verification & E2E Reconciliation
**Goal**: Automated tests cover the new resolution/P&L/universe/reconciliation logic, and an end-to-end check on paper data proves resolution rate and reconciliation are within tolerance after the fix.
**Depends on**: Phase 11, Phase 12, Phase 13, Phase 15, Phase 18, Phase 19
**Requirements**: VERIFY-01, VERIFY-02
**Success Criteria** (what must be TRUE):
  1. Unit/integration tests cover order-state resolution, realized-P&L math (with fees), universe rejection, and the reconciliation check — all green in `pytest`.
  2. An end-to-end check on live/paper data shows resolution rate ≈100% and per-bot P&L reconciliation within tolerance.
  3. The full suite (existing + new) passes with zero failures.
**Plans**: TBD

### Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 11. Order-State Resolution Engine | 0/2 | Not started | - |
| 12. Realized P&L From Fills | 0/3 | Not started | - |
| 13. Alpaca Reconciliation Check | 0/3 | Not started | - |
| 14. Stale-Trade Backfill & Repair | 0/3 | Not started | - |
| 15. Universe Hard-Gate Enforcement | 0/? | Not started | - |
| 16. Effective-Universe Dashboard Visibility | 0/? | Not started | - |
| 17. Per-Symbol Performance Analysis | 0/? | Not started | - |
| 18. Profitable Retune (Confluence + Kelly) | 0/? | Not started | - |
| 19. Reliable Runtime & Honest Monitoring | 0/? | Not started | - |
| 20. Verification & E2E Reconciliation | 0/? | Not started | - |

### Requirement → Phase Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| PNL-01 | Phase 11 | Pending |
| PNL-04 | Phase 11 | Pending |
| PNL-02 | Phase 12 | Validated |
| PNL-03 | Phase 13 | Pending |
| PNL-05 | Phase 14 | Pending |
| UNIV-01 | Phase 15 | Pending |
| UNIV-02 | Phase 15 | Pending |
| UNIV-03 | Phase 16 | Validated |
| TUNE-02 | Phase 17 | Pending |
| TUNE-01 | Phase 18 | Pending |
| TUNE-03 | Phase 18 | Pending |
| RUN-01 | Phase 19 | Pending |
| RUN-02 | Phase 19 | Pending |
| VERIFY-01 | Phase 20 | Pending |
| VERIFY-02 | Phase 20 | Pending |

**Coverage:** 15/15 v1.1 requirements mapped ✓ — no orphans, no duplicates.
