# Requirements — Milestone v1.0 Day-Trading Upgrade

Derived from `docs/superpowers/specs/2026-06-08-day-trading-upgrade-design.md`.

## v1.0 Requirements

### Strategy Profile (PROFILE)
- [ ] **PROFILE-01**: A `StrategyProfile` config object bundles timeframe, scan cadence, indicator periods, exit params, max-hold, and sizing.
- [ ] **PROFILE-02**: A `SWING` preset reproduces current bot behavior byte-for-byte (bots A/B unaffected).
- [ ] **PROFILE-03**: A `DAYTRADE` preset configures 5-min bars, ~2-min scan, 1h HTF filter, ATR exits, 4–8h max-hold.
- [ ] **PROFILE-04**: The orchestrator selects its profile via `BOT_PROFILE` env (default `swing`).

### Deterministic Exits (EXIT)
- [ ] **EXIT-01**: `PositionMonitor` no longer imports or calls the MiroFish `ExitAdvisor`.
- [ ] **EXIT-02**: Exits use an ATR-scaled stop (entry − atr_mult × ATR) and an ATR-scaled trailing stop.
- [ ] **EXIT-03**: Hard-stop percentage and max-hold-duration auto-close act as absolute overrides.
- [ ] **EXIT-04**: Claude-CLI auth startup/daily checks (which only served MiroFish) are removed from the Alpaca path.

### Self-Learning Loop (LEARN)
- [ ] **LEARN-01**: Before sizing, the orchestrator calls `get_advice()`; `should_trade=False` vetoes the candidate.
- [ ] **LEARN-02**: `confidence_adjustment` from advice scales position size.
- [ ] **LEARN-03**: `get_dynamic_thresholds()` feeds min/max position % and confluence thresholds into Kelly sizing.
- [ ] **LEARN-04**: `trade_context` records intraday dimensions: time-of-day bucket, hold-minutes, volatility regime.
- [ ] **LEARN-05**: Lessons incorporate the new intraday dimensions.
- [ ] **LEARN-06**: Shadow mode logs would-be vetoes/scaling until `LEARNING_SHADOW_UNTIL_TRADES` (default 30) closed trades, then auto-applies.

### Signal Engine (SIGNAL)
- [ ] **SIGNAL-01**: `analyze()` takes indicator periods from the profile (no hardcoded 9/21/14).
- [ ] **SIGNAL-02**: `Signal` carries an `atr_value` computed from bar data.
- [ ] **SIGNAL-03**: VWAP is session-anchored (rolling intraday window) for the daytrade profile.

### Fee Gate (FEE)
- [ ] **FEE-01**: A pre-trade check skips a candidate when expected move to soft-target does not clear `2 × taker_fee + slippage_buffer`.

### Bot D Deployment (BOT)
- [ ] **BOT-01**: Bot D runs on its own Alpaca paper account (`ALPACA_API_KEY_D` / `ALPACA_SECRET_KEY_D`), `BOT_ID=D`, `BOT_PROFILE=daytrade`.
- [ ] **BOT-02**: Bot D is deployed as a separate Coolify service.
- [ ] **BOT-03**: Dashboard `KNOWN_BOTS` includes "D" and attributes its trades/equity correctly.

### Verification (VERIFY)
- [ ] **VERIFY-01**: Unit tests cover profile presets (SWING parity), ATR exit math, fee gate, learning veto/scale wiring, and session VWAP.
- [ ] **VERIFY-02**: A backtest over historical 5-min bars validates daytrade signal frequency before live paper.

## Future Requirements (deferred)
- Options v3 (calls/puts/spreads/multi-leg)
- Live-trading promotion automation

## Out of Scope
- Kalshi prediction markets (paused)
- Live trading (paper-gated this milestone)

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| PROFILE-01 | Phase 1 | Pending |
| PROFILE-02 | Phase 1 | Pending |
| PROFILE-03 | Phase 2 | Pending |
| PROFILE-04 | Phase 2 | Pending |
| SIGNAL-01 | Phase 3 | Pending |
| SIGNAL-02 | Phase 3 | Pending |
| SIGNAL-03 | Phase 3 | Pending |
| EXIT-02 | Phase 4 | Pending |
| EXIT-03 | Phase 4 | Pending |
| EXIT-01 | Phase 5 | Pending |
| EXIT-04 | Phase 5 | Pending |
| FEE-01 | Phase 6 | Pending |
| LEARN-01 | Phase 7 | Pending |
| LEARN-02 | Phase 7 | Pending |
| LEARN-03 | Phase 7 | Pending |
| LEARN-04 | Phase 8 | Pending |
| LEARN-05 | Phase 8 | Pending |
| LEARN-06 | Phase 8 | Pending |
| BOT-01 | Phase 9 | Pending |
| BOT-02 | Phase 9 | Pending |
| BOT-03 | Phase 9 | Pending |
| VERIFY-01 | Phase 10 | Pending |
| VERIFY-02 | Phase 10 | Pending |

**Coverage:** 21/21 requirements mapped — no orphans, no duplicates.
