---
phase: 15-universe-hard-gate
verified: 2026-07-12T00:00:00Z
status: passed
score: 7/7 must-haves verified
verdict: SHIP
requirements:
  UNIV-01: SATISFIED
  UNIV-02: SATISFIED
---

# Phase 15: Universe Hard-Gate Enforcement — Verification Report

**Phase Goal:** Entry is hard-gated to the per-bot allowlist; off-universe/quarantined symbols
are blocked and logged before order submission. Exits are never gated.
**Status:** PASS — SHIP
**Verifier:** independent QC gate (read-only on source; nothing fixed)

## Must-Have Scorecard

| # | Must-have | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | Every entry path gated before submission | **PASS** | see UNIV-01 table |
| 2 | Rejection is LOGGED at every gate | **PASS** | 5/5 sites emit `log.warning("ENTRY BLOCKED ...")` |
| 3 | Quarantine is config-only (no code change) | **PASS** | see UNIV-02 chain |
| 4 | Exits are NEVER gated | **PASS** | `git diff --stat 5eb7f9c HEAD -- src/alpaca_client.py` → **empty** |
| 5 | No false block of a working bot | **PASS** | BITX carve-out, Bot C stocks, Bot E union, normalization all checked |
| 6 | Zero regressions | **PASS** | 358 passed / 5 skipped (baseline 336/4 + 22/1 new) |
| 7 | 19 VALIDATION cases implemented, non-vacuous | **PASS (1 warning)** | 19/19 mapped; one weak test noted below |

**Score: 7/7**

## UNIV-01 — Entry hard-gate: SATISFIED

Exhaustive audit of **every** `place_market_order` / `place_limit_order` call site in `src/`
(grep, not the SUMMARY). All 6 entry sites are gated; all 4 exit sites are gate-free by design.

| Call site | Kind | Gated? | Gate location |
|---|---|---|---|
| `src/bot_thread.py:368,371` (via `_submit_order`) | entry (long + short-to-open) | **YES** | `src/bot_thread.py:352-362` — gate of record; blocks, writes terminal `rejected` row (pnl=0), returns `(None, None)`, never reaches Alpaca |
| `src/bot_thread.py:145,165` selectors | entry pre-filter | **YES** | `entry_allowed(...)[0]` in `select_long_candidates` / `select_short_candidates` |
| `src/trend_strategy.py:129` | entry (BITX buy) | **YES** | `src/trend_strategy.py:100-109` |
| `src/bot_c/strategy.py:324` | entry (buy) | **YES** | `src/bot_c/strategy.py:287-294` |
| `src/copytrade_thread.py:409` | entry (mirror) | **YES** | `src/copytrade_thread.py:380-406` (reduce-only skip) |
| `src/alpaca_orchestrator.py:983` | CLI long entry | **YES** | `:936-942` |
| `src/alpaca_orchestrator.py:1146` | CLI short-to-open | **YES** | `:1100-1106` |
| `src/alpaca_orchestrator.py:295` `close_position` | **exit** | no (correct) | PositionMonitor |
| `src/bot_c/strategy.py:376` `_exit_position` | **exit** | no (correct) | separate fn; exit path `:269-278` returns before the gate |
| `src/trend_strategy.py:161` | **exit** | no (correct) | sell branch below the gate |
| `src/alpaca_client.py:386` `close_position` | **exit** | no (correct) | file untouched |

**No remaining ungated entry path.** `bot_thread`'s two `_submit_order` callers (`:820` buy,
`:1016` sell-short) are both OPENs; bot_thread exits do not traverse `_submit_order` — they go
through `PositionMonitor` → `close_position`. Confirmed by grep: no `close_position` in
`bot_thread.py` and no `_submit_order` on any exit branch.

**Rejection logged:** every gate emits a WARNING carrying bot_id + symbol + reason
(`off_universe` | `quarantined`). `bot_thread` additionally persists a terminal `rejected` row,
so a block is auditable in the DB, not only in logs. `bot_thread.py:222-230` also logs the
EFFECTIVE normalized allowlist/quarantine on every config update — a fat-fingered bare `BTC`
(which will not match `BTC/USD`) is visible rather than silently no-op.

## UNIV-02 — Config-only quarantine: SATISFIED

End-to-end chain traced; **no column referenced but never provisioned**:

`dashboard/api/migrations/018_universe_quarantine.sql:14` (`ADD COLUMN IF NOT EXISTS
quarantined_symbols TEXT DEFAULT ''`) → `src/db_schema.sql:17` mirror →
`BotConfig.quarantined_symbols` (`src/bot_config.py:39`, `from_row` `:68` with pre-migration
`None → ""` safety) → `.quarantined` property `:81` → all 5 gate call sites →
`dashboard/api/models.py:228/251/276` (BotFull/BotCreate/BotUpdate) →
`dashboard/api/routes/bots.py:24` `_BOT_COLS` SELECT + `:86,92` INSERT + generic PUT
`UPDATE bots SET quarantined_symbols = ...` → `seed_bots.py:42/65/90/114` env plumbing.

Quarantining BTC/USD requires **zero code change**: `PUT /api/bots/A {"quarantined_symbols":
"BTC/USD"}`, picked up next cycle via `update_config`. The CLI orchestrator has its own
env-var equivalent (`QUARANTINED_SYMBOLS`, `alpaca_orchestrator.py:98-100`).

**Migration safety:** additive + idempotent. No DROP / DELETE / TRUNCATE / constraint change
anywhere in the diff. Default `''` = nothing quarantined, so the migration is safe to apply
BEFORE the code deploys.

**Warning (non-blocking):** `seed_bots.py` only INSERTs when the row is absent (`:135-137`);
the `else` branch patches NULL keys only. Bots A–D already exist in prod, so
`BOT_x_QUARANTINED` env vars will **not** retro-apply to existing rows. Quarantine for the
live bots must be set via the PUT endpoint (or SQL), which works. UNIV-02 is still met; this
is an operator-doc note, not a defect.

## Exits are never gated — proven

- `git diff --stat 5eb7f9c HEAD -- src/alpaca_client.py` → **empty output**. The exit layer is
  byte-identical to the Phase 14 tip.
- Static regression guard in the suite: `test_gate_absent_from_alpaca_client` asserts
  `"entry_allowed" not in src/alpaca_client.py` — the property is now enforced by CI, not by a
  manual diff.
- **Copytrade skip is REDUCE-ONLY, as specified.** `src/copytrade_thread.py:392-393`:
  `reduces = (held_qty > 0 and side == "sell") or (held_qty < 0 and side == "buy")`, computed
  from a **signed** `get_positions()` qty. A BUY that ADDS to a held off-universe long (the
  audited TRUMP case) is still BLOCKED; a SELL on a not-held symbol (short-to-open) is BLOCKED.
  Not presence-based — no loophole.
- **Fails CLOSED.** `:386-389`: `get_positions()` raising → `held = {}` → `held_qty = 0.0` →
  `reduces = False` → gate applies. Covered by an explicit assertion
  (`test_copytrade_buy_held_symbol_blocked`, `alpaca4.positions_error = True` → `orders == []`).

## False-block risk — none found

- **BITX / trend carve-out:** `bot_thread.py:552-554` branches to `run_trend_cycle` *before* the
  confluence loop, so BITX never reaches `_submit_order`. `trend_strategy.py:101` builds
  `allow = list(cfg.symbols) + [cfg.trend_symbol]`, so BITX passes despite being absent from
  `stock_universe` — while a quarantined trend target is still blocked. Correct.
- **Bot C stocks:** gate uses `cfg.symbols`, which resolves to `stock_universe` when
  `asset_class == "stock"` (`bot_config.py:74-77`). No block.
- **Bot E cross-asset-class mirrors:** copytrade correctly uses `cfg.all_symbols`
  (`bot_config.py:85-98`, crypto ∪ stock, deduped, order-stable) — **not** `cfg.symbols`, which
  would have wrongly killed half of Bot E's legitimate mirrors. TRUMP/FIL are in neither
  universe, so the leak still closes.
- **BTCUSD vs BTC/USD:** `normalize()` (`src/universe.py:17-23`) uppercases, strips whitespace,
  drops the slash. `BTC/USD` == `btc/usd` == `BTCUSD`. Applied on **both** sides of every
  comparison and to the `get_positions()` keys. Total (`None`/`""` → `""`) and idempotent.
- **Empty allowlist = no restriction** (`universe.py:48`) — the dynamic-universe safety net.
  A bot with an unset `crypto_universe` cannot be accidentally bricked; the quarantine
  deny-list still applies.

## Commands run (verbatim)

```
$ python -c "import src.alpaca_orchestrator"
IMPORT OK

$ python -m pytest tests/test_universe.py -q
.....................s.                     [100%]
22 passed, 1 skipped in 0.17s

$ python -m pytest tests/ -q
358 passed, 5 skipped, 1 warning in 6.25s
```

Baseline reconciles **exactly**: 336 + 22 = 358 passed; 4 + 1 = 5 skipped. The 1 new skip is
case 16 (`test_quarantine_column_sql`), correctly `DATABASE_URL`-gated. **Zero regressions.**

## VALIDATION coverage — 19/19

All 19 cases map to named tests in `tests/test_universe.py`. Vacuity audit of the fakes:
`FakeAlpacaClient` records into `.orders` / `.closed` and every gate test asserts **both**
directions — `alpaca.orders == []` on a block AND `len(alpaca.orders) == 1` on an allow. A
no-op gate fails the block tests; an over-broad gate fails the allow tests. The fakes can fail.

**Warning (non-blocking):** `test_exit_not_gated` (case 11, `tests/test_universe.py:310-324`)
**is vacuous** — it calls `FakeAlpacaClient.close_position` / `place_market_order` directly and
asserts the fake recorded the call. It exercises no production code and would pass even if
every exit were gated. The property it claims to cover is nonetheless genuinely proven, twice
over, by case 17's static guard and by the empty `alpaca_client.py` diff. Recommend
strengthening later; not a ship blocker.

## Scope fence — clean

Diff vs `5eb7f9c` touches only: `src/universe.py` (new), the 5 gate call sites, `bot_config.py`,
migration 018, `db_schema.sql`, dashboard models/routes/seed, and `tests/test_universe.py`.
**No change** to sizing, confluence, `risk_gate.py`, `exit_advisor.py`, exits, Phase 12 P&L,
Phase 13 reconciliation, or Phase 14 backfill. No destructive SQL anywhere (migration is
`ADD COLUMN IF NOT EXISTS` only).

## Ship Verdict

**SHIP.** Both requirements are met with code-level evidence, not self-report. The gate is at
the true chokepoints, blocks are logged and persisted, exits are provably untouched, the
copytrade skip is reduce-only and fails closed, and no currently-working bot is falsely
blocked. Two non-blocking warnings recorded above (seed env no-op on existing rows; one
vacuous exit test whose property is proven elsewhere).

---
_Verifier: Claude (gsd-verifier) — read-only, nothing modified._
