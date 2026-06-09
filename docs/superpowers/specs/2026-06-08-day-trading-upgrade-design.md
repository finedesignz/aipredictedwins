# Day-Trading Upgrade — Design Spec

**Date:** 2026-06-08
**Status:** Approved (brainstorming)
**Author:** Michael + Claude

## Goal

Upgrade AI Predicted Wins from hourly **swing** trading to intraday **day** trading on
Alpaca crypto, **drop MiroFish entirely** from the trading path, and make the bot genuinely
**self-learning** by closing the existing (currently open) learning loop.

## Context & Key Finding

The codebase already supports most of what day trading needs:

- `alpaca_orchestrator.py` is timeframe-parameterized (`scan_assets(..., timeframe=...)`).
- The entry risk gate is **already deterministic** (`RulesGate`); MiroFish's only remaining
  presence in the Alpaca path is the **Exit Advisor** in `PositionMonitor`, plus the Claude-CLI
  auth checks that exist solely to support it.
- A **full self-learning system exists** (`TradeMemory` + `LearningLoop`): it records trade
  context, generates lessons, scores strategies, and computes dynamic thresholds — but the loop
  is **OPEN**. The orchestrator calls `record_trade_context()` and `run_cycle()` yet **never
  consumes** `get_advice()` or `get_dynamic_thresholds()` to change entry/sizing decisions.
  Lessons are printed, not applied.

"Self-learning" therefore means: **close the loop** (make learning drive real decisions) and add
intraday-specific learning dimensions.

## Decisions (locked)

| Decision | Choice |
|----------|--------|
| Timeframe / cadence | **5-minute bars, scan every ~2 min** |
| Hold style | **Max-hold auto-close (4–8h configurable), no overnight** |
| Learning aggressiveness | **Shadow first (default 30 closed trades), then auto-apply** |
| Structure | **`StrategyProfile` abstraction + dedicated day-trade bot (Bot D)** |
| MiroFish | **Removed from Alpaca path; deterministic ATR exits replace Exit Advisor** |

## Architecture

### 1. `StrategyProfile` abstraction (backbone)

A frozen dataclass (new `src/strategy_profile.py`) bundling everything that differs between
trading styles:

```
StrategyProfile:
  name: str
  timeframe: str               # "5Min" | "1Hour"
  scan_interval_s: int         # 120 daytrade | 1800 swing
  bar_count: int
  htf_filter_timeframe: str    # "1Hour" daytrade | "4Hour" swing
  ema_fast, ema_slow, rsi_period, adx_period: int
  atr_period: int
  atr_mult_stop, atr_mult_trail: float
  hard_stop_pct: float
  max_hold_hours: float | None # None for swing (overnight allowed)
  kelly_fraction, max_position_pct: float
  min_confluence, min_short_confluence: int
```

Two presets: `SWING` (reproduces today's constants exactly) and `DAYTRADE`. Orchestrator selects
via `BOT_PROFILE` env (default `swing`). **Existing swing bots A/B unaffected** — they run the
`SWING` preset, which must reproduce current behavior byte-for-byte.

### 2. Drop MiroFish → deterministic ATR exits

- Remove `ExitAdvisor` import & usage from `PositionMonitor`.
- Replace soft-threshold LLM consults with **ATR-scaled stop + trail**:
  - stop = entry − (atr_mult_stop × ATR)
  - trailing stop ratchets up as price rises (atr_mult_trail × ATR below high-water mark)
  - hard stop (pct) and **max-hold auto-close** are absolute overrides
- ATR computed from existing bars (reuses true-range math already in `_adx`).
- Remove Claude-CLI auth startup/daily checks (they only served MiroFish).
- `risk_gate.py` / `exit_advisor.py` / `mirofish_client.py` remain in repo (Kalshi paused, not
  deleted) but are no longer imported by the Alpaca path.

### 3. Close the self-learning loop (core upgrade)

- **Entry filter:** before sizing each candidate, call `memory.get_advice(symbol, signal_type, …)`.
  `should_trade=False` (win-rate <30% over ≥3 trades) → veto. `confidence_adjustment` scales size.
- **Sizing:** `get_dynamic_thresholds()` feeds `min/max_position_pct` + confluence thresholds into
  `_kelly_technical`.
- **New intraday learning dimensions** added to `trade_context`: `time_of_day_bucket`,
  `hold_minutes`, `volatility_regime`. Lessons capture e.g. "5/5 SOL, US-afternoon, low-vol → 70% WR".
- **Shadow mode:** `LEARNING_SHADOW_UNTIL_TRADES` (default 30). Until that many closed trades,
  learning logs "WOULD veto / WOULD scale ×N" without acting; after, auto-applies. One env flag.

### 4. Signal engine changes (`technical_signals.py`)

- `analyze()` takes period params from the profile (no more hardcoded 9/21/14).
- Add `atr_value` to `Signal`.
- VWAP becomes **session-anchored** (rolling intraday window) — correct day-trade VWAP semantics.

### 5. Fee/slippage gate

- New deterministic pre-trade check: skip candidate if expected move to soft-target doesn't clear
  `2 × taker_fee + slippage_buffer`. Prevents intraday churn.

### 6. New Alpaca account + Coolify service

- Per one-account-per-bot hard rule: Bot D gets its own paper account
  (`ALPACA_API_KEY_D` / `ALPACA_SECRET_KEY_D`), `BOT_ID=D`, `BOT_PROFILE=daytrade`.
- Deployed as a separate Coolify service.
- Dashboard `KNOWN_BOTS` gains "D".

## Testing

- Unit: `StrategyProfile` presets (SWING reproduces current constants), ATR exit math, fee gate,
  learning veto/scale wiring (highest-risk new logic), session-VWAP.
- Backtest: reuse `scan_assets(fetch_4h=False)` on historical 5-min bars to validate signal
  frequency before live paper.
- Regression: swing-preset path must be unchanged.

## Out of Scope

- Kalshi (paused), options v3, live trading (stays paper-gated: 50+ trades, >40% WR, equity target).

## Risks

- **Overfitting** on small intraday samples → mitigated by shadow mode + min-sample gates.
- **Fee drag** at higher frequency → mitigated by fee gate.
- **Swing regression** → mitigated by SWING preset parity tests.
