# Phase 7: Close the Self-Learning Loop (Entry + Sizing) - Research

**Researched:** 2026-06-08
**Domain:** In-process wiring of an existing learning module (`TradeMemory`) into the two live trade-entry pipelines (`bot_thread.py`, `alpaca_orchestrator.py`)
**Confidence:** HIGH (all findings are direct codebase reads; no external dependencies)

## Summary

`TradeMemory.get_advice()` and `get_dynamic_thresholds()` are fully implemented and tested but only PARTIALLY consumed. The live runtime (`bot_thread.py`) already consults `get_advice()` on the LONG path and vetoes on `should_trade=False` — but it does NOT use `confidence_adjustment` (LEARN-02), does NOT call `get_dynamic_thresholds()` (LEARN-03), and does NOT consult advice on the SHORT path. The legacy CLI runtime (`alpaca_orchestrator.py`) consults advice on NEITHER path.

This phase is pure consumption wiring with no new packages. The cleanest seam is to compute advice (veto) BEFORE sizing and pass `confidence_adjustment` + dynamic min/max caps INTO `_kelly_technical`, while keeping `MAX_POSITION_PCT` / `MAX_TOTAL_EXPOSURE_PCT` as hard ceilings applied last. A single module-level flag (`LEARNING_ENFORCE`, default True) wrapped around the veto/scale effects makes Phase 8's shadow gate a one-line flip.

**Primary recommendation:** Extend `_kelly_technical` with two optional kwargs (`confidence_adjustment: float = 1.0`, `min_position_pct: float | None = None`, `max_position_pct` already exists) and a shadow flag at the call site for veto. Apply adjustment AFTER Kelly, clamp into `[min_position_pct, max_position_pct]`, then enforce the existing hard cap. Mirror identical logic into all four entry paths (long+short × both files).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Advice lookup (veto) | Backend / bot runtime | — | Decision logic at entry, before order placement |
| Position scaling | Backend / `_kelly_technical` | — | Sizing math owns the dollar amount |
| Dynamic threshold feed | Backend / `_kelly_technical` caps | — | Caps are a sizing concern |
| Hard ceiling enforcement | Backend / sizing (last) | exposure check in entry loop | `MAX_POSITION_PCT` inviolable regardless of learning |

## Current State of Learning Wiring (D-01 — the critical map)

### `src/bot_thread.py` (LIVE runtime — priority)

| Call site | Line(s) | Status |
|-----------|---------|--------|
| `memory = TradeMemory(bot_id=bot_id)` | 204 | constructed when `_HAS_LEARNING`; `memory=None` otherwise (200, 209) |
| `learning_loop.run_cycle()` | 342 | CONSUMED (outcome sync + lessons) |
| LONG `memory.get_advice(...)` | 514–533 | **PARTIALLY CONSUMED** — vetoes on `should_trade=False` (522 `continue`); logs reasoning. `confidence_adjustment` IGNORED. |
| LONG `_kelly_technical(...)` | 543–549 | passes `cfg.kelly_fraction`, `cfg.max_position_pct`. No adjustment, no dynamic thresholds. |
| LONG `memory.record_trade_context(...)` | 591–614 | `signal_type="technical_confluence_{score}"` (505) |
| SHORT `get_advice` | — | **MISSING** — no advisory call at all on short path (673–708) |
| SHORT `_kelly_technical(...)` | 698–704 | same gap; `signal_type="technical_short_{short_score}"` (682) |
| SHORT `record_trade_context` | — | **NOT SHOWN in 673–745** — short path does NOT record context (recording gap; verify full short block, only the order log at 719 is `market_sentiment=signal_type`) |
| `get_dynamic_thresholds()` | — | **NEVER CALLED in bot_thread** |

### `src/alpaca_orchestrator.py` (legacy CLI runtime)

| Call site | Line(s) | Status |
|-----------|---------|--------|
| `memory = TradeMemory()` | 586 | constructed when `_HAS_LEARNING` |
| `learner.run_cycle()` | 1063 | CONSUMED |
| LONG `get_advice` | — | **MISSING entirely** |
| LONG `_kelly_technical(...)` | 864–870 | `kelly_fraction`, `max_position_pct=MAX_POSITION_PCT`. No advice/thresholds. |
| LONG `record_trade_context(...)` | 922–931 | `signal_type="technical_confluence_{score}"` (924) |
| SHORT `get_advice` | — | **MISSING** |
| SHORT `_kelly_technical(...)` | 976–982 | `max_position_pct=MAX_POSITION_PCT` |
| SHORT `record_trade_context` | — | **MISSING** — short path only `log_alpaca_trade` with `market_sentiment="short_technical_{score}"` (1006). No context recorded. |
| `get_dynamic_thresholds()` | — | **NEVER CALLED** |

**Double-wiring risk:** ONLY bot_thread LONG already vetoes. Do NOT add a second veto there — extend it with scaling + thresholds. Everywhere else, add fresh.

## signal_type Strings (D-02 — alignment audit)

`record_trade_context` stores the string `get_advice(signal_type=...)` must match exactly, or advice is always empty (no similar trades → default `should_trade=True, adjustment=1.0`).

| Path | File | record_trade_context signal_type | get_advice signal_type | Aligned? |
|------|------|-----------------------------------|------------------------|----------|
| LONG | bot_thread | `technical_confluence_{confluence_score}` (505→596) | `technical_confluence_{...}` (518) | YES |
| SHORT | bot_thread | (none recorded) but local `signal_type="technical_short_{short_score}"` (682) | (no get_advice) | n/a — wire both with `technical_short_{score}` |
| LONG | orchestrator | `technical_confluence_{confluence_score}` (924) | (none) | wire get_advice with same string |
| SHORT | orchestrator | (none recorded); order log uses `short_technical_{score}` (1006) | (none) | **MISMATCH HAZARD**: bot_thread uses `technical_short_`, orchestrator order-log uses `short_technical_`. Pick ONE canonical string per side. |

**RECOMMENDATION:** Canonicalize short `signal_type = f"technical_short_{score}"` (matches bot_thread). When adding short `record_trade_context` to the orchestrator, use `technical_short_`, NOT the `short_technical_` order-log string. Cross-bot advice is per-`bot_id` so A/B isolation holds.

## get_advice() / get_dynamic_thresholds() Return Shapes (D-04)

### `get_advice(symbol, signal_type, sentiment, price_change)` → dict
- `should_trade: bool` — **False only when** `win_rate < 0.30 AND ≥3 closed similar trades` (trade_memory.py:480). Otherwise True.
- `confidence_adjustment: float` — range `[0.0, 1.5]`:
  - `0.0` when vetoed
  - `0.5` when `win_rate < 0.50`
  - `1.0` neutral (also when <2 closed similar, or no history)
  - `min(1.5, 1.0 + (win_rate - 0.60))` when `win_rate > 0.60` → max 1.5
- `win_rate_for_pattern: float | None`, `sample_size: int`, `reasoning: str`, `similar_trades`, `lessons`

**Caps interaction (D-04 hazard):** adjustment can be >1 (up to 1.5) → it CAN breach `max_position_pct` if applied naively. MUST clamp post-scale.

### `get_dynamic_thresholds()` → dict
- `bullish_threshold` / `bearish_threshold` (0.42–0.58 band; confluence threshold use)
- `min_position_pct` (0.01–0.02) / `max_position_pct` (0.03–0.05)
- `signal_scores: dict`, `overall_win_rate`, `total_closed_trades`
- No-data default: bull 0.53 / bear 0.47, min 0.02 / max 0.05.

## _kelly_technical Signature & Recommended Change (D-04, D-05, discretion)

Current (identical in both files, orchestrator is the source — `_kelly_technical` is imported into bot_thread at line 66):
```python
def _kelly_technical(confluence, current_price, bankroll,
                     kelly_fraction=0.25, max_position_pct=0.05) -> dict
```
Returns `{side, kelly_pct, adjusted_pct, dollar_amount, shares, capped}`. Caps at `max_position_pct` (line 416–418).

**Recommended signature extension (single definition, both files inherit since bot_thread imports it):**
```python
def _kelly_technical(confluence, current_price, bankroll,
                     kelly_fraction=0.25, max_position_pct=0.05,
                     confidence_adjustment=1.0, min_position_pct=None) -> dict
```
Order of operations (insert after line 414 `adjusted_pct = kelly_pct * kelly_fraction`):
1. `adjusted_pct *= confidence_adjustment`  (LEARN-02 scale)
2. if `min_position_pct` and `adjusted_pct > 0`: `adjusted_pct = max(adjusted_pct, min_position_pct)` (LEARN-03 floor)
3. dynamic `max_position_pct` already clamps (LEARN-03 ceiling) — pass `min(static_MAX_POSITION_PCT, dynamic_max)` from caller so the static hard cap is never exceeded (D-04).
4. existing `capped` clamp at the resulting `max_position_pct` stays LAST → hard ceiling inviolate.

Default args (`adjustment=1.0`, `min=None`) make this backward-compatible → existing 217 tests unaffected.

## Insertion Points (D-05)

For each of the 4 paths, after fee gate, before sizing:
1. **bot_thread LONG (513–549):** advice ALREADY computed at 514. Add: capture `advice["confidence_adjustment"]`; compute `thresholds = memory.get_dynamic_thresholds()` once per cycle (cache, not per-symbol); pass both into `_kelly_technical` at 543. Wrap veto (522) in `if LEARNING_ENFORCE`.
2. **bot_thread SHORT (683–704):** ADD full advisory block (mirror 514–533 with `sentiment=short_score/4.0`); ADD scale+thresholds into 698; ADD `record_trade_context` after order (currently missing).
3. **orchestrator LONG (852–870):** ADD advisory block before fee gate / sizing; pass adjustment+thresholds into 864.
4. **orchestrator SHORT (940–982):** ADD advisory block; ADD scale into 976; ADD `record_trade_context` (currently missing — and use canonical `technical_short_`).

Compute `get_dynamic_thresholds()` ONCE per cycle (it's a full-table scan), not per candidate.

## Shadow-Gateable Seam (Phase 8 prep)

Add module-level flag, default enforce:
```python
LEARNING_ENFORCE = os.environ.get("LEARNING_ENFORCE", "1") == "1"
```
- VETO: `if not advice["should_trade"]: log(...); if LEARNING_ENFORCE: continue` — log-only when shadow.
- SCALE: `adj = advice["confidence_adjustment"] if LEARNING_ENFORCE else 1.0` (still log the would-be value).
- Thresholds: pass `None` for min/max when shadow.

Phase 8 replaces the flag with the `LEARNING_SHADOW_UNTIL_TRADES` count gate — single seam, no structural change. Keep the would-be values logged in both modes so Phase 8 can measure shadow impact.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Win-rate lookup | re-query trade_context | `get_advice()` | already tiered/sanitized |
| Threshold derivation | recompute from db | `get_dynamic_thresholds()` | already implemented + tested |
| Position math | new sizing fn | extend `_kelly_technical` | one definition, both files import it |

## Common Pitfalls

### Pitfall 1: Double-veto in bot_thread LONG
Already vetoes at 522. Adding a second one breaks the partial wiring. **Extend, don't add.**

### Pitfall 2: signal_type mismatch → advice always empty
If `get_advice` is called with a string that never appears in `trade_context.signal_type`, `find_similar_trades` returns [] → `should_trade=True, adjustment=1.0` (silent no-op). Verify the exact string per path (table above). The orchestrator short-side `short_technical_` vs bot_thread `technical_short_` divergence is a live trap.

### Pitfall 3: adjustment>1 breaches MAX_POSITION_PCT
`confidence_adjustment` reaches 1.5. Apply BEFORE the cap clamp; pass `min(MAX_POSITION_PCT, dynamic_max)` as the effective ceiling so the static hard cap always wins (D-04). Test: adjustment=1.5 with high Kelly → `adjusted_pct == MAX_POSITION_PCT`, `capped==True`.

### Pitfall 4: memory is None path
Both files set `memory=None` when `_HAS_LEARNING` false / construction fails. ALL new advice/threshold code must be inside `if memory is not None:`. Default `confidence_adjustment=1.0`, `min_position_pct=None` → unchanged behavior when learning disabled.

### Pitfall 5: get_dynamic_thresholds per-candidate cost
Full trade_context scan. Compute once per cycle, reuse.

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `trade_context` rows keyed by `(bot_id, signal_type)`. Adding short recording in orchestrator with canonical `technical_short_` will create NEW signal_type values; old `short_technical_` order-log strings are in `alpaca_trades.market_sentiment` (not context) and unaffected. | code edit only; no data migration |
| Live service config | None — in-process Python, no external service holds learning state | None |
| OS-registered state | None | None |
| Secrets/env vars | New `LEARNING_ENFORCE` (Coolify env, optional, default on). No rename of existing. | add to Coolify env doc (optional) |
| Build artifacts | None | None |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (conftest.py at tests/conftest.py) |
| Config file | none explicit — pytest default discovery (`tests/test_*.py`) |
| Quick run command | `python -m pytest tests/test_learning_wiring.py -x -q` |
| Full suite command | `python -m pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LEARN-01 | `should_trade=False` → candidate vetoed (no order) | unit | `pytest tests/test_learning_wiring.py::test_veto_skips_candidate -x` | ❌ Wave 0 |
| LEARN-02 | `confidence_adjustment` scales dollar amount | unit | `pytest tests/test_learning_wiring.py::test_adjustment_scales_size -x` | ❌ Wave 0 |
| LEARN-02 | adjustment=1.5 never breaches MAX_POSITION_PCT | unit | `pytest tests/test_learning_wiring.py::test_hard_cap_inviolate -x` | ❌ Wave 0 |
| LEARN-03 | dynamic min/max override static caps | unit | `pytest tests/test_learning_wiring.py::test_dynamic_thresholds_applied -x` | ❌ Wave 0 |
| D-02 | signal_type matches record/advice both sides | unit | `pytest tests/test_learning_wiring.py::test_signal_type_alignment -x` | ❌ Wave 0 |
| shadow | `LEARNING_ENFORCE=0` → log-only, no veto/scale | unit | `pytest tests/test_learning_wiring.py::test_shadow_mode_no_effect -x` | ❌ Wave 0 |

`_kelly_technical` is pure → unit-testable directly without Alpaca. Veto path test the candidate loop via a fake `memory` stub returning canned advice dicts (mirror `test_fee_gate.py` style — pure functions, monkeypatched module constants).

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_learning_wiring.py tests/test_position_sizer.py -q`
- **Per wave merge:** `python -m pytest -q`
- **Phase gate:** full suite green (217+ existing + new) before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_learning_wiring.py` — covers LEARN-01/02/03 + shadow + signal_type alignment
- [ ] Fake `TradeMemory` fixture in conftest or inline (canned `get_advice`/`get_dynamic_thresholds`)

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| LEARN-01 | Veto on `should_trade=False` before sizing | get_advice rule (wr<0.30, ≥3); bot_thread LONG already does it (522) — extend to 3 other paths |
| LEARN-02 | `confidence_adjustment` scales size | `_kelly_technical` extension; clamp post-scale; range 0.0–1.5 |
| LEARN-03 | `get_dynamic_thresholds()` feeds min/max into Kelly | call once/cycle; pass min floor + `min(MAX_POSITION_PCT, dynamic_max)` ceiling |

## Open Questions

1. **Short-path `record_trade_context` absence** — Phase 7 scope is consumption, but get_advice for shorts is useless without recorded short context. Recommendation: add short `record_trade_context` in this phase (small, unblocks LEARN-01/02 for shorts). Confirm with planner whether to include.
2. **`sentiment` value for advice** — bot_thread LONG uses `confluence_score/4.0` but confluence is /5 in orchestrator (lines 879 `/5` vs 896 `/4.0` inconsistency exists). `find_similar_trades` matches sentiment ±0.10, so divergence narrows matches. Recommend standardizing on `/4.0` (as recorded) for advice lookups to match stored values.

## Sources

### Primary (HIGH confidence)
- `src/trade_memory.py` (full) — get_advice 436–504, get_dynamic_thresholds 506–584
- `src/learning_loop.py` (full)
- `src/bot_thread.py` lines 66–80, 200–342, 500–745
- `src/alpaca_orchestrator.py` lines 384–430, 582–1068
- `.planning/REQUIREMENTS.md` LEARN-01..06
- `07-CONTEXT.md` D-01..D-05
- `tests/test_fee_gate.py` (test pattern reference)

## Metadata

**Confidence breakdown:**
- Current wiring map: HIGH — direct reads
- Return shapes: HIGH — source
- signal_type alignment: HIGH — found a real divergence (`technical_short_` vs `short_technical_`)
- Test plan: MEDIUM — no learning test file exists yet (Wave 0)

**Research date:** 2026-06-08
**Valid until:** 2026-07-08 (stable; internal code only)
