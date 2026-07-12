# Phase 15 — Universe Hard-Gate Enforcement — CONTEXT

*Milestone v1.1 · captured 2026-07-12 · mode: --auto (YOLO, decisions auto-selected)*

## Domain

The 2026-07-06 audit found off-universe symbols traded despite the configured 8-asset universe:
TRUMP (−$295) and FIL (−$66). BTC is 0-for-12 (−$479) yet keeps being entered. Two gaps:
there is **no hard gate at the submission chokepoint** (the universe is only a *scan input*, and
`_resolve_crypto_universe` falls back to the **dynamic volume-ranked** list when the curated list is
empty — that is the leak), and there is **no way to quarantine a chronically losing symbol without a
code change** (`MEME_CRYPTO` / `_ALPACA_UNTRADEABLE` are hardcoded module constants).

**Requirements owned:** UNIV-01 (hard allowlist gate + logged rejection), UNIV-02 (config-driven
quarantine/drop list).

## Grounding (from code scout)

- `src/bot_config.py` — `BotConfig` frozen dataclass; `crypto_universe` / `stock_universe`
  comma-separated strings (L23-24), `from_row` (L38) maps the `bots` DB row, `symbols` property
  (L66-71) splits the active list by `asset_class`. This is the per-bot allowlist source of truth.
- `src/bot_thread.py`
  - `_resolve_crypto_universe` (L96-115) — curated list preferred, **dynamic fallback** when empty.
  - `select_long_candidates` (L129) / `select_short_candidates` (L150) — per-cycle filters; already
    exclude `MEME_CRYPTO` + `_ALPACA_UNTRADEABLE` (hardcoded sets), but **not** the cfg universe.
  - `_submit_order` (L328-359) — the single chokepoint every entry passes through (Phase 11). It
    already writes a terminal `rejected` row on failure. **This is where the hard gate belongs.**
- Symbol format is mixed: `BTC/USD` in config/signals, `BTCUSD` from Alpaca positions — the gate
  must normalize before comparing.
- `dashboard/api/migrations/` — next free number is **`018`** (015=P11, 016=P12, 017=P13).
  Numbered SQL, additive/idempotent, mirrored into `src/db_schema.sql`. **Not alembic.**

## Decisions (locked — auto-selected recommended defaults)

1. **Pure gate module `src/universe.py`.** Two pure functions, no I/O:
   - `normalize(symbol) -> str` (uppercase, strip `/`, so `BTC/USD` == `BTCUSD`).
   - `entry_allowed(symbol, allowlist, quarantined) -> (bool, reason)` where `reason` is one of
     `None` / `"off_universe"` / `"quarantined"`. Unit-testable to the letter, independent of DB.
2. **Hard gate at EVERY entry-submit site (CORRECTED after research).** `_submit_order` is the
   chokepoint only for `strategy=="confluence"`. Research found **four live entry paths that bypass
   it**: `src/trend_strategy.py:116`, `src/bot_c/strategy.py:313`, `src/copytrade_thread.py:380`
   (Bot E copy-trader — the most likely source of the TRUMP/FIL leak, since it mirrors someone
   else's symbols), and the CLI orchestrator `src/alpaca_orchestrator.py:968`/`:1123`. UNIV-01 says
   *any* symbol outside the allowlist is rejected before order submission — so the gate goes on
   **all five entry sites**, not just `_submit_order`.
   A blocked symbol: **never** reaches Alpaca, emits a WARNING with bot_id/symbol/reason, and (where
   a trade-log row exists — the `_submit_order` path) writes a terminal `rejected` row (pnl=0,
   existing Phase-11 path) so the block is auditable; then the entry is skipped.
   Belt-and-braces: the same predicate is also applied in `select_long_candidates` /
   `select_short_candidates` so blocked symbols are dropped early — but the *gates of record* are the
   submit sites (a leak anywhere upstream still fails closed).
   **Exits are NEVER gated.** Research confirmed exits go through `alpaca.close_position` /
   `place_market_order(side="sell")` and never touch `_submit_order`. Do NOT put the gate in
   `AlpacaClient.place_market_order` — that would strand open positions in a quarantined symbol.
   **Trend-strategy carve-out:** `cfg.trend_symbol` (default `BITX`) is NOT in the default
   `stock_universe`, so the trend bot's allowlist is `cfg.symbols ∪ {cfg.trend_symbol}` — otherwise
   the gate would break a working bot.
3. **Quarantine is config-driven (UNIV-02).** New `bots` column `quarantined_symbols TEXT` (default
   `''`), migration **`018_universe_quarantine.sql`** (`ADD COLUMN IF NOT EXISTS`), mirrored in
   `src/db_schema.sql`; `BotConfig.quarantined_symbols` + a `quarantined` property that splits it the
   same way `symbols` does. Dropping BTC = one config write, zero code change. Empty = nothing
   quarantined.
4. **Allowlist = the bot's curated `cfg.symbols`.** The dynamic volume-ranked list may still *feed
   the scanner*, but it can never widen what is *tradeable* — the gate compares against
   `cfg.symbols`. Research correction: `BotConfig.from_row` (bot_config.py:51) coalesces a falsy
   `crypto_universe` to the 8-asset default, so **`cfg.symbols` is never empty** and the dynamic
   fallback in `_resolve_crypto_universe` is unreachable in production. No bot relies on it ⇒
   Decision 4 carries zero regression risk for Bot C/D. Quarantine format is the same as the
   universe format (`BTC/USD`, slash included) — a bare `BTC` will not match; log the effective
   normalized allowlist/quarantine set at bot start so a misconfiguration is visible.
5. **No behavior change to sizing, risk gate, confluence, or exits.** This phase only *subtracts*
   candidates.

## Scope discipline (fences)

- Does NOT change P&L (Phase 12), reconciliation (Phase 13), or backfill (Phase 14).
- Does NOT surface the effective universe on the dashboard — that is Phase 16 (UNIV-03), which
  consumes `src/universe.py` + the new column.
- Does NOT retune confluence/Kelly (Phase 18) and does NOT decide *which* symbols to quarantine —
  it only makes quarantining possible. (Phase 17 produces the per-symbol evidence.)
- Risk invariants (max 5% per position, quarter-Kelly, drawdown stop, paper gate) untouched.

## Canonical refs (MANDATORY reading for research/plan)

- `.planning/REQUIREMENTS.md` — UNIV-01, UNIV-02.
- `src/bot_config.py` — `BotConfig`, `from_row`, `symbols`.
- `src/bot_thread.py` — `_resolve_crypto_universe` (L96), `select_long_candidates` (L129),
  `select_short_candidates` (L150), `_submit_order` (L328).
- `src/alpaca_evaluator.py` — `MEME_CRYPTO`, `get_dynamic_crypto_universe`.
- `src/db_schema.sql` — `bots` table (mirror the new column here).
- `dashboard/api/migrations/` — numbering (next free = `018`), `run_migrations.py`.
- `tests/test_order_resolution.py` — FakeAlpacaClient/FakeLogger fake-double convention to reuse.
- CLAUDE.md — numbered-migration rule, one-account-per-bot, never delete DB rows.

## Deferred ideas (not this phase)

- Auto-quarantine (a symbol that goes N-for-M gets quarantined automatically) — needs the Phase-17
  per-symbol stats; revisit in Phase 18.
- Folding the hardcoded `MEME_CRYPTO` / `_ALPACA_UNTRADEABLE` sets into the DB quarantine column —
  keep both for now (constants are a floor, the column is per-bot policy on top).
