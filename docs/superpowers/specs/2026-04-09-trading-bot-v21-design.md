# Trading Bot v2.1 — Design Spec

**Date:** 2026-04-09  
**Status:** Approved, ready for implementation plan  
**Owner:** artic  

---

## Problem

Bot v2.0 produces flat or negative returns across 20+ days of paper trading. Root causes identified from A/B data and code review:

1. **Risk gate is counterproductive.** Bot A (gate ON) is at $97,127; Bot B (gate OFF, live since 2026-04-01) is at $99,533 and hit $101,128 on 2026-04-08. Monitor P&L delta: $2,027 in Bot B's favor. The gate vetoed ETH on 2026-04-09 while Bot B held it profitably. Binary PROCEED/VETO authority is the failure mode — not LLM context itself.

2. **Fixed exit thresholds are wrong for crypto volatility.** A −2% soft stop and −4% hard stop are meaningless when BTC moves 3% in an hour. We're exiting normal pullbacks as losses.

3. **Flat confluence scoring misses signal strength.** Five binary indicators count to a flat integer. A barely-crossed EMA is worth the same as an ADX of 80. Sizing has no information about signal quality, only quantity.

4. **No backtesting framework.** Every change is deployed directly to paper trading. We cannot validate hypotheses, tune parameters, or compare approaches without burning real time and money.

5. **No correlation awareness.** All 8 assets in the universe are crypto — they move together. The bot can stack 5 correlated longs and take on 5× the effective risk it thinks it has.

---

## Goals

1. Ship a backtesting framework that validates every change before deployment.
2. Retire the binary risk gate; replace with a bounded advisory layer (max 30% Kelly reduction).
3. Replace fixed stop/take-profit percentages with ATR-based dynamic thresholds.
4. Replace flat confluence scoring with a weighted, continuous signal ensemble.
5. Add volatility-adjusted Kelly sizing.
6. Add correlation-aware position limits.
7. Add re-entry cooldown management.
8. Add regime detection (trending vs. mean-reverting) to adjust strategy weights.
9. Add bounded sentiment signal from Alpaca news.
10. Formalize the Bot A/B canary process with automated promotion gate checks.

---

## Non-Goals

- Options/spreads/multi-leg trading (separate spec: `project_options_v3_plan.md`).
- Postgres migration / dashboard changes (separate spec: `2026-04-09-postgres-ab-dashboard-design.md`).
- Live trading enablement (paper-only gate unchanged: 50+ trades, >40% win rate, $100k equity).
- Kalshi orchestrator (still paused).
- Switching from Claude CLI to direct Anthropic API (OAuth-only constraint stands).

---

## Architecture Overview

v2.1 is an evolutionary upgrade of v2.0. All changes are additive or replacing internal implementations. The external contract (Alpaca paper API, same asset universe, same Coolify deployment) is unchanged.

### New files

```
src/pipeline_state.py       # Phase 0 — immutable stage contract
src/backtester/             # Phase 0 — validation framework
  __init__.py
  engine.py
  data_loader.py
  portfolio.py
  metrics.py
  report.py
  cli.py
src/volatility.py           # Phase 2 — ATR, annualized vol, vol percentile
src/correlation.py          # Phase 3 — rolling correlation matrix
src/research_panel.py       # Phase 1 — replaces risk_gate.py (advisory, bounded)
src/sentiment_signal.py     # Phase 4 — Alpaca news + LLM classification
src/reentry_manager.py      # Phase 4 — exit cooldown tracking
scripts/promote_phase.py    # Phase 5 — canary promotion gate checker
```

### Modified files

```
src/technical_signals.py    → src/technical_signals/ package (Phase 3)
src/exit_advisor.py         upgraded: richer context, ATR thresholds, sub-agent (Phase 1+2)
src/alpaca_orchestrator.py  refactored: PipelineState stages, new components wired in
src/risk_gate.py            call removed from pipeline (Phase 1); file kept for history
```

### Unchanged files

```
src/claude_llm.py           no changes
src/trade_logger.py         no changes (Postgres migration is a separate spec)
src/trade_memory.py         no changes
```

---

## Phase 0 — Backtester + PipelineState Refactor

**Purpose:** Mandatory validation gate before any behavior change ships. Also cleans up the 881-line orchestrator into well-bounded pipeline stages.

### PipelineState

`src/pipeline_state.py` — immutable dataclass flowing through all pipeline stages.

```python
@dataclass(frozen=True)
class PipelineState:
    # Inputs
    symbol: str
    bars: tuple[dict, ...]      # tuple, not list — required for frozen dataclass
    signal: Signal | None = None

    # Stage outputs (populated as pipeline progresses)
    # Types use Any in Phase 0; upgraded to ResearchOpinion/SentimentResult
    # once those modules exist (Phase 1 / Phase 4 respectively)
    research_opinion: Any | None = None
    sentiment_result: Any | None = None
    correlation_penalty: float = 0.0
    kelly_fraction: float = 0.0
    order_id: str | None = None
    skipped_reason: str | None = None

    def with_updates(self, **kwargs) -> "PipelineState":
        return dataclasses.replace(self, **kwargs)
```

Each stage in the orchestrator consumes a `PipelineState` and returns a new one with its outputs populated. No stage mutates the object. Skipped trades carry a `skipped_reason` for logging and backtester replay.

### Backtester Architecture

`src/backtester/` — offline replay engine. Reads historical bars from cached Alpaca data (or fixture files for CI), replays the trading pipeline, and produces metrics.

**Key design decisions:**

- **LLM replay cache:** all LLM calls are cached by `sha256(full_prompt_string)` in `data/llm_cache.db`. The backtester replays prompts from cache; live cache entries accumulate during paper trading. Flag `--no-cache` bypasses cache (for fresh runs); `--cache-stage N` uses only the cache entries from a specific phase deployment window.
- **Walk-forward split:** nominal train window = Oct 2025 – Jan 2026; holdout = Feb 2026 – present. However, because the bots only started trading in March 2026, the LLM call cache will be empty before that date. **Effective Phase 0 train window:** March 2026 only (first ~3 weeks of live paper trading). As the cache warms up, the full 6-month window becomes usable for Phase 3+ tuning. All parameter tuning is done on the train window only. Holdout is touched once per phase to validate the gate assertion. No re-tuning on holdout data.
- **PhaseConfig feature flags:** one `PhaseConfig` dataclass controls which features are active. Each phase has a named preset. `--compare-phases 0,1,2,3,4` runs all phases head-to-head on the same data.

**CLI:**

```bash
# Run a single phase on holdout
python -m src.backtester --phase 2 --holdout

# Compare all phases
python -m src.backtester --compare-phases 0,1,2,3,4 \
  --train 2025-10-01:2026-01-31 \
  --holdout 2026-02-01:2026-04-30

# Disable a specific feature (counterfactual)
python -m src.backtester --phase 4 --disable use_sentiment --holdout
```

**Output:** HTML report saved to `data/backtest_results/`. Equity curves, per-phase P&L table, phase delta column, LLM cache hit rate.

### Phase 0 Exit Criteria

1. Backtester produces a report on the train window without errors.
2. PipelineState is wired into the orchestrator; all existing tests pass.
3. Phase 0 live behavior is identical to pre-refactor (smoke test: deploy to Bot B, assert trade count and position sizing unchanged after 24h).

---

## Phase 1 — Risk Gate Retirement + Research Layer + Exit Advisor Upgrade

**Prerequisite:** Phase 0 complete.

### Risk Gate Retirement

The `RiskGate.evaluate()` call is removed from the orchestrator pipeline. `src/risk_gate.py` is kept for git history but no longer called. Deleted in Phase 3 cleanup after backtester confirms no regression.

Bot A gets `SKIP_RISK_GATE=true` to match Bot B — the env var is now the default.

### `src/research_panel.py` — Bounded Advisory Layer

Replaces binary PROCEED/VETO with a continuous `concern_score ∈ [0.0, 1.0]` that soft-reduces Kelly sizing. Maximum Kelly reduction: 30%. The panel can never zero out a trade.

```python
@dataclass
class ResearchOpinion:
    concern_score: float        # 0.0 = no concern, 1.0 = maximum concern
    kelly_multiplier: float     # 1.0 - (concern_score * 0.30), floor 0.70
    themes: list[str]           # 2-3 bullet concerns for logging
    confidence: str             # "low" | "medium" | "high"
```

**Inputs to the panel (richer than the old risk gate):**
- Symbol, price, 24h change, confluence score
- Last 10 bars
- Current open positions + their P&L (correlation context)
- News headlines from sentiment signal (empty list until Phase 4)

**Prompt:** single LLM call. Panel rates concern 0–10; code maps to `concern_score`. `kelly_multiplier = 1.0 - (concern_score * 0.30)`.

**Fallback:** LLM failure → `concern_score=0.0`, `kelly_multiplier=1.0`. Panel failure never blocks a trade.

**Pipeline integration:**

```python
state = state.with_updates(
    research_opinion=research_panel.evaluate(state),
    kelly_fraction=base_kelly * state.research_opinion.kelly_multiplier,
)
```

### Exit Advisor Upgrade

Two changes to `src/exit_advisor.py`:

**1. Richer prompt context:**
- `hours_to_market_close` — prevents "HOLD" near crypto session boundaries
- `open_positions_count` — signals whether tightening frees up meaningful exposure
- `trailing_stop_status` — tells LLM whether gains are already protected

**2. Sub-agent team for high-conviction positions.** When trigger is `soft_take_profit` AND position size > 2% of portfolio:
- Two `ClaudeLLM.call()` invocations run in parallel via `ThreadPoolExecutor`
- Second call is a "devil's advocate" that explicitly argues for the opposite decision
- Reconciliation: both EXIT → EXIT; both HOLD → HOLD; split → TIGHTEN (conservative)
- Adds ~1s latency on large gains — acceptable given position size

### Phase 1 Exit Criteria (backtester gate)

1. Holdout run: `monitor_pnl_delta ≥ 0` vs. Phase 0 baseline.
2. `trade_count ≥ Phase 0` baseline (risk gate retirement must not reduce trades — it should increase them).
3. Bot B canary: 7-day live comparison vs. Bot A. Promote to Bot A if B monitor P&L delta positive.

---

## Phase 2 — ATR-Based Dynamic Thresholds + Volatility-Adjusted Kelly

**Prerequisite:** Phase 1 complete.

### `src/volatility.py`

Three pure-math functions, no LLM calls:

```python
def atr(bars: list[dict], period: int = 14) -> float: ...
def annualized_vol(bars: list[dict], period: int = 20) -> float: ...
def vol_percentile(bars: list[dict], lookback: int = 90) -> float: ...
```

All accept the same `list[dict]` bar format used throughout the codebase.

### ATR-Based Exit Thresholds

Replaces fixed constants in `exit_advisor.py`:

| Threshold | Old (fixed) | New (ATR multiple) | Floor/Ceiling |
|---|---|---|---|
| Soft stop | −2% | −1.0 × ATR% | never wider than −5% |
| Soft take-profit | +5% | +2.5 × ATR% | — |
| Hard stop | −4% | −2.0 × ATR% | — |
| Hard take-profit | +10% | +5.0 × ATR% | never narrower than +6% |

Where `ATR% = atr(bars) / entry_price`.

ATR multiples are the backtester's first tuning target on the train window. `check_position_thresholds()` and `ExitAdvisor.should_exit()` gain a `bars` parameter. No extra API calls — bars are already in `PipelineState`.

### Volatility-Adjusted Kelly

```python
def vol_adjustment(ann_vol: float, vol_pct: float) -> float:
    TARGET_VOL = 0.20
    vol_ratio = min(TARGET_VOL / max(ann_vol, 0.01), 1.0)  # never size UP
    regime_penalty = 1.0 - (max(vol_pct - 0.75, 0.0) * 0.40)
    return max(vol_ratio * regime_penalty, 0.10)  # floor: never eliminates trade
```

Combined Kelly:

```python
kelly = base_kelly * confluence_fraction * vol_adjustment * research_multiplier
```

Default weights (env-configurable via `SIGNAL_WEIGHTS_JSON`):

```
ema_cross: 1.2  |  adx: 1.0  |  rsi: 0.8  |  volume: 1.1  |  vwap: 1.0
```

### Phase 2 Exit Criteria

1. Holdout: average position drawdown before exit ≤ Phase 1 baseline.
2. Holdout: average gain captured ≥ Phase 1 baseline.
3. Trade count not significantly reduced by vol adjustment.
4. Tune ATR multiples on train window if assertions fail (max 3 iterations).
5. Canary: Bot B → 7-day → Bot A.

---

## Phase 3 — Signal Ensemble + Weighted Scoring + Correlation Limits

**Prerequisite:** Phase 2 complete.

### `src/technical_signals/` Package

`src/technical_signals.py` (339 lines) → `src/technical_signals/` package:

| File | Responsibility |
|---|---|
| `types.py` | `Signal`, `StrategyResult` dataclasses, constants |
| `data.py` | Bar fetching, normalization, caching |
| `strategies.py` | 5 indicator functions → `StrategyResult` each |
| `ensemble.py` | Weighted combination → `Signal`; public API |

**Public API unchanged:** `from src.technical_signals import analyze, scan_assets, Signal` continues to work. No orchestrator imports change.

### `StrategyResult`

```python
@dataclass
class StrategyResult:
    name: str           # "ema_cross", "adx", "rsi", "volume", "vwap"
    bullish: bool       # backwards-compatible binary flag
    score: float        # 0.0–1.0 continuous confidence
    weight: float       # from config
```

**Continuous score derivation:**

| Strategy | Score logic |
|---|---|
| EMA cross | `(fast_ema - slow_ema) / slow_ema` normalized to [0,1] |
| ADX | `min(adx / 50, 1.0)` |
| RSI | Gaussian peak at RSI=55, falloff toward 30 and 70 |
| Volume | `min(volume_ratio / 3.0, 1.0)` |
| VWAP | `(price - vwap) / vwap` normalized, clipped [0,1] |

**Ensemble:**

```python
def weighted_score(results: list[StrategyResult]) -> float:
    total_weight = sum(r.weight for r in results)
    weighted_sum = sum(r.score * r.weight for r in results if r.bullish)
    return weighted_sum / total_weight  # 0.0–1.0
```

`Signal` gains `weighted_score: float` alongside the existing `confluence_score: int`. `MIN_CONFLUENCE` gate unchanged. Kelly sizing uses `weighted_score` for finer-grained sizing.

### `src/correlation.py`

```python
def rolling_correlation_matrix(
    positions: list[dict],
    bars_by_symbol: dict,
    window: int = 30,
) -> dict[tuple[str, str], float]: ...

def max_correlated_exposure(
    candidate: str,
    open_positions: list[dict],
    correlation_matrix: dict,
    threshold: float = 0.70,
) -> float: ...
```

If `max_correlated_exposure(candidate, ...) > MAX_CORRELATED_NOTIONAL` (default 15% of portfolio), position size is clipped — not vetoed. Bot still trades, just smaller. `PipelineState` carries `correlation_penalty`.

### Phase 3 Exit Criteria

1. Holdout: `sharpe_ratio` and `total_pnl` ≥ Phase 2 baseline.
2. Tune `DEFAULT_WEIGHTS` via backtester grid search on train window. Log winning weights to `data/backtest_results/`.
3. Correlation penalty: assert trade count not reduced below 80% of Phase 2 baseline (correlation should trim size, not eliminate trades).
4. Canary: Bot B → 7-day → Bot A.

---

## Phase 4 — Sentiment Signal + Re-entry Manager + Regime Detection

**Prerequisite:** Phase 3 complete.

### `src/sentiment_signal.py`

```python
@dataclass
class SentimentResult:
    symbol: str
    score: float          # -1.0 to +1.0
    headline_count: int
    confidence: str       # "low" | "medium" | "high"
    summary: str
```

**Data source:** Alpaca `/v1beta1/news` endpoint. Free for paper accounts, already in `alpaca-py`.

**LLM call:** single `ClaudeLLM.call()` with up to 10 headlines. Score normalized from [-10, +10] response to [-1, +1]. LLM cache applies (`sha256(prompt)` keyed).

**Fallback:** 0 headlines or LLM failure → `SentimentResult(score=0.0, confidence="low")`. Neutral, no influence.

**Research panel integration:**

```python
sentiment_adjustment = -result.sentiment.score * 0.15  # max ±0.15
concern_score = max(0.0, min(1.0, base_concern + sentiment_adjustment))
```

Sentiment nudges `concern_score` by at most 0.15. Never dominates.

### `src/reentry_manager.py`

Tracks recent exits and imposes cooldowns:

| Exit reason | Cooldown |
|---|---|
| `hard_stop` (−4%) | 4 hours |
| `soft_stop` + EXIT | 2 hours |
| `trailing_stop` | 1 hour |
| `hard_take_profit` | 30 minutes |
| `soft_take_profit` + EXIT | 30 minutes |

**High-confidence override:** `weighted_score ≥ 0.85` AND `confluence_score = 5` → cooldown halved. Perfect-signal re-entry allowed sooner, never immediate.

**State:** in-memory. Bot restart clears all cooldowns — acceptable for a swing system with ≤ 4-hour cooldowns.

**Pipeline gate:** added after signal scan, before research panel. Blocked symbols get `skipped_reason="reentry_blocked: ..."` in `PipelineState`.

### Regime Detection

Added to `ensemble.py`. Rolling Hurst exponent (30-bar window):
- H > 0.55 → trending regime → EMA/ADX weights × 1.2, RSI weight × 0.7
- H < 0.45 → mean-reverting regime → RSI weight × 1.3, EMA weight × 0.8
- 0.45–0.55 → ambiguous → no adjustment

Multiplicative on top of `DEFAULT_WEIGHTS`. Combined with `vol_percentile` from Phase 2, provides full regime context.

### Phase 4 Exit Criteria

1. Holdout: `total_pnl ≥ Phase 3` baseline.
2. Sentiment counterfactual: `--disable use_sentiment` backtest. If delta < 0.5%, sentiment is removed in Phase 5 cleanup.
3. Re-entry manager: average loss on re-entered positions (post-cooldown) < average loss without cooldown from Phase 3 data.
4. Canary: Bot B → 7-day → Bot A.

---

## Phase 5 — Backtester Maturity + Live Promotion Gates

**Prerequisite:** Phase 4 complete. No new trading features.

### `--compare-phases` Flag

```bash
python -m src.backtester --compare-phases 0,1,2,3,4 \
  --train 2025-10-01:2026-01-31 \
  --holdout 2026-02-01:2026-04-30
```

Produces a single HTML report: all equity curves overlaid, per-phase P&L/Sharpe/drawdown table, phase delta column, LLM cache hit rate per phase.

CI runs this on every PR to `main` that touches any file in `src/`.

### `scripts/promote_phase.py`

Decision support tool for promoting a phase from Bot B canary to Bot A:

```
Checks:
  1. Bot B monitor_pnl_delta vs Bot A for past N days > 0
  2. Backtest prediction vs. actual live delta within 30%
  3. No open positions in Bot A (safe promotion window)

Output: Coolify env var diff to apply, or failing check + recommendation.
Does NOT auto-deploy. Requires human confirmation.
```

### Phase 5 Evidence Review

After 30+ days of live data, each advisory component is audited via backtester counterfactual:

| Component | Cut criterion | Action if cut |
|---|---|---|
| Research panel | Kelly reduction shows ≤ 0.5% P&L delta | Set `concern_score=0` constant |
| Sentiment signal | Sentiment trades ≤ 0.5% better than baseline | Set `sentiment_adjustment=0` constant |
| Exit advisor sub-agent | Split-decision TIGHTEN ≤ 0.5% better than single-agent | Remove devil's advocate call |
| Regime detection | Regime-adjusted weights ≤ 0.5% better than fixed | Revert to Phase 3 fixed weights |

---

## Rollout Summary

| Phase | Key deliverable | Gate before shipping |
|---|---|---|
| 0 | Backtester + PipelineState | Backtester produces clean report; live behavior unchanged |
| 1 | Risk gate retired; research panel + upgraded exit advisor | Holdout monitor P&L ≥ 0 vs P0; trade count ≥ P0 |
| 2 | ATR thresholds + vol-adjusted Kelly | Holdout drawdown ≤ P1; gains captured ≥ P1 |
| 3 | Weighted ensemble + correlation limits | Holdout Sharpe + P&L ≥ P2 |
| 4 | Sentiment + re-entry + regime detection | Holdout P&L ≥ P3 |
| 5 | Backtester maturity + promotion gates | Evidence review; remove components with no measured edge |

**Canary process for all phases:** deploy to Bot B first → 7-day live comparison → run `promote_phase.py` → apply Coolify env diff to Bot A manually.

**Kill condition per phase:** if live P&L diverges > 30% from backtest prediction during the 7-day canary window, revert Bot B to the previous phase config and investigate before proceeding.

---

## Open Questions

None remaining. Architectural decisions settled:
- LLM cache keying: `sha256(full_prompt_string)` (not structured-input hash — prompt edits must invalidate cache)
- Phase 0 is pure plumbing only — no behavior changes
- Walk-forward split is mandatory; 6-month train window sufficient
- Research panel is bounded soft-blocking (max 30% Kelly reduction), not binary veto and not pure observation
- `technical_signals` package split: 4 files, not 7; "regime detection" naming, not "stat_arb"

## Risks

- **Backtester LLM cache cold start:** first run will make live LLM calls for every historical signal. Expensive and slow. Mitigation: seed the cache by running the current paper bots for 2 more weeks before starting Phase 0 backtest.
- **Walk-forward data scarcity:** train window starts Oct 2025 but the bots only started in late March 2026. Historical bar data from Alpaca is available back to 2020, but LLM call cache will be sparse before March 2026. Mitigation: for Phase 0 tuning, use only the live paper trading period (March–April 2026); expand to full 6-month window once cache warms up.
- **Weighted ensemble overfit:** 5 tunable weights + regime multipliers on a short train window is a genuine overfit risk. Mitigation: keep the grid search coarse (3 levels per weight, top 2 weights only), and treat the holdout result as the binding gate — not the train result.
- **Correlation matrix stale:** computed once per cycle (every 30 min). Between cycles, a new correlated position could open and exceed the notional cap. Acceptable for a swing trading system — the next cycle will clip it.
