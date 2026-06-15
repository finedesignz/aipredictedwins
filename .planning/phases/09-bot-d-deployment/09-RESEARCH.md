# Phase 9: Bot D Deployment - Research

**Researched:** 2026-06-15
**Domain:** Multi-bot deployment plumbing (Python orchestrator + Next.js/FastAPI dashboard + Coolify)
**Confidence:** HIGH (all findings verified directly against repo source)

## Summary

Bot D is the day-trade bot (`BOT_PROFILE=daytrade`, built in Phases 1–8) standing up alongside
swing bots A/B (and existing experimental C/E). This phase is overwhelmingly **config + small
code edits + docs**; the only true blockers are two outward-facing acts: creating Bot D's Alpaca
paper account (browser signup) and creating its Coolify service.

The architecture has **two separate key-wiring conventions** that must not be confused:

1. **Bot orchestrator (`src/`)** — each bot runs as its **own Coolify service** and reads the
   **BARE, unsuffixed** `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` via `src/config.py`. Coolify maps
   that service's env to the bot's keys. `AlpacaClient._init_clients()` raises `ValueError` if
   either is empty — **no silent fallback to A/B exists** (verified). `BOT_ID` selects the
   trade-DB partition only, not the keys.
2. **Dashboard (`dashboard/`, single multi-bot container)** — reads **SUFFIXED**
   `ALPACA_API_KEY_{bot_id}` for every known bot (e.g. `_A`, `_B`, `_C`, `_D`) and seeds the
   `bots` Postgres table. Attribution is by `bot_id` column.

**The one code blocker:** `src/trade_logger.py` validates `BOT_ID not in ("A", "B")` and raises —
this rejects `BOT_ID=D`. This must be widened (BOT-01 code side).

**Primary recommendation:** Widen the `trade_logger` BOT_ID allow-list to include `D` (prefer a
shared `KNOWN_BOT_IDS` constant), add `"D"` to dashboard `KNOWN_BOTS`, fix two hardcoded A/B
frontend cells, document the exact Coolify env set mirroring Bot B, and HALT for the human to
create the Alpaca account + Coolify service.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Bot D key selection (trading) | Orchestrator service env (bare `ALPACA_API_KEY`) | — | One Coolify service per bot; isolation by service, not code branch |
| Bot D BOT_ID validation | `src/trade_logger.py` | `src/trade_memory.py` | Partitions trade DB rows; currently A/B-only |
| Bot D dashboard listing | `dashboard/api/db.py` `KNOWN_BOTS` + `bots` table | seed_bots.py | Aggregate filtering + equity fetch driven off table |
| Bot D equity/positions attribution | `dashboard/api/routes/*` (`ALPACA_API_KEY_{bot_id}`) | `bots` table | Dynamic per-bot key lookup already generic |
| Bot D trade-row badge in UI | `dashboard/web/components` | — | Two components hardcode binary A/B — pitfall |
| Alpaca paper account creation | **HALT — human/browser** | — | Outward-facing, irreversible brokerage signup |
| Coolify service creation | **HALT — human/Coolify API** | — | Outward-facing prod provisioning |

## Standard Stack

No new packages. Uses existing: `alpaca-py` 0.43.2, `psycopg`/`psycopg_pool`, FastAPI, Next.js,
`python-dotenv`. **No `## Package Legitimacy Audit` needed — zero external installs this phase.**

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BOT-01 | Bot D on own Alpaca paper acct, `BOT_ID=D`, `BOT_PROFILE=daytrade` | Code: widen `trade_logger.py` BOT_ID allow-list to include D. Keys: orchestrator reads bare `ALPACA_API_KEY` (no fallback — verified fail-clear). Account creation = HALT. |
| BOT-02 | Bot D as separate Coolify service | Mirror Bot B's service. Exact env recipe below. Creation = HALT. |
| BOT-03 | Dashboard `KNOWN_BOTS` includes "D", attributes correctly | Add `"D"` to `dashboard/api/db.py:18`. Attribution already dynamic via `ALPACA_API_KEY_{bot_id}` + `bots` table. Fix 2 hardcoded A/B UI cells. |

## Architecture Patterns

### Per-bot key wiring (CRITICAL — two conventions)

```
Orchestrator service (one container per bot):
  Coolify env:  BOT_ID=D
                BOT_PROFILE=daytrade
                ALPACA_API_KEY     = <Bot D paper key>     # BARE — no _D suffix
                ALPACA_SECRET_KEY  = <Bot D paper secret>  # BARE
  src/config.py -> Config.alpaca_api_key (reads ALPACA_API_KEY)
  AlpacaClient._init_clients(): raises ValueError if empty  # fail-clear, NO A/B fallback

Dashboard service (single multi-bot container):
  Coolify env:  ALPACA_API_KEY_D    = <Bot D paper key>     # SUFFIXED
                ALPACA_SECRET_KEY_D = <Bot D paper secret>  # SUFFIXED
  routes read os.environ[f"ALPACA_API_KEY_{bot_id}"]  # already generic
  seed_bots.py seeds bots table row for D
```

### Fail-clear verification (D-01)
- `src/alpaca_client.py:94-97` raises `ValueError("ALPACA_API_KEY and ALPACA_SECRET_KEY must be
  set in .env")` when empty. `[VERIFIED: src/alpaca_client.py]`
- `src/config.py` reads bare `ALPACA_API_KEY` with default `""` — no suffix logic, **no path that
  substitutes A's or B's key**. `[VERIFIED: src/config.py:155-156]`
- **Residual risk is operator-side, not code-side:** the bare-key model means if a human pastes
  A's key into D's Coolify service, code cannot detect it (one-account-per-bot violated silently).
  Mitigation belongs in the HALT recipe (verify account number after wiring) — see pitfalls.

### Dashboard attribution (D-02 / BOT-03)
- `dashboard/api/db.py:18` `KNOWN_BOTS = ("A", "B", "C")` → add `"D"`. `query_filtered()` and
  `is_specific_bot()` key off this. `[VERIFIED: dashboard/api/db.py]`
- `equity.py` / `positions.py` / `portfolio.py` already use `f"ALPACA_API_KEY_{bot_id}"` and
  iterate `bots WHERE enabled=TRUE` — **no code change needed for attribution itself**, just the
  D row in the `bots` table (via `seed_bots.py` + the `_D` env vars). `[VERIFIED]`
- `seed_bots.py` has explicit A/B/C blocks — add a parallel `key_d`/`secret_d` block (or
  generalize). `[VERIFIED: dashboard/api/seed_bots.py:70-93]`

### Anti-Patterns to Avoid
- Do NOT add a `_D` suffix lookup to the orchestrator `src/config.py` — that breaks the
  one-service-per-bot model. Orchestrator stays bare-key.
- Do NOT reuse A/B's Alpaca account for D (hard rule — equity overlap, dedup blocking, P&L corruption).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Bot list source of truth | New config | Extend `KNOWN_BOTS` + `bots` table | Already the canonical pattern (A/B/C/E precedent) |
| Per-bot equity fetch | Per-bot route | Existing `ALPACA_API_KEY_{bot_id}` loop | Already generic |
| Seeding D bot row | Ad-hoc SQL | `seed_bots.py` pattern (idempotent upsert) | Matches A/B/C; safe on every startup |

## Runtime State Inventory

This phase ADDS a bot (not a rename), but touches multi-place identifier state:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `bots` table needs a `bot_id='D'` row; `trade_context`/`trade_lessons`/`strategy_scores`/`alpaca_trades` all carry `bot_id` — auto-partition once D writes | seed D row via `seed_bots.py` (code+data); no migration of existing rows |
| Live service config | Coolify: NEW orchestrator service for D (bare keys); dashboard service needs `ALPACA_API_KEY_D`/`_SECRET_KEY_D` env added — **dashboard env lives in Coolify UI, not git** | HALT: human/API adds env + creates service |
| OS-registered state | None — Coolify-managed containers, no OS task registration | None — verified (no Task Scheduler/pm2 refs in repo) |
| Secrets/env vars | `ALPACA_API_KEY`/`_SECRET_KEY` (bare, D's service) + `ALPACA_API_KEY_D`/`_SECRET_KEY_D` (dashboard) — all NEW, produced only by Alpaca signup | HALT: created at account signup |
| Build artifacts | None — same image, env-driven | None |

**Hardcoded A/B identifier state in code (must edit):**
- `src/trade_logger.py:26` — `BOT_ID not in ("A","B")` rejects D. **BLOCKER.**
- `dashboard/web/components/trades/TradeTable.tsx:116-119` — `isB = val.includes("B")` renders
  every non-B bot as "A". D would mislabel as "A".
- `dashboard/web/components/positions/PositionCard.tsx:22-26` — binary A/B color/label; D falls to
  the `position.bot` raw value (less broken than TradeTable but inconsistent styling).

## Common Pitfalls

### Pitfall 1: BOT_ID=D rejected at startup
**What goes wrong:** `TradeLogger.__init__` raises `ValueError` because `"D" not in ("A","B")`.
**How to avoid:** Widen allow-list. Prefer a single `KNOWN_BOT_IDS = ("A","B","C","D")` constant
shared by `trade_logger.py` (and align `trade_memory.py`, which already accepts any non-empty id).
**Warning sign:** Orchestrator crashes immediately on boot with the BOT_ID message.

### Pitfall 2: D silently shares A/B's Alpaca account (HARD-RULE violation)
**What goes wrong:** Operator pastes A's key into D's bare `ALPACA_API_KEY`. Code can't detect it.
**Why:** Bare-key model has no cross-check. **How to avoid:** HALT recipe must include a
post-wiring verification: hit `/v2/account` for D and confirm the account number differs from A/B.
**Warning sign:** D's equity curve identical to A/B on the dashboard.

### Pitfall 3: Dashboard double-counting / mislabel
**What goes wrong:** `KNOWN_BOTS` missing "D" → D excluded from "all" aggregates; or TradeTable
renders D as "A". **How to avoid:** Add "D" to `KNOWN_BOTS`, seed the `bots` row, fix the two
hardcoded A/B UI cells to render `bot_id` generically.

### Pitfall 4: bot_id casing
**What goes wrong:** Env `BOT_ID=d` (lowercase) → DB rows `bot_id='d'` won't match `KNOWN_BOTS`
`"D"` or dashboard `ALPACA_API_KEY_D` suffix (uppercased in dashboard `_get_keys`, NOT in
orchestrator). **How to avoid:** Document `BOT_ID=D` uppercase; consider `.upper()` normalization
in the widened validator.

## Code vs Infra (HALT items)

### (a) Automatable code/config this phase — can build + test NOW
1. `src/trade_logger.py` — widen BOT_ID allow-list to include `D` (shared constant). **Test:**
   `BOT_ID=D` instantiates `TradeLogger` without raising; `BOT_ID=Z` still raises.
2. `dashboard/api/db.py:18` — `KNOWN_BOTS = ("A","B","C","D")`. **Test:** `is_specific_bot("D")`
   true; `query_filtered(..., bot="D")` wraps with `bot_id='D'`.
3. `dashboard/api/seed_bots.py` — add D block (`key_d`/`secret_d`, label "Agent D — Daytrade",
   `asset_class` per profile, daytrade defaults). Idempotent. **Test:** with `_D` env set, a D row
   inserts; without, skipped.
4. `dashboard/web/components/trades/TradeTable.tsx` + `PositionCard.tsx` — render `bot_id`
   generically (drop binary `isB`). **Test:** D rows show "D" badge.
5. Deployment artifact: documented Coolify env set + recipe (below).
6. Docs (D-05): `CLAUDE.md` Alpaca Accounts table add Bot D row + `ALPACA_API_KEY_D`/`_SECRET_KEY_D`
   + `LEARNING_SHADOW_UNTIL_TRADES`; project memory `project_coolify_infra.md` / `project_ab_testing.md`.

### (b) Outward-facing — HALT, requires human auth (exact recipe)

**HALT-1: Create Bot D's Alpaca paper account**
1. Log in to https://app.alpaca.markets (or sign up a new login if a separate account is required).
2. Create/select a **Paper** trading account dedicated to Bot D (one account per bot — must NOT be
   A's, B's, or C's account).
3. Generate API keys for that paper account → record `KEY` and `SECRET` (secret shown once).
4. Provide to the session as `ALPACA_API_KEY_D` / `ALPACA_SECRET_KEY_D` (do NOT commit; store in
   `~/.claude/secrets` or Coolify env only).

**HALT-2: Create Bot D's Coolify orchestrator service** (mirror Bot B; project UUID
`u7x0xw0y4qvcgeh8vyidsgyi`)
- Image/repo: same as Bot B's orchestrator service. Command: `python -m src.alpaca_orchestrator --mode paper`.
- **Orchestrator env (BARE keys):**

  | Var | Value |
  |-----|-------|
  | `BOT_ID` | `D` |
  | `BOT_PROFILE` | `daytrade` |
  | `ALPACA_API_KEY` | `<Bot D paper key>` (bare — not `_D`) |
  | `ALPACA_SECRET_KEY` | `<Bot D paper secret>` (bare) |
  | `ALPACA_ENV` | `paper` |
  | `DATABASE_URL` | shared app Postgres (same as A/B) |
  | `LEARNING_SHADOW_UNTIL_TRADES` | `30` (Phase 8 default) |
  | `BOT_LABEL` | `Agent D` |

- **Dashboard service env (SUFFIXED keys — add to EXISTING dashboard app, do not recreate):**
  `ALPACA_API_KEY_D=<key>`, `ALPACA_SECRET_KEY_D=<secret>`.
- Post-deploy verification: GET D's `/v2/account` and confirm account number ≠ A/B/C (pitfall 2).

**Optional automation:** If Coolify API creds (in `~/.claude/secrets/services.json`) are present
AND the user explicitly authorizes, the service can be created via Coolify API in a follow-up. The
Alpaca account (HALT-1) cannot be automated.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | repo root (`tests/`) — existing suite 261+ tests |
| Quick run command | `python -m pytest tests/test_trade_logger_shim.py -x` |
| Full suite command | `python -m pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BOT-01 | `BOT_ID=D` instantiates TradeLogger; invalid id still raises | unit | `pytest tests/test_trade_logger_shim.py -x` | ✅ extend existing |
| BOT-01 | No silent A/B key fallback (empty bare key raises) | unit | `pytest tests/test_*alpaca*client* -x` | ❌ Wave 0 (add) |
| BOT-03 | `is_specific_bot("D")` true; `KNOWN_BOTS` contains D | unit | `pytest tests/test_dashboard_db.py -x` | ❌ Wave 0 (add) |
| BOT-03 | seed_bots seeds D row when `_D` env set | unit | `pytest tests/test_seed_bots.py -x` | ❌ Wave 0 (add) |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_trade_logger_shim.py -x`
- **Per wave merge:** `python -m pytest -q`
- **Phase gate:** Full suite green (261+) before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] Extend `tests/test_trade_logger_shim.py` — assert `BOT_ID=D` accepted (currently only A/B).
- [ ] `tests/test_dashboard_db.py` — `KNOWN_BOTS`/`is_specific_bot("D")` (if not already covered).
- [ ] `tests/test_seed_bots.py` — D-row seeding with monkeypatched `_D` env.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Bot B's Coolify orchestrator service uses bare `ALPACA_API_KEY` (inferred from `src/config.py` reading bare key + one-service-per-bot model) | Code vs Infra | If B's service actually uses a suffix wrapper, D recipe needs adjusting. Verify via Coolify env before HALT-2. |
| A2 | `daytrade` asset_class for D's `bots` row is crypto (matches A/B) | seed_bots D block | Wrong asset_class mislabels universe; confirm against DAYTRADE profile. |
| A3 | Coolify project UUID `u7x0xw0y4qvcgeh8vyidsgyi` current | HALT-2 | From CLAUDE.md; stale UUID → wrong project. |

## Open Questions

1. **Does Bot B's orchestrator Coolify service literally set bare `ALPACA_API_KEY`?**
   - Known: `src/config.py` reads bare; no suffix logic in `src/`.
   - Unclear: exact env on B's live service (Coolify UI, not in git).
   - Recommendation: verify B's env in Coolify before writing HALT-2; treat A1 as confirmed-on-check.

## Sources

### Primary (HIGH confidence)
- `src/config.py`, `src/alpaca_client.py`, `src/trade_logger.py`, `src/trade_memory.py` — key wiring + BOT_ID validation
- `dashboard/api/db.py`, `dashboard/api/seed_bots.py`, `dashboard/api/routes/equity.py|positions.py|portfolio.py` — attribution
- `dashboard/web/components/trades/TradeTable.tsx`, `.../positions/PositionCard.tsx` — hardcoded A/B
- `scripts/seed_bot_e.py`, `dashboard/api/seed_bots.py` (C block) — multi-bot precedent
- `docs/superpowers/specs/2026-06-08-day-trading-upgrade-design.md` §6, `CLAUDE.md`

## Metadata

**Confidence breakdown:**
- Code edits (trade_logger, KNOWN_BOTS, seed, UI): HIGH — exact lines located.
- Fail-clear no-fallback claim: HIGH — verified in config.py + alpaca_client.py.
- Coolify recipe: MEDIUM — bare-key wiring inferred (A1), needs B-service env confirmation.

**Research date:** 2026-06-15
**Valid until:** 2026-07-15 (stable; Coolify env may drift)
