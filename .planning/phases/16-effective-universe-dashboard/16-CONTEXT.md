# Phase 16 — Effective-Universe Dashboard Visibility — CONTEXT

*Milestone v1.1 · captured 2026-07-12 · mode: --auto (YOLO, decisions auto-selected)*

## Domain

Phase 15 built the hard gate (`src/universe.py::entry_allowed`) and the config-driven quarantine
column, so an off-universe symbol can no longer be traded. But the *operator still cannot see* what
each bot's tradeable set actually is — the audit found TRUMP/FIL had been trading for weeks without
anyone noticing. UNIV-03 closes that: the dashboard surfaces the **effective live universe per bot**,
so a leak (or an over-aggressive quarantine that has silently starved a bot to zero candidates) is
visible at a glance.

**Requirement owned:** UNIV-03.

## Grounding (from code scout)

- `dashboard/api/routes/bots.py` — `GET /api/bots` (L51) returns all bots + live thread status;
  `_BOT_COLS` (L20-24) now includes `quarantined_symbols` (Phase 15). `PUT /api/bots/{bot_id}`
  (L120) already accepts `quarantined_symbols` via `BotUpdate` — so *editing* the quarantine is
  already possible; this phase is about *display* plus a computed effective set.
- `src/universe.py` (Phase 15) — pure `normalize(symbol)` and
  `entry_allowed(symbol, allowlist, quarantined) -> (bool, reason)`. The effective universe is
  exactly `[s for s in allowlist if entry_allowed(s, allowlist, quarantined)[0]]`. **Reuse it — do
  not reimplement the set math**, or the dashboard will drift from the gate and lie.
- `src/bot_config.py` (Phase 15) — `symbols`, `all_symbols` (crypto ∪ stock), `quarantined`.
- The dashboard is Next.js + FastAPI in one container (see CLAUDE.md).

## Decisions (locked — auto-selected recommended defaults)

1. **New read-only endpoint `GET /api/bots/{bot_id}/universe`.** Returns, per bot:
   `{bot_id, asset_class, allowlist[], quarantined[], effective[], blocked[]}` where `effective` is
   the allowlist minus quarantine (computed via `src/universe.py`, never re-derived) and `blocked`
   is the complement with a `reason` each. Read-only: no writes, no Alpaca calls, no thread access.
   Editing stays on the existing `PUT /api/bots/{bot_id}` — this phase adds **no** new write path.
2. **Source of truth = the same inputs the gate uses.** Build a `BotConfig` from the bots row and
   call `entry_allowed` — so what the dashboard shows is, by construction, what the gate enforces.
   The trend carve-out (`cfg.symbols ∪ {cfg.trend_symbol}`) and the copytrade union
   (`cfg.all_symbols`) must be reflected: the endpoint reports the allowlist *for that bot's actual
   strategy*, not a generic one, or it will show a false universe for Bot E / the trend bot.
3. **Dashboard UI: a per-bot "Universe" panel.** Shows the effective symbols as chips, quarantined
   symbols visibly struck-through/greyed with their reason, and a count (`6 of 8 tradeable`).
   **Two loud states** (the whole point of the requirement):
   - a symbol in `blocked` with reason `off_universe` that has **open positions or recent trades**
     → a LEAK warning (this is the TRUMP/FIL case);
   - `effective` empty → a "bot has no tradeable symbols" warning (over-quarantine starvation).
3b. **The shadow deny-lists MUST be shown (CORRECTED after research).** `BotThread`'s selectors
   subtract `MEME_CRYPTO` **and `_ALPACA_UNTRADEABLE`** on top of the Phase-15 gate
   (`src/bot_thread.py:144-145`, `163-164`), and `_ALPACA_UNTRADEABLE`'s default
   (`src/alpaca_orchestrator.py:79-84`) **already contains `DOT/USD`, `LINK/USD`, `ETH/USD`** — three
   of the eight symbols in every bot's default `crypto_universe`. A panel that reported only the
   gate's answer would say "8 of 8 tradeable" for a bot that actually scans 5 — a new lie, in a
   phase whose entire purpose is to stop the dashboard lying. So `effective` subtracts the shadow
   sets too, and `blocked` carries the distinct reasons: `quarantined` | `off_universe` | `meme` |
   `untradeable`. Caveat to record in VERIFICATION.md: `_ALPACA_UNTRADEABLE` is env-derived in the
   orchestrator process, so if the dashboard container's env differs the panel can drift — report
   the constant's source, and hand consolidation of these hardcoded sets into `quarantined_symbols`
   to Phase 17/18. Do NOT refactor the constants in this phase.

4. **No schema change.** Everything needed exists (`crypto_universe`, `stock_universe`,
   `quarantined_symbols`, `asset_class`, `strategy`, `trend_symbol`). If any migration were needed
   it would be `019_*.sql`, additive + mirrored — but prefer none.
5. **OpenAPI + docs.** The new route appears in `/openapi.json` and `/docs` (repo docs convention);
   `docs/api.md` regenerated if it is committed.

## Scope discipline (fences)

- Does NOT change the gate (Phase 15) — it *reads* it. If the dashboard and the gate ever disagree,
  the gate wins and the dashboard is the bug.
- Does NOT add a new write/edit path for the universe or the quarantine (PUT already does it).
- Does NOT touch P&L (12), reconciliation (13), backfill (14), retune (18), or runtime (19).
- Does NOT decide which symbols to quarantine (that is Phase 17's evidence + Phase 18's call).
- Risk invariants untouched. No Alpaca calls from this endpoint.

## Canonical refs (MANDATORY reading for research/plan)

- `.planning/REQUIREMENTS.md` — UNIV-03.
- `.planning/phases/15-universe-hard-gate/` — CONTEXT/RESEARCH/VERIFICATION (what the gate does).
- `src/universe.py`, `src/bot_config.py` — the set math + config to reuse.
- `dashboard/api/routes/bots.py` — `_BOT_COLS`, `GET /api/bots`, `PUT /api/bots/{bot_id}`.
- `dashboard/api/models.py` — Pydantic models (add the response model here).
- `dashboard/` frontend — the existing bot card/panel components + their fetch layer.
- `tests/test_universe.py` — the Phase-15 suite; extend the same conventions.
- CLAUDE.md — `/openapi.json` + `/docs` contract, docs-drift CI.

## Deferred ideas (not this phase)

- Editing the universe/quarantine from the UI (a form on the panel) — the PUT exists; wiring a form
  is UX polish, revisit after Phase 18 decides what to quarantine.
- Showing the *dynamic* volume-ranked universe alongside the curated one — the dynamic fallback is
  unreachable in production (Phase-15 research), so it would be dead UI.
