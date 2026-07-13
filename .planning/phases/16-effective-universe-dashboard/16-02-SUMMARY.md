---
phase: 16
plan: 02
subsystem: universe
tags: [UNIV-03, resolver, pure]
requires: [src.universe.entry_allowed, src.bot_config.BotConfig]
provides: [src.effective_universe.resolve_universe, src.effective_universe.allowlist_for, src.effective_universe.shadow_applies_to]
affects: [dashboard/api/routes/bots.py, dashboard/web/components/bots/UniversePanel.tsx]
tech-stack:
  added: []
  patterns: [pure-function, lazy-import, delegation-to-gate]
key-files:
  created: [src/effective_universe.py]
  modified: []
decisions:
  - "Every allow/block verdict delegated to src.universe.entry_allowed — no independent set math in the resolver (anti-lie invariant)"
  - "Shadow subtraction is strategy-conditional: confluence only (shadow_applies_to)"
  - "Shadow sets loaded via a try/except-guarded FUNCTION-LOCAL import; failure reported as shadow_sets_loaded=False, never swallowed"
  - "Both sides of every symbol comparison normalized via src.universe.normalize"
metrics:
  duration: ~15m
  completed: 2026-07-12
---

# Phase 16 Plan 02: Pure Effective-Universe Resolver Summary

`src/effective_universe.py` — one pure, zero-I/O function answers "what can this bot actually trade, and why not the rest?" It cannot disagree with the entry gate (it delegates to it), and it cannot invent a block the bot's own strategy never applies.

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1-2 | allowlist_for + shadow_applies_to + _load_shadow_sets + resolve_universe | `2f07854` | src/effective_universe.py |

## Verification

```
python -m pytest tests/test_effective_universe.py -q
15 passed, 4 skipped in 0.07s        # 15 pure cases GREEN; route cases skip without TEST_DATABASE_URL

python -c "import src.effective_universe" -> alpaca sdk loaded: False
```

Import purity confirmed: no module-level `src.alpaca_*` import, no Alpaca SDK pulled, no env read.

## Contract implemented

- `allowlist_for(cfg)` — copytrade → `cfg.all_symbols`; trend_btc → `cfg.symbols + [cfg.trend_symbol]`; otherwise → `cfg.symbols`. Dispatches purely on `cfg.strategy`.
- `shadow_applies_to(strategy)` — True only for the confluence path (`not in {copytrade, trend_btc, tradingagents}`).
- `resolve_universe(cfg, *, exposure, exposure_loaded, meme, untradeable)` — single pass; every verdict from `entry_allowed`; shadow reasons applied only when `shadow_applied`; precedence `quarantined > off_universe > meme > untradeable` falls out of the branch order.
- `leak` = off_universe symbols with `open > 0 or recent > 0`. A quarantined symbol holding an open position is NOT a leak (expected wind-down).
- `exposure_loaded` propagated verbatim; with it False, `leak == []` reads as UNKNOWN.

## KNOWN OVER-REPORT (W2 — carry into VERIFICATION.md)

For `trend_btc` the panel reports `allowlist = cfg.symbols + [BITX]` because that is exactly what the **gate** permits (src/trend_strategy.py:103) — but the trend cycle in practice only ever *enters* `cfg.trend_symbol` (BITX). The panel therefore **over-reports the trend bot's real trading surface**. Deliberate, per CONTEXT Decision 2 (mirror the gate, not the strategy's internal appetite); not special-cased.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED
- src/effective_universe.py — FOUND
- Commit 2f07854 — FOUND
