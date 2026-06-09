# Phase 1: StrategyProfile Abstraction + SWING Parity - Research

**Researched:** 2026-06-08
**Domain:** Python config-object refactor (frozen dataclass), behavior-preserving extraction of scattered module constants
**Confidence:** HIGH (all claims VERIFIED against repo source this session)

## Summary

This is a pure, mechanical refactor: introduce `src/strategy_profile.py` with a frozen
`StrategyProfile` dataclass and a `SWING` preset whose field values equal the **current
effective defaults** in `src/alpaca_orchestrator.py` / `src/technical_signals.py`, then
re-source those constants from the profile. No control flow, threshold, or ordering changes.

The single sharpest hazard is **env-override precedence**. Today every style constant is
`int/float(os.environ.get("NAME", "<default>"))` evaluated at *import time*. The profile must
supply the **default**, while the existing `os.environ.get` layer continues to win — so bots
A/B running with their current Coolify env produce byte-identical behavior. The minimal-diff
pattern is: keep the `os.environ.get(NAME, str(SWING.<field>))` shape (env still wins, default
now sourced from profile) rather than replacing the env layer.

A second subtlety: indicator periods (9/21/14) are hardcoded as **literals inside
`technical_signals.py`** (`_ema(closes, 9)`, `_adx(..., 14)`, `_rsi(..., 14)`), NOT read from
the orchestrator constants. SIGNAL parameterization is Phase 3. **Phase 1 should only make the
profile CARRY these periods** (so SWING.ema_fast==9 etc.) and must NOT rewire `technical_signals.py`.

**Primary recommendation:** Add `src/strategy_profile.py` (frozen dataclass + `SWING` + `PROFILES`
dict). In `alpaca_orchestrator.py`, resolve a module-level `PROFILE = SWING` and change each
style constant to `os.environ.get(NAME, str(PROFILE.<field>))`. Leave `technical_signals.py`
math and literals untouched; the profile merely records 9/21/14/50/timeframes for later phases.
Add `tests/test_strategy_profile.py` asserting SWING field values == today's literals.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Profile definition (dataclass + SWING preset) | Config / value-object (`src/strategy_profile.py`) | — | New immutable value object, peer to `Config` |
| Constant resolution (env-override on profile default) | Orchestrator module-init (`alpaca_orchestrator.py`) | strategy_profile | Env precedence must live where constants are read |
| Indicator math (EMA/ADX/RSI) | Signal engine (`technical_signals.py`) | — | Untouched this phase; profile only carries periods |
| Sizing (kelly_fraction) | Config (`load_config`) | strategy_profile mirrors value | `kelly_fraction` already lives in `Config`; profile duplicates the default for parity |

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PROFILE-01 | `StrategyProfile` object bundles timeframe, scan cadence, indicator periods, exit params, max-hold, sizing | Field set enumerated below (D-02); frozen-dataclass pattern matches existing `Config` (`config.py:34`) |
| PROFILE-02 | `SWING` preset reproduces current behavior byte-for-byte (bots A/B unaffected) | Exact current values table below, all VERIFIED from source; parity test design in Validation Architecture |

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** New module `src/strategy_profile.py`. `StrategyProfile` is a frozen `@dataclass`.
- **D-02:** Fields: `name`, `timeframe`, `scan_interval_s`, `bar_count`, `htf_filter_timeframe`,
  `ema_fast`, `ema_slow`, `rsi_period`, `adx_period`, `atr_period`, `atr_mult_stop`,
  `atr_mult_trail`, `hard_stop_pct`, `max_hold_hours` (`None` ⇒ overnight), `kelly_fraction`,
  `max_position_pct`, `min_confluence`, `min_short_confluence`.
- **D-03:** Presets as module constants `SWING` + `PROFILES` dict keyed by name. DAYTRADE is Phase 2 — do NOT define here.
- **D-04:** SWING values MUST equal current effective defaults (table below).
- **D-05:** Existing env overrides (`MIN_CONFLUENCE`, `CYCLE_SLEEP_SECONDS`, etc.) MUST continue to win.
- **D-06:** Refactor is mechanical: replace constant reads with profile-sourced defaults; no control-flow/threshold/ordering change.

### Claude's Discretion
- Wiring style (pass `profile` through `main()` vs module-level resolved profile) is the planner's
  call, provided env-override precedence (D-05) holds and the diff stays minimal (Karpathy).

### Deferred Ideas (OUT OF SCOPE)
- DAYTRADE preset + `BOT_PROFILE` selection — Phase 2.
- ATR fields present on the profile now but only *consumed* in Phase 4 (exits) — define here, wire later.
- SIGNAL parameterization of `technical_signals.py` — Phase 3.

## Standard Stack

No new dependencies. Uses Python stdlib `dataclasses` (frozen=True), already used by `Config`
(`src/config.py:34`) — establishes the house pattern. `os.environ.get` already pervasive.

### Package Legitimacy Audit
No external packages installed this phase. Audit: N/A.

## Current SWING Values — Field → Literal → Source (VERIFIED)

> Every value confirmed by reading repo source this session. This is the parity contract.

| Profile field | Current value | Source location | Env override (today) |
|---------------|---------------|-----------------|----------------------|
| `name` | `"swing"` | (new) | — |
| `timeframe` | `"1Hour"` | `alpaca_orchestrator.py:722,1139` (scan_assets call), `:235,:462` | none (literal arg) |
| `scan_interval_s` | `1800` | `alpaca_orchestrator.py:73` `CYCLE_SLEEP_SECONDS` | `CYCLE_SLEEP_SECONDS` |
| `bar_count` | `50` | `alpaca_orchestrator.py:722,1139` (`bar_count=50`); `scan_assets` default `:419` | none (literal arg) |
| `htf_filter_timeframe` | `"4Hour"` | `technical_signals.py:455` (`timeframe="4Hour"`), `alpaca_orchestrator.py:473` | none (literal arg) |
| `ema_fast` | `9` | `technical_signals.py:241` `_ema(closes,9)`, `:363` | none (literal) |
| `ema_slow` | `21` | `technical_signals.py:242` `_ema(closes,21)`, `:364` | none (literal) |
| `rsi_period` | `14` | `technical_signals.py:269` `_rsi(closes,14)` | none (literal) |
| `adx_period` | `14` | `technical_signals.py:255` `_adx(...,14)` | none (literal) |
| `atr_period` | `14` | NOT YET USED (Phase 4); set 14 for parity-neutral default [ASSUMED — see Assumptions A1] | — |
| `atr_mult_stop` | (Phase 4) | NOT YET USED | — |
| `atr_mult_trail` | (Phase 4) | NOT YET USED | — |
| `hard_stop_pct` | `-0.15` | `exit_advisor.py:27` `HARD_STOP_PCT` | `HARD_STOP_PCT` |
| `max_hold_hours` | `None` | swing has no max-hold today (overnight allowed) | — |
| `kelly_fraction` | `0.25` | `config.py:54` Config default / `:142` `KELLY_FRACTION` env | `KELLY_FRACTION` (via load_config) |
| `max_position_pct` | `0.05` | `alpaca_orchestrator.py:52` `MAX_POSITION_PCT` (also `config.py:53`) | `MAX_POSITION_PCT` |
| `min_confluence` | `4` | `alpaca_orchestrator.py:57` `MIN_CONFLUENCE` | `MIN_CONFLUENCE` |
| `min_short_confluence` | `3` | `alpaca_orchestrator.py:59` `MIN_SHORT_CONFLUENCE` | `MIN_SHORT_CONFLUENCE` |

**Not in profile (leave as-is, out of scope):** `MAX_TOTAL_EXPOSURE_PCT` (0.80), `DRAWDOWN_STOP_PCT`
(0.10), `MIN_PAPER_TRADES` (50), `MIN_WIN_RATE` (0.40), `POSITION_CHECK_INTERVAL` (60),
`BEAR_MARKET_PAUSE_THRESHOLD` (0.60), `LIVE_TRADING_THRESHOLD` (100000), `SHORT_ENABLED`,
`SKIP_RISK_GATE`, `_ALPACA_UNTRADEABLE`, `DYNAMIC_UNIVERSE_SIZE`. The CONTEXT field set (D-02)
deliberately excludes these — they are not style-varying. Do NOT pull them into the profile.

## Refactor Surface — Use-Sites in alpaca_orchestrator.py (VERIFIED)

Constants the profile replaces, and where they are consumed:

| Constant | Definition | Use-sites (line) |
|----------|-----------|------------------|
| `MAX_POSITION_PCT` | `:52` | `:329` (banner), `:881`, `:985` (`_kelly_technical` arg) |
| `MIN_CONFLUENCE` | `:57` | `:328` (banner), `:390` (inside `_kelly_technical`), `:747`, `:1152`, `:1155`, `:1166` |
| `MIN_SHORT_CONFLUENCE` | `:59` | `:759` |
| `CYCLE_SLEEP_SECONDS` | `:73` | `:335` (banner), `:716`, `:727`, `:1081`, `:1082` |
| `HARD_STOP_PCT` (imported from exit_advisor) | `exit_advisor.py:27` | `:205`, `:331` (banner), `:911`, `:1012` |
| `timeframe="1Hour"`/`bar_count=50` literals | inline | `:722`, `:1139` (scan_assets); `:235`,`:801`,`:956` (monitor/other `get_bars`) |

**Critical parity note — `_kelly_technical` default vs call-site:** `_kelly_technical`
(`:378-383`) declares `kelly_fraction=0.25, max_position_pct=0.05` as *function defaults*, but
both real call-sites (`:880-881`, `:984-985`) explicitly pass `config.kelly_fraction` and
`MAX_POSITION_PCT`. The function defaults are dead for the live path. If the refactor sources
these from the profile at the call-sites, parity holds; do NOT change the function signature
defaults (Karpathy: smallest diff, no drive-by).

**`MIN_CONFLUENCE` referenced inside `_kelly_technical:390`** — it reads the module global
directly. After refactor this global must still resolve to the same value (4) or the function
must read `profile.min_confluence`. Easiest minimal-diff: keep a module-level `MIN_CONFLUENCE`
name bound to `os.environ.get("MIN_CONFLUENCE", str(PROFILE.min_confluence))` so the in-function
reference is unchanged. (Confirms why module-level resolved profile is the lower-risk wiring.)

## Indicator Periods — Phase 1 Boundary (technical_signals.py)

Hardcoded literals (VERIFIED): `_ema(closes,9)` `:241,:363`; `_ema(closes,21)` `:242,:364`;
`_adx(highs,lows,closes,14)` `:255`; `_rsi(closes,14)` `:269`. `scan_assets` already takes
`timeframe`/`bar_count` params (`:415-419`) with swing defaults; the 4H HTF fetch limit=30 is at `:455`.

**Phase 1 action: NONE on these literals.** The profile records `ema_fast/ema_slow/rsi_period/adx_period`
for Phase 3 to consume, but rewiring `analyze()` to take periods from the profile is SIGNAL-01
(Phase 3, deferred). Touching them now risks parity drift and exceeds scope. Recommended minimal-diff
boundary: **profile carries the periods; `technical_signals.py` is read-only this phase.**

## Architecture Patterns

### Pattern 1: Frozen dataclass value object (matches existing Config)
```python
# Source: mirrors src/config.py:34 @dataclass(frozen=True) Config
from dataclasses import dataclass

@dataclass(frozen=True)
class StrategyProfile:
    name: str
    timeframe: str
    scan_interval_s: int
    bar_count: int
    htf_filter_timeframe: str
    ema_fast: int
    ema_slow: int
    rsi_period: int
    adx_period: int
    atr_period: int
    atr_mult_stop: float
    atr_mult_trail: float
    hard_stop_pct: float
    max_hold_hours: float | None
    kelly_fraction: float
    max_position_pct: float
    min_confluence: int
    min_short_confluence: int

SWING = StrategyProfile(
    name="swing", timeframe="1Hour", scan_interval_s=1800, bar_count=50,
    htf_filter_timeframe="4Hour", ema_fast=9, ema_slow=21, rsi_period=14,
    adx_period=14, atr_period=14, atr_mult_stop=2.0, atr_mult_trail=1.5,
    hard_stop_pct=-0.15, max_hold_hours=None, kelly_fraction=0.25,
    max_position_pct=0.05, min_confluence=4, min_short_confluence=3,
)
PROFILES = {"swing": SWING}
```
(atr_mult_* are placeholders consumed only in Phase 4 — values are not parity-load-bearing now.)

### Pattern 2: Env-wins-over-profile-default (the precedence contract, D-05)
```python
# alpaca_orchestrator.py — env still wins; default now sourced from profile
from src.strategy_profile import SWING, PROFILES
PROFILE = SWING  # Phase 2 will select via BOT_PROFILE env

MAX_POSITION_PCT = float(_os.environ.get("MAX_POSITION_PCT", str(PROFILE.max_position_pct)))
MIN_CONFLUENCE   = int(_os.environ.get("MIN_CONFLUENCE",   str(PROFILE.min_confluence)))
CYCLE_SLEEP_SECONDS = int(_os.environ.get("CYCLE_SLEEP_SECONDS", str(PROFILE.scan_interval_s)))
```
This keeps every existing module-global *name* alive (so the `:390` in-function read and all
banner/use-sites are untouched) while sourcing the default from the profile. Smallest diff.

### Anti-Patterns to Avoid
- **Replacing the env layer with a pure `profile.<field>` read** — breaks D-05; bots A/B that
  set `MIN_CONFLUENCE`/`CYCLE_SLEEP_SECONDS` in Coolify env would silently revert to profile defaults.
- **Mutating the profile at runtime** — it is frozen; do not attempt per-call override by mutation.
- **Rewiring `technical_signals.py` periods now** — that is Phase 3; doing it here is scope creep + parity risk.
- **Pulling non-style constants (exposure, drawdown) into the profile** — not in D-02 field set.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Immutable preset object | custom `__setattr__` guard | `@dataclass(frozen=True)` | stdlib, matches `Config` |
| Env coercion | new parser | existing `int/float(os.environ.get(...))` pattern | preserves exact current behavior |

## Common Pitfalls

### Pitfall 1: Import-time evaluation order
**What goes wrong:** module-level constants are computed at import. If `PROFILE` is defined *after*
the constants that reference it, you get `NameError`.
**How to avoid:** import `SWING`/`PROFILES` and bind `PROFILE = SWING` at the TOP of the constants
block (before line 52), so all `os.environ.get(..., str(PROFILE.x))` calls resolve.
**Warning sign:** `ImportError`/`NameError` at orchestrator startup.

### Pitfall 2: Env precedence regression (highest risk)
**What goes wrong:** dropping the `os.environ.get` wrapper changes behavior for any bot whose
Coolify env sets that var. Bot B is documented to run different params (Kelly 0.50, conf 2 — see memory).
**How to avoid:** preserve env-wins shape; add a test that sets an env var and asserts it overrides the profile default.
**Warning sign:** Bot B equity curve changes after deploy.

### Pitfall 3: `kelly_fraction` double-source
**What goes wrong:** `kelly_fraction` lives in BOTH `Config` (`config.py:54`, env `KELLY_FRACTION`)
and now the profile. If the orchestrator starts reading `profile.kelly_fraction` instead of
`config.kelly_fraction`, the `KELLY_FRACTION` env override (used by Bot B) is bypassed.
**How to avoid:** for parity, keep call-sites passing `config.kelly_fraction` (`:880,:984`). The
profile's `kelly_fraction=0.25` documents the swing default but must NOT replace the `config` read
this phase. Flag this boundary explicitly to the planner.
**Warning sign:** Bot B (Kelly 0.50) sizes positions as if 0.25.

### Pitfall 4: `1Hour`/`bar_count` literals at non-scan call-sites
**What goes wrong:** `get_bars(..., timeframe="1Hour", limit=...)` appears at `:235,:462,:473,:801,:956`
for monitor/regime/exit logic with various limits (10/50/24). These are NOT all the scan timeframe.
**How to avoid:** only the `scan_assets` calls (`:722,:1139`) represent the profile `timeframe`/`bar_count`.
Do not blanket-replace every `"1Hour"` string — the monitor's 1Hour fetches are independent. Minimal-diff: leave them.

## Code Examples

### Parity test (the core deliverable verification)
```python
# tests/test_strategy_profile.py
from src.strategy_profile import SWING, PROFILES

def test_swing_values_match_current_constants():
    assert SWING.timeframe == "1Hour"
    assert SWING.scan_interval_s == 1800
    assert SWING.bar_count == 50
    assert SWING.htf_filter_timeframe == "4Hour"
    assert (SWING.ema_fast, SWING.ema_slow) == (9, 21)
    assert SWING.rsi_period == 14 and SWING.adx_period == 14
    assert SWING.hard_stop_pct == -0.15
    assert SWING.max_hold_hours is None
    assert SWING.kelly_fraction == 0.25
    assert SWING.max_position_pct == 0.05
    assert SWING.min_confluence == 4 and SWING.min_short_confluence == 3

def test_profile_is_frozen():
    import dataclasses, pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        SWING.min_confluence = 2

def test_profiles_registry():
    assert PROFILES["swing"] is SWING

def test_env_override_wins_over_profile_default(monkeypatch):
    monkeypatch.setenv("MIN_CONFLUENCE", "2")
    import importlib, src.alpaca_orchestrator as o
    importlib.reload(o)
    assert o.MIN_CONFLUENCE == 2  # env beats profile default of 4
```

## Runtime State Inventory

Refactor phase — runtime state check:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no stored value keys on these constant names; trades.db is Postgres, schema unaffected | none |
| Live service config | Coolify env vars `MIN_CONFLUENCE`, `CYCLE_SLEEP_SECONDS`, `MAX_POSITION_PCT`, `KELLY_FRACTION`, `HARD_STOP_PCT` etc. set per-bot (A/B). These must continue to override (D-05) — code-only change, env keys unchanged | preserve env-override layer; no env edits |
| OS-registered state | None | none |
| Secrets/env vars | No secret renames; the listed env vars are config not secrets, names unchanged | none |
| Build artifacts | None — no packaging change, no entry-point rename | none |

**Canonical question answer:** After the refactor, the only runtime state that references these
names is the Coolify per-bot env config. Because the env-override layer is preserved (D-05), no
migration is needed — verified by the env-precedence test.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing `tests/*.py`, e.g. `tests/test_technical_signals.py`, import `from src...`) |
| Config file | none at root — pytest uses default discovery; tests import `src.` (run from repo root) |
| Quick run command | `python -m pytest tests/test_strategy_profile.py -x -q` |
| Full suite command | `python -m pytest tests/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROFILE-01 | Profile object exists with full field set, frozen | unit | `python -m pytest tests/test_strategy_profile.py::test_profile_is_frozen -x` | ❌ Wave 0 |
| PROFILE-01 | `PROFILES` registry keyed by name | unit | `python -m pytest tests/test_strategy_profile.py::test_profiles_registry -x` | ❌ Wave 0 |
| PROFILE-02 | SWING values == current constants | unit | `python -m pytest tests/test_strategy_profile.py::test_swing_values_match_current_constants -x` | ❌ Wave 0 |
| PROFILE-02 | Env override still wins (D-05) | unit | `python -m pytest tests/test_strategy_profile.py::test_env_override_wins_over_profile_default -x` | ❌ Wave 0 |
| PROFILE-02 | No regression in existing signal/exit tests | unit | `python -m pytest tests/test_technical_signals.py tests/test_exit_advisor.py -q` | ✅ |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_strategy_profile.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -q`
- **Phase gate:** Full suite green + the two existing pre-refactor tests still pass unchanged.

### Wave 0 Gaps
- [ ] `tests/test_strategy_profile.py` — covers PROFILE-01, PROFILE-02 (4 tests above)
- [ ] No framework install needed (pytest already used)

## Security Domain

`security_enforcement` not relevant to this phase — no auth, network, input-handling, or crypto
changes. No new attack surface (constant extraction, no I/O). ASVS categories: none applicable.

## Environment Availability

Code-only refactor; only dependency is the existing Python env + pytest. No external services.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pytest | parity tests | ✓ (existing tests run) | — | — |
| Python stdlib `dataclasses` | profile | ✓ | — | — |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `atr_period=14`, `atr_mult_stop=2.0`, `atr_mult_trail=1.5` are reasonable placeholders for swing | SWING values table | LOW — not consumed until Phase 4; swing uses %-stop (`hard_stop_pct=-0.15`) today, so ATR fields are inert in Phase 1. Planner/Phase 4 confirms real swing ATR multipliers. |

## Open Questions

1. **Should the orchestrator read `profile.kelly_fraction` or keep `config.kelly_fraction`?**
   - What we know: Bot B overrides Kelly via `KELLY_FRACTION` env → `config.kelly_fraction`.
   - What's unclear: whether Phase 2 wants profile to own kelly.
   - Recommendation: Phase 1 keeps `config.kelly_fraction` at call-sites (parity). Profile's value
     is documentary only this phase. Revisit in Phase 2.

## Sources

### Primary (HIGH confidence)
- `src/alpaca_orchestrator.py:34,52-81,205,235,328-335,378-410,722,747,759,801,865-911,956-1012,1081-1166` — constants + use-sites (read this session)
- `src/technical_signals.py:241-269,361-364,415-455` — hardcoded periods + scan_assets (read this session)
- `src/config.py:34,53-54,140-146` — frozen Config pattern, kelly_fraction/KELLY_FRACTION env (read this session)
- `src/exit_advisor.py:25-27` — HARD_STOP_PCT=-0.15 (read this session)
- `.planning/codebase/CONVENTIONS.md` — house style, env-override-with-default pattern
- `.planning/phases/01-.../01-CONTEXT.md`, `.planning/REQUIREMENTS.md` — locked decisions, PROFILE-01/02

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps, stdlib dataclass mirrors existing Config
- SWING values: HIGH — every value read from source this session
- Refactor surface: HIGH — use-sites grepped and line-verified
- Pitfalls: HIGH — derived from observed call-site/env coupling

**Research date:** 2026-06-08
**Valid until:** 2026-07-08 (stable; only drifts if constants change before planning)
