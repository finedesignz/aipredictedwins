---
phase: 16
plan: 04
subsystem: dashboard-web
tags: [UNIV-03, ui, panel]
requires: ["GET /api/bots/{bot_id}/universe"]
provides: [UniversePanel, types.BotUniverse, types.BlockedSymbol]
affects: [dashboard/web/components/bots/BotCard.tsx]
tech-stack:
  added: []
  patterns: [useAPI-poll, existing-primitives-only]
key-files:
  created: [dashboard/web/components/bots/UniversePanel.tsx]
  modified: [dashboard/web/types/index.ts, dashboard/web/components/bots/BotCard.tsx]
decisions:
  - "No `title` prop on Badge (B2) — the reason renders as visible muted text; Badge.tsx untouched"
  - "Panel recomputes nothing: no .filter/.includes deriving allow-vs-block; leak detail is a render-only lookup keyed by the server's leak list"
  - "All evidence captured against a LOCAL stack + local Postgres — prod never touched"
metrics:
  duration: ~25m
  completed: 2026-07-12
---

# Phase 16 Plan 04: UniversePanel Summary

The bot card no longer shows the raw `Assets: BTC/USD,ETH/USD,…` config string that let TRUMP/FIL trade unnoticed for weeks. It now shows the effective set, the blocked set with visible reasons, an `N of M tradeable` count, two loud alarms (LEAK, STARVATION) and three degraded-state footnotes.

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1-3 | types realignment + UniversePanel + BotCard mount + evidence | `551fa17` | types/index.ts, UniversePanel.tsx, BotCard.tsx |

## Verification

```
$ cd dashboard/web && npm run build
✓ Compiled successfully   (/bots 5.17 kB, 107 kB first load)

$ git diff --stat dashboard/web/components/shared/Badge.tsx dashboard/web/package.json
(empty)
```

TS `BotFull` field-by-field check against the Pydantic `BotFull` (dashboard/api/models.py:209-232): added the 8 drifted fields — `asset_class`, `min_short_confluence`, `tradingagents_enabled`, `strategy`, `trend_ma_window`, `trend_symbol`, `trend_benchmark`, `quarantined_symbols`. Every Pydantic field now has a TS counterpart; no existing field removed or renamed.

## Screenshot evidence (LOCAL stack only)

`.planning/phases/16-effective-universe-dashboard/evidence/`

| File | State | What it shows |
|------|-------|---------------|
| `A-normal.png` | normal | `4 of 8 tradeable`; effective chips BTC/SOL/XRP/ADA; struck-through AVAX/USD `quarantined`, ETH/USD + DOT/USD + LINK/USD `untradeable` |
| `B-leak.png` | LEAK | red alert: `LEAK: TRUMP/USD (1 open, 3 in 30d) traded outside this bot's universe`; TRUMP/USD struck through as `off_universe` |
| `C-starvation.png` | STARVATION | amber alert: `No tradeable symbols — every symbol is blocked. This bot cannot enter a position.`; `0 of 2 tradeable` |
| `00-bots-page-localhost.png` | full page | all cards, URL `http://localhost:3000/bots` |

Captured with Playwright (Chromium) against `http://localhost:3000` (Next dev) → `http://127.0.0.1:8000` (uvicorn) → local Postgres `aipw_test` on 5433. Seed rows (`UNIVNORM`, `UNIVLEAK`, `UNIVSTARVE`) inserted by direct SQL on dedicated TEST bot ids and deleted afterwards. Stack torn down.

## PROD SAFETY ATTESTATION

**No writes to the production database. No API calls to the deployed dashboard (app.aipredictedwins.com). No live bot was quarantined, and no phantom open position was seeded anywhere Phase-13/14 reconciliation could ingest it.** Every write went to the local `aipw_test` Postgres, and even those seed rows were deleted at teardown.

## Deviations from Plan

**1. [Rule 2 - Correctness] Leak-detail lookup avoids `.filter`/`.includes`**
- **Found during:** Task 2
- **Issue:** the natural way to join `leak` with `blocked` for the banner text is `blocked.filter(b => leak.includes(b.symbol))`. That is render-only, but it trips the plan's acceptance grep (which forbids `.filter(`/`.includes(`) and blurs the "panel computes nothing" boundary.
- **Fix:** build a `Record<symbol, BlockedSymbol>` lookup and map over the server's `leak` array. No `.filter(`/`.includes(` anywhere in the file.
- **Commit:** `551fa17`

## Self-Check: PASSED
- dashboard/web/components/bots/UniversePanel.tsx — FOUND
- evidence/A-normal.png, B-leak.png, C-starvation.png — FOUND
- Commit 551fa17 — FOUND
