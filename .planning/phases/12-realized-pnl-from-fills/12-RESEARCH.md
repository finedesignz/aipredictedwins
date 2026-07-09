# Phase 12: Realized P&L From Fills - Research

**Researched:** 2026-07-09
**Domain:** Trade-close P&L accounting (Python, psycopg3/Postgres, pytest)
**Confidence:** HIGH (all claims verified against current source in this repo)

## Summary

Phase 11 made every submitted order reach a terminal DB state and persist the entry
`filled_avg_price`. Phase 12 fixes the *number* the close writes: today `PositionMonitor._check_positions`
computes P&L and `exit_price` from `current_price` (the live quote fetched for the exit ladder), and
deducts no fees. The fix is a single-source-of-truth pure helper `src/pnl.py::realized_pnl(...)` called
from the monitor's close block; entry fill from the row's persisted `filled_avg_price` (fallback
`entry_price`), exit fill from `close_position()`'s already-returned dict (fallback `current_price`),
minus `TAKER_FEE` on both legs. A new additive migration `016_realized_pnl_fees.sql` adds a `fees`
column (mirrored in `src/db_schema.sql`).

**Primary recommendation:** Add `src/pnl.py` pure helper + `fees` column; edit exactly one close block
in `PositionMonitor._check_positions` (L287-300 of `src/alpaca_orchestrator.py`); thread a `fees` kwarg
through `TradeLogger.update_alpaca_trade` and `src/db.py::update_alpaca_trade`. No behavior change to the
exit trigger ladder. All live bots (main orchestrator + `bot_thread` BotManager) share the one
`PositionMonitor` class, so one edit covers everything.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
1. **Realized P&L = fills, both legs, net of fees.** On close, compute
   `realized_pnl = (exit_fill - entry_fill) * filled_qty (side-aware) - fees`:
   - `entry_fill` = row's persisted `filled_avg_price`; fallback to `entry_price` only if missing/zero (legacy rows), log the fallback.
   - `exit_fill` = `filled_avg_price` from `close_position()` return dict; fallback to live `current_price` only if the close dict lacks a fill, log the fallback.
   - `fees` = `TAKER_FEE` on **both** legs: `(entry_fill*qty + exit_fill*qty) * TAKER_FEE`, reusing `src/fee_gate.py`. Do NOT double-count `SLIPPAGE_BUFFER` (real fills already embed slippage).
2. **Store the real exit fill as `exit_price`** and `pnl = realized_pnl`.
3. **Persist fees** via additive/idempotent `ADD COLUMN IF NOT EXISTS fees` in `016_realized_pnl_fees.sql`, mirrored in `src/db_schema.sql`. Not alembic. `exit_price`/`pnl` columns already exist.
4. **Single source of truth:** `src/pnl.py::realized_pnl(side, entry_fill, exit_fill, qty, taker_fee)`, unit-testable to the cent. Monitor calls it; does not inline arithmetic.
5. **No silent behavior change to exits.** Exit trigger ladder (hard_stop/max_hold/ATR) untouched — only the P&L number and `exit_price` change. `total_pnl` accumulation uses the new realized figure.

### Claude's Discretion
- Helper signature/param naming, log message wording, exact fallback-guard ordering, test names.

### Deferred Ideas (OUT OF SCOPE)
- Per-leg fee/slippage attribution beyond a single `fees` total (only if Phase 13 needs it).
- Funding/borrow costs for shorts.
- Phase 13 reconciliation vs Alpaca account P&L; Phase 14 historical backfill; universe gate; threshold retune.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PNL-02 | Each closed trade records realized P&L from actual fill prices/quantities, net of fees/slippage, not target/estimated prices. | Helper design (§Standard Stack), exact edit sites (§Q1), migration mechanism (§Q3), fill-availability confirmation (§Q4), test plan (§Q5). |
</phase_requirements>

## Q1 — Exact edit sites in `src/alpaca_orchestrator.py`

`PositionMonitor` is at L107; the close path is inside `_check_positions`.

- **`trade_pnl` computation — L204-211.** Currently side-aware but built from `current_price` and DB
  `entry_price`. This value is used for the exit-ladder display/threshold (`pnl_pct`) AND written on
  close. **Keep `pnl_pct`/`trade_pnl` as the quote-based display figure for the ladder** (do NOT change
  the trigger logic — locked decision 5). Compute the *realized* figure separately, only at close.
- **Close block — L287-300** (inside `with self._lock:`):
  ```
  L289: result = self.alpaca.close_position(symbol)   # currently return value discarded
  L290-295: self.logger.update_alpaca_trade(trade_id, status="closed", exit_price=current_price, pnl=trade_pnl)
  L297: self.total_pnl += trade_pnl
  L300: alert_position_closed(symbol, side, entry_price, current_price, trade_pnl, close_reason)
  ```
  Change: capture `result = self.alpaca.close_position(symbol)`; derive `exit_fill = result.get("filled_avg_price")`
  (fallback `current_price`), `entry_fill = trade.get("filled_avg_price")` (fallback `entry_price`),
  `fees` = both-legs taker fee; `realized = realized_pnl(side, entry_fill, exit_fill, qty, TAKER_FEE)`;
  pass `exit_price=exit_fill, pnl=realized, fees=fees` to `update_alpaca_trade`; accumulate
  `self.total_pnl += realized`. Consider passing `realized`/`exit_fill` to `alert_position_closed`
  (Claude's discretion — locked scope says only the P&L number/exit_price change; alert can stay on the
  display figure or move to realized, planner picks — recommend realized for consistency).
- **Reconciliation stub — L165-170** (externally-exited rows) writes `exit_price=entry_price, pnl=0.0`.
  Locked scope covers the *triggered close* path only; this external-exit path has no fill data available
  and should remain `pnl=0.0`. Add `fees=0.0` (or omit; new kwarg defaults None). Note it in the plan as
  deliberately unchanged.

**`close_position` return shape (verified, `src/alpaca_client.py` L382-389 → `_parse_order` L421-439):**
returns the full `_parse_order` dict, which **includes** `filled_avg_price` (L432, `float(... or 0)`) and
`filled_qty` (L431), plus `status`, `order_id`, etc. So both exit fill price and exit filled qty are
available. `_parse_order` coerces missing values to `0.0` — a `0` fill price is the "missing" signal that
triggers the `current_price` fallback.

## Q2 — `fees` parameter threading

`update_alpaca_trade` exists in two layers; both need a new optional `fees` kwarg (default `None`, so all
existing callers keep working — additive):

1. **`src/db.py::update_alpaca_trade` (L101-121).** Add `fees: float | None = None` to the signature; add
   `fees = %s` to the UPDATE SET clause; add `fees` to the params tuple. Minimal, backward-compatible.
2. **`src/trade_logger.py::TradeLogger.update_alpaca_trade` (L40-43).** Add `fees: float = None`; forward
   to `_db.update_alpaca_trade(self.bot_id, trade_id, status, exit_price, pnl, fees)`.

**Recommendation:** thread the kwarg (not a separate write path) — it is 4 lines and keeps the close atomic
in one UPDATE. **Every call site that must be reviewed** (grep `update_alpaca_trade`):
- `src/alpaca_orchestrator.py` L165 (external-exit; leave `fees` unset) and L290 (the target close; pass `fees`).
- `src/bot_thread.py` L306, L314, L329, L335 — order-resolution calls (`rejected`/status with `pnl`), NOT
  position closes; leave unchanged (new kwarg defaults None).
- `tests/test_order_resolution.py` `FakeLogger.update_alpaca_trade` (L54) — signature is `(trade_id, status,
  exit_price=None, pnl=None)`; add `fees=None` so the double stays call-compatible if any test passes it.

## Q3 — Migration number, filename, mechanism, DDL mirror

- **Next free number = 016.** Existing files go `002`…`015`; `015_order_state_resolution.sql` is Phase 11.
  New file: **`dashboard/api/migrations/016_realized_pnl_fees.sql`**.
- **Application mechanism (`dashboard/api/migrations/run_migrations.py`):** globs `*.sql` sorted
  lexicographically, tracks applied files in a `_migrations` table (PK `filename`), skips already-applied,
  runs each via raw libpq `conn.pgconn.exec_()` (multi-statement) inside a transaction, records on success.
  So the migration must be **idempotent** (guarded `IF NOT EXISTS`) and safe to run before code deploys —
  mirror the `015` header/style exactly.
- **DDL block to add** (mirror `015`'s additive/nullable/idempotent convention):
  ```sql
  ALTER TABLE alpaca_trades ADD COLUMN IF NOT EXISTS fees DOUBLE PRECISION;
  ```
  Use `DOUBLE PRECISION` to match every other money column (`exit_price`, `pnl`, `filled_avg_price` are all
  `DOUBLE PRECISION`). No NOT NULL, no DEFAULT, no backfill (global rule 6; Phase 14 backfills historicals).
- **`src/db_schema.sql` mirror:** the `alpaca_trades` CREATE TABLE is L20-45; the Phase 11 additive columns
  sit at L40-44. Add `fees DOUBLE PRECISION` as a new trailing column after `filled_avg_price` (L44), with a
  `-- Phase 12 realized-P&L fees (mirror of migration 016; additive, nullable).` comment.

## Q4 — Is entry `filled_avg_price` reliably on the row?

- **Persistence:** `src/db.py::log_alpaca_trade` (L94-95) writes `filled_qty` and `filled_avg_price` from
  `trade_data` at insert. Post-Phase-11 the entry fill is persisted on the row.
- **Load path:** the monitor loads open positions via `TradeLogger.get_open_alpaca_positions` →
  `src/db.py::get_open_alpaca_positions` (L124-129) = `SELECT * FROM alpaca_trades ...`. `SELECT *` means
  **`filled_avg_price` is present in the trade dict** — accessible as `trade.get("filled_avg_price")`.
- **Legacy-row fallback (required):** rows created before Phase 11, or entries where the fill price was
  never captured, will have `filled_avg_price` NULL or `0`. Guard: `entry_fill = trade.get("filled_avg_price")
  or 0; if entry_fill <= 0: entry_fill = entry_price; log fallback`. Same guard as the existing sub-penny
  `entry_price <= 0` reconciliation at L194-202 (which resolves entry from the live Alpaca position).
- **qty:** the row carries both `qty` (L181, ordered qty) and `filled_qty`. Locked helper signature takes a
  single `qty`. Use the row's `qty` for the P&L math (it is what the monitor already uses at L207/L211 and
  matches the closed notional for a fully-filled crypto position). See Q6 gotcha on `filled_qty`.

## Q5 — Test approach

Reuse the no-network / no-Postgres double pattern from `tests/test_order_resolution.py`
(`FakeLogger` in-memory `alpaca_trades`, `FakeAlpacaClient` scripting `_parse_order`-shaped dicts).

**A. Pure-helper unit tests — `tests/test_pnl.py` (new).** Import `src.pnl.realized_pnl`; assert cent-exact:
- `test_realized_pnl_long_gain` — entry 100, exit 110, qty 2, fee 0.0025 → gross 20 − fees
  (100*2+110*2)*0.0025 = 20 − 1.05 = **18.95**.
- `test_realized_pnl_long_loss` — entry 110, exit 100, qty 2 → −20 − 1.05 = **−21.05**.
- `test_realized_pnl_short_gain` — side `short`/`sell`, entry 110, exit 100, qty 2 → +20 − 1.05 = **18.95**
  (short profits when price falls).
- `test_realized_pnl_short_loss` — short, entry 100, exit 110, qty 2 → −20 − 1.05 = **−21.05**.
- `test_realized_pnl_zero_fee` — fee 0.0 → gross only (isolates fee term).
- `test_realized_pnl_side_synonyms` — `"sell"` and `"short"` both treated short; `"buy"`/anything-else long.
- Use `pytest.approx(..., abs=1e-9)` or `round(...,2)` for float equality.

**B. Monitor-level close test — extend `tests/test_order_resolution.py` or new `tests/test_close_pnl.py`.**
Drive `PositionMonitor._check_positions` (or the close block) with doubles:
- `FakeAlpacaClient` scripts: `get_positions()` (return the symbol so reconciliation keeps it),
  `get_latest_price()` (returns `current_price` distinct from the exit fill, to prove the quote is NOT
  used for pnl), `get_bars()` (empty → ATR 0, so exit is driven by a hard_stop pnl_pct), and
  **`close_position()` returning a `_parse_order`-shaped dict with a specific `filled_avg_price`**.
- Seed a `FakeLogger` open row with a known entry `filled_avg_price` and `qty`, side long, an
  `entry_price`/`current_price` arranged to trip `hard_stop_pct`.
- Assertions (concrete test names):
  - `test_close_stores_exit_fill_not_quote` — after close, `row["exit_price"] == exit_fill` (the close-dict
    fill), NOT `current_price`.
  - `test_close_stores_net_realized_pnl` — `row["pnl"]` equals `realized_pnl(side, entry_fill, exit_fill,
    qty, TAKER_FEE)` (net of fees), NOT the quote-based `trade_pnl`.
  - `test_close_persists_fees` — `row["fees"]` equals `(entry_fill*qty + exit_fill*qty) * TAKER_FEE`.
  - `test_close_falls_back_to_current_price_when_no_fill` — close dict with `filled_avg_price=0` → exit_fill
    falls back to `current_price`, and a fallback is logged (`caplog`).
  - `test_close_falls_back_to_entry_price_for_legacy_row` — row `filled_avg_price` NULL/0 → entry_fill uses
    `entry_price`, fallback logged.
  - `test_total_pnl_uses_realized` — `monitor.total_pnl` (and `get_stats()["total_pnl"]`) accumulates the
    realized figure.

`FakeLogger.update_alpaca_trade` already stores `exit_price`/`pnl` conditionally (L54-60); add a `fees`
kwarg + `row["fees"] = fees` so the fees assertion works.

## Q6 — Gotchas

- **Short-side sign.** Helper must branch on `side in ("sell","short")`: short realized = `(entry_fill −
  exit_fill) * qty − fees`; long = `(exit_fill − entry_fill) * qty − fees`. Matches existing L204-211 side
  logic. Test both explicitly (Q5-A).
- **`qty` vs `filled_qty`.** The row has both. For a fully-filled crypto position they're equal; the monitor
  currently uses `qty`. Locked helper takes one `qty` — use the row `qty`. Do NOT mix (e.g. entry `qty` with
  exit `filled_qty`) — a partial close would then mis-scale. Crypto close_position closes the whole position,
  so exit `filled_qty` should equal `qty`; note the assumption in the plan, keep single `qty`.
- **Zero / None fill guards.** `_parse_order` coerces missing fills to `0.0`; DB legacy rows give `None`.
  Guard both: `entry_fill = trade.get("filled_avg_price") or 0` then `if entry_fill <= 0: fallback`. Same for
  `exit_fill`. Never feed `0` fill into the P&L (would look like a −100% loss).
- **Double-counting slippage.** `src/fee_gate.py` exposes both `TAKER_FEE` and `SLIPPAGE_BUFFER`. Realized
  P&L uses **only `TAKER_FEE`** — real fills already embed slippage. `SLIPPAGE_BUFFER` stays a pre-trade gate
  concern only. Do not subtract it here.
- **Ladder figure unchanged.** `pnl_pct`/`trade_pnl` at L204-211 still drive the exit *trigger* and the
  console/log lines (L273-285). Only the *stored* number and `total_pnl` switch to realized. Do not rip out
  `trade_pnl` — the ladder needs `pnl_pct`.
- **One class, all bots.** `PositionMonitor` is instantiated by both `alpaca_orchestrator` (L618) and
  `bot_thread` BotManager (L421); the single edit propagates to every live bot. No per-bot duplication.
- **`bot_id IN ('A','B')` CHECK** in `db_schema.sql` L23 is stale (migration 009 drops it in prod); irrelevant
  to this phase — do not touch.

## Standard Stack

No new dependencies. Reuse in-repo: `src/fee_gate.py` (TAKER_FEE), psycopg3 migrations
(`run_migrations.py`), pytest + in-memory doubles (`tests/test_order_resolution.py` pattern). New file
`src/pnl.py` is pure Python (no imports beyond stdlib). **No external packages installed → no Package
Legitimacy Audit required.**

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Fee constant | New literal 0.0025 | `from src.fee_gate import TAKER_FEE` | Single env-overridable source of truth |
| Exit-fill parsing | Re-parse Alpaca order | `close_position()` return dict (`_parse_order`) | Already normalized incl. `filled_avg_price` |
| Migration runner | Ad-hoc SQL exec | `016_*.sql` + `run_migrations.py` | Idempotent, tracked, deploy-safe |
| Test DB | Real Postgres/Alpaca | `FakeLogger`/`FakeAlpacaClient` | Established zero-network pattern |

## Common Pitfalls

### Pitfall 1: P&L from the quote, not the fill
**What goes wrong:** exit_price/pnl reflect `current_price` (last-poll quote), diverging from what Alpaca
booked. **Avoid:** always source both legs from fills; quote is fallback-only, and the fallback is logged.

### Pitfall 2: Zero fill silently → catastrophic P&L
**What goes wrong:** `_parse_order` returns `0.0` for a not-yet-populated fill → helper computes a fake
−100%. **Avoid:** `<= 0` guard with fallback before calling the helper.

### Pitfall 3: Subtracting slippage twice
**Avoid:** fees = `TAKER_FEE` only; real fills already include slippage.

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `alpaca_trades` rows: adds `fees` column; existing rows get NULL (no backfill this phase — Phase 14) | Migration 016 (additive) + schema mirror |
| Live service config | None — no external service embeds this | None |
| OS-registered state | None | None |
| Secrets/env vars | `TAKER_FEE`/`SLIPPAGE_BUFFER` already env-overridable in `fee_gate.py`; no new secrets | None |
| Build artifacts | None — pure Python, no compiled artifacts | None (redeploy applies migration + code) |

**Deployment note:** migration 016 is deploy-safe to run before code (additive nullable), mirroring 015.

## Environment Availability

Code/config + Postgres migration only; no new external tools. Postgres (Coolify) and pytest already in use.
Migration applied on redeploy via `run_migrations.py`.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | (repo `tests/`; no special config needed) |
| Quick run command | `python -m pytest tests/test_pnl.py -x -q` |
| Full suite command | `python -m pytest tests/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PNL-02 | Cent-exact realized P&L, long & short, net of fees | unit | `python -m pytest tests/test_pnl.py -x` | ❌ Wave 0 |
| PNL-02 | Close stores exit fill + net pnl + fees (not quote) | integration | `python -m pytest tests/test_close_pnl.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_pnl.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -q`
- **Phase gate:** full suite green before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_pnl.py` — covers PNL-02 pure math (long/short/fees/fallbacks-of-math)
- [ ] `tests/test_close_pnl.py` (or extend `tests/test_order_resolution.py`) — covers close-path storage
- [ ] `src/pnl.py` — the helper under test (created in implementation)

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Crypto `close_position` fully closes the position so exit `filled_qty` == row `qty`; single `qty` in helper is safe | Q4/Q6 | Partial fill would mis-scale P&L; low risk (Alpaca crypto closes whole position) |
| A2 | `alert_position_closed` may switch to realized figure without violating locked scope | Q1 | Cosmetic alert mismatch only; planner decides |

## Sources

### Primary (HIGH confidence) — repo source, read this session
- `src/alpaca_orchestrator.py` L107,150-311,618 — PositionMonitor, close block, monitor instantiation
- `src/alpaca_client.py` L382-389, L421-439 — `close_position` return + `_parse_order` shape
- `src/db.py` L80-129 — `log_alpaca_trade` fill persistence, `update_alpaca_trade`, `get_open_alpaca_positions`
- `src/trade_logger.py` L37-43 — TradeLogger wrappers
- `src/fee_gate.py` — TAKER_FEE / SLIPPAGE_BUFFER
- `src/db_schema.sql` L20-45 — alpaca_trades DDL
- `dashboard/api/migrations/015_order_state_resolution.sql` + `run_migrations.py` — migration pattern/mechanism
- `tests/test_order_resolution.py` L1-68 — FakeLogger/FakeAlpacaClient double pattern
- `src/bot_thread.py` L64-65,306-335,421 — shared PositionMonitor + resolution call sites

## Metadata

**Confidence breakdown:**
- Edit sites / call sites: HIGH — exact line numbers verified in current source
- Migration mechanism: HIGH — `run_migrations.py` + 015 read directly
- Fill availability: HIGH — `SELECT *` load + `log_alpaca_trade` insert confirmed
- Test approach: HIGH — mirrors existing suite; math values hand-computed

**Research date:** 2026-07-09
**Valid until:** 2026-08-09 (stable; internal code)

---

## RESEARCH COMPLETE — Confidence: HIGH
