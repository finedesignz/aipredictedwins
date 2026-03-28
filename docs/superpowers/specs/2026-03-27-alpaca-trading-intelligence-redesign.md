# Alpaca Trading Intelligence Redesign

**Date:** 2026-03-27
**Status:** Approved (user approved design verbally, delegated full build)

## Problem

The Alpaca crypto trading system has a 0% win rate across 10 closed trades (-$1,653.63).
Root causes:
1. MiroFish probabilities cluster at 0.50-0.55 — no actionable signal
2. Threshold was lowered from 65% to 53% to generate volume, destroying signal quality
3. Fixed 3%/8% stop-loss/take-profit triggers stops on normal noise
4. No pre-trade risk filtering (validation gate exists but is empty)
5. No ticker deduplication for open positions
6. Simulation gap math is broken for Alpaca (compares probability to dollar price)

## Design

Three-layer architecture: Technical Signal Engine → MiroFish Risk Gate → MiroFish Exit Advisor.

### Layer 1: Technical Signal Engine (`src/technical_signals.py`)

Generates buy candidates from proven quantitative indicators. No LLM calls.

**Indicators computed per asset:**
- **EMA Crossover (9/21):** Bullish when EMA9 > EMA21, bearish when below
- **ADX (14-period):** Trend strength. Only trade when ADX > 20 (confirms real trend)
- **RSI (14-period):** Oversold (<30) = buy opportunity, overbought (>70) = avoid/exit
- **Volume Spike:** Current volume > 1.5x 20-period average = institutional interest
- **VWAP:** Price above VWAP = bullish, below = bearish

**Confluence scoring:**
- Each indicator votes bullish (+1), bearish (-1), or neutral (0)
- Minimum 3 of 5 bullish votes required to generate a BUY candidate
- Score 0-5 is carried forward for position sizing (higher confluence = bigger position)

**Data source:** Alpaca `get_bars()` with `1Hour` timeframe, 50 bars (≈2 days of crypto data).

**Asset universe:** BTC/USD, ETH/USD, SOL/USD, XRP/USD, ADA/USD, AVAX/USD, DOT/USD, LINK/USD.

### Layer 2: MiroFish Risk Gate (`src/risk_gate.py`)

For each candidate that passes Layer 1, MiroFish runs a risk scenario simulation.
Uses the existing QuickSimulator infrastructure (single LLM call) with a new prompt.

**New prompt design — Risk Scenario Simulation:**
Feed MiroFish real context (price, recent bars, 24h change, volume) and ask:
"You are a panel of 5 risk analysts. Brainstorm 3-5 scenarios that could cause
this trade to lose money in the next 48 hours. Rate each scenario's likelihood
(low/medium/high) and potential impact. Then vote: PROCEED or VETO."

**Decision logic:**
- If any HIGH likelihood + HIGH impact scenario → VETO
- If 3+ analysts vote VETO → VETO
- Otherwise → PROCEED (with risk notes logged)

**All results logged to `validations` table** (finally populating it).

### Layer 3: MiroFish Exit Advisor (`src/exit_advisor.py`)

Replaces the fixed 3%/8% stop-loss/take-profit. Called by the PositionMonitor thread
when a position crosses threshold levels.

**Trigger points:**
- Position reaches -2% → ask MiroFish: "Is this dip noise or a real reversal?"
- Position reaches +5% → ask MiroFish: "Should we take profit or let it run?"
- Position reaches -4% → hard stop (no MiroFish consultation, immediate exit)
- Position reaches +10% → hard take-profit (immediate exit)

**MiroFish evaluation prompt:**
Feed current position context (entry price, current price, P&L %, time held,
recent price action, volume) and ask for one of:
- HOLD — noise, thesis intact, keep position
- TIGHTEN — move stop-loss to breakeven, risk is elevated
- EXIT — thesis broken or profit target reached, close now

**Fallback:** If MiroFish call fails or times out (10s), fall back to the hard stops (-4%/+10%).

### Orchestrator Changes (`src/alpaca_orchestrator.py`)

**Replace the signal pipeline:**
- Old: scan assets → MiroFish sim → extract probability → trade if >53%
- New: scan assets → technical signals → filter by confluence ≥3 → risk gate → trade if PROCEED

**New constants:**
```python
BULLISH_THRESHOLD = 3          # min confluence score (out of 5)
HARD_STOP_LOSS_PCT = 0.04      # -4% hard stop (no override)
HARD_TAKE_PROFIT_PCT = 0.10    # +10% hard take-profit
SOFT_STOP_PCT = 0.02           # -2% triggers MiroFish consultation
SOFT_TAKE_PROFIT_PCT = 0.05    # +5% triggers MiroFish consultation
```

**Deduplication:** Before trading, check `get_open_alpaca_positions()` — skip symbols already held.

**Position sizing:** Kelly criterion adapted for technical signals.
- `win_prob` = confluence_score / 5 (normalized)
- Quarter-Kelly with 5% max position cap (unchanged)

### Asset Universe Update (`src/alpaca_evaluator.py`)

Replace `TOP_CRYPTO_TICKERS` with:
```python
TOP_CRYPTO_TICKERS = [
    "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD",
    "ADA/USD", "AVAX/USD", "DOT/USD", "LINK/USD",
]
```

Remove meme coins (DOGE, SHIB, PEPE). Remove the tier/scoring system (no longer needed — technicals don't care about "sentiment fitness").

### Kalshi Pause

No code changes. Just don't run `python -m src.orchestrator`. Document in CLAUDE.md that Kalshi is paused.

## Files to Create

| File | Purpose |
|------|---------|
| `src/technical_signals.py` | EMA, ADX, RSI, Volume, VWAP computation + confluence scoring |
| `src/risk_gate.py` | MiroFish risk scenario simulation + PROCEED/VETO decision |
| `src/exit_advisor.py` | MiroFish exit intelligence for open positions |

## Files to Modify

| File | Changes |
|------|---------|
| `src/alpaca_orchestrator.py` | Replace signal pipeline, update constants, add dedup |
| `src/alpaca_evaluator.py` | Update asset universe, simplify evaluation |
| `requirements.txt` | Add `pandas-ta` for technical indicators |

## Files Unchanged

| File | Reason |
|------|--------|
| `src/trade_logger.py` | Already has all needed tables |
| `src/alpaca_client.py` | `get_bars()` already returns OHLCV data we need |
| `src/position_sizer.py` | Kelly sizing works, just needs different inputs |
| `src/config.py` | No new config needed (constants are hardcoded per risk rules) |
| `src/quick_simulator.py` | Risk gate wraps this with new prompts |

## Testing Strategy

1. **Unit tests for technical_signals.py** — feed known OHLCV data, verify indicator outputs
2. **Unit tests for risk_gate.py** — mock LLM responses, verify PROCEED/VETO logic
3. **Unit tests for exit_advisor.py** — mock LLM responses, verify HOLD/TIGHTEN/EXIT logic
4. **Integration test** — full pipeline with mocked Alpaca data: bars → signals → gate → decision
5. **Smoke test** — run orchestrator in evaluate mode, verify it scans and scores without trading

## Success Criteria (Paper Trading)

- Win rate > 40% over 50+ trades (current: 0%)
- Average winner > average loser (positive expectancy)
- MiroFish veto rate between 20-50% (proves it's filtering, not rubber-stamping)
- No duplicate positions on same symbol
- All trades logged with full context in validations table
