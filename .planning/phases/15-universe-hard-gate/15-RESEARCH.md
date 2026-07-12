# Phase 15: Universe Hard-Gate Enforcement — Research

**Researched:** 2026-07-12
**Domain:** Trading-bot order-submission control flow, per-bot config plumbing (Postgres `bots` table), pure-predicate gating
**Confidence:** HIGH (all findings are direct codebase evidence with file:line; no external library research needed)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

1. **Pure gate module `src/universe.py`.** Two pure functions, no I/O:
   - `normalize(symbol) -> str` (uppercase, strip `/`, so `BTC/USD` == `BTCUSD`).
   - `entry_allowed(symbol, allowlist, quarantined) -> (bool, reason)` where `reason` is one of
     `None` / `"off_universe"` / `"quarantined"`. Unit-testable to the letter, independent of DB.
2. **Hard gate at `_submit_order`.** Every entry order — long or short, limit or market — is checked
   immediately before the Alpaca call. A blocked symbol: **never** reaches Alpaca, emits a WARNING
   with bot_id/symbol/reason, and writes a terminal `rejected` row (pnl=0, existing Phase-11 path)
   so the block is auditable, then returns `(None, None)`. Belt-and-braces: the same predicate is
   also applied in `select_long_candidates`/`select_short_candidates` so blocked symbols are dropped
   early — but the *gate of record* is `_submit_order` (a leak anywhere upstream still fails closed).
   **Exits are never gated** — an already-open position must always be closeable.
3. **Quarantine is config-driven (UNIV-02).** New `bots` column `quarantined_symbols TEXT` (default
   `''`), migration **`018_universe_quarantine.sql`** (`ADD COLUMN IF NOT EXISTS`), mirrored in
   `src/db_schema.sql`; `BotConfig.quarantined_symbols` + a `quarantined` property that splits it the
   same way `symbols` does. Dropping BTC = one config write, zero code change. Empty = nothing
   quarantined.
4. **Allowlist = the bot's curated `cfg.symbols`.** When a bot has a curated universe, the dynamic
   volume-ranked list may still *feed the scanner*, but it can never widen what is *tradeable* —
   the gate compares against `cfg.symbols`. When `cfg.symbols` is empty (dynamic-only bot), the
   allowlist is the resolved dynamic universe for that cycle, so those bots keep working; the
   quarantine list still applies. This is what closes the TRUMP/FIL leak without breaking Bot C/D.
5. **No behavior change to sizing, risk gate, confluence, or exits.** This phase only *subtracts*
   candidates.

### Claude's Discretion

Not enumerated in CONTEXT.md (mode `--auto`). Implementation detail *within* the five decisions
(function signatures, log wording, test layout) is discretionary.

### Deferred Ideas (OUT OF SCOPE)

- Auto-quarantine (a symbol that goes N-for-M gets quarantined automatically) — needs the Phase-17
  per-symbol stats; revisit in Phase 18.
- Folding the hardcoded `MEME_CRYPTO` / `_ALPACA_UNTRADEABLE` sets into the DB quarantine column —
  keep both for now (constants are a floor, the column is per-bot policy on top).
- Dashboard surfacing of the effective universe — Phase 16 (UNIV-03).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UNIV-01 | Entry is hard-gated to the configured per-bot allowlist; any symbol outside it is rejected and the rejection is logged. | §1 identifies `BotThread._submit_order` (`src/bot_thread.py:328-359`) as the chokepoint for the `confluence` strategy and enumerates the four **non-confluence bypass paths** the gate does not cover. §3 gives the exact symbol formats `normalize()` must reconcile. §2 proves exits do not traverse `_submit_order`, so gating it cannot trap an open position. |
| UNIV-02 | Chronically unprofitable symbols (BTC, 0-for-12) are droppable/quarantinable via config, not code. | §4 gives the exact `bots`-row → `BotConfig.from_row` contract, the migration-018 shape, and the complete list of files/lines that read or write `bots` columns and therefore need the new column. |
</phase_requirements>

## Summary

`BotThread._submit_order` (`src/bot_thread.py:328-359`) **is** the single entry chokepoint — but only
for the `confluence` strategy. It has exactly two call sites: the long entry
(`src/bot_thread.py:790`) and the short entry (`src/bot_thread.py:986`), both with
`order_type="market"`. The `limit` branch (`src/bot_thread.py:337-340`) exists but has **no
production caller today** — it is exercised only by `tests/test_order_resolution.py:246`. Placing the
gate inside `_submit_order` therefore covers 100% of confluence-bot entries, long and short, market
and (future) limit, in one place.

There are **four production entry paths that bypass `_submit_order` entirely** and call
`AlpacaClient.place_market_order` directly: the trend-follower (`src/trend_strategy.py:116`), the
TradingAgents bot (`src/bot_c/strategy.py:313`), the copy-trader (`src/copytrade_thread.py:380`), and
the standalone CLI orchestrator (`src/alpaca_orchestrator.py:968` long, `:1123` short). The first
three are dispatched *from inside* `BotThread._run_cycle` (`src/bot_thread.py:521-536`) or
`BotManager._spawn` (`src/bot_manager.py:287-294`), so they are live, in-container code paths — not
dead code. Decision 2 scopes the gate to `_submit_order`, which means those four paths remain
ungated. That is a **scope fact the planner must state explicitly**, not a bug to fix here: the
copy-trader (which maps arbitrary leader symbols, `src/copytrade_thread.py:380`) and the CLI
orchestrator (which uses the *dynamic* volume-ranked universe, `src/alpaca_orchestrator.py:615`) are
the two paths most plausibly capable of having produced the TRUMP/FIL fills the audit found.

**A material correction to the CONTEXT grounding:** `BotConfig.from_row` coalesces a falsy
`crypto_universe` to the 8-asset default (`src/bot_config.py:51` — `row.get("crypto_universe") or
"BTC/USD,..."`). An empty-string column value therefore becomes the curated 8-asset list, so
`cfg.symbols` is **never empty** for any DB-loaded crypto bot, and the dynamic-fallback branch in
`_resolve_crypto_universe` (`src/bot_thread.py:108-112`) is **unreachable in production**. No bot
today relies on the dynamic fallback (§5). Decision 4's dynamic-bot carve-out is still worth
implementing as a safety net, but it protects a case that cannot currently occur — which means
Decision 4 carries **zero regression risk to Bot C/D**.

**Primary recommendation:** add `src/universe.py` (pure `normalize` + `entry_allowed`), call it at the
top of `_submit_order` before the try-block, and mirror it in `select_long_candidates` /
`select_short_candidates`; add `quarantined_symbols TEXT DEFAULT ''` via migration `018` plus the
`BotConfig` field/property, and thread the column through `_BOT_COLS`, the three Pydantic models,
and `seed_bots.py`'s INSERT. No existing test breaks (§6). No new dependency.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Symbol normalization + allow/deny predicate | Pure domain module (`src/universe.py`) | — | Zero I/O, zero config coupling → exhaustively unit-testable; Decision 1. |
| Hard enforcement at order submission | Bot runtime (`BotThread._submit_order`) | — | The single point every confluence entry crosses; a leak upstream still fails closed. |
| Early candidate pruning (cosmetic/log-noise reduction) | Bot runtime (`select_long_candidates` / `select_short_candidates`) | — | Belt-and-braces only; NOT the gate of record. |
| Per-bot quarantine policy storage | Database (`bots.quarantined_symbols`) | Dashboard API (`PUT /api/bots/{id}`) | Config-driven per UNIV-02: change policy without a deploy. |
| Policy → runtime delivery | `BotConfig.from_row` + `BotManager.update` hot-swap | — | `src/bot_manager.py:236-243` already pushes a new `BotConfig` into the live thread; the new column rides that existing path for free. |
| Exit / close | `AlpacaClient.close_position` + direct `place_market_order` sells | — | Must remain **ungated**. Gate belongs at `_submit_order`, never at the `AlpacaClient` layer (§2 pitfall). |

## Standard Stack

**No new dependency.** This phase is pure-Python + one additive SQL migration. Everything needed is
already in the tree.

### Core (already present)
| Component | Location | Purpose |
|-----------|----------|---------|
| `psycopg` (v3) + `dict_row` | `dashboard/api/migrations/run_migrations.py:6-7`, `src/bot_manager.py` | DB access; migrations run via raw libpq `exec_` for multi-statement SQL. [VERIFIED: codebase] |
| `pytest` | `tests/` (35+ files) | Test framework; fake-double convention, no mocking library needed for the new tests. [VERIFIED: codebase] |
| Numbered SQL migrations | `dashboard/api/migrations/*.sql` | **Not alembic.** `run_migrations.py:11` `sorted(glob("*.sql"))`, `_migrations` filename ledger at `:14-19`. [VERIFIED: codebase] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Gate in `_submit_order` | Gate in `AlpacaClient.place_market_order` | **REJECTED — would break exits.** `src/trend_strategy.py:148`, `src/bot_c/strategy.py:365` and `src/copytrade_thread.py:380` close positions via `place_market_order(side="sell")`. Gating the client would strand open positions in a quarantined symbol. This is the single most dangerous wrong turn in this phase. |
| DB column | Env var (`QUARANTINED_SYMBOLS`) | Env change = Coolify redeploy of each orchestrator service. The column gives per-bot policy with a live hot-swap via `BotManager.update` (`src/bot_manager.py:236`). Decision 3 locks the column. |

**Installation:** none.

## Package Legitimacy Audit

**Not applicable** — this phase installs zero external packages. No `pip install` in scope.

## Architecture Patterns

### System Architecture Diagram

```
                     ┌──────────────── Postgres `bots` row ────────────────┐
                     │ crypto_universe TEXT   ← allowlist source           │
                     │ quarantined_symbols TEXT (NEW, migration 018)       │
                     └───────────────────────┬─────────────────────────────┘
                                             │ SELECT *  (bot_manager.py:67)
                                             ▼
                                  BotConfig.from_row  (bot_config.py:38)
                                             │  .symbols (L66)  .quarantined (NEW)
                                             ▼
   universe ──► scan_assets ──► signals ──► select_long_candidates (bot_thread.py:129)
   (resolve @ L96)                       └─► select_short_candidates (bot_thread.py:150)
                                             │        [belt-and-braces prune — NOT the gate]
                                             ▼
                                     risk gate ──► kelly sizing
                                             │
                                             ▼
                    ┌────────────── BotThread._submit_order (L328) ─────────────┐
                    │  ★ HARD GATE HERE ★                                        │
                    │  entry_allowed(symbol, cfg.symbols, cfg.quarantined)       │
                    │     ├─ blocked → WARN + log_alpaca_trade(status=rejected,  │
                    │     │             pnl=0)  → return (None, None)   [no API] │
                    │     └─ allowed → alpaca.place_limit/market_order(...)      │
                    └────────────────────────────────────────────────────────────┘
                                             │
                                             ▼
                                        Alpaca API

   ── EXIT PATHS (never gated, never touch _submit_order) ──
   PositionMonitor ────────► alpaca.close_position()          (alpaca_orchestrator.py:290)
   trend exit ─────────────► alpaca.place_market_order(sell)  (trend_strategy.py:148)
   bot_c _exit_position ───► alpaca.place_market_order(sell)  (bot_c/strategy.py:365)

   ── ENTRY PATHS THAT BYPASS THE GATE (out of scope, must be documented) ──
   strategy=trend_btc     ► trend_strategy.py:116      (dispatched bot_thread.py:521-527)
   strategy=tradingagents ► bot_c/strategy.py:313      (dispatched bot_thread.py:530-536)
   strategy=copytrade     ► copytrade_thread.py:380    (dispatched bot_manager.py:287-292)
   CLI `python -m src.alpaca_orchestrator` ► alpaca_orchestrator.py:968 / :1123
```

### Pattern 1: Pure predicate module (Decision 1)

**What:** A dependency-free module holding the gate logic, so the rule can be tested exhaustively
without a DB, an Alpaca client, or a thread.
**When to use:** Always, for any rule that must hold at multiple layers (here: two — the candidate
selectors and `_submit_order`).
**Precedent in this repo:** `src/order_resolution.py` — Phase-11/14 extracted `classify_order` into a
pure module, and `BotThread._classify` (`src/bot_thread.py:266-268`) is a one-line delegate. Mirror
that exactly.

```python
# src/universe.py — shape only; matches Decision 1's contract
def normalize(symbol: str) -> str:
    """'BTC/USD' -> 'BTCUSD'; 'spy' -> 'SPY'. Idempotent."""
    return (symbol or "").upper().replace("/", "").strip()

def entry_allowed(symbol, allowlist, quarantined) -> tuple[bool, str | None]:
    """(allowed, reason). reason ∈ {None, 'off_universe', 'quarantined'}."""
    s = normalize(symbol)
    if s in {normalize(q) for q in quarantined}:
        return False, "quarantined"
    allow = {normalize(a) for a in allowlist}
    if allow and s not in allow:
        return False, "off_universe"
    return True, None
```

Note the `if allow and ...` guard: an **empty allowlist means "no restriction"**, which is exactly
Decision 4's dynamic-bot carve-out. The caller passes the resolved dynamic universe when it has one;
if it passes nothing, the bot is not bricked — only the quarantine list applies.

### Pattern 2: Gate placed before the try-block, reusing the Phase-11 rejected-row path

`_submit_order` already writes a terminal `rejected` row on a submit exception
(`src/bot_thread.py:342-348`). The gate must produce the **same** terminal row so the block is
auditable in exactly the way the reconciliation (Phase 13) and backfill (Phase 14) work already
understand. Reuse the existing `dict(trade_data)` + `status=rejected, pnl=0` shape verbatim; do not
invent a new status value.

### Anti-Patterns to Avoid

- **Gating in `AlpacaClient`.** Blocks exits (§2). Never.
- **Gating only in `select_*_candidates`.** Leaves `_submit_order` open — and the selectors are not on
  the trend/tradingagents/copytrade paths at all. The selectors are the *cosmetic* layer.
- **A new `status` value (e.g. `'blocked'`).** `src/order_resolution.py`'s terminal set and the
  dashboard both key on the existing statuses; introducing a sixth breaks Phase-12/13 accounting.
  Use `rejected` (Decision 2 says so explicitly).
- **Adding the column to `BotUpdate` but not `_BOT_COLS`.** The PUT would silently write a column the
  subsequent `SELECT {_BOT_COLS}` never returns → the API echoes stale config. Both must change (§4).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Symbol comparison across layers | Ad-hoc `.replace("/","")` at each call site | `src/universe.normalize` (one function) | Four distinct formats already exist in this codebase (§3). Scattering the normalization is exactly how `BTCUSD != BTC/USD` bugs get born. `AlpacaClient` already has one such scattered strip at `src/alpaca_client.py:385`. |
| Recording a blocked entry | A new table / a new status / a log-only record | The existing `logger.log_alpaca_trade({... "status": "rejected", "pnl": 0})` path (`src/bot_thread.py:345-347`) | Phase-11 built it; Phase-13 reconciliation and Phase-14 backfill already handle `rejected` rows correctly. |
| Pushing new config to a running bot | A restart, a signal, a poll | `BotManager.update` → `BotThread.update_config` (`src/bot_manager.py:236-243`, `src/bot_thread.py:214-218`) | Atomic config swap already exists and is re-read at the top of every cycle (`src/bot_thread.py:459`). The new column rides it with zero new machinery. |
| Migration ordering / idempotency | A hand-rolled runner | `dashboard/api/migrations/run_migrations.py` + `ADD COLUMN IF NOT EXISTS` | Filename-sorted, ledgered in `_migrations`. Follow the `004_stock_universe.sql:4-5` / `008_asset_class.sql:4-7` pattern exactly. |

**Key insight:** every mechanism this phase needs (pure-module precedent, rejected-row path, hot-swap,
migration runner) already exists. This is a *wiring* phase, not an invention phase. Any task that
proposes new infrastructure is over-scoped.

## Runtime State Inventory

Not a rename/refactor/migration phase — but it *does* add DB state, so the additive equivalent:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `bots` table gains `quarantined_symbols TEXT DEFAULT ''`. No existing rows are modified (default backfills to `''` = nothing quarantined = current behavior). | Migration `018` only. **No data migration.** No DELETE/DROP (CLAUDE.md hard rule). |
| Live service config | Coolify Postgres for the dashboard app — migration must run against it. `run_migrations.py` is invoked on dashboard boot; the column is additive and safe to apply **before** the new orchestrator code deploys (same property migration 017 documents at its header, `017_reconciliation.sql:5-6`). | Deploy dashboard (runs migration) → then orchestrators. |
| OS-registered state | None — verified: no Task Scheduler / pm2 artifacts reference universe config. | None. |
| Secrets/env vars | None. `ALPACA_UNTRADEABLE` env already exists (`src/alpaca_orchestrator.py:79-82`) and is **unchanged** by this phase (deferred idea: do not fold it into the column). | None. |
| Build artifacts | None. | None. |

## Findings — the six questions, with evidence

### 1. Every entry-order call site

**`BotThread._submit_order` (`src/bot_thread.py:328-359`) is the chokepoint for the `confluence`
strategy — and only that strategy.** [VERIFIED: codebase grep + read]

Call sites of `_submit_order` (exhaustive, repo-wide):

| File:line | Side | order_type | Notes |
|-----------|------|-----------|-------|
| `src/bot_thread.py:790` | `buy` (long entry) | `"market"` | The long entry, after risk gate + Kelly. |
| `src/bot_thread.py:986` | `sell` (short **entry**) | `"market"` | Short entry — a `sell` that OPENS a position. Must be gated (Decision 2). |
| `tests/test_order_resolution.py:156, 246` | test | market | Test-only. |

Inside `_submit_order`, both order types are reachable:
- limit → `alpaca.place_limit_order` (`src/bot_thread.py:338-340`)
- market → `alpaca.place_market_order` (`src/bot_thread.py:341`)

**No production call passes `order_type="limit"` today** — the limit branch is exercised only by
`tests/test_order_resolution.py:246`. Gating at the top of `_submit_order` covers both branches
regardless, satisfying Decision 2's "limit or market". [VERIFIED: codebase]

**BYPASSES — production entry paths that never touch `_submit_order`:**

| # | File:line | Strategy / entry point | Dispatched from |
|---|-----------|------------------------|-----------------|
| B1 | `src/trend_strategy.py:116` — `alpaca.place_market_order(symbol=target, qty=qty, side="buy")` | `strategy == "trend_btc"` | `src/bot_thread.py:521-527` (`run_trend_cycle`) |
| B2 | `src/bot_c/strategy.py:313` — `alpaca.place_market_order(symbol=symbol, qty=..., side="buy")` | `strategy == "tradingagents"` | `src/bot_thread.py:530-536` (`run_tradingagents_cycle`) |
| B3 | `src/copytrade_thread.py:380` — `alpaca.place_market_order(symbol=mapped, qty=qty, side=side)` | `strategy == "copytrade"` (Bot E) | `src/bot_manager.py:287-292` — a **`CopyTraderThread`, not a `BotThread`** |
| B4 | `src/alpaca_orchestrator.py:968` (long) and `:1123` (short) | standalone CLI: `python -m src.alpaca_orchestrator` | Not the container bot path; uses the **dynamic** universe (`src/alpaca_orchestrator.py:615`) |

B3 is the highest-suspicion source of the audited TRUMP/FIL fills: it trades whatever symbol the
leader traded, after a symbol mapping (`src/copytrade_thread.py:87`), with no universe concept at
all. B4 is the second (dynamic volume-ranked universe, meme-filter only).

**Planner instruction:** Decision 2 scopes the gate to `_submit_order`. Therefore the plan MUST state,
in the phase summary and in `VERIFICATION.md`, that B1–B4 remain ungated by design, and that UNIV-01
is satisfied *for the confluence strategy*. Silently claiming "all entries are gated" would be false.
Whether to extend the gate to B1–B4 is a **scope decision for the user**, not a research call
(candidate: a follow-on phase, or an explicit CONTEXT amendment).

### 2. Exits do NOT go through `_submit_order` — confirmed

[VERIFIED: codebase — exhaustive grep of `close_position` / `place_market_order` in `src/`]

| Exit path | File:line | Mechanism |
|-----------|-----------|-----------|
| **PositionMonitor** (the confluence bots' only exit) | `src/alpaca_orchestrator.py:290` | `self.alpaca.close_position(symbol)` |
| `AlpacaClient.close_position` | `src/alpaca_client.py:382-389` | `trading_client.close_position(symbol_or_asset_id=symbol.replace("/",""))` |
| trend-follower exit | `src/trend_strategy.py:148` | `place_market_order(side="sell")` — direct, not `_submit_order` |
| TradingAgents `_exit_position` | `src/bot_c/strategy.py:365` | `place_market_order(side="sell")` — direct |
| copy-trader (both sides) | `src/copytrade_thread.py:380` | `place_market_order(side=side)` — direct |
| backtester | `src/backtester/portfolio.py:39` | In-memory sim; no API. |

**Conclusion:** no exit path calls `_submit_order`. A gate inside `_submit_order` is
**provably incapable of blocking a close.** ✅ Decision 2's safety property holds.

**⚠ Corollary — the load-bearing pitfall:** because three exits call `place_market_order` *directly*,
putting the gate in `AlpacaClient.place_market_order` (a tempting "one true chokepoint") would strand
open positions in any quarantined symbol. The gate must live at `_submit_order`. This must appear as
an explicit verification check.

Note the asymmetry the implementer must not fumble: in `_submit_order`, `side="sell"` at
`src/bot_thread.py:986` is an **entry** (opening a short), not an exit. The gate applies to *every*
`_submit_order` call regardless of `side` — correct, because `_submit_order` is only ever called to
open.

### 3. Exact symbol formats at each layer

[VERIFIED: codebase]

| Layer | Format | Evidence |
|-------|--------|----------|
| Config `crypto_universe` | **slash** — `"BTC/USD,ETH/USD,..."` | `src/bot_config.py:23`; `dashboard/api/seed_bots.py:36,58,82,105`; DB default `002_multi_bot.sql:17` |
| Config `stock_universe` | **bare** — `"SPY,QQQ,NVDA"` | `src/bot_config.py:24` |
| `cfg.symbols` (list) | slash (crypto) / bare (stock) — split on `,`, stripped | `src/bot_config.py:66-71` |
| `scan_assets(symbols=...)` | passes the universe strings straight through | `src/technical_signals.py:481-497` (docstring: `e.g. ["BTC/USD", "ETH/USD"]`) |
| **`TechnicalSignal.symbol`** | **slash** (inherited from the universe string) | same — the Signal's `symbol` is the input symbol |
| `open_symbols` (dedup set) | **slash** — sourced from the DB, which stores what was submitted | `src/bot_thread.py:556-557` ← `logger.get_open_alpaca_positions()` ← `alpaca_trades.symbol` ← written at `src/bot_thread.py:795` from `signal.symbol` |
| `_submit_order(symbol=...)` → Alpaca | **slash PRESERVED** | `src/alpaca_client.py:296` / `:334` pass `symbol` through unmodified; confirmed by the `get_closed_orders` docstring: *"slash PRESERVED — only close_position strips it"* (`src/alpaca_client.py:423`) |
| **Alpaca position `symbol`** (live API) | **NO slash** — `"BTCUSD"` | `src/alpaca_client.py:146` — `"symbol": pos.symbol` from the Alpaca SDK |
| `close_position` | strips the slash before the call | `src/alpaca_client.py:385` — `close_symbol = symbol.replace("/", "")` |
| Hardcoded exclusion sets | **slash** | `MEME_CRYPTO` = `{"DOGE/USD", ...}` (`src/alpaca_evaluator.py:42`); `_ALPACA_UNTRADEABLE` default `"LDO/USD,POL/USD,ONDO/USD,RENDER/USD,DOT/USD,ARB/USD,SUSHI/USD,HYPE/USD,LINK/USD,ETH/USD"` (`src/alpaca_orchestrator.py:78-82`) |
| Dynamic universe | **slash** — `'BTC/USD' format` | `src/alpaca_evaluator.py:57-62` docstring + `:97-99` |

**Therefore `normalize()` must:** uppercase, strip `/`, strip whitespace. That makes
`BTC/USD → BTCUSD` (matching the live-position format), `btc/usd → BTCUSD`, and `SPY → SPY`
(stocks unaffected). Everything the gate compares — `cfg.symbols`, `signal.symbol`,
`quarantined_symbols`, and an Alpaca position symbol — collapses to one canonical key.

Operator note for the quarantine column: an operator may plausibly type `BTC`, `BTC/USD`, or `BTCUSD`.
`normalize("BTC") == "BTC"` ≠ `"BTCUSD"`, so **bare `BTC` will NOT match `BTC/USD`.** This is a real
usability edge. Recommend the plan either (a) document that `quarantined_symbols` must use the same
format as `crypto_universe` (i.e. `BTC/USD`), or (b) add a suffix-tolerant match. Decision 1 locks the
`normalize` contract to *uppercase + strip slash* only, so **(a) — document it** is the in-scope
answer; flag (b) as a Phase-16 dashboard-input-validation concern.

### 4. The `bots` row → `BotConfig.from_row` contract, and everything the new column touches

**Row shape reaching `from_row`:** a psycopg3 `dict_row` from `SELECT * FROM bots WHERE enabled = TRUE
AND alpaca_api_key IS NOT NULL AND alpaca_api_key != ''` (`src/bot_manager.py:67-70`; identical query
in the watchdog at `:105`). `SELECT *` means **the new column arrives automatically** once the
migration runs. `from_row` (`src/bot_config.py:38-64`) uses `row.get(...)` throughout, so a row from a
*pre-migration* DB (missing key) is also safe → the field defaults to `""` → nothing quarantined →
current behavior. Fail-open on the *quarantine* dimension is correct; the allowlist dimension is
sourced from `crypto_universe`, which always exists.

**Changes needed in `src/bot_config.py` (do not edit — plan only):**
- add field `quarantined_symbols: str = ""` (after `trend_benchmark`, L36)
- add to `from_row`: `quarantined_symbols=row.get("quarantined_symbols") or ""` (alongside L63)
- add property `quarantined` mirroring `symbols` (L66-71): `[s.strip() for s in
  self.quarantined_symbols.split(",") if s.strip()]` — note: **asset-class-agnostic**, unlike
  `symbols`, since a quarantine list is a flat deny-list.

**Migration `018_universe_quarantine.sql`** — follow `004_stock_universe.sql:4-5` verbatim:
```sql
ALTER TABLE bots
    ADD COLUMN IF NOT EXISTS quarantined_symbols TEXT DEFAULT '';
```
Runner: `dashboard/api/migrations/run_migrations.py` — `sorted(glob("*.sql"))` (`:11`), ledgered in
`_migrations` by filename (`:14-19`), raw libpq `exec_` so multi-statement SQL is fine (`:36`).
Additive + idempotent + no data change ⇒ safe to apply before the new code deploys (same property
`017_reconciliation.sql:5-6` asserts for itself).

**⚠ `src/db_schema.sql` mirror — a real discrepancy the planner must handle.** The `bots` DDL there
(`src/db_schema.sql:8-15`) is **stale**: it declares only `id, label, starting_equity,
alpaca_key_prefix, config_flags, created_at` — plus a `CHECK (id IN ('A','B'))` that live DBs have
outgrown (migration `009_drop_bot_id_check.sql`). It contains **no** `bot_id`, **no**
`crypto_universe`, **no** `kelly_fraction` — every config column comes from migration `002+`. So there
is no sibling column next to which `quarantined_symbols` would naturally sit. `alpaca_trades` in the
same file *does* carry mirror comments for Phases 11/12 (`src/db_schema.sql:39-45`). Options for the
planner (pick one and state it): (a) add `quarantined_symbols TEXT DEFAULT ''` to the `bots` CREATE
TABLE with a `-- Phase 15 (mirror of migration 018)` comment, accepting that the block remains
otherwise incomplete; (b) add only a comment pointing to migration 018. CONTEXT Decision 3 says
"mirrored in `src/db_schema.sql`" → **(a)**, plus a one-line note that the config columns live in
migrations. Do **not** attempt to reconcile the whole stale block — out of scope, and touching the
`CHECK (id IN ('A','B'))` risks breaking C/D/E.

**Files/lines that read or write `bots` columns and need the new column** (evidence; **do not edit —
this is the planner's checklist**):

| File:line | What it is | Needs `quarantined_symbols`? |
|-----------|-----------|------------------------------|
| `dashboard/api/routes/bots.py:20-24` | `_BOT_COLS` — the projection used by GET list (`:56`), GET one (`:96`), PUT-return (`:136`), enable/disable-return (`:183`, `:218`) | **YES** — else the API never echoes the value |
| `dashboard/api/routes/bots.py:82-90` | `POST /api/bots` INSERT column list | **YES** (else new bots can't be created with a quarantine list) |
| `dashboard/api/routes/bots.py:113-131` | `PUT /api/bots/{id}` — builds `set_clauses` dynamically from non-`None` `BotUpdate` fields | **No SQL change** — works automatically once the field exists on `BotUpdate`. Note `""` is not `None`, so "clear the quarantine list" is expressible. |
| `dashboard/api/models.py:209-232` | `BotFull` (response) | **YES** — `quarantined_symbols: str = ""` |
| `dashboard/api/models.py:234-250` | `BotCreate` | **YES** — `quarantined_symbols: str = ""` |
| `dashboard/api/models.py:252-270` | `BotUpdate` | **YES** — `quarantined_symbols: Optional[str] = None` |
| `dashboard/api/seed_bots.py:136-155` | INSERT column list + VALUES for A/B/C/D | **YES** — column list at `:138-144`, params at `:146-152`; per-bot dicts at `:26-46` (A), `:48-68` (B), `:70-93` (C), `:95-118` (D). Suggest `os.environ.get("BOT_X_QUARANTINED", "")`. |
| `dashboard/api/seed_bots.py:160-169` | `UPDATE bots SET alpaca_api_key = COALESCE(...)` on the already-exists branch | **NO** — key-patch only; must NOT be widened (would clobber live operator edits). |
| `dashboard/api/routes/settings.py:49` | `SELECT * FROM bots ...` | **NO change** — `SELECT *` picks it up; the route only reads `crypto_universe`/`stock_universe` (`:99-106`). |
| `src/bot_manager.py:67-70`, `:105` | `SELECT *` → `BotConfig.from_row` | **NO change** — `SELECT *`. |
| `dashboard/web/types/index.ts`, `dashboard/web/components/bots/BotCard.tsx`, `BotDrawer.tsx` | TS `Bot` type + the config drawer | **Phase 16 (UNIV-03)** — out of scope here. Adding a field to `BotFull` does not break the TS client (extra JSON keys are ignored), so this phase can ship without touching the frontend. |

### 5. Which bots rely on the dynamic fallback today

**None. Verified.** [VERIFIED: codebase]

- `dashboard/api/seed_bots.py` seeds A (`:36`), B (`:58`), C (`:82`), D (`:105`) each with a
  **non-empty** `crypto_universe` (env-overridable, default = the 8-asset curated list).
- DB column default is non-empty: `'BTC/USD,ETH/USD,SOL/USD,XRP/USD'` (`002_multi_bot.sql:17`).
- **Decisive:** `BotConfig.from_row` coalesces falsy → default (`src/bot_config.py:51`):
  `crypto_universe=row.get("crypto_universe") or "BTC/USD,ETH/USD,SOL/USD,XRP/USD,ADA/USD,AVAX/USD,DOT/USD,LINK/USD"`.
  A `NULL` **or an empty string** therefore becomes the 8-asset list. Consequently `cfg.symbols`
  (`src/bot_config.py:66-71`) is **never empty** for a DB-loaded crypto bot, and the dynamic branch of
  `_resolve_crypto_universe` (`src/bot_thread.py:108-112`) is **unreachable in production**. The only
  construction path that yields an empty `crypto_universe` is a direct `BotConfig(crypto_universe="")`
  — which exists solely in `tests/test_universe_resolution.py:48`.
- Bot E (`strategy == "copytrade"`) does not use a universe at all — `CopyTraderThread`
  (`src/bot_manager.py:287-292`) never calls `_resolve_crypto_universe`.

**Grounding for Decision 4:** the "dynamic-only bot keeps working" carve-out protects a case that
**cannot currently occur**, so implementing it carries **zero regression risk to Bot C or D** — and it
is still worth implementing, because it is the difference between a gate that fails *safe* and one
that bricks a bot if someone later blanks a universe. Implement it as the `if allow and ...` guard in
`entry_allowed` (empty allowlist ⇒ no allowlist restriction). Do **not** claim in the plan that this
"fixes Bot C/D" — it prevents a future break, nothing more.

**Consequence for the leak narrative:** since the dynamic fallback is unreachable, the TRUMP/FIL
entries did **not** come from `_resolve_crypto_universe`'s fallback on a confluence bot as CONTEXT §Domain
hypothesizes. The gate is still the right fix (it makes the invariant enforced rather than merely
implied), but the plan should state the leak's actual likely origin as B3 (copy-trader,
`src/copytrade_thread.py:380` — arbitrary leader symbols) or B4 (CLI orchestrator dynamic universe,
`src/alpaca_orchestrator.py:615`) — **neither of which this phase's gate covers.** [ASSUMED — the
audit's per-trade `bot_id` attribution was not re-derived in this research; confirm against
`alpaca_trades` before asserting it in the plan.]

### 6. Existing tests that would break

**None break.** [VERIFIED: read every test that touches the selectors, `_submit_order`, or `BotConfig`]

| Test file | Uses | Symbols exercised | Verdict |
|-----------|------|-------------------|---------|
| `tests/test_risk_hardening.py:36` `_cfg()` | default `BotConfig(...)` → default 8-asset universe; drives **the real** `select_long_candidates` (`:70`, `:84`) and `select_short_candidates` (`:101`) | `BTC/USD`, `ETH/USD`, `SOL/USD`, `XRP/USD`, `ADA/USD` — **all in the default allowlist** | **PASS.** (`ETH/USD` at `:68` is *already* expected to be filtered — by `rsi_ceiling`, and it is additionally in `_ALPACA_UNTRADEABLE`.) The `bear_fraction` tests at `:42-57` use symbols `A`–`D` but never call the selectors. |
| `tests/test_learning_realloop.py:89-102` | real `BotThread._run_cycle`, `crypto_universe="BTC/USD"`, signal symbol `BTC/USD` (`:36`), `universe=["BTC/USD"]` (`:145`) | `BTC/USD` — in allowlist | **PASS.** Order-count assertions (`alpaca.orders == []` on veto, qty ratio on scale) unaffected. |
| `tests/test_order_resolution.py:131` `_bot()` | default `BotConfig`; calls `_submit_order` directly at `:156` and `:246` with `symbol="BTC/USD"` | `BTC/USD` — in the default allowlist | **PASS** — including `test_submit_exception_records_rejected` (`:240-258`), which asserts *exactly one* rejected row; the gate must not add a second row when it lets the symbol through. |
| `tests/test_universe_resolution.py` | `_resolve_crypto_universe` only | n/a | **PASS** — `_resolve_crypto_universe` is not modified by this phase. |
| `tests/test_atr_exits.py`, `tests/test_close_pnl.py`, `tests/conftest.py:52` | `close_position` mocks | n/a | **PASS** — exits untouched (§2). |

**The one live regression risk:** `_submit_order`'s current signature (`src/bot_thread.py:328-329`)
takes no `cfg`. It is a `BotThread` method, so the gate must read `self.config` (thread-safe accessor,
`src/bot_thread.py:204-212`) rather than adding a parameter — adding a required parameter would break
`tests/test_order_resolution.py:156` and `:246`. **Read `self.config` inside `_submit_order`.**

## Common Pitfalls

### Pitfall 1: Gating the wrong layer strands open positions
**What goes wrong:** the gate is placed in `AlpacaClient.place_market_order`; a quarantined symbol's
open position can never be closed, because three exit paths call that method directly (§2).
**Why:** `place_market_order` looks like the "one true chokepoint" from a naive grep.
**How to avoid:** gate at `BotThread._submit_order` only. **Warning sign:** any diff touching
`src/alpaca_client.py`.
**Verification:** a test that opens a position in symbol X, quarantines X, and asserts the
PositionMonitor still closes it.

### Pitfall 2: Claiming "all entries gated" when four paths bypass
**What goes wrong:** UNIV-01 is marked Complete while `trend_btc`, `tradingagents`, `copytrade`, and
the CLI orchestrator can still fill off-universe symbols (§1, B1–B4).
**How to avoid:** the plan and `VERIFICATION.md` must scope the claim to the confluence strategy and
name B1–B4 explicitly.

### Pitfall 3: `_BOT_COLS` / model drift
**What goes wrong:** the column is added to the DB and `BotUpdate` but not to `_BOT_COLS`
(`dashboard/api/routes/bots.py:20-24`) → the PUT succeeds but the GET never returns the value, so the
dashboard shows a stale/absent quarantine list and the operator cannot confirm the write landed.
**How to avoid:** the §4 checklist is a single atomic change-set.

### Pitfall 4: Bare-ticker quarantine entries silently no-op
**What goes wrong:** operator writes `BTC` into `quarantined_symbols`; `normalize("BTC") == "BTC"` ≠
`normalize("BTC/USD") == "BTCUSD"` → BTC keeps trading, and the operator believes it is quarantined.
This is a *silent* failure of the phase's headline use case ("dropping BTC = one config write").
**How to avoid:** document the required format (`BTC/USD`), and — strongly recommended — have the gate
emit an INFO line at bot start listing the *effective* quarantine set as normalized, so a typo is
visible in the logs. **Warning sign:** a quarantine write that produces no `off_universe`/`quarantined`
WARNINGs in the next cycle.

### Pitfall 5: Double-writing the rejected row
**What goes wrong:** the gate writes a `rejected` row, then falls through into the existing
try/except which writes another. **How to avoid:** `return None, None` immediately after the gate's
`log_alpaca_trade`. `tests/test_order_resolution.py:255` (`len(logger.rows) == 1`) is the existing
guard for the exception path; add the symmetric assertion for the gate path.

### Pitfall 6: The `bots` CHECK constraint
`src/db_schema.sql:9` still has `CHECK (id IN ('A','B'))`; live DBs dropped the equivalent on
`alpaca_trades` via `009_drop_bot_id_check.sql`, and `017_reconciliation.sql:4-5` explicitly warns
"NO bot_id CHECK (live bots dropped it for C/D, mig 009)". Migration 018 must be a bare
`ADD COLUMN IF NOT EXISTS` and must not touch constraints.

## Code Examples

### The existing rejected-row path to reuse (`src/bot_thread.py:342-348`)
```python
        except Exception as exc:
            log.exception("[bot:%s] Order placement failed for %s: %s",
                          self.bot_id, symbol, exc)
            rejected = dict(trade_data)
            rejected.update({"status": "rejected", "order_type": order_type, "pnl": 0})
            logger.log_alpaca_trade(rejected)
            return None, None
```
The gate's block branch must produce the identical row shape (with a distinct WARNING message
carrying `bot_id`, `symbol`, `reason`).

### The pure-module delegate precedent (`src/bot_thread.py:266-268`)
```python
    def _classify(self, order: dict):
        """Delegate to the pure src.order_resolution.classify_order (Phase-14)."""
        return classify_order(order)
```
`src/universe.py` should be imported and used the same way (`src/bot_thread.py:17` shows the import
convention: `from src.order_resolution import classify_order, _TERMINAL_NONPOSITION`).

### Migration precedent (`dashboard/api/migrations/004_stock_universe.sql:4-5`)
```sql
ALTER TABLE bots
    ADD COLUMN IF NOT EXISTS stock_universe TEXT DEFAULT 'QQQ,SPY,AAPL,NVDA,MSFT,TSLA,AMZN,META';
```

## State of the Art

Not applicable — no external technology decision in this phase. The only "old vs new" is internal:

| Old | Current | Impact |
|-----|---------|--------|
| Universe = a *scan input* only (`_resolve_crypto_universe` → `scan_assets`) | Universe = an *enforced allowlist* at submission | An off-universe symbol reaching the selector by any route now fails closed. |
| Exclusions = hardcoded module constants (`MEME_CRYPTO`, `_ALPACA_UNTRADEABLE`) | Per-bot `quarantined_symbols` column *on top of* the constants (constants stay — deferred idea) | Drop a symbol without a deploy. |

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `pytest` | new unit tests | ✓ | in `tests/` (pytest 8.3.5 per `__pycache__` artifacts) | — |
| `psycopg` (v3) | migration 018 | ✓ | used by `run_migrations.py:6` | — |
| Coolify Postgres | applying 018 in prod | ✓ (live) | — | Migration is additive + idempotent; runs on dashboard boot. |
| Alpaca API | not needed — all new tests use fakes | n/a | — | — |

**Missing dependencies with no fallback:** none.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (8.3.5) |
| Config file | none dedicated — tests run from repo root; `tests/conftest.py` provides shared fixtures |
| Quick run command | `python -m pytest tests/test_universe_gate.py tests/test_order_resolution.py -x -q` |
| Full suite command | `python -m pytest tests/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UNIV-01 | `normalize()` collapses `BTC/USD`/`btcusd`/`BTCUSD` to one key; is idempotent | unit | `pytest tests/test_universe_gate.py -k normalize -x` | ❌ Wave 0 |
| UNIV-01 | `entry_allowed` returns `(False, "off_universe")` for a symbol not in the allowlist | unit | `pytest tests/test_universe_gate.py -k off_universe -x` | ❌ Wave 0 |
| UNIV-01 | `entry_allowed` with an **empty** allowlist allows everything (Decision 4 dynamic bot) | unit | `pytest tests/test_universe_gate.py -k empty_allowlist -x` | ❌ Wave 0 |
| UNIV-01 | `_submit_order` blocks an off-universe entry: **no** `place_market_order` call, **exactly one** `rejected` row (pnl=0), returns `(None, None)` | unit (FakeAlpacaClient/FakeLogger, `tests/test_order_resolution.py:95-127` convention) | `pytest tests/test_order_resolution.py -k gate -x` | ❌ Wave 0 (extend existing file or new `tests/test_universe_gate.py`) |
| UNIV-01 | `_submit_order` blocks a **short** entry (`side="sell"`) the same way — a sell-to-open is still an entry | unit | `pytest tests/test_universe_gate.py -k short -x` | ❌ Wave 0 |
| UNIV-01 | An **allowed** symbol still submits and writes exactly one `submitted` row (no regression) | unit | `pytest tests/test_order_resolution.py::test_submit_persists_submitted_row -x` | ✅ exists (`tests/test_order_resolution.py:148`) |
| UNIV-01 | `select_long_candidates` / `select_short_candidates` drop off-universe + quarantined signals | unit | `pytest tests/test_risk_hardening.py -x` + new cases | ✅ file exists; new cases needed |
| UNIV-01 | **Exits are never gated** — a quarantined symbol's open position still closes | unit | `pytest tests/test_universe_gate.py -k exit_not_gated -x` | ❌ Wave 0 |
| UNIV-02 | `BotConfig.from_row` reads `quarantined_symbols`; missing key → `""`; `quarantined` property splits like `symbols` | unit | `pytest tests/test_bot_config.py -x` | ✅ file exists (`tests/test_bot_config.py`); new cases needed |
| UNIV-02 | `entry_allowed` returns `(False, "quarantined")` and quarantine **precedes** the allowlist check (a symbol both in-universe and quarantined ⇒ reason=`"quarantined"`) | unit | `pytest tests/test_universe_gate.py -k quarantined -x` | ❌ Wave 0 |
| UNIV-02 | Migration 018 applies idempotently (re-run is a no-op) | manual/integration | `python dashboard/api/migrations/run_migrations.py` (needs `DATABASE_URL`) | manual-only — no DB fixture exists in this repo's test suite |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_universe_gate.py tests/test_order_resolution.py tests/test_risk_hardening.py tests/test_bot_config.py -q`
- **Per wave merge:** `python -m pytest tests/ -q`
- **Phase gate:** full suite green before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_universe_gate.py` — the new pure-module + `_submit_order`-gate tests (covers UNIV-01, UNIV-02). Reuse `FakeAlpacaClient` / `FakeLogger` from `tests/test_order_resolution.py:95-127`.
- [ ] New cases in `tests/test_bot_config.py` (quarantine field/property) and `tests/test_risk_hardening.py` (selector pruning).
- [ ] No framework install needed.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface changed. |
| V3 Session Management | no | — |
| V4 Access Control | no | The dashboard `PUT /api/bots/{id}` surface is unchanged in shape; one field added. |
| V5 Input Validation | **yes** | `quarantined_symbols` is operator-supplied free text reaching a **parameterized** UPDATE (`dashboard/api/routes/bots.py:128-131` — `%(col)s` placeholders, values bound). ⚠ Note the `set_clauses` **column names** are interpolated into the SQL string from `BotUpdate` field names (`:113`) — those are Pydantic-model-derived, never user-controlled, so no injection. Adding the field to `BotUpdate` preserves that property. The *value* is bound. Validate/normalize the string on read (in `BotConfig.quarantined`), not with a fragile regex on write. |
| V6 Cryptography | no | — |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via a new dynamic column in `set_clauses` | Tampering | Column names come from `BotUpdate.model_dump()` keys (a fixed Pydantic schema), values are bound params (`dashboard/api/routes/bots.py:113-131`). Do **not** widen this to accept arbitrary keys. |
| Fail-open gate (an exception in the gate lets an order through) | Elevation / Tampering | `entry_allowed` is pure and total (no I/O, no raise). Do **not** wrap the gate call in a `try/except: pass` — a raising gate must fail **closed**. |
| Unauditable block (a rejected entry leaves no record) | Repudiation | Decision 2's terminal `rejected` row (pnl=0) + WARNING with bot_id/symbol/reason. |
| Denial-of-trading (a bad quarantine write silently halts a bot) | DoS | Log the effective normalized quarantine set once per config swap so a fat-fingered write is visible (Pitfall 4). |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The TRUMP/FIL fills most likely originated from the copy-trader (B3) or the CLI orchestrator (B4), not the confluence dynamic fallback. | §5 | If they came from a confluence bot via a path not found here, this phase's gate still closes it (the gate is path-agnostic *within* `_submit_order`) — but the plan's narrative would be wrong. **Mitigation: query `alpaca_trades` for the `bot_id` on the TRUMP/FIL rows before writing the plan summary.** Low risk to the code, moderate to the claim. |
| A2 | pytest version is 8.3.5 (inferred from `tests/__pycache__/*.cpython-313-pytest-8.3.5.pyc`). | Validation Architecture | Cosmetic only — no version-specific API is used. |
| A3 | The Coolify dashboard service runs `run_migrations.py` on boot (so 018 auto-applies). | Runtime State Inventory | If not, migration 018 must be applied manually before the orchestrators deploy. **Verify the dashboard entrypoint before the deploy step.** If wrong: bots load a row without the column → `from_row`'s `.get()` returns `None` → `""` → quarantine inert (fails safe, no crash). |

## Open Questions

1. **Do B1–B4 (trend / tradingagents / copytrade / CLI) need the gate too?**
   - What we know: they are live entry paths that bypass `_submit_order` entirely (§1).
   - What's unclear: CONTEXT Decision 2 scopes the gate to `_submit_order` and does not mention them.
   - Recommendation: **implement Phase 15 exactly as locked** (do not scope-creep), and have the plan
     raise B1–B4 as an explicit finding in `VERIFICATION.md` + a proposed follow-on phase. Extending
     the gate to `run_trend_cycle` / `run_tradingagents_cycle` / `CopyTraderThread` is a
     mechanically small change but a real scope change, and copy-trade *by definition* trades whatever
     the leader trades — gating it may be a product decision, not a bug fix.

2. **Quarantine entry format (`BTC` vs `BTC/USD`).**
   - What we know: `normalize` per Decision 1 does not resolve a bare base ticker to a pair (§3, Pitfall 4).
   - Recommendation: document `BTC/USD` as the required format; log the effective normalized set at
     config-swap time. Defer input validation/UX to Phase 16.

3. **`src/db_schema.sql` `bots` block is stale** (missing every config column; has an obsolete
   `CHECK (id IN ('A','B'))`).
   - Recommendation: add only `quarantined_symbols` + a pointer comment. A full reconciliation is its
     own (worthwhile) phase and must not ride along here.

## Sources

### Primary (HIGH confidence) — all direct codebase reads
- `src/bot_thread.py` — `_resolve_crypto_universe` (96-115), `select_long_candidates` (129-147), `select_short_candidates` (150-164), `_submit_order` (328-359), long entry call (790), short entry call (986), strategy dispatch (521-536), config hot-swap (204-218, 459).
- `src/bot_config.py` — dataclass (7-36), `from_row` (38-64), `symbols` (66-71).
- `src/alpaca_client.py` — `get_positions` (140-157), `place_market_order` (296), `place_limit_order` (334), `close_position` (382-389), `get_closed_orders` slash-preservation note (423).
- `src/alpaca_orchestrator.py` — `_ALPACA_UNTRADEABLE` (78-82), PositionMonitor close (290), `_select_cycle_candidates` (469-482), dynamic universe filter (615), CLI long entry (968), CLI short entry (1123).
- `src/alpaca_evaluator.py` — `MEME_CRYPTO` (42), `get_dynamic_crypto_universe` (57-105).
- `src/bot_manager.py` — `SELECT * FROM bots` (67-70, 105), `update` (236-243), `_spawn` strategy dispatch (274-296).
- `src/trend_strategy.py` (116, 148), `src/bot_c/strategy.py` (313, 365), `src/copytrade_thread.py` (87, 380), `src/technical_signals.py` (481-501), `src/order_resolution.py` (pure-module precedent).
- `src/db_schema.sql` — `bots` DDL (8-15), `alpaca_trades` phase-mirror comments (39-45), seed rows (253-255).
- `dashboard/api/migrations/` — `002_multi_bot.sql` (8-23), `004_stock_universe.sql` (4-5), `008_asset_class.sql` (4-7), `017_reconciliation.sql` (1-18), `run_migrations.py` (1-52).
- `dashboard/api/routes/bots.py` (20-24, 56, 82-90, 113-136, 183, 218), `dashboard/api/models.py` (199-270), `dashboard/api/routes/settings.py` (49, 99-106), `dashboard/api/seed_bots.py` (20-118, 130-171).
- `tests/test_order_resolution.py` (95-170, 236-258), `tests/test_risk_hardening.py` (25-131), `tests/test_learning_realloop.py` (36-150), `tests/test_universe_resolution.py` (1-55).
- `.planning/REQUIREMENTS.md` (33-37, 74-76), `.planning/phases/15-universe-hard-gate/15-CONTEXT.md`, `CLAUDE.md`.

### Secondary / Tertiary
None — no external sources were needed or consulted. No WebSearch, no Context7: this phase is entirely
internal-codebase, and every claim above is backed by a file:line read in this session.

## Metadata

**Confidence breakdown:**
- Entry/exit call-site inventory: **HIGH** — exhaustive repo-wide grep of `place_market_order` /
  `place_limit_order` / `close_position` / `_submit_order`, every hit read in context.
- Symbol formats: **HIGH** — each layer read directly; the `get_closed_orders` docstring
  (`src/alpaca_client.py:423`) independently corroborates the slash-preservation rule.
- `bots` column plumbing: **HIGH** — every reader/writer of `bots` enumerated by grep and read.
- "No bot uses the dynamic fallback": **HIGH** — proven by the `or`-coalesce at `src/bot_config.py:51`,
  not merely by inspecting seed defaults.
- Test-breakage analysis: **HIGH** — every test touching the selectors, `_submit_order`, or `BotConfig`
  was read in full.
- Leak-origin attribution (TRUMP/FIL → which bot): **LOW** — see A1; not verified against the DB.

**Research date:** 2026-07-12
**Valid until:** 30 days (internal codebase; invalidated by any change to `_submit_order`, the strategy
dispatch in `bot_thread.py:521-536`, or the `bots` schema)
</content>
</invoke>
