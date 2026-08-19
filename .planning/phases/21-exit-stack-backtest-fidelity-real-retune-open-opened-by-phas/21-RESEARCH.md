# Phase 21: Exit-Stack Backtest Fidelity + Real Retune - Research

**Researched:** 2026-07-20
**Domain:** Backtest engine fidelity (Python trading system) — modeling the live deterministic exit ladder + entry/exit knob sweep
**Confidence:** HIGH (all findings from direct codebase reads; no external deps)

## Summary

Phase 18 ran a well-formed entry-knob sweep and honestly recorded a negative result, but its
own `18-BACKTEST.md` FIDELITY GAP section (lines 176-246) names the reason the sweep was
unfalsifiable: **the backtester models only two flat thresholds** (`HARD_STOP_PCT=-0.15`,
`HARD_TAKE_PROFIT_PCT=+0.30`) while the **live swing bot runs a 4-rung deterministic ATR exit
ladder** with a `-0.08` hard stop. Phase 17 located the actual losses on the EXIT side; the
Phase 18 sweep looked for them on the entry side. Phase 21 closes that gap.

The good news: **everything needed to model the live ladder faithfully already exists in the
repo and is fully deterministic and reproducible.** The `TrailingStop.update_atr` method
(`src/exit_advisor.py:234-278`) and the `_atr` helper (`src/technical_signals.py:162-183`) are
the exact primitives the live monitor calls. The backtester already loads full OHLC bars and
keeps a 50-bar sliding window per symbol — ATR is computable per-bar with zero new data.

**Primary recommendation:** Extract the live deterministic exit ladder (`alpaca_orchestrator.py:316-345`)
into ONE shared, pure, side-aware helper that both the live monitor and the backtest engine call.
Source the five exit knobs from `StrategyProfile`. Extend `sweep_backtest.py` to grid over
entry AND exit knobs. Keep the `18-HOLDOUT.lock` discipline. Report the honest result — pass or
documented negative — against the true model.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Per-bar ATR computation | Backtest engine (`engine.py`) | `technical_signals._atr` (reused) | Engine already holds the OHLC window; ATR is a pure function of it |
| Exit precedence decision | Shared exit helper (new, extracted) | live monitor + engine both call it | D-02: single source of truth, no live/backtest drift |
| Exit knob values | `StrategyProfile` | `PhaseConfig`/CLI overrides | D-03: sweep varies knobs the same way it varies entry knobs |
| Grid orchestration | `scripts/sweep_backtest.py` | fresh subprocess per cell | Reproducibility (BAR_CACHE_DIR baked at import) |
| Holdout gate | `18-HOLDOUT.lock` + `passes_bar` | — | D-04: no holdout peeking |

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Model the full live exit precedence in the backtester exactly as
  `alpaca_orchestrator.py:317-331`: `hard_stop -> max_hold -> ATR trailing -> ATR fixed`, plus
  soft stop/take. `[auto] recommended — fidelity to live is the entire point of the phase.`
  **⚠️ RESEARCH CORRECTION (see Pitfall 1): the LIVE deterministic ladder does NOT execute a
  soft-stop/soft-take rung — those route to a now-UNWIRED LLM advisor. Model the 4 deterministic
  rungs faithfully; "soft stop/take" is a dead path in the live monitor.**
- **D-02:** Reuse the SINGLE source of truth — import constants + the `TrailingStop` class and any
  exit-decision helpers from `src/exit_advisor.py`; do NOT fork/duplicate the exit logic into the
  backtester. Extract shared exit-decision logic into a reusable function if needed.
- **D-03:** Exit knobs (`hard_stop_pct`, `soft_stop_pct`, ATR trailing multiplier, ATR fixed-stop
  multiplier, `max_hold_hours`) come from `StrategyProfile` (`src/strategy_profile.py` /
  `src/bot_config.py`), so the sweep varies them the same way it varies entry knobs.
- **D-04:** Sweep the grid over BOTH entry knobs (confluence threshold, Kelly fraction) AND exit
  knobs. Report the best train cell, then validate on the Phase 18 holdout under `18-HOLDOUT.lock`
  discipline — no holdout peeking during selection.
- **D-05:** TUNE-01 closes only if the retune produces a validated, non-degenerate result against
  the real exit model. If the sweep still cannot beat the criterion, record the honest negative.

### Claude's Discretion
- Exact grid resolution / knob ranges, ATR window length, and any parallelization of the sweep.
- Whether to refactor exit logic into a shared helper vs import-in-place (D-02 intent preserved).
- Backtest data window and bar granularity (subject to matching prior phases' harness).

### Deferred Ideas (OUT OF SCOPE)
- Redesigning the live exit logic (only measured here).
- Live-mode promotion / paper-gate changes.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TUNE-01 | Retune confluence entry threshold + quarter-Kelly sizing using the real resolved-trade dataset + backtest harness, targeting win rate ≥40% and halted drawdown. Currently PARTIAL — entry-only sweep was unfalsifiable because the backtest exit model (flat -15%/+30%) did not match the live ATR ladder. | This phase makes the engine model the live exit ladder (§Live Exit Stack), sources knobs from StrategyProfile (§Knobs), and re-runs the sweep over entry+exit knobs (§Sweep Harness). Closes the fidelity gap named in `18-BACKTEST.md:176-246`. |
</phase_requirements>

## Standard Stack

No new external packages. Everything is in-repo. Version-verification / Package Legitimacy Audit
sections are **N/A** — this phase installs nothing.

| Component | Location | Role in Phase 21 |
|-----------|----------|------------------|
| `_atr` (Wilder) | `src/technical_signals.py:162-183` | Per-bar ATR in the backtest, identical formula to live |
| `TrailingStop.update_atr` | `src/exit_advisor.py:234-278` | ATR trailing rung — side-aware, arms only in profit, ratchets |
| exit constants | `src/exit_advisor.py:25-33` | `HARD_STOP_PCT` etc. (but see D-03: prefer StrategyProfile) |
| `StrategyProfile` | `src/strategy_profile.py:23-68` | The knob source: `hard_stop_pct`, `atr_mult_stop`, `atr_mult_trail`, `atr_period`, `max_hold_hours` |
| `BacktestEngine.run` | `src/backtester/engine.py:44-169` | The position-close loop to replace |
| `sweep_backtest.py` | `scripts/sweep_backtest.py` | Grid driver to extend (entry→entry+exit) |

## Architecture Patterns

### System Data Flow

```
cached OHLC bars (data/backtest_bars/<SYM>_1Hour.json)
        │
        ▼
BacktestEngine.run — per timestamp, per symbol:
   advance 50-bar sliding window ──► compute ATR from window (NEW)
        │                                   │
        ▼                                   ▼
  [EXITS] for each open position:  shared_exit_ladder(profile, pos, price, atr, hours_held, trailing)
        │      rung 1 hard_stop  → close
        │      rung 2 max_hold   → close      ◄── SAME helper the live monitor calls
        │      rung 3 ATR trail  → close
        │      rung 4 ATR fixed  → close
        ▼
  [ENTRIES] confluence≥mc, rsi<ceiling, entry_allowed, throttled → open
        │
        ▼
  equity curve ──► metrics.compute_summary ──► sweep cell row ──► passes_bar()
```

### CURRENT backtester exit model (what exists today)

`src/backtester/engine.py:89-105` — the entire exit logic:
- Iterates `open_trade_ids` per timestamp; `price = current_prices[sym]` (the bar close).
- Computes `pnl_pct = (price - entry_price) / entry_price` (LONG-ONLY — no side awareness).
- Two flat rungs only: `pnl_pct <= HARD_STOP_PCT` (-0.15) → close `"hard_stop"`;
  `pnl_pct >= HARD_TAKE_PROFIT_PCT` (+0.30) → close `"hard_take_profit"`.
- A "trade" = `_Position` dataclass (`portfolio.py:11-18`); closed via
  `BacktestPortfolio.close_position(trade_id, exit_price, ts, reason)` → appends to `_history`.
- Force-close at end-of-window (`engine.py:157-166`, reason `"end_of_backtest"`).
- **This is exactly where the new ladder slots in** (replace lines 89-105).

Data available per bar: `normalise_bar` (`data_loader.py:23-34`) guarantees
`open/high/low/close/volume/vwap` floats. The engine already keeps `windows[sym]` (≥50 bars) →
**ATR needs no new data source.**

### LIVE exit stack (what to mirror) — `src/alpaca_orchestrator.py:283-345`

Fully deterministic ladder, FIRST-MATCH WINS, comment on `:318` says "No LLM: exits are fully
deterministic":

| Rung | Condition (`alpaca_orchestrator.py`) | Constant source |
|------|--------------------------------------|-----------------|
| 0 (side) | LONG: `pnl_pct=(cur-entry)/entry`; SHORT: `(entry-cur)/entry` (`:283-290`) | — |
| 1 hard_stop | `pnl_pct <= profile.hard_stop_pct` (`:322`) | `StrategyProfile.hard_stop_pct` (swing `-0.08`) |
| 2 max_hold | `max_hold_hours is not None and hours_held > max_hold_hours` (`:325`) | swing `168.0`, daytrade `6.0`, `None`=never |
| 3 ATR trail | `atr>0 and trailing.update_atr(id, side, entry, cur, atr, atr_mult_trail)` (`:328-330`) | swing `atr_mult_trail=1.5` |
| 4 ATR fixed | `atr>0`; LONG `cur <= entry - atr_mult_stop*atr`; SHORT `cur >= entry + atr_mult_stop*atr` (`:333-341`) | swing `atr_mult_stop=2.0` |
| 5 (dormant) | `_tightened` tightened-stop — never set this phase (`:343-345`) | — |

- **ATR computation (live):** `_atr(highs, lows, closes, profile.atr_period)` over
  `atr_period + 5` bars (`:302-312`). `atr=0.0` on insufficient bars → rungs 3 & 4 both skip.
- **`TrailingStop.update_atr` semantics** (`exit_advisor.py:234-278`): LONG ratchets a
  high-water peak up only; arms only once peak > entry (in profit); trail = `peak - mult*atr`;
  triggers when `current <= trail`; clears tracking on trigger. SHORT is the mirror (trough,
  `+mult*atr`, `current >= trail`). `atr<=0 or entry<=0` → None.
- **Reusable vs live-only:** `_atr`, `TrailingStop`, all constants, the pnl/side math, the
  4-rung precedence = **100% reusable, pure, no broker**. Live-only = the `self.alpaca.close_position`
  call, fee/fill reconciliation (`:366-397`), DB writes, alerts. The backtest substitutes
  `portfolio.close_position` for all of that.

### Recommended shared-helper shape (D-02)

Extract a pure function, e.g. `src/exit_ladder.py`:
```python
def evaluate_exit(profile, side, entry_price, current_price, hours_held,
                  atr, trailing: TrailingStop, trade_id) -> str | None:
    # returns "hard_stop" | "max_hold" | "trailing_stop" | "atr_stop" | None
```
Live monitor (`alpaca_orchestrator.py:316-345`) and `engine.py` both call it. This is the
cleanest way to satisfy D-02 "same code, no drift" — import-in-place is possible but the live
ladder is currently inline in a 130-line method mixed with broker/DB/alert code, so extraction
is the lower-risk path. **Add a parity test** asserting the extracted helper reproduces the old
inline decision on a table of cases (guards against a silent extraction bug).

### Anti-Patterns to Avoid
- **Re-implementing the ladder in the engine** (forks the source of truth — D-02 forbids).
- **Long-only ATR stop.** The live helper is side-aware; even if the backtest stays long-only
  for now, call the side-aware helper with `side="buy"` so shorts can be added later without a
  second code path.
- **Recomputing ATR from scratch each bar with a fresh list** — fine for correctness, but note
  the live bot fetches `atr_period+5` bars; match that window length for parity.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ATR per bar | New ATR math in engine | `src/technical_signals._atr` | Live uses this exact Wilder impl; any reimpl drifts |
| Trailing stop state | New peak/trough tracking | `TrailingStop.update_atr` | Exact live ratchet/arm semantics incl. tighten threshold |
| Exit precedence | New if/elif chain in engine | Extracted shared `evaluate_exit` | D-02 single source of truth |
| Grid subprocess/repro | New runner | Extend `scripts/sweep_backtest.py` | BAR_CACHE_DIR-at-import repro trap already solved (`sweep_backtest.py:14-19`) |
| Holdout gate | New lock logic | `18-HOLDOUT.lock` + `passes_bar` | Discipline already coded and enforced |

**Key insight:** the phase is a *fidelity* task, not a *design* task — maximum reuse of the live
primitives is the whole point. New code should be glue (call the helper per bar) + parameter
plumbing (StrategyProfile → engine), not new trading logic.

## Knobs (D-03) — where they live and how the sweep varies them

| Knob | StrategyProfile field | swing default | In backtest today? | Sweep plumbing needed |
|------|----------------------|---------------|--------------------|-----------------------|
| confluence threshold | `min_confluence` | 4 | YES (`PhaseConfig.min_confluence`, `--min-confluence`) | exists |
| Kelly fraction | `kelly_fraction` | 0.25 (hard CEILING) | YES (`--kelly-fraction`, capped ≤0.25 at `cli.py:57`) | exists |
| hard stop | `hard_stop_pct` | -0.08 | NO (engine uses -0.15 constant) | ADD to PhaseConfig + CLI |
| ATR fixed mult | `atr_mult_stop` | 2.0 | NO | ADD |
| ATR trail mult | `atr_mult_trail` | 1.5 | NO | ADD |
| ATR period | `atr_period` | 14 | NO | ADD (or fix at 14) |
| max hold hrs | `max_hold_hours` | 168.0 | NO | ADD |
| soft stop | `soft_stop_pct` | -0.05 (`BotConfig`) | N/A — dead path (Pitfall 1) | do NOT model as active |

**Kelly ceiling is HARD-ENFORCED** (`cli.py:56-59`, `bot_config.from_row:53`): the sweep may
lower Kelly but `--kelly-fraction > 0.25` is a `parser.error`. Keep this in any new grid.

**Note the engine currently reads `PhaseConfig`, not `StrategyProfile`.** Two viable paths:
(a) add the exit fields to `PhaseConfig` (matches the existing `--min-confluence`/`--kelly` CLI
pattern, lowest-friction, keeps the frozen-dataclass repro model); or (b) thread a real
`StrategyProfile` into the engine. D-03 says "come from StrategyProfile" — cleanest is to make
`PhaseConfig` carry a `StrategyProfile` (or its exit fields) so the CLI/​sweep override layer and
the profile defaults coexist, mirroring how the live orchestrator lets env overrides win over
profile defaults. Planner decides; both satisfy D-03's intent.

## The Phase 18 sweep harness (extend, don't rebuild)

- **Driver:** `scripts/sweep_backtest.py`. `MIN_CONFLUENCES × KELLYS × QUARANTINES` nested loops
  (`:181-186`); each cell = a fresh `subprocess.run` of `python -m src.backtester` with
  `BAR_CACHE_DIR` in env (`:53-75`). **Do NOT convert to an in-process loop** — `data_loader.py:20`
  bakes `BAR_CACHE_DIR` at import (repro trap documented at `sweep_backtest.py:14-19`).
- **Metric capture:** regex-scrapes the child's stdout `INFO backtester:` metric lines
  (`_METRIC`, `:50`, `:66-69`). New exit knobs must be logged in the same `key value` format
  (`cli.py:127-129`) so the scraper picks them up, OR passed as CLI args (preferred — args don't
  need scraping).
- **Acceptance bar (`passes_bar`, `:83-99`):** conjunction, `trades>=30` checked FIRST, then
  `win_rate>=0.40`, then `max_dd` improved-vs-baseline AND `<0.20`, then `return>=baseline`.
- **Tiebreak (`18-BACKTEST.md:66`):** prefer LOWER kelly, then HIGHER min_confluence — toward
  less risk / fewer trades. State any new exit-knob tiebreak BEFORE reading the grid.
- **Holdout discipline:** `--holdout` requires an explicit `--candidate` (no picking on holdout,
  `:147-155`); `18-HOLDOUT.lock` refuses a second run. **The lock already exists from Phase 18**
  (`candidate=4,0.25,on`). Phase 21 changes the engine → it is a NEW experiment on a NEW model.
  **Decision the planner must make explicitly:** Phase 21 needs its OWN holdout lock (e.g.
  `21-HOLDOUT.lock`) — reusing Phase 18's lock would either block the run or conflate two models'
  holdout budgets. Recommend a fresh `21-HOLDOUT.lock` and a Phase-21 candidate chosen on TRAIN.
- **Windows:** TRAIN `2025-10-01→2026-01-31`, HOLDOUT `2026-02-01→2026-04-30` (`cli.py:22-25`).
  Bars cached via `scripts/fetch_backtest_bars.py`. **ADA/USD has NO train bars** (starts
  2026-02-13, `18-BACKTEST.md:54-60`) — carry that caveat forward.

## ATR Feasibility (THE key question) — VERDICT: FEASIBLE, no new data

- The engine loads full OHLC bars (`normalise_bar` guarantees high/low/close) and keeps a
  ≥50-bar sliding window per symbol (`engine.py:71,84-86`, `SIGNAL_WINDOW=50`).
- `_atr(highs, lows, closes, period)` needs only `period+1` bars (`technical_signals.py:170`);
  swing `atr_period=14` ≪ 50 → **always satisfied once the window is warm** (entries already gate
  on `len(window) >= 50`, so any open position has a full window behind it).
- Per-bar ATR = slice the window's `high`/`low`/`close` lists and call `_atr`. Cost is trivial
  (≤50 elems). Optional: cache/incrementally update, but not required for correctness.
- Live parity nuance: live fetches `atr_period+5` bars for ATR (`:306`); backtest should use the
  same trailing-window length (last `atr_period+5`) so the Wilder seed matches. Minor, but
  affects exact parity.
- **Feasibility conclusion:** the ATR trailing + ATR fixed rungs are fully buildable from data
  the backtester already has in memory. No blocker.

## Common Pitfalls

### Pitfall 1: "soft stop/take" is a DEAD path in the live monitor (fidelity trap)
**What goes wrong:** D-01 says model "plus soft stop/take". But the live deterministic ladder
(`alpaca_orchestrator.py:316-345`) has NO soft rung — verified: `ExitAdvisor.should_exit` is
never called in `alpaca_orchestrator.py` (grep: only the `TrailingStop`/`_atr` imports are used;
`SOFT_STOP_PCT`/`SOFT_TAKE_PROFIT_PCT` are imported at `:36` but unreferenced in the ladder). The
soft path routes to an LLM advisor that is **not wired into the current live loop**. Modeling a
soft rung would make the backtest LESS faithful, not more, AND inject non-determinism (LLM).
**How to avoid:** model the 4 deterministic rungs only. Note the D-01 wording discrepancy in the
plan; treat "soft stop/take" as a documented dead path. `[VERIFIED: grep src/alpaca_orchestrator.py]`

### Pitfall 2: Live/backtest exit-logic drift
**What goes wrong:** the ladder gets copy-pasted into the engine and the two diverge on the next
live tweak. **How to avoid:** D-02 — one extracted `evaluate_exit` helper, called by both; a
parity test pinning the extracted helper to the old inline decisions.

### Pitfall 3: Look-ahead / intra-bar exit ordering
**What goes wrong:** with 1H bars, a single bar can cross MULTIPLE rungs (e.g. the low pierces
the hard stop AND the high would've hit a trail). Using only `close` (as the engine does today)
can UNDER- or OVER-count exits and silently assume which fired first. The live monitor polls
every 60s against a live quote — it sees intra-bar prices the backtest cannot. **How to avoid:**
pick and DOCUMENT an intra-bar convention BEFORE running (recommend: conservative/pessimistic —
within a bar, evaluate the hard stop against the bar `low` (long) before the trail against the
`high`, so a stop that could have triggered is not skipped by a favorable close). Never let the
close price alone decide when high/low would have triggered a stop first. This is the #1
correctness risk and a classic backtest look-ahead vector.

### Pitfall 4: Holdout leakage / reusing Phase 18's lock
**What goes wrong:** Phase 21 changes the model, so Phase 18's `18-HOLDOUT.lock` and its
`candidate=4,0.25,on` no longer describe this experiment; reusing it either blocks the run or
mixes two models' one-shot budgets. **How to avoid:** fresh `21-HOLDOUT.lock`, candidate chosen
on TRAIN only, single holdout shot. Keep `passes_bar`'s trades-first conjunction.

### Pitfall 5: max_hold needs real timestamps
**What goes wrong:** the ladder's rung 2 uses `hours_held`. The backtest must derive hours from
bar timestamps (entry ts → current ts), not wall-clock. 1H bars → hours = bar-index delta.
Swing `max_hold_hours=168` = 7 days = 168 hourly bars. **How to avoid:** compute `hours_held`
from the entry/current bar timestamps already stored on `_Position.entry_timestamp`.

## Runtime State Inventory

Not a rename/migration phase, but it touches a live-shared helper and a lock file:

| Category | Items | Action |
|----------|-------|--------|
| Stored data | Backtest bar cache `data/backtest_bars/<SYM>_1Hour.json` (gitignored, ~5.5MB) | Reuse; re-fetch only if extending window |
| Live service config | None changed — phase MEASURES the live exit, does not alter live bots | None |
| OS-registered state | None | None — verified, code + backtest only |
| Secrets/env vars | ATR/exit env overrides (`HARD_STOP_PCT`, `TRAIL_*` in `exit_advisor.py:25-33`) still win over profile — keep that precedence | None |
| Build artifacts | `18-HOLDOUT.lock` exists; Phase 21 needs its own `21-HOLDOUT.lock` | Create new, do not overwrite 18's |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing; `tests/backtester/fixtures/` present per `cli.py:9`) |
| Quick run | `python -m pytest tests/test_exit_ladder.py -x` (NEW file, Wave 0) |
| Full suite | `python -m pytest tests/ -q` |
| Backtest smoke | `BAR_CACHE_DIR=data/backtest_bars python -m src.backtester --phase 0 --train --min-confluence 4 --kelly-fraction 0.25 --symbols "BTC/USD,..."` |

### Phase Requirement → Test Map
| Behavior | Test Type | Automated Command | Exists? |
|----------|-----------|-------------------|---------|
| Extracted `evaluate_exit` reproduces live inline ladder decisions | unit (parity table) | `pytest tests/test_exit_ladder.py::test_parity -x` | ❌ Wave 0 |
| hard_stop fires at `pnl<=hard_stop_pct` before other rungs | unit | `pytest -k test_hard_stop_precedence` | ❌ Wave 0 |
| max_hold fires only when configured + `hours_held>max_hold_hours` | unit | `pytest -k test_max_hold` | ❌ Wave 0 |
| ATR trail arms only in profit, ratchets, triggers on pullback | unit | `pytest -k test_atr_trail` (can reuse existing TrailingStop tests if any) | ❌ Wave 0 |
| ATR fixed stop side-aware level | unit | `pytest -k test_atr_fixed` | ❌ Wave 0 |
| Engine computes ATR per bar from window (non-zero once warm) | integration | `pytest -k test_engine_atr` on a fixture | ❌ Wave 0 |
| Intra-bar ordering convention (Pitfall 3) is applied | unit | `pytest -k test_intrabar_convention` | ❌ Wave 0 |
| Backtest with new ladder on fixture produces exits with new reasons | integration | `pytest -k test_engine_ladder_exits` | ❌ Wave 0 |
| Sweep grid runs + `passes_bar` conjunction unchanged | existing | `pytest -k sweep` (if present) / manual | check |
| Holdout lock refuses second run | existing behavior | manual (`sweep_backtest.py:152-155`) | exists |

### Sampling Rate
- Per task commit: `pytest tests/test_exit_ladder.py -x` (<5s).
- Per wave merge: `pytest tests/ -q`.
- Phase gate: full suite green + one TRAIN sweep reproduced + single `21-HOLDOUT.lock` shot, then
  the TUNE-01 verdict (pass or documented negative per D-05).

### Wave 0 Gaps
- [ ] `src/exit_ladder.py` — extracted shared `evaluate_exit` helper (or in-place import decision).
- [ ] `tests/test_exit_ladder.py` — parity + per-rung + intra-bar tests.
- [ ] Engine ATR-per-bar fixture (extend `tests/backtester/fixtures/`).
- [ ] `PhaseConfig`/CLI exit-knob plumbing tests.

## Security Domain

`security_enforcement` not triggered materially — this is an offline analysis harness. Relevant
invariants (from CLAUDE.md risk rules, treat as locked): **quarter-Kelly is a hard CEILING**
(sweep may only lower Kelly; `cli.py:57` enforces), max 5% bankroll/position, paper-only gate
unchanged, NO live-bot writes in this phase (Phase 18 fenced all prod writes to a held rollout
plan — carry that fence). The sweep driver is read-only (`AIPW_DB_READONLY=1`,
`sweep_backtest.py:62`). No new input-validation/crypto/authz surface.

## State of the Art

| Old (Phase 18 engine) | New (Phase 21 engine) | Impact |
|-----------------------|-----------------------|--------|
| Flat `-0.15` hard stop + `+0.30` take, long-only | 4-rung ATR ladder from StrategyProfile, side-aware | Win-rate criterion becomes continuous/falsifiable (was 2 values across 12 cells) |
| Entry-knob sweep only | Entry + exit knob grid | Tunes the dimension Phase 17 located the losses on |
| `18-HOLDOUT.lock` (candidate 4,0.25,on) | fresh `21-HOLDOUT.lock`, new candidate on new model | Clean one-shot budget for the new experiment |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Live monitor's exit ladder is fully deterministic and the ONLY live exit path (LLM advisor unwired) | Pitfall 1 | If a soft/LLM rung is actually live elsewhere (e.g. a separate PositionMonitor), the backtest would omit a real exit — LOW risk, grep-verified in orchestrator |
| A2 | `PhaseConfig` is the right place to add exit knobs (vs full StrategyProfile threading) | Knobs | Either works; only ergonomics differ |
| A3 | Phase 21 should mint its own holdout lock rather than reuse 18's | Sweep Harness / Pitfall 4 | If planner reuses 18's, the run is blocked or budgets conflate |
| A4 | Same TRAIN/HOLDOUT windows + cached bars as Phase 18 are the intended data | Sweep Harness | Discretion per CONTEXT; changing windows re-opens repro |

## Open Questions

1. **StrategyProfile vs PhaseConfig for exit knobs.** D-03 says StrategyProfile; engine reads
   PhaseConfig. Recommend carrying the exit fields on PhaseConfig (mirrors existing CLI override
   layer) — planner confirms.
2. **Intra-bar exit-ordering convention.** Recommend pessimistic (stop-before-trail within a
   bar, using low/high not close). Planner must lock this before the sweep.
3. **Does a PASS even exist?** D-05 pre-authorizes an honest negative. The modeled `-0.08` stop
   is ~2× tighter than the old `-0.15`; it will change results, direction unknown until run.

## Environment Availability

| Dependency | Required By | Available | Notes |
|------------|------------|-----------|-------|
| Cached bars `data/backtest_bars/*_1Hour.json` | sweep repro | assume present (Phase 18, gitignored) | Re-fetch via `scripts/fetch_backtest_bars.py` if missing |
| Alpaca public crypto feed | bar re-fetch only | ✓ (keyless fallback, `data_loader.py:124-129`) | no creds needed for read |
| pytest | tests | assume ✓ | verify Wave 0 |

## Sources

### Primary (HIGH — direct codebase reads, 2026-07-20)
- `src/backtester/engine.py`, `portfolio.py`, `config.py`, `data_loader.py`, `metrics.py`, `cli.py`
- `src/alpaca_orchestrator.py:270-407` (live exit ladder)
- `src/exit_advisor.py` (TrailingStop, constants, dormant LLM advisor)
- `src/strategy_profile.py`, `src/bot_config.py` (knobs)
- `src/technical_signals.py:162-183` (`_atr`)
- `scripts/sweep_backtest.py` (grid driver + acceptance bar)
- `.planning/phases/18-profitable-retune/18-BACKTEST.md` (fidelity gap, holdout discipline)
- `18-HOLDOUT.lock`, `.planning/milestones/v1.1-REQUIREMENTS.md` (TUNE-01 text)
- grep `src/alpaca_orchestrator.py` confirming ExitAdvisor unwired (Pitfall 1)

## Metadata

**Confidence breakdown:**
- Exit-stack fidelity mapping: HIGH — read both live ladder and current engine line-by-line.
- ATR feasibility: HIGH — verified data + helper are in-memory and reused live.
- Sweep/holdout extension: HIGH — driver read end-to-end.
- Soft-stop dead-path finding: HIGH — grep-verified, but flagged A1 in case of a second monitor.

**Research date:** 2026-07-20
**Valid until:** stable (in-repo, no external deps) — re-verify only if live exit ladder changes.
