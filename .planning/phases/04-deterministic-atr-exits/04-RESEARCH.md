# Phase 4: Deterministic ATR Exits - Research

**Researched:** 2026-06-08
**Domain:** Python algo-trading exit logic (volatility-scaled stops, ATR, trailing stops, side-aware position management)
**Confidence:** HIGH (all findings sourced from the live codebase; no external library claims)

## Summary

The single most important finding: **the two "monitors" are not duplicated — they are the same class.** `bot_thread.py` imports `PositionMonitor` directly from `src/alpaca_orchestrator.py` (line 63-71) and instantiates it (`monitor = PositionMonitor(alpaca, logger, exit_advisor)`, line 226). The orchestrator's `main()` instantiates the identical class (line 620). **There is exactly ONE exit-decision code path to change** — `PositionMonitor._check_all_positions()` in `alpaca_orchestrator.py` (lines 137-305). Editing it once fixes both the standalone orchestrator and the production `bot_thread` runtime. The phase's framing of "BOTH monitors, keep them behaviorally identical" is satisfied automatically by the shared class; the real work is (a) threading the profile into the one constructor and (b) replacing the soft-threshold LLM branch with ATR math.

`ExitAdvisor.should_exit()` is called in exactly **one place for a decision**: lines 247-254 of `alpaca_orchestrator.py`, inside the `elif threshold in ("soft_stop", "soft_take_profit")` branch. That branch is the entire deletion/replacement surface. Hard stop, trailing stop, and tightened stop already close deterministically without any LLM (lines 235-236) and must be preserved.

ATR is **not persisted** in the DB (`alpaca_trades` has no `atr` column — verified `src/db.py` INSERT, line 70-83). The monitor therefore must **recompute ATR live** from a fresh bar fetch each check. The monitor already fetches bars in the soft branch (`self.alpaca.get_bars(symbol, timeframe="1Hour", limit=10)`, line 246) — extend that fetch to `profile.atr_period + 1` bars and call `technical_signals._atr(highs, lows, closes, profile.atr_period)`. Carrying `Signal.atr_value` from entry is NOT viable (entry-time Signal is gone by monitor time, and a stop should track *current* volatility anyway).

**Primary recommendation:** Add a `profile` parameter to `PositionMonitor.__init__`, extend `TrailingStop` to support ATR-distance + short side (track low-water for shorts), and replace lines 235-272 of `_check_all_positions` with a first-match-wins decision ladder: hard_stop_pct → max_hold → ATR trailing stop → ATR stop. Compute ATR once per position per check from a live bar fetch.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Exit decision (stop/trail/max-hold) | `PositionMonitor` (shared class in alpaca_orchestrator.py) | — | Single class consumed by both orchestrator and bot_thread |
| ATR computation | `technical_signals._atr` | PositionMonitor (caller) | Phase-3 indicator, reused; monitor fetches bars + calls it |
| Trailing-stop state | `TrailingStop` (exit_advisor.py) | PositionMonitor (owns instance) | Per-trade high/low-water tracking; extend for ATR + shorts |
| Profile params | `StrategyProfile` (strategy_profile.py) | PositionMonitor constructor | Immutable config threaded in at construction |
| Position close / DB / alert | `AlpacaClient` + `TradeLogger` + `notifier` | PositionMonitor | Unchanged close path (lines 289-305) |

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Replace the soft_stop/soft_take_profit branch that calls `exit_advisor.should_exit()` with deterministic ATR logic. Compute ATR from the monitor's existing bar fetch (reuse `technical_signals._atr` from Phase 3) over `profile.atr_period`.
- **D-02:** Long: hard stop level = entry − atr_mult_stop×ATR; trail = highwater − atr_mult_trail×ATR, only ratchets up. Short: mirror (entry + atr_mult_stop×ATR; trail from low-water). Reuse the existing `TrailingStop` tracker where it fits; extend for ATR distance + shorts.
- **D-03:** Keep the existing absolute hard-threshold behavior but source the level from `profile.hard_stop_pct` (already wired). Existing trailing-stop and tightened-stop machinery stays; ATR augments/replaces the LLM-advisor branch only.
- **D-04:** Max-hold: compute hours-held from the trade's entry timestamp (the monitor already parses `timestamp`); if `profile.max_hold_hours` is not None and exceeded → immediate close (reason `max_hold`). `None` ⇒ skip (swing unaffected).
- **D-05:** Override ordering (first match wins): hard_stop_pct → max_hold → ATR trailing stop → ATR stop. Document the precedence explicitly.
- **D-06:** `PositionMonitor` (orchestrator) and the `bot_thread.py` monitor must know the active profile. Thread the profile into the monitor constructor (orchestrator passes `PROFILE`; bot_thread resolves `PROFILES.get(BOT_PROFILE, SWING)`).

### Claude's Discretion
- Whether to keep `ExitAdvisor` import present-but-unused this phase (removed Phase 5) or guard it — planner's call, but the monitor must NOT make exit decisions via the LLM after this phase.

### Deferred Ideas (OUT OF SCOPE)
- Delete ExitAdvisor import + mirofish_client + Claude-CLI auth — Phase 5.
- Fee gate — Phase 6.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EXIT-02 | ATR-scaled stop (entry − atr_mult × ATR) + ATR-scaled trailing stop | `_atr` exists (technical_signals.py:162); `profile.atr_mult_stop/atr_mult_trail/atr_period` exist (strategy_profile.py:36-37,59); `TrailingStop` exists (exit_advisor.py:203) but is long-only and pct-based — must extend |
| EXIT-03 | hard_stop_pct + max_hold_hours absolute overrides | `profile.hard_stop_pct` (strategy_profile.py:39) wired; `max_hold_hours: float\|None` (strategy_profile.py:40, SWING=None, DAYTRADE=6.0); hours_held already computed in monitor (alpaca_orchestrator.py:240-244) |

## Standard Stack

No new packages. All capability exists in-repo (Python stdlib + pandas already present). **Package Legitimacy Audit: N/A — phase installs zero external packages.**

| Module | Purpose | Reuse |
|--------|---------|-------|
| `src/technical_signals._atr(highs, lows, closes, period)` | Wilder ATR, returns latest float, 0.0 on insufficient data, needs `period+1` bars | Call from monitor |
| `src/exit_advisor.TrailingStop` | Per-trade-id high-water tracker | Extend for ATR distance + short low-water |
| `src/strategy_profile.StrategyProfile` | atr_mult_stop, atr_mult_trail, atr_period, hard_stop_pct, max_hold_hours | Read in monitor |

## Exact Current Exit-Decision Code (the surface to change)

**ONE class, ONE method:** `PositionMonitor._check_all_positions` in `src/alpaca_orchestrator.py`.

**Constructor (line 109):** `def __init__(self, alpaca, logger, exit_advisor)` — no profile. Add `profile` param.
Owns: `self._tightened: set[int]` (line 119), `self._trailing = TrailingStop()` (line 120).

**Decision ladder today (lines 208-272):**
- L209-211: `trail_trigger = self._trailing.update(...)` — **long-only** (`if side not in ("sell","short")`).
- L216-223: threshold from side-aware `pnl_pct` vs `HARD_STOP_PCT` / `SOFT_STOP_PCT` / `SOFT_TAKE_PROFIT_PCT` (module consts from exit_advisor, pct-based).
- L226-227: tightened_stop check.
- L235-236: `hard_stop`/`tightened_stop`/`trailing_stop` → `should_close = True` (deterministic, NO LLM — preserve).
- **L237-272: the LLM branch — DELETE/REPLACE.** `elif threshold in ("soft_stop","soft_take_profit")` → fetches bars (L246), **calls `self.exit_advisor.should_exit(...)` (L247-254)** → EXIT/TIGHTEN/HOLD. **This is the ONLY decision call to ExitAdvisor.should_exit().**

**hours_held already computed** at L240-244 (only inside the soft branch today): `entry_dt = datetime.fromisoformat(ts.replace("Z","+00:00"))`; `hours_held = (now_utc - entry_dt).total_seconds()/3600`. For max-hold this must move up to fire unconditionally per position.

**Close path (lines 289-305) — unchanged:** `alpaca.close_position`, `logger.update_alpaca_trade(status="closed", exit_price, pnl)`, `self._trailing.remove(trade_id)`, `alert_position_closed(...)`. Side-aware pnl already correct (L199-206). Sub-penny/zero-entry guards present (L186, L190-197).

**Module-level consts imported (line 34):** `HARD_STOP_PCT, SOFT_STOP_PCT, SOFT_TAKE_PROFIT_PCT` from exit_advisor. Post-phase, SOFT_* become unused in the monitor (still used by bot_thread entry logging L569/L711). Hard stop should now read `profile.hard_stop_pct` (D-03) not module `HARD_STOP_PCT` — note SWING `hard_stop_pct=-0.15` equals current `HARD_STOP_PCT=-0.15`, so swing parity holds.

## Architecture Patterns

### ATR math (side-aware)
```
ATR = _atr(highs, lows, closes, profile.atr_period)   # 0.0 if insufficient bars → skip ATR rules, fall back to hard_stop only

LONG:
  atr_stop_level  = entry - profile.atr_mult_stop * ATR
  high_water      = max(seen highs)            # ratchets up only
  atr_trail_level = high_water - profile.atr_mult_trail * ATR
  exit if current <= atr_trail_level (only once high_water advanced past entry) OR current <= atr_stop_level

SHORT:
  atr_stop_level  = entry + profile.atr_mult_stop * ATR
  low_water       = min(seen lows)             # ratchets down only
  atr_trail_level = low_water + profile.atr_mult_trail * ATR
  exit if current >= atr_trail_level OR current >= atr_stop_level
```

### Override precedence (D-05, first match wins)
Implement as an ordered sequence of `if ... : close_reason = X; should_close = True` returning/continuing on first hit:
1. **hard_stop_pct** — `pnl_pct <= profile.hard_stop_pct` (absolute; existing behavior, side-aware pnl_pct already computed L199-206) → reason `hard_stop`.
2. **max_hold** — `profile.max_hold_hours is not None and hours_held > profile.max_hold_hours` → reason `max_hold`. **Guard `is not None` so SWING (None) never time-closes.**
3. **ATR trailing stop** — reason `trailing_stop` (reuse label).
4. **ATR stop** — reason `atr_stop`.
Keep `tightened_stop` (L226-227) — it predates ATR; planner decides whether ATR trail supersedes it. Recommendation: keep tightened check as a 5th rung (it only arms via the now-removed TIGHTEN path, so it becomes dormant but harmless).

### Profile threading (D-06)
- `PositionMonitor.__init__(self, alpaca, logger, exit_advisor, profile)`.
- orchestrator `main()` L620: `PositionMonitor(alpaca, logger, exit_advisor, PROFILE)`.
- bot_thread `_main_loop()` L226: `PositionMonitor(alpaca, logger, exit_advisor, PROFILES.get(os.environ.get("BOT_PROFILE","swing").lower(), SWING))`. (bot_thread already imports `PROFILES, SWING` at L62 and already resolves `_profile` this exact way at L384 — mirror it.)
- **Back-compat option:** default `profile=SWING` keeps any other caller working; verify grep shows only these two instantiation sites.

### TrailingStop extension
Currently `_peaks: dict[int,float]` + pct activation/distance (exit_advisor.py:203-235). Options:
- (A) Add `update_atr(trade_id, side, entry, current, atr, mult_trail, high_low)` method that tracks `_peaks` (long) and a new `_troughs` (short) and returns `"trailing_stop"`. Keep old `update()` untouched for any non-ATR caller.
- (B) New small `ATRTrailingStop` class in exit_advisor.py.
Recommendation: (A) — minimal diff, one tracker instance per monitor, reset via existing `remove()`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ATR | New true-range loop | `technical_signals._atr` | Wilder smoothing already correct, tested, period+1 guard |
| Hours-held | New timestamp parser | Existing L240-244 pattern | Handles `Z`→`+00:00`, UTC-aware |
| Per-trade high-water | New dict | `TrailingStop._peaks` | Already lifecycle-managed via `remove()` on close |
| Side-aware pnl | New formula | Existing L199-206 | Long/short already correct |

## Runtime State Inventory

Rename/refactor-flavored (replacing a decision path). Categories:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `alpaca_trades` rows have NO `atr` column (db.py:70-83). `timestamp`, `entry_price`, `side`, `qty` present and used. | None — recompute ATR live; no migration |
| Live service config | None — exit logic is pure code, no external config | None |
| OS-registered state | None | None |
| Secrets/env vars | `HARD_STOP_PCT/SOFT_STOP_PCT/SOFT_TAKE_PROFIT_PCT` env-overridable (exit_advisor.py:25-27). Monitor moves to `profile.hard_stop_pct`; SOFT_* env vars become inert for exits (still read by bot_thread entry logging). | Document that SOFT_STOP_PCT/SOFT_TAKE_PROFIT_PCT no longer affect exits |
| Build artifacts | None | None |

**Canonical question — what still has the old behavior after files change?** Nothing runtime-stored: the only place the old LLM exit decision lives is the in-memory `PositionMonitor` code. Both consumers (orchestrator, bot_thread) import the same class, so one edit propagates. No DB rows, no Coolify config, no scheduled tasks reference exit logic.

## Common Pitfalls

### Pitfall 1: Gapping the exit path
**What goes wrong:** Removing the soft LLM branch without ATR replacement leaves soft-threshold crossings with no action until hard stop — positions run to -15% before closing. Phase 5 then strips MiroFish assuming ATR is live.
**Avoid:** ATR stop+trail MUST be functional and tested in THIS phase. Verify a soft-zone position closes on ATR trail, not only on hard stop.

### Pitfall 2: ATR returns 0.0 (insufficient bars)
**What goes wrong:** `_atr` returns `0.0` when fewer than `period+1` bars; `entry − mult×0 = entry` → instant exit on any tick.
**Avoid:** If `ATR <= 0`, skip ATR rungs and fall through to hard_stop_pct + max_hold only. Fetch `limit=profile.atr_period + 5` bars to be safe.

### Pitfall 3: Swing time-closes
**What goes wrong:** Forgetting the `is not None` guard time-closes swing positions (SWING `max_hold_hours=None`).
**Avoid:** `if profile.max_hold_hours is not None and hours_held > profile.max_hold_hours`. Test: SWING never returns `max_hold`.

### Pitfall 4: Short trailing using high-water
**What goes wrong:** `TrailingStop` is long-only (guarded at L210). Applying `_peaks` high-water to a short inverts the stop.
**Avoid:** Separate low-water (`_troughs`) for shorts; trail = low_water + mult×ATR; exit when price rises into it.

### Pitfall 5: ATR timeframe mismatch
**What goes wrong:** Monitor hardcodes `timeframe="1Hour"` (L246) but DAYTRADE trades 5Min. ATR on 1h bars is far wider than 5-min volatility → stops never trigger for daytrade.
**Avoid:** Fetch bars at `profile.timeframe`, not hardcoded `"1Hour"`.

## Code Examples

ATR fetch + compute in the monitor (replaces L246-254):
```python
# Source: pattern derived from alpaca_orchestrator.py:246 + technical_signals._atr:162
from src.technical_signals import _atr
bars = self.alpaca.get_bars(symbol, timeframe=self.profile.timeframe,
                            limit=self.profile.atr_period + 5)
atr = 0.0
if bars and len(bars) > self.profile.atr_period:
    highs  = [b["high"]  for b in bars]
    lows   = [b["low"]   for b in bars]
    closes = [b["close"] for b in bars]
    atr = _atr(highs, lows, closes, self.profile.atr_period)
```

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Fixed pct soft stop/TP → LLM consult | ATR-scaled stop + trail, deterministic | No LLM latency/cost/failure in exit path; volatility-adaptive |
| Long-only trailing | Side-aware ATR trail | Shorts get proper trailing |
| Hardcoded 1Hour monitor bars | profile.timeframe | Daytrade exits scale to 5-min volatility |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | ATR should be recomputed live, not carried from entry Signal | Summary | If user wants entry-anchored stops, need DB `atr` column + migration. LOW — D-01 says "from the monitor's bar fetch" |
| A2 | tightened_stop machinery kept dormant (TIGHTEN path removed) | Precedence | If kept active, no harm; dormant is safe |
| A3 | Monitor should fetch bars at profile.timeframe not 1Hour | Pitfall 5 | If kept 1Hour, daytrade stops mis-scale — but matches D-01 intent |

## Open Questions

1. **Does ATR trail replace or coexist with the pct `TrailingStop`?**
   - Known: D-02 says "reuse where it fits; extend for ATR." Pct trail and ATR trail both ratchet.
   - Recommendation: ATR trail supersedes pct trail in the monitor; keep pct logic only if a profile lacks atr_mult_trail (none do).

2. **Keep `tightened_stop` rung?** Recommendation: keep as dormant final rung (zero behavioral change since TIGHTEN is removed).

## Environment Availability

| Dependency | Required By | Available | Notes |
|------------|------------|-----------|-------|
| pandas / stdlib | _atr | ✓ | Already used by technical_signals |

No external services. Code/logic-only phase.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | none detected at repo root — see Wave 0 (check `pyproject.toml`/`pytest.ini`) |
| Quick run command | `python -m pytest tests/test_atr_exits.py -x -q` |
| Full suite command | `python -m pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EXIT-02 | Long ATR stop level = entry − mult×ATR | unit | `pytest tests/test_atr_exits.py::test_long_atr_stop_level -x` | ❌ Wave 0 |
| EXIT-02 | Short ATR stop level = entry + mult×ATR | unit | `pytest tests/test_atr_exits.py::test_short_atr_stop_level -x` | ❌ Wave 0 |
| EXIT-02 | ATR trail ratchets up only (long), down only (short) | unit | `pytest tests/test_atr_exits.py::test_atr_trail_ratchet -x` | ❌ Wave 0 |
| EXIT-02 | ATR<=0 falls back to hard_stop only (no instant exit) | unit | `pytest tests/test_atr_exits.py::test_zero_atr_safe -x` | ❌ Wave 0 |
| EXIT-03 | max_hold closes after N hours (DAYTRADE) | unit | `pytest tests/test_atr_exits.py::test_max_hold_fires -x` | ❌ Wave 0 |
| EXIT-03 | SWING (max_hold None) never time-closes | unit | `pytest tests/test_atr_exits.py::test_swing_no_time_close -x` | ❌ Wave 0 |
| EXIT-03 | Precedence: hard_stop → max_hold → trail → stop | unit | `pytest tests/test_atr_exits.py::test_override_precedence -x` | ❌ Wave 0 |
| EXIT-02/03 | Decision made WITHOUT LLM (assert should_exit not called) | unit | `pytest tests/test_atr_exits.py::test_no_llm_call -x` | ❌ Wave 0 |

**No-LLM test pattern:** construct `PositionMonitor` with a `MagicMock()` exit_advisor, drive a position through each exit type, assert `exit_advisor.should_exit.assert_not_called()`. Mock `alpaca.get_bars`/`get_latest_price`/`get_positions`/`close_position` and `logger.get_open_alpaca_positions`/`update_alpaca_trade`.

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_atr_exits.py -x -q`
- **Per wave merge:** `python -m pytest -q`
- **Phase gate:** full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_atr_exits.py` — covers EXIT-02, EXIT-03 (math, ratchet, precedence, max-hold, swing-skip, no-LLM)
- [ ] `tests/conftest.py` — shared fixture: fake bars generator (known highs/lows for deterministic ATR), mock AlpacaClient/TradeLogger
- [ ] Confirm pytest installed / `pyproject.toml` test config — if absent: `pip install pytest`

## Security Domain

Not applicable beyond existing posture — phase is internal exit-logic refactor with no auth, input, crypto, or network surface changes. No new endpoints, no user input, no secrets touched. `security_enforcement` not configured (no `.planning/config.json`); default ASVS review finds no applicable category for this change (V5 input-validation: ATR inputs are internal bar data, already guarded for empty/insufficient).

## Sources

### Primary (HIGH confidence)
- `src/alpaca_orchestrator.py` PositionMonitor L102-312 — exact exit-decision code, single ExitAdvisor.should_exit call site (L247)
- `src/bot_thread.py` L60-71, L196, L226 — imports & instantiates the SAME PositionMonitor (not duplicated)
- `src/exit_advisor.py` L203-235 — TrailingStop (long-only, pct-based)
- `src/technical_signals.py` L162 — _atr signature
- `src/strategy_profile.py` L36-40,49-92 — atr_mult_*, atr_period, hard_stop_pct, max_hold_hours; SWING(None)/DAYTRADE(6.0)
- `src/db.py` L70-83,118-121 — alpaca_trades schema (no atr column)
- `docs/superpowers/specs/2026-06-08-day-trading-upgrade-design.md` §2 — design intent
- `.planning/REQUIREMENTS.md` — EXIT-02, EXIT-03
- `.planning/phases/04-deterministic-atr-exits/04-CONTEXT.md` — D-01..D-06

## Metadata

**Confidence breakdown:**
- Exit-decision mapping: HIGH — read both files in full, confirmed shared class
- ATR/profile reuse: HIGH — signatures and fields verified in source
- Pitfalls: HIGH — derived from concrete code guards and timeframe mismatch
- Test plan: MEDIUM — pytest assumed standard; test files do not yet exist (Wave 0)

**Research date:** 2026-06-08
**Valid until:** 2026-07-08 (stable; internal code)
