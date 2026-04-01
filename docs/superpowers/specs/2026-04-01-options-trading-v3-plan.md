# Options Trading v3 Enhancement Plan

**Date:** 2026-04-01
**Status:** Draft
**Depends on:** v2 Technical Signal Engine (complete), Dashboard (in progress)

## Problem Statement

The AI Predicted Wins system currently trades only crypto spot positions on Alpaca. This limits the system to one instrument type (long-only crypto), one market regime strategy (swing trading with directional bets), and a single source of alpha (technical confluence scoring). Options trading on stocks and ETFs opens up defined-risk entries, hedging, income generation in flat markets, and volatility plays -- none of which are possible with spot crypto alone.

Alpaca supports options on US equities and ETFs but NOT on crypto. This means options trading introduces a new asset class (stocks/ETFs) into the system alongside the existing crypto pipeline.

## 1. Asset Universe for Options

### Tier 1 -- High-Liquidity ETFs (tight spreads, deep order books)

These are the safest starting point. Options chains are extremely liquid with penny-wide spreads.

| Symbol | Name | Why |
|--------|------|-----|
| SPY | S&P 500 ETF | Most liquid options in the world. Baseline for market-level plays. |
| QQQ | Nasdaq-100 ETF | Tech-heavy. Complements crypto correlation thesis. |
| IWM | Russell 2000 ETF | Small-cap exposure, different risk profile from SPY/QQQ. |
| TLT | 20+ Year Treasury Bond ETF | Interest rate plays. Inverse correlation to equities. |
| GLD | Gold ETF | Hedge against crypto and equity drawdowns. |

### Tier 2 -- High-Liquidity Single Stocks (after Tier 1 is proven)

These have liquid options but wider spreads and more event risk (earnings, product launches).

| Symbol | Name | Why |
|--------|------|-----|
| NVDA | NVIDIA | AI/semiconductor leader. High IV, good premium. |
| TSLA | Tesla | High retail interest, elevated IV, good premium income. |
| AAPL | Apple | Most liquid single-stock options. Lower IV but tight spreads. |
| AMZN | Amazon | High beta tech. Good for directional plays. |
| META | Meta Platforms | Social/AI thesis. Liquid options chain. |
| AMD | AMD | Semiconductor sector correlation with NVDA. |

### Tier 3 -- Sector ETFs (Phase 3, for sector rotation)

| Symbol | Name | Why |
|--------|------|-----|
| XLF | Financial Select SPDR | Bank sector exposure. |
| XLE | Energy Select SPDR | Oil/energy correlation. |
| SMH | VanEck Semiconductor ETF | Direct semiconductor exposure. |

### Configuration

Add to `src/alpaca_evaluator.py`:

```python
OPTIONS_ETF_TICKERS = ["SPY", "QQQ", "IWM", "TLT", "GLD"]
OPTIONS_STOCK_TICKERS = ["NVDA", "TSLA", "AAPL", "AMZN", "META", "AMD"]
OPTIONS_SECTOR_TICKERS = ["XLF", "XLE", "SMH"]
```

### Market Hours Constraint

Unlike crypto (24/7), equity options trade only during US market hours: 9:30 AM - 4:00 PM ET, Monday through Friday. The orchestrator must enforce this by checking market open status via `alpaca.get_account()` or a clock endpoint before scanning equity/options.

## 2. Options Strategies

### 2.1 Phase 1 Strategies -- Single-Leg (Basic Calls and Puts)

#### Long Calls -- Defined-Risk Bullish Entry

**When:** Technical signal engine produces confluence >= 3 with EMA bullish, RSI < 60 (room to run), ADX trending.

**How:** Buy a slightly in-the-money (ITM) or at-the-money (ATM) call with 30-45 days to expiration (DTE). The delta of 0.50-0.70 provides directional exposure while the maximum loss is capped at the premium paid.

**Sizing rule:** Premium paid must not exceed the dollar amount that `_kelly_technical()` would allocate for a spot position on the same signal. This keeps the risk budget consistent between crypto spot and equity options.

**Exit rules:**
- Take profit at 50-100% of premium paid (configurable).
- Stop loss at 50% of premium paid.
- Time decay exit: close if position reaches 14 DTE with < 20% profit (theta accelerates past this point).
- Hard exit at 7 DTE regardless of P&L (avoid gamma risk near expiry).

#### Long Puts -- Protective Hedge

**When:** Portfolio has significant long exposure (3+ open long positions across crypto and equities) AND VIX is below 20 (cheap insurance) AND market shows mixed signals (confluence 2 on SPY/QQQ = uncertainty).

**How:** Buy a 5-10% out-of-the-money (OTM) put on SPY or QQQ with 30-60 DTE. This is portfolio insurance, not a directional bet.

**Sizing rule:** Hedge cost must not exceed 1% of total portfolio value per month. This is a cost of doing business, not a profit center.

**Exit rules:**
- If VIX spikes above 30, take profit on the hedge (panic = expensive insurance).
- Roll forward at 14 DTE if portfolio still has significant long exposure.
- Let expire worthless if market stays calm (insurance premium consumed).

#### Cash-Secured Puts -- Income in Flat Markets

**When:** Technical signal engine shows confluence <= 2 across most assets (flat/choppy market). ADX < 20 on SPY = no trend. RSI between 40-60 = neutral.

**How:** Sell OTM puts (delta -0.20 to -0.30) on Tier 1 ETFs or Tier 2 stocks you would be willing to own. Requires cash collateral equal to 100x the strike price per contract.

**Sizing rule:** Cash secured by the put must not exceed MAX_POSITION_PCT (5%) of portfolio per trade. Total premium at risk from all short puts must not exceed 3% of portfolio.

**Exit rules:**
- Buy back at 50% profit (premium captured).
- Buy back at 200% loss (premium doubled against you).
- Roll down and out if challenged (price approaching strike with > 14 DTE).
- If assigned, the stock position enters the normal technical signal monitoring pipeline.

#### Covered Calls -- Income on Existing Holdings

**When:** The system holds a stock/ETF position from a prior options assignment or direct stock purchase, AND the technical signal for that holding shows confluence <= 2 (momentum fading).

**How:** Sell an OTM call (delta 0.20-0.30) against the existing position, 14-30 DTE.

**Sizing rule:** One call contract per 100 shares held. Never sell uncovered calls.

**Exit rules:**
- Buy back at 50% profit.
- Let expire if OTM at expiry (keep shares + premium).
- If challenged (price above strike), evaluate: roll up and out for credit, or allow assignment and collect the profit.

### 2.2 Phase 2 Strategies -- Vertical Spreads (Defined Risk, Both Directions)

#### Bull Call Spread

**When:** Confluence >= 3, bullish signal, but IV is high (making naked long calls expensive). The spread reduces cost by selling a higher-strike call.

**Structure:** Buy ATM call + sell OTM call, same expiration (30-45 DTE). Net debit trade.

**Max profit:** Difference between strikes minus net debit.
**Max loss:** Net debit paid.

**Exit rules:**
- Take profit at 50% of max profit.
- Stop loss at 50% of net debit.
- Close at 14 DTE regardless (time decay kills both legs unevenly).

#### Bear Put Spread

**When:** Confluence >= 3 bearish (inverse signals -- EMA bearish, RSI overbought > 70, VWAP bearish). This is the first time the system can profit from bearish signals, which the crypto spot pipeline cannot do.

**Structure:** Buy ATM put + sell OTM put, same expiration (30-45 DTE). Net debit trade.

**Exit rules:** Same as bull call spread.

#### Credit Spreads (Bull Put Spread / Bear Call Spread)

**When:** Flat market (confluence <= 2, ADX < 20), selling premium. Defined risk unlike naked puts.

**Structure:** Sell closer-to-money option + buy further-OTM option for protection. Net credit trade.

**Max profit:** Net credit received.
**Max loss:** Difference between strikes minus net credit.

**Exit rules:**
- Buy back at 50% of max profit (credit captured).
- Stop loss at 200% of credit received.
- Close at 7 DTE.

### 2.3 Phase 3 Strategies -- Multi-Leg (Volatility Plays)

#### Iron Condor

**When:** Low ADX (< 15) on the underlying, RSI 45-55 (dead neutral), VIX declining or stable. The market is range-bound with no catalyst expected.

**Structure:** Sell OTM put + buy further OTM put (bull put spread) + sell OTM call + buy further OTM call (bear call spread). All same expiration, 30-45 DTE.

**Wing width:** 2-5 points for ETFs, wider for stocks. Choose strikes at ~1 standard deviation from current price (roughly delta 0.15-0.20 on short strikes).

**Max profit:** Total net credit.
**Max loss:** Width of wider spread minus net credit.

**Exit rules:**
- Buy back at 50% of max profit.
- Close if underlying moves within 50% of the distance to either short strike.
- Close at 14 DTE.
- If one side is challenged, close the full position (do not leg out).

#### Straddle (Long)

**When:** Expected volatility event (earnings for stocks, major economic data release). ADX > 25 but direction unclear. Technical signals conflicting (EMA bullish but RSI overbought, or VWAP bearish but volume spiking).

**Structure:** Buy ATM call + buy ATM put, same strike, same expiration. High cost but profits from large moves in either direction.

**Sizing rule:** Total premium must not exceed 3% of portfolio. This is an expensive trade.

**Exit rules:**
- Take profit when total position value reaches 150% of premium paid.
- Stop loss at 50% of premium paid.
- Must close by 7 DTE (theta decay is catastrophic for long straddles near expiry).

#### Strangle (Long)

**When:** Same as straddle but when IV is high (ATM options expensive). Cheaper entry, requires a bigger move.

**Structure:** Buy OTM call + buy OTM put, different strikes (typically 1 strike width OTM each), same expiration. 21-45 DTE.

**Exit rules:** Same as straddle.

## 3. Technical Signal Engine Integration

### Current Architecture

The `technical_signals.py` module computes EMA(9/21), ADX(14), RSI(14), Volume Spike, and VWAP from OHLCV bars and returns a `Signal` dataclass with `confluence_score` (0-5). The `scan_assets()` function takes an `AlpacaClient` and a list of symbols.

### Required Changes

The existing signal engine is asset-agnostic -- it operates on OHLCV bar data from `alpaca_client.get_bars()`, which already handles both crypto (`BTC/USD` format) and stocks (ticker format). No changes are needed to the core indicator math.

**New function: `scan_options_candidates()`**

```python
def scan_options_candidates(
    alpaca_client,
    symbols: list[str],
    timeframe: str = "1Hour",
    bar_count: int = 50,
) -> list[OptionsSignal]:
```

This wraps `analyze()` and adds options-specific metadata:

1. **Regime classification** from the signal:
   - `confluence >= 3` + `ema_bullish` = "bullish" regime -> long calls, bull call spreads
   - `confluence >= 3` + `not ema_bullish` + `rsi > 70` = "bearish" regime -> long puts, bear put spreads
   - `confluence <= 2` + `adx < 20` = "neutral" regime -> iron condors, credit spreads, CSPs, covered calls
   - `adx > 25` + conflicting signals = "volatile" regime -> straddles, strangles

2. **IV context** (new data point):
   - Fetch the options chain from Alpaca to get current implied volatility.
   - Compare to 30-day IV rank (IVR) -- high IVR favors selling premium, low IVR favors buying premium.
   - This determines whether to use debit strategies (buy options) or credit strategies (sell options).

3. **DTE selection** based on timeframe:
   - Swing trades (1-5 day hold): 14-30 DTE options
   - Position trades (1-4 week hold): 30-60 DTE options
   - Income trades (premium decay): 30-45 DTE options

**New dataclass: `OptionsSignal`**

Extends the existing `Signal` with:
- `regime`: str -- "bullish", "bearish", "neutral", "volatile"
- `iv_rank`: float -- 0-100 percentile
- `recommended_strategies`: list[str] -- ordered list of suitable strategies
- `recommended_dte`: int -- suggested days to expiration
- `recommended_delta`: float -- target delta for strike selection

### Integration with Existing Pipeline

The options signal engine runs alongside the existing crypto pipeline, not replacing it:

```
Main Loop (alpaca_orchestrator.py):
  |
  +-- Crypto pipeline (existing, unchanged)
  |     scan_assets(crypto_tickers) -> risk_gate -> trade spots
  |
  +-- Options pipeline (new)
        scan_options_candidates(options_tickers) -> options_risk_gate -> trade options
```

Both pipelines share the same `AlpacaClient`, `TradeLogger`, and position limits. The total position count across BOTH pipelines is subject to `MAX_SIMULTANEOUS_POSITIONS`.

## 4. Position Sizing for Options

### Problem

The existing `_kelly_technical()` function sizes positions in terms of shares/units of the underlying. Options require sizing in terms of premium (cost of the option) and number of contracts.

### Greeks-Aware Kelly Criterion

**New function: `kelly_options()`** in `src/options_sizer.py`

For **debit trades** (buying options):

```
win_prob = confluence_to_win_prob(confluence_score)  # same mapping: 3->55%, 4->60%, 5->65%
b = (expected_profit_at_target / premium_paid)       # reward/risk ratio
kelly_pct = max(0, (b * win_prob - (1 - win_prob)) / b)
adjusted_pct = kelly_pct * KELLY_FRACTION            # quarter-Kelly
dollar_at_risk = portfolio_value * adjusted_pct
contracts = floor(dollar_at_risk / (premium_per_contract * 100))
```

Key differences from spot sizing:
- `dollar_at_risk` is the premium paid, which IS the max loss (defined risk).
- The reward is estimated from delta: if delta = 0.60 and we target a 3% move in the underlying, expected option gain = 0.60 * 3% * underlying_price * 100 / premium.
- Contract count must be a whole number (no fractional options).

For **credit trades** (selling options):

```
# Risk is the max loss, not the credit received
max_loss = (spread_width * 100) - net_credit
probability_of_profit = 1 - abs(short_delta)  # approximate POP
kelly_pct = max(0, (net_credit / max_loss * probability_of_profit - (1 - probability_of_profit)) / (net_credit / max_loss))
adjusted_pct = kelly_pct * KELLY_FRACTION
max_capital_at_risk = portfolio_value * adjusted_pct
contracts = floor(max_capital_at_risk / max_loss)
```

### Position Limits for Options

**New constants** (hardcoded, never override):

| Rule | Value | Rationale |
|------|-------|-----------|
| Max premium at risk per trade | 2% of portfolio | Options can go to zero; tighter than 5% spot limit |
| Max total premium at risk (all options) | 10% of portfolio | Portfolio-level options exposure cap |
| Max short premium exposure | 5% of portfolio | Selling premium has assignment risk |
| Max contracts per trade | 10 | Prevents fat-finger errors in paper mode |
| Min contract value | $50 | Avoids micro-positions with bad fill quality |
| Max spread width | $10 (ETFs), $20 (stocks) | Caps max loss per spread |

## 5. Greeks Exposure Management

### Portfolio-Level Greeks Limits

Track aggregate Greeks across all open options positions. New module: `src/greeks_monitor.py`.

| Greek | Portfolio Limit | What It Means |
|-------|-----------------|---------------|
| Net Delta | +/- 200 | Equivalent directional exposure in shares. Prevents unintentional large directional bets. |
| Net Gamma | +/- 50 | Rate of delta change. High gamma = delta shifts rapidly on price moves. |
| Net Theta | Must be > -$100/day | Maximum daily time decay cost. If net theta exceeds this, stop buying options. |
| Net Vega | +/- $500 | Exposure to IV changes. Limits loss from IV crush (e.g., post-earnings). |

### Greeks Calculation

Alpaca's options API returns Greeks (delta, gamma, theta, vega) per contract. The monitor sums them across all open positions every cycle.

**Decision gates based on Greeks:**
- If net delta exceeds limit: prefer delta-neutral strategies (iron condors, straddles) or hedging trades.
- If net theta is too negative: stop buying options, prefer credit strategies.
- If net vega is too positive: reduce long options exposure before known IV events.
- Log all Greeks violations to the `validations` table for audit.

## 6. Exit Management

### Theta Decay Monitoring

New background task in `PositionMonitor` (or a separate `OptionsMonitor` thread):

**Theta decay acceleration schedule:**
- 45+ DTE: Theta negligible. No action needed.
- 30-45 DTE: Monitor weekly. Normal position management.
- 14-30 DTE: Monitor daily. Evaluate roll-forward if position is not at target profit.
- 7-14 DTE: Theta accelerates sharply. Close or roll any position not at >= 50% of target.
- 0-7 DTE: Close ALL open options. No exceptions. Gamma risk is unacceptable for automated system.

### Roll-Forward Logic

**When to roll:**
- Position is profitable but not at target, with 14 DTE approaching.
- Credit trade is at 50% profit but you want to continue collecting premium.

**How to roll:**
1. Close the current position (buy back short, sell long).
2. Open a new position at the same strikes (or adjusted) with 30-45 DTE.
3. The roll should be done as a single order if Alpaca supports it, or as two legs within the same cycle.

**Roll rules:**
- Only roll for a net credit (credit trades) or a net debit less than remaining extrinsic value (debit trades).
- Maximum 2 rolls per position. After 2 rolls, close and move on.
- Log each roll as a separate trade in `alpaca_trades` with `notes = "roll_forward_from_{original_trade_id}"`.

### Early Exercise Decisions

Alpaca paper mode uses American-style options. The bot should NEVER exercise early. Reasons:
- Exercising discards remaining extrinsic (time) value.
- It is almost always better to sell the option than exercise it.
- The only exception is deep ITM short puts near ex-dividend date, which the bot will not encounter in paper mode.

**Hardcoded rule:** `NEVER_EXERCISE_EARLY = True`. If the system detects an approaching assignment on a short option, it should close the position before expiry rather than accept assignment (unless the cash-secured put strategy explicitly allows assignment for stock acquisition).

## 7. Risk Management

### Per-Trade Risk Rules (Hardcoded)

| Rule | Value | Enforced In |
|------|-------|-------------|
| Max premium at risk (debit trade) | 2% of portfolio | `kelly_options()` |
| Max loss on spread (credit trade) | 2% of portfolio | `kelly_options()` |
| Minimum DTE at entry | 14 days | `options_orchestrator.py` |
| Maximum DTE at entry | 60 days | `options_orchestrator.py` |
| Close all positions by 7 DTE | Mandatory | `OptionsMonitor` |
| No naked short calls | Ever | `options_orchestrator.py` |
| No naked short puts beyond CSP sizing | Ever | `options_orchestrator.py` |
| Max 2 rolls per position | Then close | `OptionsMonitor` |
| Max 10 contracts per trade | Paper mode safety | `kelly_options()` |

### Portfolio-Level Risk Rules (Hardcoded)

| Rule | Value | Enforced In |
|------|-------|-------------|
| Total options premium at risk | 10% of portfolio | Pre-trade check |
| Total short premium exposure | 5% of portfolio | Pre-trade check |
| Net delta limit | +/- 200 | `greeks_monitor.py` |
| Net theta limit | > -$100/day | `greeks_monitor.py` |
| Combined drawdown (spot + options) | 10% daily | `alpaca_orchestrator.py` |
| Correlation limit | Max 3 positions on same underlying | Pre-trade check |

### MiroFish Risk Gate for Options

The existing `RiskGate` class needs an adapted prompt for options trades. The risk scenarios are different:

**Additional risk scenarios for options:**
1. **IV Crush** -- implied volatility collapses (post-earnings, post-event), destroying long option value
2. **Assignment Risk** -- short options get assigned early (American style)
3. **Liquidity Risk** -- wide bid-ask spreads make exit expensive
4. **Pin Risk** -- underlying closes near the strike at expiration
5. **Correlation Risk** -- multiple positions on correlated underlyings all move against you simultaneously

The options risk gate prompt adds these scenario categories to the existing 5-analyst panel format.

## 8. Dashboard Additions

### New Dashboard Page: Options (`/options`)

Integrates with the dashboard spec from `2026-03-31-trading-dashboard-design.md`.

#### Options Overview Section
- **Options P&L card**: total realized + unrealized options P&L, separate from spot crypto P&L
- **Premium deployed**: total premium currently at risk across all open options
- **Win rate (options)**: separate tracking from crypto win rate
- **Greeks summary row**: Net Delta, Net Gamma, Net Theta/day, Net Vega

#### Open Options Positions Table
- Columns: Symbol, Strategy, Strike(s), Expiry, DTE, Delta, Theta, P&L ($), P&L (%), Status
- Color coding: Green for profitable, red for losing, amber for < 14 DTE (time warning)
- Expandable rows showing individual legs for multi-leg strategies

#### Expiry Calendar
- Monthly calendar view showing all options expiration dates
- Each date shows: number of expiring contracts, total premium at risk, net P&L if expired now
- Color intensity based on premium concentration (darker = more exposure on that date)
- 7-day warning highlights for upcoming expirations

#### Greeks Display Panel
- Portfolio-level Greeks gauges (semicircle gauges like speedometers)
- Delta gauge: green in center, red at limits
- Theta gauge: green near zero, red when > -$100/day
- Vega gauge: similar to delta
- Historical Greeks chart: line chart showing delta/theta/vega over time

#### Strategy Performance Breakdown
- Table showing win rate, avg P&L, and count per strategy type (long calls, CSPs, iron condors, etc.)
- Helps identify which strategies are working and which to adjust

### Modifications to Existing Pages

**Overview page (`/`):**
- Add "Options P&L" to the 4 metric cards (becomes 5, or replace Daily P&L with a combined card)
- Open positions section shows both crypto spots and options in separate tabs

**Positions page (`/positions`):**
- Add "Options" tab alongside Open/Closed
- Options positions show legs, Greeks, DTE countdown

**Trade History page (`/trades`):**
- Add `asset_type` filter: Crypto Spot / Stock Options / All
- Options trades show strategy name, strike, expiry in additional columns

### FastAPI Endpoints (New)

```
GET  /api/options/positions     -- open options positions with Greeks
GET  /api/options/history       -- closed options trades
GET  /api/options/greeks        -- portfolio-level Greeks summary
GET  /api/options/calendar      -- expiry calendar data
GET  /api/options/strategies    -- strategy performance breakdown
```

## 9. Implementation Phases

### Phase 1: Basic Calls and Puts (2-3 weeks)

**Goal:** Single-leg options trading with the same technical signal -> risk gate -> execution pipeline.

**New files to create:**

| File | Purpose |
|------|---------|
| `src/options_client.py` | Alpaca options API wrapper: chain lookup, quote, order placement, Greeks retrieval |
| `src/options_sizer.py` | Kelly sizing adapted for options premium, contract count calculation |
| `src/options_signals.py` | `OptionsSignal` dataclass, `scan_options_candidates()`, regime classification |
| `src/options_monitor.py` | Background thread for DTE tracking, theta decay alerts, auto-close at 7 DTE |

**Files to modify:**

| File | Changes |
|------|---------|
| `src/alpaca_orchestrator.py` | Add options pipeline alongside crypto pipeline. Market hours check. |
| `src/alpaca_evaluator.py` | Add `OPTIONS_ETF_TICKERS`, `OPTIONS_STOCK_TICKERS` constants |
| `src/risk_gate.py` | Add options-specific risk scenarios to prompt (IV crush, assignment, pin risk) |
| `src/trade_logger.py` | Add `options_trades` table with strike, expiry, option_type, greeks columns |
| `src/config.py` | Add `options_enabled` flag (default False), options-specific thresholds |

**Strategies implemented:** Long calls, long puts, cash-secured puts, covered calls.

**Testing:**
1. Unit tests for `options_sizer.py` with known premium/delta inputs
2. Unit tests for `options_signals.py` regime classification
3. Integration test: full pipeline from signal scan to order placement (mocked Alpaca)
4. Paper trading: run for 2 weeks targeting 20+ options trades
5. Success criteria: all orders fill correctly, DTE auto-close works, Greeks are tracked

### Phase 2: Vertical Spreads (2-3 weeks, after Phase 1 proven)

**Prerequisite:** Phase 1 has 20+ paper trades with correct execution and position management.

**New files to create:**

| File | Purpose |
|------|---------|
| `src/spread_builder.py` | Constructs spread orders: bull call, bear put, bull put (credit), bear call (credit) |

**Files to modify:**

| File | Changes |
|------|---------|
| `src/options_client.py` | Add multi-leg order submission (Alpaca's `legs` parameter) |
| `src/options_sizer.py` | Add spread sizing: max_loss calculation, credit vs debit logic |
| `src/options_signals.py` | Add spread strategy recommendations based on IV rank |
| `src/options_monitor.py` | Handle spread-specific exit logic (close both legs together) |
| `src/trade_logger.py` | Add `spread_id` field to link legs of multi-leg trades |

**Strategies implemented:** Bull call spread, bear put spread, bull put spread (credit), bear call spread (credit).

**Testing:**
1. Unit tests for `spread_builder.py` strike selection and order construction
2. Verify multi-leg orders fill correctly on Alpaca paper
3. Verify both legs close together (no orphaned legs)
4. Paper trading: 2 weeks, 15+ spread trades
5. Success criteria: correct P&L calculation, no orphaned legs, proper exit management

### Phase 3: Multi-Leg Volatility Plays (3-4 weeks, after Phase 2 proven)

**Prerequisite:** Phase 2 has 15+ paper spread trades with correct execution.

**New files to create:**

| File | Purpose |
|------|---------|
| `src/greeks_monitor.py` | Portfolio-level Greeks aggregation, limit enforcement, alerts |
| `src/volatility_analyzer.py` | IV rank calculation, IV percentile, expected move computation |
| `src/roll_manager.py` | Roll-forward logic: detect roll opportunities, construct roll orders |

**Files to modify:**

| File | Changes |
|------|---------|
| `src/spread_builder.py` | Add iron condor, straddle, strangle construction |
| `src/options_sizer.py` | Add iron condor sizing (both wings), straddle/strangle sizing |
| `src/options_signals.py` | Add "volatile" regime detection, VIX-aware strategy selection |
| `src/options_monitor.py` | Add roll-forward triggers, Greeks limit checks |
| `src/alpaca_orchestrator.py` | Wire in `greeks_monitor` as pre-trade gate |

**Strategies implemented:** Iron condors, long straddles, long strangles.

**Testing:**
1. Unit tests for iron condor construction (4 legs, correct strikes)
2. Unit tests for `greeks_monitor.py` aggregation and limit enforcement
3. Verify 4-leg orders fill correctly on Alpaca paper
4. Paper trading: 3 weeks, 10+ multi-leg trades
5. Success criteria: Greeks within limits, roll-forward works, no orphaned legs

### Phase 4: Dashboard Integration (2 weeks, parallel with Phase 2/3)

**New files to create:**

| File | Purpose |
|------|---------|
| `dashboard/api/routes/options.py` | FastAPI endpoints for options data |
| `dashboard/web/src/app/options/page.tsx` | Options dashboard page |
| `dashboard/web/src/components/options/OptionsTable.tsx` | Open options positions table |
| `dashboard/web/src/components/options/GreeksGauges.tsx` | Portfolio Greeks visualization |
| `dashboard/web/src/components/options/ExpiryCalendar.tsx` | Expiry calendar component |
| `dashboard/web/src/components/options/StrategyBreakdown.tsx` | Per-strategy P&L table |

**Files to modify:**

| File | Changes |
|------|---------|
| `dashboard/api/models.py` | Add Pydantic models for options responses |
| `dashboard/web/src/app/layout.tsx` | Add "Options" to top nav |
| `dashboard/web/src/app/page.tsx` | Add options P&L to overview KPIs |
| `dashboard/web/src/app/positions/page.tsx` | Add options tab |
| `dashboard/web/src/types/index.ts` | Add options TypeScript types |

## 10. Database Schema Changes

New table in `trade_logger.py`:

```sql
CREATE TABLE IF NOT EXISTS options_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,                    -- underlying (e.g., "SPY")
    strategy TEXT NOT NULL,                  -- "long_call", "iron_condor", etc.
    option_type TEXT,                        -- "call", "put", or "multi" for spreads
    strike REAL,                             -- strike price (NULL for multi-leg)
    expiry TEXT NOT NULL,                    -- expiration date (YYYY-MM-DD)
    dte_at_entry INTEGER NOT NULL,           -- days to expiry at trade entry
    side TEXT NOT NULL,                      -- "buy" or "sell"
    contracts INTEGER NOT NULL,              -- number of contracts
    premium_per_contract REAL NOT NULL,      -- premium paid/received per contract
    total_premium REAL NOT NULL,             -- total premium (contracts * premium * 100)
    max_loss REAL NOT NULL,                  -- maximum possible loss
    max_profit REAL,                         -- maximum possible profit (NULL for unlimited)
    delta_at_entry REAL,
    gamma_at_entry REAL,
    theta_at_entry REAL,
    vega_at_entry REAL,
    iv_at_entry REAL,                        -- implied volatility at entry
    confluence_score INTEGER,                -- technical confluence score
    regime TEXT,                             -- "bullish", "bearish", "neutral", "volatile"
    status TEXT DEFAULT 'open',              -- "open", "closed", "rolled", "assigned", "expired"
    exit_premium REAL,                       -- premium at close
    pnl REAL,
    closed_at TEXT,
    close_reason TEXT,                       -- "profit_target", "stop_loss", "dte_limit", "roll", "expiry"
    spread_id TEXT,                          -- groups legs of multi-leg strategies
    roll_count INTEGER DEFAULT 0,            -- number of times rolled forward
    rolled_from_id INTEGER,                  -- ID of the trade this was rolled from
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_options_status ON options_trades(status);
CREATE INDEX IF NOT EXISTS idx_options_symbol ON options_trades(symbol);
CREATE INDEX IF NOT EXISTS idx_options_expiry ON options_trades(expiry);
CREATE INDEX IF NOT EXISTS idx_options_spread ON options_trades(spread_id);
```

## 11. Alpaca Options API Integration

### Key Alpaca Options Endpoints

Based on alpaca-py SDK, the `options_client.py` needs to wrap:

1. **Options Chain Lookup**: `GET /v2/options/contracts` -- filter by underlying, expiry range, strike range, option type
2. **Options Quote**: `GET /v2/options/quotes/latest` -- bid/ask/last/volume/OI/Greeks
3. **Options Order**: `POST /v2/orders` with `asset_class: "options"` -- supports single and multi-leg
4. **Options Position**: `GET /v2/positions` -- includes options positions with current Greeks

### Multi-Leg Order Format

Alpaca supports multi-leg options orders via the `legs` parameter:

```python
# Example: Iron Condor
order = {
    "symbol": "SPY",
    "qty": 1,
    "type": "limit",
    "time_in_force": "day",
    "order_class": "multileg",
    "legs": [
        {"symbol": "SPY250418P00510000", "side": "sell", "ratio_qty": 1},  # short put
        {"symbol": "SPY250418P00505000", "side": "buy", "ratio_qty": 1},   # long put
        {"symbol": "SPY250418C00530000", "side": "sell", "ratio_qty": 1},  # short call
        {"symbol": "SPY250418C00535000", "side": "buy", "ratio_qty": 1},   # long call
    ],
}
```

The `options_client.py` must construct the OCC option symbol format: `{underlying}{expiry}{type}{strike}` (e.g., `SPY250418C00530000`).

## 12. Configuration Changes

Add to `src/config.py`:

```python
# --- Options (v3) ---
options_enabled: bool = False              # Master switch
options_etf_tickers: str = ""              # Comma-separated, loaded from env
options_stock_tickers: str = ""
options_max_premium_pct: float = 0.02      # 2% portfolio per trade
options_max_total_premium_pct: float = 0.10  # 10% portfolio total
options_max_short_premium_pct: float = 0.05  # 5% portfolio short exposure
options_min_dte: int = 14
options_max_dte: int = 60
options_close_dte: int = 7                 # Auto-close at 7 DTE
options_max_contracts: int = 10
options_max_rolls: int = 2
options_net_delta_limit: float = 200.0
options_net_theta_limit: float = -100.0
```

Environment variables:
```
OPTIONS_ENABLED=false
OPTIONS_ETF_TICKERS=SPY,QQQ,IWM,TLT,GLD
OPTIONS_STOCK_TICKERS=NVDA,TSLA,AAPL,AMZN,META,AMD
OPTIONS_MAX_PREMIUM_PCT=0.02
OPTIONS_MAX_TOTAL_PREMIUM_PCT=0.10
OPTIONS_MIN_DTE=14
OPTIONS_MAX_DTE=60
OPTIONS_CLOSE_DTE=7
OPTIONS_MAX_CONTRACTS=10
OPTIONS_NET_DELTA_LIMIT=200
OPTIONS_NET_THETA_LIMIT=-100
```

## 13. Success Criteria

### Phase 1 (Basic Calls/Puts)
- 20+ paper options trades placed correctly
- All orders fill on Alpaca paper
- DTE auto-close triggers at 7 DTE
- Options P&L tracked separately from crypto
- No naked short calls (ever)

### Phase 2 (Spreads)
- 15+ spread trades with both legs managed together
- Zero orphaned legs (incomplete spread closures)
- Correct max-loss calculation for all spread types
- Roll-forward works for at least 3 positions

### Phase 3 (Multi-Leg)
- 10+ multi-leg trades (iron condors, straddles)
- Portfolio Greeks tracked and within limits
- No Greeks limit violations that go undetected
- Volatility regime detection produces correct strategy recommendations

### Overall v3 Success
- Combined system (crypto spot + stock/ETF options) has positive expectancy over 100+ trades
- Options win rate > 45%
- Maximum drawdown from options never exceeds 10% of portfolio
- Dashboard shows all options data in real-time
- System handles market hours correctly (no options orders outside trading hours)

---

### Critical Files for Implementation
- `C:/Users/artic/GitHub/aipredictedwins/src/alpaca_client.py` -- Must be extended with options chain lookup, options quotes, and multi-leg order placement
- `C:/Users/artic/GitHub/aipredictedwins/src/technical_signals.py` -- Core signal engine that needs OptionsSignal extension and regime classification
- `C:/Users/artic/GitHub/aipredictedwins/src/alpaca_orchestrator.py` -- Main loop that needs a parallel options pipeline, market hours enforcement, and Greeks pre-trade gate
- `C:/Users/artic/GitHub/aipredictedwins/src/trade_logger.py` -- Database layer that needs the `options_trades` table schema and corresponding log/query methods
- `C:/Users/artic/GitHub/aipredictedwins/src/risk_gate.py` -- Risk gate prompt needs options-specific scenario categories (IV crush, assignment, pin risk, liquidity)