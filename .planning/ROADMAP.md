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
- [x] **Phase 17: Per-Symbol Performance Analysis** - Resolved-trade dataset yields per-symbol/per-bot win-rate & P&L to drive the retune.
- [x] **Phase 18: Profitable Retune (Confluence + Kelly)** - Entry threshold and quarter-Kelly sizing retuned on real data, backtest-validated, reversible via config.
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
**Plans**: 7 plans (4 waves)
- [ ] 18-01-PLAN.md - Wave 0: RED suite, all 29 VALIDATION cases
- [ ] 18-02-PLAN.md - Wave 0 BLOCKER: real cached Alpaca bars, 8 symbols x 2025-10-01 -> 2026-04-30
- [ ] 18-03-PLAN.md - Wave 2: sentinel-writer fix (resolve the real exit, or NULL - never a fabricated 0.0)
- [ ] 18-04-PLAN.md - Wave 2: the win-rate denominator at all THREE sites + AIPW_DB_READONLY=1
- [ ] 18-05-PLAN.md - Wave 2: backtester CLI knobs + entry_allowed/rsi_ceiling fidelity fixes + the Kelly ceiling
- [ ] 18-06-PLAN.md - Wave 3: the 18-cell TRAIN sweep, ONE holdout run -> 18-BACKTEST.md
- [ ] 18-07-PLAN.md - Wave 4: config-only rollout via PUT /api/bots/{bot_id} (+ the API-side Kelly ceiling)

### Phase 19: Reliable Runtime & Honest Monitoring
**Goal**: Bots stay running reliably with unexpected-stop detection, and the dashboard headline P&L / win-rate reflects reconciled numbers, not the overstated trade-log sum.
**Depends on**: Phase 13
**Requirements**: RUN-01, RUN-02
**Success Criteria** (what must be TRUE):
  1. A bot thread death is detected and alerted via the existing notifier path (`BotManager` watchdog), verified by killing a thread in a test run and observing the alert.
  2. The dashboard headline P&L and win-rate read from the reconciled (Phase 13) numbers, not the raw trade-log sum.
  3. A reconciliation-flag indicator is visible on the dashboard when a bot is out of tolerance.
**Plans**: 7 plans (5 waves)
- [ ] 19-01-PLAN.md — Wave 0: RED suite. `tests/test_bot_manager.py` DOES NOT EXIST — all 29 VALIDATION cases + 8 fences. Nine cases (1, 5, 6, 13, 15, 17, 22, 23, 26) MUST fail on current main.
- [ ] 19-02-PLAN.md — Wave 2 foundation: migration 019 `runtime_heartbeat` + the `db_schema.sql` mirror (N3), the notifier wrappers, the `alerts_configured` self-check, the heartbeat readers
- [ ] 19-03-PLAN.md — Wave 3: **THE KILLER BUG** — delete `if not any_alive: return` (`bot_manager.py:189-190`) + both key predicates; keyless bot → `status='error'` + alert; ALL BOTS DOWN alert; heartbeat UPSERT; `main.py` never-started alert (N10)
- [ ] 19-04-PLAN.md — Wave 3: `RESOLVED := pnl IS NOT NULL AND pnl <> 0` at all four reader sites + the fifth (N7); delete `settings.py:65`'s `100_000.0 * len(bot_ids)` hardcode
- [ ] 19-05-PLAN.md — Wave 4: `reconcile()` per-bot guard (landmine N1) + the hourly schedule inside the watchdog tick that already exists
- [ ] 19-06-PLAN.md — Wave 4: headline = the reconciled number; `pnl_source` / `stale` / `unresolved` / `manager_alive` / `alerts_configured` surfaced through models, routes, TS types, and components
- [ ] 19-07-PLAN.md — Wave 5: evidence — RED→GREEN proof, the 8 fences, the Coolify read-only report (N4, a red herring), the 395-row HUMAN-AUTHORIZATION flag + a human checkpoint
**UI hint**: yes

### Phase 20: Verification & E2E Reconciliation
**Goal**: Automated tests cover the new resolution/P&L/universe/reconciliation logic, and an end-to-end check on paper data proves resolution rate and reconciliation are within tolerance after the fix.
**Depends on**: Phase 11, Phase 12, Phase 13, Phase 15, Phase 18, Phase 19
**Requirements**: VERIFY-01, VERIFY-02
**Success Criteria** (what must be TRUE):
  1. Unit/integration tests cover order-state resolution, realized-P&L math (with fees), universe rejection, and the reconciliation check — all green. The four clauses are already covered by phases 11-19; Phase 20 closes the four *seams* (G1 the E2E chain, G2 the paper gate, G3 the backfill's symbol normalization, G4 the reconciliation window).
  2. An end-to-end check on live/paper data shows resolution rate >= 95% and P&L reconciliation within tolerance **on the post-`T0` anchored window** — the period in which the fixed code was actually running. The **all-time** window is a fixed level offset and is provably unsatisfiable without an authorized write to the historical sentinel rows; it is reported as `legacy: true`, keeps breaching at the unchanged $25 tolerance, and is **never** made green by widening it. VERIFY-02 closes as **PARTIAL (scoped)**.
  3. The full suite (existing + new) passes with zero failures and **zero new skips** (`python -m pytest tests/ dashboard/api/tests/ -q` — baseline 488 passed / 29 skipped).
  4. `src/backfill.py`'s slash bug and `None`-coercion landmine are FIXED and TESTED, and the backfill is **left UNARMED**: a dry-run recovery-ceiling count and the exact `--apply` command are delivered; the 395 historical rows are **NOT touched**, behind a blocking human authorization.
**Plans**: 8 plans in 4 waves

Plans:
- [ ] 20-01-PLAN.md — RED: G3 (backfill slash bug + `None` door) & G2 (paper gate); CORRECTS the mis-test at `tests/test_backfill.py:199`
- [ ] 20-02-PLAN.md — RED: G4 (anchored window), the anchor/schema-mirror contract, G1 (E2E chain), the `e2e_verify.py` fences + fence self-test
- [ ] 20-03-PLAN.md — fix `src/backfill.py` (normalize both compare sites; preserve the `None` sentinel); leave it UNARMED
- [ ] 20-04-PLAN.md — `paper_trades_completed` = the canonical RESOLVED count; the gate reads worse, intended
- [ ] 20-05-PLAN.md — migration `020_reconciliation_anchor.sql` + the `src/db_schema.sql` mirror + `ON CONFLICT DO NOTHING` + `reconcile_window`
- [ ] 20-08-PLAN.md — fix the two LIVE fee-less GROSS-P&L writers, so the post-`T0` window is fee-clean by construction
- [ ] 20-06-PLAN.md — `scripts/e2e_verify.py`, SELECT-only under `AIPW_DB_READONLY=1`; prints the effective tolerance + source and fails loudly on an env override; non-zero exit on FAIL / INSUFFICIENT_SAMPLE / NO_ANCHOR
- [ ] 20-07-PLAN.md — pre-flight credential/window GATE → `20-EVIDENCE.md` + VERIFY-02 (scoped, on the ACTUAL state) + **BLOCKING** human checkpoint for the historical-row backfill

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
| 19. Reliable Runtime & Honest Monitoring | 0/7 | Planned | - |
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
| TUNE-02 | Phase 17 | Validated |
| TUNE-01 | Phase 18 | Pending |
| TUNE-03 | Phase 18 | Pending |
| RUN-01 | Phase 19 | Planned |
| RUN-02 | Phase 19 | Planned |
| VERIFY-01 | Phase 20 | Pending |
| VERIFY-02 | Phase 20 | Pending |

**Coverage:** 15/15 v1.1 requirements mapped ✓ — no orphans, no duplicates.

### Phase 21: Exit-Stack Backtest Fidelity + Real Retune (NEW — opened by Phase 18)

**Why:** Phase 18's entry-knob sweep returned a negative result its own harness could not have
falsified. The backtest engine models exits as a flat −15%/+30% barrier; the live bot runs −8% plus
an ATR trailing stop and an ATR fixed stop. Kelly cannot move win rate, so the ≥40% criterion had
exactly two possible values across all 12 live cells and was unreachable by construction. Phase 17
located the actual losses on the EXIT side — the one dimension the harness does not model. Tuning
entry thresholds was aiming at the wrong half of the system.

**Goal:** Model the live exit stack (soft/hard stops, ATR trailing, ATR fixed, max-hold, exit
advisor) in `src/backtester/engine.py` so the harness measures the strategy the bot actually runs,
then re-run the sweep over BOTH entry and exit knobs. Only then can TUNE-01 be honestly closed.

**Depends on**: Phase 18, Phase 20
**Closes**: TUNE-01 (currently PARTIAL)
