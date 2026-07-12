# Phase 16: Effective-Universe Dashboard Visibility (UNIV-03) — Research

**Researched:** 2026-07-12
**Domain:** FastAPI read endpoint + Next.js 15 panel over the Phase-15 universe gate
**Confidence:** HIGH (everything below is read from this repo at the cited file:line; no external deps, no new libs)

## Summary

Everything this phase needs already exists. `src/universe.py::entry_allowed` is a pure, importable
`(symbol, allowlist, quarantined) -> (bool, reason)`; `src/bot_config.py::BotConfig.from_row`
constructs directly from a `bots` dict_row; `dashboard/api/routes/bots.py` already selects
`quarantined_symbols` in `_BOT_COLS`. The new `GET /api/bots/{bot_id}/universe` is a single handler
in the existing `bots.router` (already mounted + auth'd + in `/openapi.json`), a new Pydantic model in
`dashboard/api/models.py`, one extra SQL read against `alpaca_trades` for the LEAK check, and one new
Next.js client component rendered inside `BotCard`. **No migration. No new package. No new design primitive.**

The one real trap: the effective set the *gate of record* enforces (`entry_allowed` at
`src/bot_thread.py:355`) is NOT the same as the set a confluence bot actually scans — the candidate
selectors additionally subtract `MEME_CRYPTO` and `_ALPACA_UNTRADEABLE` (`src/bot_thread.py:144-145`,
`163-164`). `_ALPACA_UNTRADEABLE` is env-driven *in the orchestrator process* and its default today
already contains `LINK/USD`, `ETH/USD`, `DOT/USD` — three symbols that are in every bot's default
`crypto_universe`. The dashboard API process does not (necessarily) share that env, so importing it
would make the panel lie in a *different* direction. Follow CONTEXT decision 2 exactly: report the
**gate** allowlist, and label the panel as "what the entry gate permits" — see Pitfall 1.

**Primary recommendation:** add `GET /api/bots/{bot_id}/universe` to `dashboard/api/routes/bots.py`,
computing `effective`/`blocked` by calling `src.universe.entry_allowed` over a per-strategy allowlist
derived from `BotConfig.from_row(row)`; render it via a new
`dashboard/web/components/bots/UniversePanel.tsx` (client component, `useAPI` hook, `Badge` primitive)
mounted inside `BotCard`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Universe set math (`effective` / `blocked` / `reason`) | Shared domain (`src/universe.py`) | — | Already the gate's single source of truth; re-deriving it anywhere else = drift = the panel lies |
| Per-strategy allowlist resolution | API / Backend | — | Needs the `bots` row (`strategy`, `asset_class`, `trend_symbol`); the browser must never reconstruct it |
| Leak detection (open/recent exposure per bot+symbol) | Database / API | — | Pure SQL over `alpaca_trades`; no Alpaca call (CONTEXT: "no Alpaca calls from this endpoint") |
| Panel rendering / chips / warning states | Browser (Next.js client component) | — | Pure presentation of the API payload |
| Auth | API (`Depends(verify_token)` at router mount) | — | Inherited free — the route lands on the already-mounted `bots.router` |

---

## 1. Route registration + app assembly + response-model conventions

**Router:** `dashboard/api/routes/bots.py:17`
```python
router = APIRouter(prefix="/api", tags=["bots"])
```
Note the prefix is `/api` (not `/api/bots`) — so paths are written in full: `@router.get("/bots")`
(`:51`), `@router.put("/bots/{bot_id}")` (`:120`), `@router.post("/bots/{bot_id}/enable")` (`:175`).
The new route is therefore `@router.get("/bots/{bot_id}/universe")` on this same router.

**Mount:** `dashboard/api/main.py:179`
```python
app.include_router(bots.router, dependencies=[Depends(verify_token)])
```
`app = FastAPI(title="AI Predicted Wins Dashboard API", version="2.0.0", lifespan=lifespan)` at
`main.py:74-79`. FastAPI's built-in `/openapi.json` + `/docs` (Swagger) are on by default — no
custom `openapi_url`/`docs_url` override anywhere in `main.py`. **A route added to `bots.router`
appears in `/openapi.json` and `/docs` automatically, and is auth-gated automatically** — no
`main.py` edit is required. [VERIFIED: codebase]

**Route-ordering caveat:** `/bots/{bot_id}/universe` is a distinct literal-suffixed path; it cannot
collide with `/bots/{bot_id}` (different segment count) or `/bots/{bot_id}/enable`. Order is
irrelevant here. [VERIFIED: codebase]

**Response-model convention** (`dashboard/api/models.py:18-27`):
```python
class Meta(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    count: Optional[int] = None

class Envelope(BaseModel, Generic[T]):
    data: T
    meta: Meta = Field(default_factory=Meta)
```
Every route returns `Envelope(data=..., meta=Meta(count=N))` — e.g. `bots.py:60`, `positions.py:115`.
Handlers do **not** declare `response_model=`; they *return* an `Envelope` instance and let FastAPI
infer. Data models are plain `BaseModel` with defaults, appended to `models.py` under a `# -- Section`
comment banner (`models.py:197`, `:207`, `:279`, `:286`).

**Follow the convention** — add to `dashboard/api/models.py`:
```python
# -- Universe (Phase 16, UNIV-03) --------------------------------------------

class BlockedSymbol(BaseModel):
    symbol: str
    reason: str                    # "off_universe" | "quarantined"
    open_positions: int = 0        # leak evidence
    recent_trades: int = 0

class BotUniverse(BaseModel):
    bot_id: str
    strategy: str
    asset_class: str
    allowlist: list[str]
    quarantined: list[str]
    effective: list[str]
    blocked: list[BlockedSymbol]
    leaked: list[str] = []         # blocked ∧ (open_positions>0 or recent_trades>0)
    starved: bool = False          # effective == []
```
For OpenAPI richness, this handler *may* declare `response_model=Envelope[BotUniverse]` (the
`Envelope` is already `Generic[T]`, so it parameterizes cleanly) — that is the only deviation from
existing routes worth making, and it is strictly additive. [VERIFIED: codebase]

## 2. How a `bots` row is fetched, and building a `BotConfig` from it

**The exact existing pattern** (`dashboard/api/routes/bots.py:138-140`, identical at `:98-101`, `:185-188`, `:220-222`):
```python
with get_db() as conn:
    row = conn.execute(
        f"SELECT {_BOT_COLS} FROM bots WHERE bot_id = %s", (bot_id,)
    ).fetchone()
```
`get_db()` (`dashboard/api/db.py:39-43`) yields a pooled psycopg3 connection whose pool is opened with
`kwargs={"row_factory": dict_row}` (`db.py:33`) — **rows are already `dict`s**. `.fetchone()` returns
`None` when the bot does not exist; the 404 idiom in this file is
`raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")` (`bots.py:137`).

`_BOT_COLS` (`bots.py:20-25`) selects — and deliberately excludes the raw Alpaca keys:
```
bot_id, label, kelly_fraction, min_confluence, hard_stop_pct, soft_stop_pct, rsi_ceiling,
crypto_universe, stock_universe, asset_class, skip_risk_gate, max_position_pct,
min_short_confluence, tradingagents_enabled, strategy, trend_ma_window, trend_symbol,
trend_benchmark, quarantined_symbols, enabled, status, status_detail
```

**Does `BotConfig.from_row` work directly on that row dict? YES.** `src/bot_config.py:42-69` reads
`row["bot_id"]`, `row["label"]` (both present in `_BOT_COLS`) and everything else via
`row.get(...) or <default>` / `row.get(...) is not None` guards. `alpaca_api_key` /
`alpaca_secret_key` are read with `row.get(...) or ""` (`bot_config.py:47-48`) — **absent keys yield
`""`, no KeyError.** So `BotConfig.from_row(row)` on a `_BOT_COLS` row is safe and produces a config
whose `symbols`, `all_symbols`, `quarantined`, `strategy`, `trend_symbol`, `asset_class` are all
exactly what the live thread sees. No key-bearing SELECT is needed — **do not add the keys back.**
[VERIFIED: codebase]

**Import path from the dashboard API process:** `dashboard/api/main.py:57-61` already inserts
`/app` (container) and the repo root (dev) into `sys.path` inside `lifespan`, then does
`from src.bot_manager import BotManager`. That `sys.path` mutation happens at startup and is
process-wide, so `from src.bot_config import BotConfig` / `from src.universe import entry_allowed`
work at *request* time from a route module. **But the route module is imported at
`main.py:21-34` — i.e. BEFORE `lifespan` runs.** A module-level `from src.universe import ...` in
`routes/bots.py` would therefore fail at import time when the API is run with cwd=`dashboard/api`.

**Mitigation (mandatory):** do the import **inside the handler** (a function-local import — the
codebase already does exactly this: `main.py:61` `from src.bot_manager import BotManager  # noqa: PLC0415`,
`main.py:141` `from fastapi.responses import JSONResponse`, `bot_thread.py:552`
`from src.trend_strategy import run_trend_cycle`). Or replicate the two-path `sys.path.insert` at the
top of `routes/bots.py`. Prefer the function-local import — it matches the house style and keeps the
degrade-gracefully posture of `main.py:65-66`. [VERIFIED: codebase]

## 3. Per-strategy allowlist — what each bot's gate allowlist ACTUALLY is today

Strategy dispatch is by the **`bots.strategy` column** (added in migration `011_trend_strategy.sql`,
read as `cfg.strategy`, default `"confluence"` — `bot_config.py:33`). Two levels of dispatch:

- **Thread class** — `src/bot_manager.py:277-297`:
  ```python
  # Dispatches on cfg.strategy:
  #   - anything else (confluence, trend_btc, ...) -> BotThread
  if cfg.strategy == "copytrade":
      thread = CopyTraderThread(...)
  else:
      thread = BotThread(cfg, on_status_change=self._on_status_change)
  ```
- **Cycle function inside `BotThread`** — `src/bot_thread.py:551` (`trend_btc` → `run_trend_cycle`),
  `:560` (`tradingagents` → `src/bot_c/strategy.run_tradingagents_cycle`), else the confluence loop.

So the API can determine a bot's strategy **purely from the `strategy` column already in `_BOT_COLS`**
— no thread access, no `BotManager` call. (Bot E is a normal `bots` row with `strategy='copytrade'`;
migration `012_copytrade_bot_e.sql` adds only `copytrade_state`/`copytrade_signals` tables and notes
"already has `strategy` column (migration 011)". Note `db.KNOWN_BOTS = ("A","B","C","D")` at
`db.py:18` does **not** include `E` — that constant gates the `bot=A|B|both` *filter* param, not the
bots table; do not use it to enumerate bots for this endpoint. Query the `bots` table.)
[VERIFIED: codebase]

### The five gate call sites — the allowlist of record

| Strategy (`bots.strategy`) | Thread / cycle | **Gate call site** | **Allowlist passed to `entry_allowed`** | Deny-list |
|---|---|---|---|---|
| `confluence` (default) | `BotThread` | `src/bot_thread.py:355` (gate of record, in `_submit_order`) — plus pre-filters at `:146` and `:165` | `cfg.symbols` | `cfg.quarantined` |
| `trend_btc` | `BotThread` → `run_trend_cycle` | `src/trend_strategy.py:104` | `list(cfg.symbols) + [cfg.trend_symbol]` (`trend_strategy.py:103` — the BITX carve-out) | `cfg.quarantined` |
| `tradingagents` (Bot C) | `BotThread` → `run_tradingagents_cycle` | `src/bot_c/strategy.py:289` | `cfg.symbols` | `cfg.quarantined` |
| `copytrade` (Bot E) | `CopyTraderThread` | `src/copytrade_thread.py:397-398` | `self.config.all_symbols` (crypto ∪ stock union) | `self.config.quarantined` |
| — (CLI, not a `bots` row) | `python -m src.alpaca_orchestrator` | `src/alpaca_orchestrator.py:939` and `:1101` | module-level `universe` var (`:611-620`: `CRYPTO_UNIVERSE` env → dynamic → `TOP_CRYPTO_TICKERS`, minus `_ALPACA_UNTRADEABLE`) | `QUARANTINED_SYMBOLS` env (`:100`) |

Corroborated by `.planning/phases/15-universe-hard-gate/VERIFICATION.md` (UNIV-01 table, all 6 entry
sites gated, all 4 exit sites gate-free by design).

**`cfg.symbols`** (`bot_config.py:72-76`) = `stock_universe.split(",")` when `asset_class == "stock"`,
else `crypto_universe.split(",")`.
**`cfg.all_symbols`** (`bot_config.py:84-99`) = order-stable dedup union of crypto ∪ stock.
**`cfg.quarantined`** (`bot_config.py:79-81`) = `quarantined_symbols.split(",")`, **asset-class-agnostic**.

**Therefore the endpoint's allowlist resolver — the ONLY correct one:**
```python
def _allowlist_for(cfg) -> list[str]:
    """Mirror the Phase-15 gate call sites exactly. See table in 16-RESEARCH.md §3."""
    if cfg.strategy == "copytrade":
        return list(cfg.all_symbols)                       # copytrade_thread.py:398
    if cfg.strategy == "trend_btc":
        return list(cfg.symbols) + [cfg.trend_symbol]      # trend_strategy.py:103
    return list(cfg.symbols)                               # bot_thread.py:355 / bot_c/strategy.py:289
```
The CLI path is not a `bots` row and is out of scope for a per-`bot_id` endpoint — but it MUST be
noted in the panel copy or the docstring, because a CLI-run bot's universe is *not* what this
endpoint shows. [VERIFIED: codebase]

**`effective` / `blocked` — reuse `entry_allowed`, never re-derive:**
```python
from src.universe import entry_allowed          # function-local import (see §2)
allow = _allowlist_for(cfg)
quar  = cfg.quarantined
effective, blocked = [], []
for s in allow:
    ok, reason = entry_allowed(s, allow, quar)
    (effective if ok else blocked).append(s if ok else (s, reason))
```
Note: iterating `allow` alone can only ever produce `reason == "quarantined"` (an allowlisted symbol
is by definition not `off_universe`). To surface the **`off_universe` LEAK** case (the TRUMP/FIL
audit finding) you must also evaluate the symbols the bot has **actually traded** — see §5. Those are
the ones whose reason comes back `off_universe`. Iterate `set(allow) | set(traded_symbols) | set(quar)`
and let `entry_allowed` label every one. That single loop yields `effective`, `blocked` (with reason),
and the leak set with zero duplicated set math. [VERIFIED: codebase]

## 4. Frontend — components, fetch layer, types

Stack: Next.js 15 App Router + React 19 + Tailwind 4 + `lucide-react` + `recharts`
(`dashboard/web/package.json`). **No SWR, no react-query.** [VERIFIED: codebase]

| Concern | File | Notes |
|---|---|---|
| Bots page | `dashboard/web/app/bots/page.tsx` | `useAPI<BotFull[]>("/api/bots", 30_000)` (`:18`), maps to `<BotCard>` (`:56`) |
| **Bot card (add panel here)** | `dashboard/web/components/bots/BotCard.tsx` | `"use client"`; renders label/status dot/toggle/Edit + a config grid. `:38` already prints a raw `Assets: {bot.crypto_universe}` string — the Universe panel **replaces/augments that line**. |
| Edit drawer (do NOT touch) | `dashboard/web/components/bots/BotDrawer.tsx` | Existing PUT form. CONTEXT fences editing out of this phase. |
| **Fetch layer** | `dashboard/web/hooks/useAPI.ts` | `useAPI<T>(url, pollInterval?)` → `{data, loading, error, refetch}`; unwraps `response.data` (`:34`), 401→`/login`. **Use this.** |
| Low-level fetch | `dashboard/web/lib/api.ts` | `apiFetch<T>` + `APIError`; `buildQueryString`. |
| **TS types (extend here)** | `dashboard/web/types/index.ts` | `BotFull` at `:163`, `APIResponse<T>` at `:206`. |
| Chip / badge primitive | `dashboard/web/components/shared/Badge.tsx` | `variant: "proceed"|"veto"|"paper"|"live"|"open"|"closed"|"bullish"|"bearish"|"neutral"`. **Reuse: `proceed`=effective chip, `veto`=quarantined/blocked chip, `neutral`=muted.** Do not invent variants unless a genuinely new semantic is needed. |
| Warning-state primitive | `dashboard/web/components/shared/ErrorBanner.tsx` | `role="alert"`, `border-loss-red/40 bg-loss-red/10 text-loss-red`. **Reuse this exact class vocabulary for the LEAK banner.** The starvation warning should use the amber token (`warning-amber`, already in the Badge palette at `Badge.tsx:11`). |

**Plan of record for the UI:**
- New file `dashboard/web/components/bots/UniversePanel.tsx` — `"use client"`, props `{ botId: string }`,
  calls `useAPI<BotUniverse>(\`/api/bots/${botId}/universe\`, 30_000)`.
- Mount it inside `BotCard.tsx`, replacing the raw `Assets:` line at `BotCard.tsx:38`.
- Struck-through/greyed quarantined chips: `line-through` + `Badge variant="veto"`, `title={reason}`.
- Count: `{effective.length} of {allowlist.length} tradeable`.
- LEAK banner: ErrorBanner-style red block listing leaked symbols.
- Starvation banner: amber block when `effective.length === 0`.

**⚠️ Type drift — fix as part of this phase.** `dashboard/web/types/index.ts:163-179` `BotFull` is
**missing** `asset_class`, `min_short_confluence`, `tradingagents_enabled`, `strategy`,
`trend_ma_window`, `trend_symbol`, `trend_benchmark`, and `quarantined_symbols` — all of which the
Python `BotFull` (`dashboard/api/models.py:209-232`) returns today. The panel needs `strategy` (to
label the carve-out) and `quarantined_symbols`. Extend the TS interface to match the Pydantic model;
add `BlockedSymbol` + `BotUniverse` interfaces alongside. [VERIFIED: codebase]

## 5. LEAK detection — the existing query to reuse

**Table:** `alpaca_trades`, columns `bot_id, symbol, status, timestamp, qty, side, entry_price, closed_at`.
**Status vocabulary, read from live code:** open = `status = 'open'` (`positions.py:67`, `:251`;
`portfolio.py:83`); closed = `status IN ('closed','stopped','target_hit')` (`positions.py:131`).

**Existing per-bot open-positions read — the one to mirror** (`dashboard/api/routes/positions.py:63-78`):
```sql
SELECT id, timestamp, symbol, side, qty, entry_price, mirofish_prob, stop_loss, bot_id
FROM alpaca_trades
WHERE status = 'open'          -- + " AND bot_id = %s" when is_specific_bot(bot)
ORDER BY timestamp DESC
```
There is **no existing endpoint or helper that aggregates per bot+symbol** — grep of
`dashboard/api/` for `GROUP BY symbol` / `DISTINCT symbol` returns nothing. The nearest thing is
`routes/chat.py:32` (`SELECT bot_id, symbol, entry_price, qty FROM alpaca_trades WHERE status='open'`).
So one new aggregate SELECT is unavoidable — but it must go **inside the universe handler**, not into
a new endpoint, and must reuse the `status` vocabulary above verbatim:

```sql
SELECT symbol,
       COUNT(*) FILTER (WHERE status = 'open')                         AS open_positions,
       COUNT(*) FILTER (WHERE timestamp > NOW() - INTERVAL '30 days')  AS recent_trades
FROM alpaca_trades
WHERE bot_id = %s
GROUP BY symbol
```
Then: `symbol` is **LEAKED** iff `entry_allowed(symbol, allow, quar) == (False, "off_universe")`
**and** (`open_positions > 0` or `recent_trades > 0`). That is exactly the TRUMP/FIL case.

**Normalization is load-bearing.** `alpaca_trades.symbol` is stored in mixed conventions —
`positions.py` seeds/queries `'BTC/USD'` (slashed), while `src/alpaca_client.py` returns slashless
`symbol` (per `tests/test_universe.py:8-9`, and `copytrade_thread.py:388` normalizes exactly for this
reason). **Join universe symbols to trade symbols through `src.universe.normalize()` on both sides**,
never on raw strings, or the leak check silently misses `BTCUSD` vs `BTC/USD`. Preserve the original
(slashed) spelling for display. [VERIFIED: codebase]

**No Alpaca HTTP call.** `positions.py:_fetch_latest_prices` / `_alpaca_open_symbols` exist but
CONTEXT decision 1 forbids them here (and they need `ALPACA_API_KEY_{X}` env, which is per-bot and
absent for E). DB-only. [CITED: 16-CONTEXT.md decision 1]

## 6. Test conventions

**FastAPI layer — `dashboard/api/tests/test_routes.py`:**
- `sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))` (`:15`) so `from main import app` works.
- Module-level gate: `pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), ...)` (`:17-20`).
- `client` fixture (`scope="module"`, `:23-79`): sets `os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]`,
  **pops `DASHBOARD_TOKEN` to disable auth**, imports `main.app`, seeds `alpaca_trades` rows with
  `ON CONFLICT DO NOTHING`, returns `TestClient(app)`.
- Tests assert on `r.status_code` + `r.json()["data"]` (`:84-90`).

**Pure-logic tests — `tests/test_universe.py` (Phase 15):** zero network, zero DB, hand-rolled
`FakeLogger`/`FakeAlpacaClient` (docstring `:1-16`), one DATABASE_URL-gated real-SQL case
(`:422-428`, `@pytest.mark.skipif(not os.environ.get("DATABASE_URL"))`).
**`tests/test_dashboard_db.py`** shows the cheap way to test dashboard code with no DB: `sys.path.insert`
the `dashboard/api` dir and import the module, exercising only pure functions/constants.

**Recommended test split for this phase** (both real, both cheap):
1. `tests/test_universe_endpoint.py` — **pure, no DB**: unit-test the extracted `_allowlist_for(cfg)`
   + the effective/blocked builder against hand-built `BotConfig`s, one per strategy
   (`confluence` / `trend_btc` / `tradingagents` / `copytrade`). Asserts the trend carve-out includes
   `BITX` and the copytrade allowlist is the union. **This is the test that stops the panel lying.**
   → requires the resolver be a module-level pure function, not inline in the handler. **Plan for that.**
2. `dashboard/api/tests/test_routes.py` — append `TEST_DATABASE_URL`-gated `TestClient` cases:
   200 shape, 404 unknown bot, quarantined symbol appears in `blocked` with `reason="quarantined"`,
   an off-universe `alpaca_trades` row for that bot surfaces in `leaked`.

**Frontend testing: none exists.** `dashboard/web/package.json` has no jest/vitest/playwright/testing-library
— scripts are only `dev`/`build`/`start`/`lint`. Verification for the UI is therefore
`npm run build` (type-check must pass — hence the §4 type-drift fix is mandatory, not optional) plus
a browser screenshot per the global Verification Loop. Do **not** invent a frontend test framework in
this phase. [VERIFIED: codebase]

## 7. Migration needed?

**No.** [VERIFIED: codebase]

- `quarantined_symbols TEXT DEFAULT ''` → `dashboard/api/migrations/018_universe_quarantine.sql:13-14`.
- `strategy`, `trend_symbol`, `trend_ma_window`, `trend_benchmark` → `011_trend_strategy.sql`.
- `asset_class` → `008_asset_class.sql`. `stock_universe` → `004_stock_universe.sql`.
- All are already in `_BOT_COLS` (`bots.py:20-25`) and in the Pydantic `BotFull` (`models.py:209-232`).
- `alpaca_trades` already carries `bot_id`, `symbol`, `status`, `timestamp`.

Highest existing migration is `018`. If a migration ever *were* needed it would be `019_*.sql`
(additive + `IF NOT EXISTS`, per the 018 house style). It is not.

---

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---|---|---|---|
| effective/blocked set math | a list-comprehension diff in the route | `src.universe.entry_allowed` (`src/universe.py:26`) | Quarantine-before-allowlist precedence + empty-allowlist semantics + normalization are all encoded there. Any reimplementation drifts from the gate → the panel lies. This is the whole point of the phase. |
| symbol comparison | `==` / `in` on raw strings | `src.universe.normalize` (`src/universe.py:17`) | `BTC/USD` vs `BTCUSD` vs `btc/usd`. `copytrade_thread.py:388` already learned this. |
| building a config from the row | manual `row["crypto_universe"].split(",")` | `BotConfig.from_row(row)` (`src/bot_config.py:42`) | Handles every default + NULL; `symbols`/`all_symbols`/`quarantined` are properties whose semantics the gate depends on. |
| the envelope | a bare dict | `Envelope(data=..., meta=Meta(count=N))` (`models.py:25`) | Every route + the TS `APIResponse<T>` + `useAPI`'s `response.data` unwrap depend on it. |
| a chip/badge | new Tailwind classes | `components/shared/Badge.tsx` | CONTEXT + design prefs: reuse primitives. |
| auth on the new route | a new dependency | inherited from `app.include_router(bots.router, dependencies=[Depends(verify_token)])` (`main.py:179`) | Free. Adding a second `Depends(verify_token)` would double-run it. |

## Common Pitfalls

### Pitfall 1 — the panel over-reports what a confluence bot will actually trade
**What goes wrong:** The gate (`entry_allowed`) is not the only filter. `select_long_candidates` /
`select_short_candidates` also subtract `MEME_CRYPTO` (`bot_thread.py:144`, `163`) and
`_ALPACA_UNTRADEABLE` (`:145`, `:164`). `_ALPACA_UNTRADEABLE` is
`frozenset(os.environ.get("ALPACA_UNTRADEABLE", "LDO/USD,POL/USD,ONDO/USD,RENDER/USD,DOT/USD,ARB/USD,SUSHI/USD,HYPE/USD,LINK/USD,ETH/USD").split(","))`
(`src/alpaca_orchestrator.py:79-84`). **Its default already contains `DOT/USD`, `LINK/USD` and
`ETH/USD` — three of the eight symbols in every bot's default `crypto_universe`.** So a bot whose
panel says "8 of 8 tradeable" may in reality scan only 5.
**Why it happens:** the phase's mandate is "show the gate", and the gate genuinely permits those 8.
**How to avoid:** (a) follow CONTEXT decision 2 — `effective` = the gate's answer, unchanged; (b) do
**not** import `_ALPACA_UNTRADEABLE` into the API (its value is read from the *orchestrator process's*
env; the dashboard container may have a different or absent `ALPACA_UNTRADEABLE`, so importing it
would produce a *different* lie); (c) label the panel honestly — "symbols the entry gate permits" —
and **raise this as an open question for Phase 17/18**, which owns what to actually quarantine. A
cheap partial mitigation available *without* new config: the leak query in §5 already tells you which
allowed symbols have **zero trades ever** — a "never traded" hint on a chip surfaces the discrepancy
empirically without importing orchestrator env.
**Warning sign:** panel says N tradeable, `alpaca_trades` shows the bot has never once traded several
of them.

### Pitfall 2 — module-level `from src.universe import ...` in `routes/bots.py` crashes the API at import
**Why:** route modules are imported at `main.py:21-34`, *before* `lifespan` (`main.py:57-60`) inserts
the repo root / `/app` into `sys.path`. Under the container's cwd this import would raise at startup —
taking the whole dashboard down, not just this route.
**Avoid:** function-local import inside the handler (house style: `main.py:61`, `bot_thread.py:552`),
or replicate the `sys.path.insert` two-path loop at the top of `routes/bots.py`. Wrap in
try/except and return a degraded payload if you want to preserve `main.py`'s fail-soft posture.

### Pitfall 3 — the leak check misses because of the slash
See §5. `normalize()` both sides. `tests/test_universe.py` docstring (`:6-10`) explicitly records that
Alpaca returns slashless symbols while the universe config is slashed.

### Pitfall 4 — enumerating bots from `db.KNOWN_BOTS`
`db.py:18` is `("A","B","C","D")` — **no `E`**. Bot E (copytrade) is a real `bots` row. This endpoint
is per-`bot_id` so it mostly dodges the issue, but any "show all bots' universes" convenience must
query `SELECT ... FROM bots`, never `KNOWN_BOTS`.

### Pitfall 5 — `quarantined` is asset-class-agnostic
`BotConfig.quarantined` (`bot_config.py:79-81`) is a flat list, not split by asset class. A stock
symbol in a crypto bot's quarantine is simply inert. Do not "helpfully" filter the quarantined list by
`asset_class` in the panel — show it as configured, or the operator will mis-diagnose a typo'd entry.

## Anti-Patterns to Avoid

- **Reimplementing set math in TypeScript.** The browser must receive `effective`/`blocked` already
  computed by `entry_allowed`. A client-side `allowlist.filter(s => !quarantined.includes(s))` is
  exactly the drift this phase exists to prevent.
- **Adding a write path.** CONTEXT fence: `PUT /api/bots/{bot_id}` already accepts
  `quarantined_symbols` (`models.py:276`). No form, no PATCH.
- **Calling Alpaca or the BotManager from the handler.** DB-only, read-only.
- **A new `/api/universe` router.** It belongs on `bots.router` — free auth, free OpenAPI, correct tag.

## Environment Availability

| Dependency | Required by | Available | Version | Fallback |
|---|---|---|---|---|
| FastAPI + pydantic v2 | endpoint | ✓ | in use (`main.py`, `models.py`) | — |
| psycopg3 + psycopg_pool | DB reads | ✓ | `dashboard/api/db.py:12-14` | — |
| `src/universe.py`, `src/bot_config.py` | set math + config | ✓ | Phase 15, merged | — |
| Next.js 15 / React 19 / Tailwind 4 | panel | ✓ | `package.json` | — |
| `lucide-react` | optional warning icon | ✓ | `^0.468.0` | plain text |
| Postgres (`TEST_DATABASE_URL`) | route integration tests | conditional | — | pure unit tests (§6 item 1) always run |
| Frontend test framework | — | ✗ | — | `npm run build` type-check + browser screenshot. **Do not add one this phase.** |

**Missing deps with no fallback:** none.
**No new package is installed by this phase** → the Package Legitimacy Audit is N/A.

## Validation Architecture

### Test framework
| Property | Value |
|---|---|
| Framework | pytest 8.3.5 (`tests/__pycache__/*-pytest-8.3.5.pyc`) |
| Config | `tests/conftest.py` (fixtures only); DB tests gated by `TEST_DATABASE_URL` / `DATABASE_URL` env |
| Quick run | `python -m pytest tests/test_universe_endpoint.py -x -q` |
| Full suite | `python -m pytest tests/ dashboard/api/tests/ -q` (Phase-15 baseline: 358 passed / 5 skipped) |

### Requirement → test map
| Req | Behavior | Type | Command | Exists? |
|---|---|---|---|---|
| UNIV-03 | allowlist resolver matches the gate for all 4 strategies | unit | `pytest tests/test_universe_endpoint.py -k allowlist -x` | ❌ Wave 0 |
| UNIV-03 | effective = allowlist − quarantine, computed via `entry_allowed` | unit | `pytest tests/test_universe_endpoint.py -k effective -x` | ❌ Wave 0 |
| UNIV-03 | off-universe symbol with an open trade → `leaked` | unit (fake rows) + integration | `pytest tests/test_universe_endpoint.py -k leak -x` | ❌ Wave 0 |
| UNIV-03 | `effective == []` → `starved: true` | unit | `pytest tests/test_universe_endpoint.py -k starved -x` | ❌ Wave 0 |
| UNIV-03 | `GET /api/bots/{id}/universe` 200 shape; 404 unknown bot | integration | `TEST_DATABASE_URL=... pytest dashboard/api/tests/test_routes.py -k universe -x` | ❌ Wave 0 (file exists) |
| UNIV-03 | route present in `/openapi.json` | integration | `pytest dashboard/api/tests/test_routes.py -k openapi -x` | ❌ Wave 0 |
| UNIV-03 | panel renders, types compile | build | `cd dashboard/web && npm run build` | ✓ (script exists) |

### Sampling rate
- Per task commit: `python -m pytest tests/test_universe_endpoint.py -x -q`
- Per wave merge: `python -m pytest tests/ dashboard/api/tests/ -q` + `cd dashboard/web && npm run build`
- Phase gate: full suite green + browser screenshot of the panel (leak state and starved state both exercised) before `/gsd-verify-work`.

### Wave 0 gaps
- [ ] `tests/test_universe_endpoint.py` — new file (pure, no DB)
- [ ] `dashboard/api/tests/test_routes.py` — append universe cases (existing file, existing fixture)
- [ ] Refactor requirement: the allowlist resolver + effective/blocked builder must be **module-level pure functions** in `routes/bots.py` (or a small `dashboard/api/universe_view.py`) so they are unit-testable without a DB.

## Security Domain

| ASVS | Applies | Control |
|---|---|---|
| V2 Authentication | yes | Inherited: `Depends(verify_token)` on the `bots` router (`main.py:179`). Bearer or `dashboard_token` httpOnly cookie (`main.py:101-125`). Nothing new. |
| V3 Session | no | No session state added. |
| V4 Access control | yes | Read-only endpoint; no write path; no privilege tiers exist in this app. |
| V5 Input validation | yes | `bot_id` is a path param used **only** as a parameterized psycopg placeholder (`%s`) — the existing `bots.py` idiom (`:139`). **Never f-string `bot_id` into SQL.** Note `_BOT_COLS`/`set_clauses` are f-strung, but from server-controlled column names, not user input — do not extend that habit to `bot_id`. |
| V6 Cryptography | no | None. |
| **Secret leakage** | **yes** | `_BOT_COLS` (`bots.py:19` comment: "never expose raw alpaca keys") deliberately omits `alpaca_api_key`/`alpaca_secret_key`. `BotConfig.from_row` tolerates their absence (`bot_config.py:47-48`). **Do not SELECT the keys to build the config.** The response model must not contain any key field. |

| Threat | STRIDE | Mitigation |
|---|---|---|
| SQL injection via `bot_id` | Tampering | psycopg parameterized `%s` (existing idiom) |
| Credential disclosure in the universe payload | Information disclosure | key-free `_BOT_COLS` SELECT; explicit Pydantic response model (no `**row` splat) |
| Unauth read of bot config | Information disclosure | router-level `verify_token` |

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|---|---|---|
| A1 | A 30-day window is the right definition of "recent trades" for the leak check | §5 | Cosmetic — a leak with an *open* position is caught regardless of window; the window only affects the "traded recently but now flat" signal. Make it a query param with a 30d default. |
| A2 | `alpaca_trades.timestamp` is a `TIMESTAMPTZ` (so `NOW() - INTERVAL` compares cleanly) | §5 | If it is TEXT, the interval predicate silently mis-filters. **Verify against the live schema before writing the query** (`positions.py:293` writes an ISO *string* into `closed_at`, which is a smell). Cheap check: `\d alpaca_trades`. |
| A3 | No CI docs-drift job currently regenerates `docs/api.md` for this repo | §1 / CLAUDE.md | If one exists, the plan needs a `docs/api.md` regen task. Grep for a docs-drift workflow before planning. |

## Open Questions

1. **Should the panel show the `_ALPACA_UNTRADEABLE` / `MEME_CRYPTO` subtraction?**
   - Known: those filters are real (`bot_thread.py:144-145`) and today remove `DOT/USD`, `LINK/USD`,
     `ETH/USD` from a default confluence bot's scan.
   - Unclear: whether the dashboard container's env even has `ALPACA_UNTRADEABLE` set.
   - Recommendation: **do not** import it (see Pitfall 1). Ship the gate view per CONTEXT decision 2,
     and hand this to Phase 17/18 as evidence — those filters are arguably a shadow quarantine that
     *should* be migrated into `quarantined_symbols` so there is exactly one deny-list. Note it in the
     phase SUMMARY as a follow-up.
2. **`alpaca_trades.timestamp` column type** — see A2. Resolve with one `\d alpaca_trades` before the plan locks the SQL.

## Sources

### Primary (HIGH — read at file:line in this repo, this session)
- `src/universe.py:17,26` · `src/bot_config.py:33,42-99` · `src/bot_manager.py:277-297`
- `src/bot_thread.py:144-146,163-165,355,551,560` · `src/trend_strategy.py:103-104`
- `src/bot_c/strategy.py:289` · `src/copytrade_thread.py:388,397-398`
- `src/alpaca_orchestrator.py:79-84,100,611-620,939,1101`
- `dashboard/api/main.py:21-34,57-61,74-79,101-125,177-189` · `dashboard/api/db.py:12-18,33,39-43`
- `dashboard/api/models.py:18-27,197-232,276` · `dashboard/api/routes/bots.py:17-25,51-60,98-101,120-148`
- `dashboard/api/routes/positions.py:61-78,118-141,251,293` · `dashboard/api/routes/chat.py:32`
- `dashboard/api/migrations/018_universe_quarantine.sql:13-14` · `012_copytrade_bot_e.sql:1-8`
- `dashboard/api/tests/test_routes.py:15-79` · `tests/test_universe.py:1-33,422-428` · `tests/test_dashboard_db.py:10-14`
- `dashboard/web/{package.json, app/bots/page.tsx, components/bots/BotCard.tsx, components/shared/{Badge,ErrorBanner}.tsx, hooks/useAPI.ts, lib/api.ts, types/index.ts:163-212}`
- `.planning/phases/15-universe-hard-gate/VERIFICATION.md` (UNIV-01 gate-site table)
- `.planning/phases/16-effective-universe-dashboard/16-CONTEXT.md` (locked decisions)

### Secondary / Tertiary
None. No web search was required — this phase is entirely internal to the repo.

## Metadata

**Confidence breakdown**
- Route/model/mount mechanics: **HIGH** — read directly from `main.py` / `bots.py` / `models.py`.
- Per-strategy allowlist: **HIGH** — all 5 gate sites grepped and read, cross-checked against the Phase-15 VERIFICATION table.
- `BotConfig.from_row` on a `_BOT_COLS` row: **HIGH** — every field access is `.get(...)`-guarded except `bot_id`/`label`, both present.
- Leak query: **MEDIUM-HIGH** — table/columns/status vocabulary verified; `timestamp` column *type* unverified (A2).
- Frontend: **HIGH** — no test framework, no SWR, `useAPI` + `Badge` + `ErrorBanner` are the primitives; TS `BotFull` drift confirmed by diffing against the Pydantic model.
- Migration: **HIGH** — every needed column traced to its migration file.

**Research date:** 2026-07-12
**Valid until:** 2026-08-11 (internal-only; invalidated by any change to `src/universe.py`, the gate call sites, or `_BOT_COLS`)
