# Phase 3: Parameterized Signal Engine + ATR + Session VWAP - Research

**Researched:** 2026-06-08
**Domain:** Pure-Python technical indicator math (no TA lib); profile parameterization; test remediation
**Confidence:** HIGH (all claims verified against current source this session)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** `analyze(symbol, bars, bars_4h=None, profile=SWING)` — periods sourced from
  `profile.ema_fast/ema_slow/rsi_period/adx_period`. Default param = `SWING` so existing
  callers and swing behavior are unchanged (defaults equal today's 9/21/14).
- **D-02:** `scan_assets(...)` gains a `profile` param and threads it + `profile.timeframe`
  / `profile.bar_count` / `profile.htf_filter_timeframe` through. Orchestrator passes the
  active profile (selection from Phase 2). Keep swing call-site behavior identical.
- **D-03:** Add `_atr(highs, lows, closes, period)` reusing the true-range computation pattern
  from `_adx` (Wilder smoothing). Add `atr_value: float` to `Signal` (default 0.0). Compute
  in `analyze()`. Do NOT wire into exits (Phase 4).
- **D-04:** VWAP anchored to current intraday session. Crypto 24/7 → "session" = daily-reset
  window keyed off bar timestamps (UTC-day anchor). Swing (1H) preserves current VWAP semantics;
  session anchor applies to the intraday (daytrade) path.
- **D-05:** Confluence/short-score scoring logic and thresholds are UNCHANGED this phase — only
  inputs (periods, VWAP basis) are parameterized. No strategy retuning.

### Claude's Discretion
- Exact VWAP session-anchor implementation and whether ATR helper returns a series or scalar —
  minimal-diff, math correctness verified by tests.

### Deferred Ideas (OUT OF SCOPE)
- ATR consumption in exits — Phase 4.
- Strategy/threshold retuning for daytrade — later.
- Fee gate (Phase 6), learning loop (Phase 7/8).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SIGNAL-01 | `analyze()` takes indicator periods from the profile (no hardcoded 9/21/14) | Exact signature change + full list of hardcoded periods below (§1) |
| SIGNAL-02 | `Signal` carries `atr_value` computed from bar data | `_atr` implementation reusing `_adx` TR math + hand-computable fixture (§2) |
| SIGNAL-03 | VWAP session-anchored (rolling intraday window) for daytrade profile | Alpaca bars carry ISO `timestamp`; UTC-day anchor design + `_vwap_bullish` change (§3) |
</phase_requirements>

## Summary

`technical_signals.py` is pure-function indicator math (no external TA library). Three locked
changes: (1) thread profile periods into `analyze()`/`scan_assets()` with `SWING` defaults that
reproduce 9/21/14 byte-for-byte; (2) add an `_atr()` helper reusing the Wilder true-range loop
already present in `_adx()`, attach `atr_value` to `Signal`; (3) make VWAP session-anchored
(UTC-day reset) for the daytrade path while preserving swing VWAP semantics.

The pre-existing test failures are **6, not 11** — and crucially, **5 of the 6 live in classes
that test `exit_advisor`/`alpaca_orchestrator`, not the signal module**. They are stale-threshold
expectations from the threshold/Kelly retuning that already shipped (env defaults moved to
`SOFT_STOP_PCT=-0.08`, `SOFT_TAKE_PROFIT_PCT=0.15`, `MIN_CONFLUENCE=4`). Only 1 failure
(`test_overbought_rsi_returns_none`) touches `analyze()` and it asserts behavior that was
**deliberately removed** (RSI is now a soft ceiling, not a hard block). All 6 are **fix-the-test**,
zero genuine code bugs found.

**Primary recommendation:** Make minimal-diff parameterization with `profile=SWING` defaults;
add `_atr` as a scalar-returning helper modeled on the existing `_adx` TR loop; add an optional
`timestamps` arg to `_vwap_bullish` that, when provided AND profile is intraday, anchors the
cumulative VWAP to the current UTC day. Update the 6 stale tests to current intended behavior.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Indicator math (EMA/RSI/ADX/ATR/VWAP) | Signal engine (`technical_signals.py`) | — | Pure functions, no I/O |
| Period selection | StrategyProfile (`strategy_profile.py`) | Signal engine consumes | Profile is the single source of style params |
| Bar fetch + timestamp | AlpacaClient (`alpaca_client.py`) | — | Already returns ISO `timestamp` per bar |
| Profile selection at runtime | Orchestrator (`alpaca_orchestrator.py`, `bot_thread.py`) | — | Phase 2 wired `BOT_PROFILE` |
| ATR consumption (exits) | Phase 4 (out of scope) | — | This phase only produces `atr_value` |

## Standard Stack

No new packages. Phase is pure stdlib Python on existing code.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`datetime`) | 3.11+ | Parse ISO bar timestamps for session anchor | Already imported in alpaca_client |
| pytest | existing | Unit tests | Repo test runner |

No external TA library — repo convention is hand-rolled indicator math. **Do not introduce
`ta`/`pandas-ta`/`talib`** — it would break the no-dependency convention and D-05 parity.

## Package Legitimacy Audit

Not applicable — no packages installed this phase.

## Architecture Patterns

### Pattern 1: Profile defaults that preserve parity
**What:** Add `profile=SWING` as the LAST positional/keyword param so existing callers
(`analyze(symbol, bars)`, `analyze(symbol, bars, bars_4h=x)`) are untouched. `SWING.ema_fast=9`,
`ema_slow=21`, `rsi_period=14`, `adx_period=14`, `atr_period=14` (verified in `strategy_profile.py`)
exactly equal today's hardcoded literals → byte-for-byte swing output.

**Exact signature changes:**
```python
# D-01
def analyze(symbol, bars, bars_4h=None, profile=SWING) -> Signal | None:
    ...
    ema_fast = _ema(closes, profile.ema_fast)   # was _ema(closes, 9)
    ema_slow = _ema(closes, profile.ema_slow)   # was _ema(closes, 21)
    adx_result = _adx(highs, lows, closes, profile.adx_period)  # was 14
    rsi_value = _rsi(closes, profile.rsi_period)                # was 14
    atr_value = _atr(highs, lows, closes, profile.atr_period)   # NEW
    # 4H filter EMAs also use profile.ema_fast/ema_slow

# D-02
def scan_assets(alpaca_client, symbols, timeframe="1Hour", bar_count=50,
                fetch_4h=True, profile=SWING) -> list[Signal]:
    ...
    bars = alpaca_client.get_bars(symbol, timeframe=profile.timeframe, limit=profile.bar_count)
    bars_4h = alpaca_client.get_bars(symbol, timeframe=profile.htf_filter_timeframe, limit=30)
    signal = analyze(symbol, bars, bars_4h=bars_4h, profile=profile)
```
**Note on `scan_assets` defaults:** keep `timeframe`/`bar_count` params for backward compat, but
when `profile` is passed prefer `profile.timeframe`/`profile.bar_count`. Cleanest: have callers
that pass a profile drop the literal `timeframe=`/`bar_count=` args. Swing call-sites can stay
literal (SWING values match) OR pass `profile=SWING` — both produce identical results.

### Pattern 2: ATR reusing `_adx` true-range (Wilder)
**What:** The TR computation in `_adx` (lines 108-123) is exactly the input to ATR. ATR =
Wilder-smoothed mean of TR over `period`. `_adx` already does Wilder smoothing of summed TR
(`atr = atr - atr/period + tr_list[i]`) but that running `atr` is a **sum**, not a mean.
True ATR = that smoothed value / period (or equivalently smooth the *mean*).

**Recommended `_atr` (scalar return, minimal diff, matches Wilder):**
```python
def _atr(highs, lows, closes, period: int = 14) -> float:
    """Average True Range (Wilder smoothing). Returns latest ATR, 0.0 if insufficient data."""
    n = len(closes)
    if n < period + 1 or len(highs) != n or len(lows) != n:
        return 0.0
    tr_list = []
    for i in range(1, n):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        tr_list.append(tr)
    atr = sum(tr_list[:period]) / period          # first ATR = simple mean of first `period` TRs
    for tr in tr_list[period:]:                    # Wilder smoothing
        atr = (atr * (period - 1) + tr) / period
    return atr
```
Requires only `period+1` bars (looser than `_adx`'s `2*period+1`). Returns scalar (discretion D-05
allows scalar). Attach in `analyze()`: `atr_value=_atr(highs, lows, closes, profile.atr_period)`.

**Hand-computable unit fixture** (closes-derived OHLC won't work — TR needs real H/L). Use:
```python
highs  = [10, 11, 12, 11, 13]
lows   = [ 9, 10, 10,  9, 11]
closes = [ 9, 11, 11, 10, 12]
# TR[1]=max(11-10, |11-9|, |10-9|)=2 ; TR[2]=max(12-10,|12-11|,|10-11|)=2
# TR[3]=max(11-9,|11-11|,|9-11|)=2 ; TR[4]=max(13-11,|13-10|,|11-10|)=3
# period=2: first ATR = mean(TR[1],TR[2]) = mean(2,2)=2.0
#   smooth TR[3]=2: (2*1 + 2)/2 = 2.0 ; smooth TR[4]=3: (2*1 + 3)/2 = 2.5
# EXPECTED _atr(highs,lows,closes,2) == 2.5
```

### Pattern 3: Session-anchored VWAP (UTC-day reset)
**What:** Alpaca bars carry `timestamp` as an ISO-8601 string (verified `alpaca_client.py:284`:
`bar.timestamp.isoformat()`). Current `_vwap_bullish` uses `vwaps[-1]` (Alpaca's per-bar VWAP)
if present, else a rolling-20 fallback. For intraday, "above session VWAP" means cumulative VWAP
since the start of the current UTC day, not a per-bar value.

**Recommended change — add optional `timestamps` + `session_anchor` flag:**
```python
def _vwap_bullish(closes, volumes, vwaps, timestamps=None, session_anchor=False) -> bool:
    if session_anchor and timestamps:
        # anchor to current UTC day: include only bars sharing the last bar's date
        last_day = timestamps[-1][:10]   # "2026-06-08" from ISO string — no parse needed
        idx = [i for i, t in enumerate(timestamps) if t[:10] == last_day]
        cum_pv = sum(closes[i] * volumes[i] for i in idx)
        cum_vol = sum(volumes[i] for i in idx)
        if cum_vol <= 0:
            return False
        return closes[-1] > cum_pv / cum_vol
    # --- existing swing behavior unchanged below ---
    if vwaps and vwaps[-1] > 0:
        return closes[-1] > vwaps[-1]
    ... # rolling-20 fallback
```
Caller in `analyze()`:
```python
session_anchor = profile.name == "daytrade"   # or a profile.session_vwap bool if added
timestamps = [b.get("timestamp") for b in bars]
vwap_bull = _vwap_bullish(closes, volumes, vwaps, timestamps=timestamps, session_anchor=session_anchor)
```
**Why string-prefix date works:** ISO timestamps sort lexically and `[:10]` is the date. No
`datetime.fromisoformat` needed (avoids tz-suffix edge cases like `+00:00`/`Z`). Swing path
(session_anchor=False) is completely unchanged → parity preserved (D-04, D-05).

### Anti-Patterns to Avoid
- **Changing confluence scoring** — D-05 forbids. Only swap inputs.
- **Making `profile` the first arg** — breaks `analyze(symbol, bars)` callers. Must be last.
- **Returning a series from `_atr`** when only the latest scalar is attached — adds surface, no value.
- **Parsing timestamps with `datetime.fromisoformat`** for the day key — string slice is simpler and tz-safe here.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| True-range computation | New TR loop | Copy the existing `_adx` TR formula (lines 115-119) | Already validated; consistency |
| Date-of-bar extraction | `datetime` parse + tz handling | ISO string `[:10]` slice | Alpaca timestamps are ISO; slice is tz-agnostic |

**Key insight:** Everything needed already exists in this module — ATR is a 6-line extraction of
the `_adx` inner loop; session VWAP is a filter on the existing cumulative-VWAP fallback.

## Runtime State Inventory

This phase is **code + test edits only** — no stored data, services, OS registrations, secrets, or build artifacts.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — `atr_value` defaults 0.0; no DB schema change; `Signal` not persisted to DB (verified: no signals table) | none |
| Live service config | None — no env var renames | none |
| OS-registered state | None | none |
| Secrets/env vars | None changed (RSI_ENTRY_CEILING etc. unchanged) | none |
| Build artifacts | None | none |

## Common Pitfalls

### Pitfall 1: Breaking the None-return contract
**What goes wrong:** `analyze()` returns `None` when `score==0 AND short_score==0` (line 374). Adding
`atr_value` must not change this — compute ATR before the None check but only include in the `Signal`
constructor on the success path. **Warning sign:** any test asserting `analyze()` returns None now
returns a Signal.

### Pitfall 2: Default-param ordering breaks callers
**What goes wrong:** 3 live call-sites use positional/keyword forms:
`alpaca_orchestrator.py:734,1151`, `bot_thread.py:383`. All call `scan_assets(alpaca, universe,
timeframe=..., bar_count=..., fetch_4h=...)`. Adding `profile=SWING` as the last param leaves these
untouched. **Verified:** no caller passes 5+ positional args.

### Pitfall 3: `_atr` insufficient-data guard
**What goes wrong:** `_adx` needs `2*period+1` bars; `_atr` only needs `period+1`. Don't copy the
`_adx` guard verbatim or you'll return 0.0 unnecessarily. Use `n < period + 1`.

### Pitfall 4: Misreading the failing-test scope
**What goes wrong:** Context says "11 failing tests ... stale-threshold from the trend-rider overhaul."
**Reality (verified this session):** 6 failures, 5 of which test `exit_advisor`/`orchestrator` (not
the signal module) and are stale because threshold/Kelly retuning ALREADY shipped. Don't "fix" code to
satisfy them — fix the test expectations. See Validation Architecture below for per-failure verdicts.

## Code Examples

(See Patterns 1-3 above — all code is verified against current source.)

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hardcoded 9/21/14 | Profile-sourced periods | This phase | Daytrade can use different periods later |
| Rolling-20 VWAP fallback | Session (UTC-day) anchor for intraday | This phase | Correct intraday VWAP semantics |
| RSI hard block (>72 → None) | RSI soft ceiling (suppresses long point only) | Already shipped (pre-phase) | `test_overbought_rsi_returns_none` is stale |
| `SOFT_STOP=-0.03`, `SOFT_TP=+9%` | `SOFT_STOP=-0.08`, `SOFT_TP=+0.15`, `HARD_STOP=-0.15` | Already shipped | 3 threshold tests stale |
| `MIN_CONFLUENCE=3` | `MIN_CONFLUENCE=4` (profile default) | Already shipped | `test_confluence_3` stale |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Daytrade session = UTC-day; crypto has no exchange session, so calendar-day reset is the intended anchor | §3 / D-04 | If a different anchor (e.g. rolling-N-hours) was intended, VWAP basis differs. D-04 says "UTC-day anchor (e.g.)" — confirm with user/planner. |
| A2 | Session-anchor toggled via `profile.name == "daytrade"` (no new profile field) | §3 | If a dedicated `session_vwap: bool` field is preferred, add to StrategyProfile. Minor. |

All other claims VERIFIED against source this session.

## Open Questions

1. **VWAP anchor granularity** — UTC-day vs rolling intraday window. D-04 lists UTC-day as an
   example. Recommendation: UTC-day reset (simplest, matches "session" for 24/7 crypto). Flag A1.
2. **Toggle mechanism** — `profile.name` check vs new `session_vwap` field. Recommendation:
   `profile.name == "daytrade"` for minimal diff; promote to a field only if a third profile needs it.

## Environment Availability

No external dependencies — pure Python + existing pytest. `python -m pytest` confirmed working
(ran this session: 6 failed, 58 passed).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | none detected — uses default discovery |
| Quick run command | `python -m pytest tests/test_technical_signals.py -q` |
| Full suite command | `python -m pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SIGNAL-01 | Swing defaults reproduce 9/21/14 output | unit/regression | `pytest tests/test_technical_signals.py -k "uptrend_signal or signal_fields" -x` | ✅ (extend with parity fixture) |
| SIGNAL-01 | `analyze(profile=DAYTRADE)` sources periods | unit | `pytest tests/test_technical_signals.py -k profile -x` | ❌ Wave 0 |
| SIGNAL-02 | `_atr` matches hand fixture (2.5) | unit | `pytest tests/test_technical_signals.py -k atr -x` | ❌ Wave 0 |
| SIGNAL-02 | `Signal.atr_value` populated | unit | `pytest tests/test_technical_signals.py -k atr_value -x` | ❌ Wave 0 |
| SIGNAL-03 | Session VWAP resets across UTC-day boundary | unit | `pytest tests/test_technical_signals.py -k session_vwap -x` | ❌ Wave 0 |
| SIGNAL-03 | Swing VWAP unchanged | regression | `pytest tests/test_technical_signals.py -k "above_vwap or below_vwap or fallback" -x` | ✅ |

### Pre-Existing Failure Triage (remediation scope) — VERIFIED per-failure verdicts

Context estimated "~11 failing tests"; **actual = 6**. None are genuine code bugs. All are
fix-the-test. Only #6 touches the signal module; #1-5 test `exit_advisor`/`alpaca_orchestrator`.

| # | Test | Module under test | Root cause | Verdict |
|---|------|-------------------|-----------|---------|
| 1 | `TestTrailingStop::test_triggers_on_pullback` | exit_advisor | Test expects 3% trail at peak; `TRAIL_DISTANCE_PCT` now 0.05 → trail at 110*0.95=104.5, price 106 doesn't trigger | **Fix test** — update expected trail distance to 5% (or build to a pullback below 104.5) |
| 2 | `TestThresholdChecks::test_hard_stop` | exit_advisor | Expects hard_stop at -5.1%; `HARD_STOP_PCT` now -0.15 → -5.1% is not a hard stop | **Fix test** — use a price past -15% |
| 3 | `TestThresholdChecks::test_soft_stop` | exit_advisor | Expects soft_stop at -3.1%; `SOFT_STOP_PCT` now -0.08 | **Fix test** — use price past -8% |
| 4 | `TestThresholdChecks::test_soft_take_profit` | exit_advisor | Expects soft_tp at +9%; `SOFT_TAKE_PROFIT_PCT` now 0.15 | **Fix test** — use price past +15% |
| 5 | `TestKellyTechnical::test_confluence_3` | alpaca_orchestrator | Expects buy at confluence=3; `MIN_CONFLUENCE` now 4 (profile default) | **Fix test** — use confluence 4 (or assert side=="none" at 3) |
| 6 | `TestRSIHardBlock::test_overbought_rsi_returns_none` | **technical_signals (analyze)** | RSI hard block removed; RSI>65 now only suppresses the long RSI point, analyze still returns a Signal | **Fix test** — assert RSI ceiling suppresses long score, not that signal is None |

**Note:** `test_normal_range` (line 353-356) currently PASSES but its inline comments reference the
old -3% soft stop. Update the comment for clarity (no logic change). `TrailingStop` tests #4
(`test_no_trigger_above_trail`, `test_remove_clears_tracking`) pass under the new 5% trail — verify
they still align after fixing #1.

**Scope decision for planner:** Remediation touches `tests/test_technical_signals.py` only — no
production code edits required to bring these green. This is consistent with D-05 (no threshold
retuning) — the thresholds already changed in prior phases; only the tests lag.

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_technical_signals.py -q`
- **Per wave merge:** `python -m pytest -q`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_technical_signals.py` — add `TestATR` (hand fixture → 2.5), `TestProfilePeriods`
      (analyze with DAYTRADE sources its periods), `TestSessionVWAP` (UTC-day reset), swing-parity
      regression (fixed bar fixture → identical Signal pre/post change).
- [ ] Fix 6 stale tests per triage table above.
- [ ] No framework install needed (pytest present).

## Security Domain

Not applicable — pure numerical computation on already-fetched market data, no auth/input/crypto
surface introduced. ASVS V5 (input validation) is satisfied upstream by `alpaca_client.get_bars`
type coercion (`float(...)`). No new threat surface.

## Sources

### Primary (HIGH confidence)
- `src/technical_signals.py` (full read) — `_adx` TR math, `_vwap_bullish`, `analyze`, `scan_assets`, None contract
- `src/strategy_profile.py` (full read) — SWING/DAYTRADE period fields (9/21/14/14 confirmed)
- `src/alpaca_client.py` (full read) — `get_bars` returns ISO `timestamp`, `vwap` keys (line 282-291)
- `src/exit_advisor.py` (grep) — current threshold env defaults
- `src/alpaca_orchestrator.py` — `MIN_CONFLUENCE` default, scan_assets call-sites (734, 1151)
- `tests/test_technical_signals.py` (full read) + live `pytest` run — 6 failures enumerated
- `.planning/phases/03.../03-CONTEXT.md`, `.planning/REQUIREMENTS.md`, day-trading-upgrade-design.md §4

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no packages, verified against source
- Architecture (signatures/ATR/VWAP): HIGH — code verified, fixture hand-computed
- Pitfalls / failure triage: HIGH — ran the suite, read each failing assertion

**Research date:** 2026-06-08
**Valid until:** 2026-07-08 (stable; internal code only)
