# Roadmap — Milestone v1.0 Day-Trading Upgrade

**Milestone CODE:** `DAY`
**Granularity:** Fine (10 phases)
**Coverage:** 21/21 requirements mapped
**Spec:** `docs/superpowers/specs/2026-06-08-day-trading-upgrade-design.md`

Brownfield upgrade to an existing Python Alpaca crypto bot. The `StrategyProfile` abstraction
is the backbone; SWING-preset parity (PROFILE-02) is locked before any behavior change so the
live swing bots (A/B) never regress. Live trading path is `BotThread` + its `PositionMonitor`
(the reference `alpaca_orchestrator.py` shares the same helpers) — phases that touch "the
orchestrator" / "PositionMonitor" apply to both the shared helpers and `BotThread`.

> Migrations: this project uses numbered SQL (`dashboard/api/migrations/NNN_*.sql`), NOT alembic.
> Any schema change in a phase uses the next `NNN_day_<slug>.sql` number. No alembic revision ids.

## Phases

- [x] **Phase 1: StrategyProfile Abstraction + SWING Parity** - Frozen profile dataclass with SWING preset reproducing current behavior byte-for-byte (completed 2026-06-09)
- [x] **Phase 2: DAYTRADE Preset + Profile Selection** - DAYTRADE preset and `BOT_PROFILE` env wiring (default swing) (completed 2026-06-09)
- [ ] **Phase 3: Parameterized Signal Engine + ATR + Session VWAP** - Profile-driven indicator periods, ATR on Signal, session-anchored VWAP
- [ ] **Phase 4: Deterministic ATR Exits** - ATR-scaled stop + trailing stop with hard-stop and max-hold overrides
- [ ] **Phase 5: MiroFish Removal from Alpaca Path** - Drop ExitAdvisor + Claude-CLI auth checks from the trading path
- [ ] **Phase 6: Fee/Slippage Pre-Trade Gate** - Skip candidates whose move-to-target can't clear round-trip fees
- [ ] **Phase 7: Close the Self-Learning Loop (Entry + Sizing)** - Wire `get_advice()` veto + `get_dynamic_thresholds()` into entry and Kelly sizing
- [ ] **Phase 8: Intraday Learning Dimensions + Shadow Mode** - Time-of-day/hold/volatility dimensions and shadow→auto gate
- [ ] **Phase 9: Bot D Deployment** - New paper account, daytrade profile, Coolify service, dashboard attribution
- [ ] **Phase 10: Verification + Backtest** - Unit tests for new logic + 5-min backtest validating signal frequency

## Phase Details

### Phase 1: StrategyProfile Abstraction + SWING Parity
**Goal**: A profile config object exists and the SWING preset reproduces today's swing behavior exactly, with bots A/B unaffected.
**Depends on**: Nothing (first phase, backbone)
**Requirements**: PROFILE-01, PROFILE-02
**Success Criteria** (what must be TRUE):
  1. A frozen `StrategyProfile` dataclass (`src/strategy_profile.py`) bundles timeframe, scan cadence, indicator periods, exit params, max-hold, and sizing.
  2. A `SWING` preset carries the exact current constants (EMA 9/21, RSI/ADX 14, current stops, sizing, confluence thresholds, no max-hold).
  3. Running the existing swing path through the SWING preset produces byte-for-byte identical decisions versus the pre-change code (parity check passes).
  4. Bots A and B continue trading unchanged on their own accounts.
**Plans**: 1 plan
- [x] 01-01-PLAN.md — StrategyProfile module + SWING preset + parity tests + minimal orchestrator wiring

### Phase 2: DAYTRADE Preset + Profile Selection
**Goal**: A DAYTRADE preset exists and the orchestrator/BotThread selects its profile from `BOT_PROFILE` (default swing).
**Depends on**: Phase 1
**Requirements**: PROFILE-03, PROFILE-04
**Success Criteria** (what must be TRUE):
  1. A `DAYTRADE` preset configures 5-min bars, ~2-min scan, 1h HTF filter, ATR exit params, and a 4–8h max-hold.
  2. The trading entry point reads `BOT_PROFILE` env and loads the matching preset; unset/`swing` yields the SWING preset.
  3. An unknown `BOT_PROFILE` value fails fast (no silent fallback to wrong constants).
**Plans**: 1 plan
- [x] 02-01-PLAN.md — DAYTRADE preset + registry, BOT_PROFILE selection at startup, banner line, tests

### Phase 3: Parameterized Signal Engine + ATR + Session VWAP
**Goal**: The signal engine takes its periods from the active profile, emits an ATR value, and uses session-anchored VWAP for daytrade.
**Depends on**: Phase 2
**Requirements**: SIGNAL-01, SIGNAL-02, SIGNAL-03
**Success Criteria** (what must be TRUE):
  1. `analyze()` reads EMA/RSI/ADX periods from the profile — no hardcoded 9/21/14 remain.
  2. `Signal` carries an `atr_value` computed from bar data (reusing the existing true-range math).
  3. For the daytrade profile, VWAP is session-anchored (rolling intraday window); the swing profile's VWAP semantics are unchanged.
  4. SWING-preset signal output remains identical to Phase 1 parity baseline.
**Plans**: 2 plans
- [ ] 03-01-PLAN.md — Parameterize analyze()/scan_assets periods, add _atr + atr_value, session-anchored VWAP, parity + new tests
- [ ] 03-02-PLAN.md — Thread profile through 3 scan_assets call-sites; remediate 6 stale-threshold tests; full suite green

### Phase 4: Deterministic ATR Exits
**Goal**: Position exits are driven by deterministic ATR math plus absolute overrides, no LLM consult.
**Depends on**: Phase 3 (needs `atr_value` on Signal)
**Requirements**: EXIT-02, EXIT-03
**Success Criteria** (what must be TRUE):
  1. The monitor computes an ATR-scaled stop (entry − atr_mult_stop × ATR) and an ATR-scaled trailing stop that ratchets up below the high-water mark.
  2. Hard-stop percentage triggers an immediate close regardless of ATR state.
  3. Max-hold-duration auto-close exits a daytrade position once `max_hold_hours` elapses; swing (max-hold None) is never force-closed by time.
  4. ATR exit math is exercised by a unit test (covered fully in Phase 10).
**Plans**: TBD

### Phase 5: MiroFish Removal from Alpaca Path
**Goal**: MiroFish exit advisory and its Claude-CLI auth scaffolding no longer run in the Alpaca trading path.
**Depends on**: Phase 4 (ATR exits must replace ExitAdvisor before removing it)
**Requirements**: EXIT-01, EXIT-04
**Success Criteria** (what must be TRUE):
  1. `PositionMonitor` (and `BotThread`) no longer import or call the MiroFish `ExitAdvisor`.
  2. Claude-CLI auth startup/daily health checks that only served MiroFish are removed from the Alpaca path.
  3. `risk_gate.py` / `exit_advisor.py` / `mirofish_client.py` remain in the repo (Kalshi paused) but are unreferenced by the Alpaca path.
  4. A paper/evaluate run completes with no Claude-CLI auth dependency for exits.
**Plans**: TBD

### Phase 6: Fee/Slippage Pre-Trade Gate
**Goal**: Candidates that can't clear round-trip fees before the soft target are skipped.
**Depends on**: Phase 3 (needs profile + ATR/target context)
**Requirements**: FEE-01
**Success Criteria** (what must be TRUE):
  1. A deterministic pre-trade check skips a candidate when expected move to soft-target does not exceed `2 × taker_fee + slippage_buffer`.
  2. The check runs before sizing and is logged when it skips a candidate.
  3. Swing candidates with wide targets are unaffected (gate only bites on thin intraday moves).
**Plans**: TBD

### Phase 7: Close the Self-Learning Loop (Entry + Sizing)
**Goal**: Learning advice and dynamic thresholds drive real entry and sizing decisions instead of being printed and ignored.
**Depends on**: Phase 6
**Requirements**: LEARN-01, LEARN-02, LEARN-03
**Success Criteria** (what must be TRUE):
  1. Before sizing each candidate the orchestrator calls `get_advice()`; `should_trade=False` vetoes the candidate.
  2. `confidence_adjustment` from advice scales the computed position size.
  3. `get_dynamic_thresholds()` feeds min/max position % and confluence thresholds into `_kelly_technical`.
  4. With no learning history, behavior matches the pre-loop baseline (no veto, neutral scaling).
**Plans**: TBD

### Phase 8: Intraday Learning Dimensions + Shadow Mode
**Goal**: Learning records intraday dimensions and only auto-applies after enough closed trades.
**Depends on**: Phase 7
**Requirements**: LEARN-04, LEARN-05, LEARN-06
**Success Criteria** (what must be TRUE):
  1. `trade_context` records time-of-day bucket, hold-minutes, and volatility regime for each trade.
  2. Generated lessons incorporate the new intraday dimensions (e.g. "5/5 SOL, US-afternoon, low-vol → 70% WR").
  3. Until `LEARNING_SHADOW_UNTIL_TRADES` (default 30) closed trades, learning logs "WOULD veto / WOULD scale ×N" without acting; after the threshold it auto-applies.
  4. The shadow→auto transition is controlled by a single env flag.
**Plans**: TBD

### Phase 9: Bot D Deployment
**Goal**: Bot D runs the daytrade profile on its own account and is attributed correctly in the dashboard.
**Depends on**: Phase 8 (full daytrade behavior ready)
**Requirements**: BOT-01, BOT-02, BOT-03
**Success Criteria** (what must be TRUE):
  1. Bot D runs on its own Alpaca paper account (`ALPACA_API_KEY_D`/`ALPACA_SECRET_KEY_D`), `BOT_ID=D`, `BOT_PROFILE=daytrade` (own `bots` row — never shares an account).
  2. Bot D is deployed as a separate Coolify service and its thread is spawned/revived by BotManager.
  3. Dashboard `KNOWN_BOTS` includes "D" and attributes its trades and equity curve correctly.
**Plans**: TBD
**UI hint**: yes

### Phase 10: Verification + Backtest
**Goal**: New money-touching logic is unit-tested and daytrade signal frequency is validated on historical bars before live paper.
**Depends on**: Phase 9
**Requirements**: VERIFY-01, VERIFY-02
**Success Criteria** (what must be TRUE):
  1. Unit tests cover SWING preset parity, ATR exit math, the fee gate, learning veto/scale wiring, and session VWAP, and pass under `pytest tests/`.
  2. A backtest over historical 5-min bars (`scan_assets(fetch_4h=False)` path) reports daytrade signal frequency and a STRONG/MARGINAL/NO-EDGE verdict.
  3. The swing-preset regression path remains green (no behavior drift).
**Plans**: TBD

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. StrategyProfile + SWING Parity | 1/1 | Complete    | 2026-06-09 |
| 2. DAYTRADE Preset + Selection | 1/1 | Complete    | 2026-06-09 |
| 3. Signal Engine + ATR + Session VWAP | 0/2 | Planned     | - |
| 4. Deterministic ATR Exits | 0/0 | Not started | - |
| 5. MiroFish Removal | 0/0 | Not started | - |
| 6. Fee/Slippage Gate | 0/0 | Not started | - |
| 7. Self-Learning Loop (Entry+Sizing) | 0/0 | Not started | - |
| 8. Intraday Dimensions + Shadow | 0/0 | Not started | - |
| 9. Bot D Deployment | 0/0 | Not started | - |
| 10. Verification + Backtest | 0/0 | Not started | - |
