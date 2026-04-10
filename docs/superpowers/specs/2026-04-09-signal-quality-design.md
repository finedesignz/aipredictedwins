# Signal Quality & Entry Discipline Fixes

**Version:** 1.0  
**Date:** 2026-04-09  
**Status:** Approved — ready for implementation  
**Authored by:** Investor Advisor sub-agent + Claude Code

---

## Background

Both bots entered all 8 crypto assets simultaneously at 01:44 UTC 2026-04-09 with RSI values of 73–81 across the board. The risk gate was bypassed because confluence was 4/5. Result: both bots are losing money in a rising crypto market (BTC benchmark +2.42%, Agent A -3.27%, Agent B -1.22%).

---

## Root Cause Analysis

### RC1 — RSI > 70 is silent, not a veto

RSI > 70 contributes 0 to the confluence score — it is treated as neutral. Overbought is not neutral; it is an active negative. At RSI=80 you are buying a crowded trade where the marginal buyer is exhausted. Combined with 4 other bullish indicators, the system scored 4/5 on every asset and entered them all.

### RC2 — HIGH_CONFLUENCE_BYPASS inverts the risk gate's purpose

The bypass logic skips the LLM risk panel when confluence = 4+/5 on the premise that "high confidence = less review needed." This is backwards. High confluence in a heated market means late entry, not high-quality entry. The gate was absent exactly when it was most needed.

### RC3 — No per-cycle position cap

The system has an 80% total exposure cap but no per-cycle entry limit. A single scan deployed 80% of capital in one correlated burst. Eight crypto assets entering simultaneously on a market-wide pump is one bet, not eight independent bets.

### RC4 — ADX has no directional confirmation

ADX measures trend *strength*, not *direction*. `ADX > 20` fires whether price is trending up or down. The +DI/-DI directional lines are unused. During distribution phases, ADX stays elevated while price peaks — contributing a false +1 to confluence.

### RC5 — Volume spike has no market context

A 1.5x volume spike on one asset signals institutional interest. A 1.5x spike across all 8 assets simultaneously signals retail FOMO. The system cannot distinguish between the two. The 01:44 UTC event was a textbook market-wide pump where every asset spiked together.

### RC6 — Soft exit thresholds are too tight for crypto

Soft thresholds of -2%/+5% are calibrated for equities. BTC's average hourly true range is 1.5–2.5%. A -2% soft stop fires within one candle's noise, triggering unnecessary LLM advisory calls and premature exits from winning trades.

### RC7 — Hard take-profit at +10% caps winners

For a 7-10%/week return target, the trades that become 20-30% moves represent the majority of P&L. Capping at +10% cuts this tail. The trailing stop should capture gains, not a fixed ceiling.

---

## Recommended Changes

### Change 1: RSI Hard Block at Entry

**File:** `src/technical_signals.py`  
**What:** Before computing confluence score, check RSI. If RSI > 72, return `None` — the asset is removed from the candidate list entirely, not scored.  
**Parameter:** RSI ceiling = **72** (not 70: a non-round number avoids crowding with other RSI-70 systems).  
**Why not soft penalty:** A -1 penalty still allows RSI=80 assets to score 3/5 and pass the MIN_CONFLUENCE=3 threshold. A hard block is the only way to guarantee zero overbought entries.

### Change 2: ADX Directional Filter (+DI > -DI)

**File:** `src/technical_signals.py`  
**What:** The ADX confluence condition becomes: `ADX > 20 AND +DI > -DI`. The +DI/-DI values must be computed from the same 14-period ADX calculation.  
**Parameter:** Same 14-period ADX, add directional check.  
**Why:** ADX > 20 on a downtrending asset still fires today. +DI > -DI confirms the trend is upward, not just strong. This costs nothing on true uptrends and eliminates false positives during distribution.  
**Implementation note:** The current `_adx()` function returns a single `float`. It must be refactored to return a tuple `(adx, plus_di, minus_di)`. The `Signal` dataclass must add `plus_di: float` and `minus_di: float` fields. All callers of `_adx()` must be updated.

### Change 3: Volume Spike Market Context Filter

**File:** `src/alpaca_orchestrator.py` (post-scan, cross-asset filter)  
**What:** After computing signals for all 8 assets, count how many have `volume_spike=True`. If 4 or more assets are simultaneously spiking, suppress the volume spike signal for all of them (set `volume_spike=False` on every signal before scoring).  
**Parameter:** Threshold = **4 assets** spiking simultaneously.  
**Why 4:** 1-3 simultaneous spikes can be coincidence. 4+ is definitionally a market-wide event, not asset-specific interest. At 01:44 UTC all 8 were spiking — this rule would have zeroed that signal across the board.  
**Implementation note:** This is a post-computation cross-asset filter, not a per-asset rule. Run the scan for all 8 assets first, then apply the suppression before selecting candidates.

### Change 4: Per-Cycle Entry Cap

**File:** `src/alpaca_orchestrator.py`  
**What:** After all filters (RSI block, volume context), sort passing candidates by: confluence score descending, then RSI ascending (lower RSI = more room to run). Take the top 3. Never open more than 3 new positions in a single cycle.  
**Parameter:** Max new positions per cycle = **3**.  
**Selection logic:** `sorted(candidates, key=lambda s: (-s.confluence_score, s.rsi_value))[:3]`

### Change 5: Remove HIGH_CONFLUENCE_BYPASS

**File:** `src/risk_gate.py`  
**What:** Delete the `HIGH_CONFLUENCE_BYPASS = 4` constant and the bypass logic. The LLM risk panel runs on every candidate trade without exception. If LLM is unavailable, fail-closed regardless of confluence score.  
**Why:** There is no valid argument for bypassing the risk gate. LLM latency (30–60s per asset) is acceptable for hourly-bar swing trading.

### Change 6: BTC Market Regime Filter

**File:** `src/alpaca_orchestrator.py`  
**What:** Before the scan loop, fetch BTC/USD bars at both 1-hour and 4-hour timeframes and compute RSI for each. If BTC RSI(1h) > 70 AND BTC RSI(4h) > 65, set regime = OVERHEATED and skip all new entries for that cycle. Log the regime status each cycle.  
**Parameters:**
- OVERHEATED: BTC RSI(1h, 14-period) > 70 AND BTC RSI(4h, 14-period) > 65
- NORMAL: all other conditions
- No OVERSOLD adjustment — do not lower confluence thresholds in oversold conditions until 100+ paper trades provide calibration data

**Implementation note:** Fetch 4h bars separately (need ~50 bars = ~200 hours of history). BTC/USD is always scanned regardless of whether it's in the asset trading universe.

### Change 7: Exit Threshold Recalibration

**File:** `src/exit_advisor.py` and constants in `src/alpaca_orchestrator.py`  

| Threshold | Current | New |
|-----------|---------|-----|
| Soft stop (LLM eval) | -2% | -3% |
| Soft take-profit (LLM eval) | +5% | +8% |
| Hard stop (immediate exit) | -4% | -5% |
| Hard take-profit (immediate exit) | +10% | **Removed** |
| Trailing stop activation | +3% | +5% |
| Trailing stop distance | 2% | 3% |
| Trail tighten above | — | +12% → tighten trail to 2% |

**Rationale:** BTC average hourly ATR is 1.5–2.5%. Former -2% soft stop was within one candle's noise. Removing the +10% hard ceiling lets the trailing stop capture large moves. A trade running to +20% now exits at ~+17% via trailing stop instead of being capped at +10%.

---

## What Is NOT Changing

| Item | Reason |
|------|--------|
| EMA crossover (9/21) | Clean, well-tested. Not the problem. |
| Kelly fraction (Bot A=0.25, Bot B=0.50) | Conservative sizing is correct. Revisit after 100+ trades. |
| 5% max per position | Right discipline. Per-cycle cap addresses concentration separately. |
| 80% total exposure cap | Sensible ceiling, will rarely be hit with new per-cycle cap. |
| Asset universe (top 8, no meme coins) | Well-chosen. Expanding before fixing signal quality is wrong. |
| Exit advisor architecture (HOLD/TIGHTEN/EXIT) | Architecture is sound. Only thresholds change. |
| Limit orders only | Non-negotiable. Slippage on market orders eats the edge. |
| MIN_CONFLUENCE = 3 (Bot A) | Keep. May feel rare with new filters — if idle rate > 60%, revisit RSI ceiling to 75, not before. |

---

## Deployment Order

Ship in two batches. Do not deploy batch 2 until batch 1 has been running 48 hours with entries occurring.

**Batch 1 (core entry quality):**
1. Change 1 — RSI hard block
2. Change 2 — ADX directional filter
3. Change 5 — Remove risk gate bypass
4. Change 4 — Per-cycle entry cap

**Batch 2 (context and exits):**
5. Change 6 — BTC regime filter
6. Change 7 — Exit threshold recalibration
7. Change 3 — Volume market context filter

---

## Success Criteria

### Leading indicators (watch immediately)

- Average RSI at entry across new trades: target **45–62**
- Simultaneous entries per cycle: target **≤ 3**
- Entries while BTC regime = OVERHEATED: target **0**
- Idle cycle rate (no valid entries): expect **30–40%** — this is healthy

### 20-trade targets

| Metric | Target |
|--------|--------|
| Win rate | > 40% |
| Entries with RSI > 72 | 0 |
| Max single-cycle drawdown | < 3% |

### 50-trade targets

| Metric | Target |
|--------|--------|
| Win rate | > 45% |
| Avg winner / avg loser | > 1.8x |
| Weekly return | 4–7% |

### 100-trade targets

| Metric | Target |
|--------|--------|
| Win rate | > 45% |
| Weekly return | 7–10% |
| Sharpe vs BTC benchmark | > 0.8 |
| Correlation with BTC | < 0.5 |

---

## Risks of the Changes

| Risk | Mitigation |
|------|-----------|
| System idles too often in bull runs | Expected and correct. If idle rate > 60%, raise RSI ceiling to 75 (not lower). |
| Per-cycle cap creates sequential laggard entries | This is actually desirable — entering laggards sequentially is better than one correlated burst. |
| ADX filter reduces trade frequency significantly | Run informal backtest on recent bars before deploying. If < 1 valid signal/day on average, reconsider ADX threshold. |
| Trailing stop exposed to gap-down reversals | Tighten trail from 3% to 2% once position is above +12%. |
| BTC regime filter misses ETH-led overheating | Known limitation. Add ETH as secondary check in a future iteration. |
| LLM risk gate inconsistency without bypass | Log all gate decisions with full input/output for ongoing prompt tuning. |
