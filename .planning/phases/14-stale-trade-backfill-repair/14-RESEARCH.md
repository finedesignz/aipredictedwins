# Phase 14: Stale-Trade Backfill & Repair — Research

**Researched:** 2026-07-10
**Domain:** One-shot idempotent DB backfill against Alpaca order/position history (Python, alpaca-py 0.43.2, Postgres via psycopg)
**Confidence:** HIGH (all mechanisms verified against real code in this repo)

## Summary

Phase 14 is a standalone script `scripts/backfill_trades.py` that walks genuinely-stale
`alpaca_trades` rows (`status IN ('open','submitted')` with an `order_id`, older than a guard
window), resolves each against Alpaca via the **already-shipped** Phase-11 classification +
Phase-12 realized-P&L path, and reports `resolved / unresolvable / unchanged` per bot. Every
building block already exists in the codebase and must be **reused, not reimplemented**:
`AlpacaClient.get_order`, `AlpacaClient._parse_order`, `pnl.realized_pnl`, `TAKER_FEE`,
`TradeLogger.update_alpaca_trade`, and the per-bot key-sourcing driver from `src/reconciliation.py`.

The one genuinely new mechanism is the **closing-order lookup**: for a filled entry whose
position is no longer live, find the opposite-side CLOSED order that closed it via
`GetOrdersRequest(status=QueryOrderStatus.CLOSED, symbols=[...])`. This is not yet wired anywhere
and needs a small new `AlpacaClient` method plus a matching heuristic (below). Two new read-only
`db.py` queries are also needed (stale-candidate select + NULL-order_id residue count).

**Primary recommendation:** Add one new `AlpacaClient.get_closed_orders(symbol)` method, two new
read-only `db.py` queries, and a small pure `resolve_stale_row(...)` helper that reuses `_classify`
logic + `realized_pnl`. Drive it from a `reconcile.py`-shaped `scripts/backfill_trades.py` with
`--apply`/`--dry-run` (dry-run default). No schema change. No new dependencies.

## User Constraints (from CONTEXT.md)

### Locked Decisions
1. **One-shot script, not a runtime loop.** `scripts/backfill_trades.py` (matches
   `scripts/reconcile.py` / `scripts/check_trades.py`). Read-mostly against Alpaca; writes only
   resolved rows via existing `update_alpaca_trade` / Phase-12 close path. Per-bot Alpaca keys
   (never bare/shared) — same sourcing as the Phase-13 driver.
2. **Candidate set = genuinely stale rows.** `status IN ('open','submitted')` WITH an `order_id`,
   older than a small config-driven guard window (avoid racing live in-flight orders). Rows without
   `order_id` (pre-Phase-11 legacy) are **unresolvable** — count + report, never guess.
3. **Resolution ladder per row** (reuse Phase 11 + 12):
   - `get_order(order_id)` → entry order terminal state.
   - Entry `canceled`/`rejected`/`expired`, 0 filled → terminal non-position status, pnl=0.
   - Entry `filled`/partial: became a position. Check live positions; still open → leave `open`,
     count **unchanged**. No longer open → find closing order via CLOSED-status query; if found,
     compute `realized_pnl(...)` and write `status='closed'`, `exit_price`, `pnl`, `fees`.
   - Closing order not findable → **unresolvable** (report, leave unchanged).
4. **Idempotent.** Re-run touches only rows still in the candidate stale set; already-terminal rows
   skipped. Keyed on `order_id`. Safe to run repeatedly.
5. **Report counts.** Print/log `resolved / unresolvable / unchanged` per bot + overall, plus the
   irreducible residue (no order_id / no Alpaca history).
6. **Dry-run by default.** `--apply` flag to write; default lists what WOULD change.

### Claude's Discretion
- Whether to extract a pure `resolve_stale_row` helper vs. call a lightly-refactored `_classify`.
- Exact matching heuristic for the closing order among candidates.
- Guard-window env var name/default.

### Deferred Ideas (OUT OF SCOPE)
- Alpaca account **activities** feed for exact historical fees — use `TAKER_FEE` estimate
  consistent with Phase 12 (revisit Phase 20).
- Backfilling pre-`order_id` legacy rows via fuzzy symbol/time matching — leave as reported residue.
- Does NOT change the forward resolver (Phase 11) or the P&L formula (Phase 12) — reuses them.
- Does NOT reconcile against account totals (Phase 13).
- No schema change (columns from migrations 011/016 suffice).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PNL-05 | One-shot idempotent backfill resolves existing open/stale `alpaca_trades` rows to true terminal state from Alpaca history, writing realized P&L via the Phase-12 path; reports resolved/unresolvable/unchanged + residue. | Closing-order lookup (§1), stale-candidate query (§2), reuse surface (§3), write path (§4), key sourcing (§5), entrypoint (§6), tests (§7). |

---

## 1. Closing-order lookup (the one new mechanism) — HIGH confidence

**Goal:** given a filled entry order whose position is gone, find the opposite-side CLOSED order
that closed it.

**Exact request shape** (mirrors the existing `get_open_orders`, `src/alpaca_client.py` L406-417,
which already imports `GetOrdersRequest` + `QueryOrderStatus` — enum path **confirmed** in-repo):

```python
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

request = GetOrdersRequest(
    status=QueryOrderStatus.CLOSED,   # terminal orders (filled/canceled/expired/...)
    symbols=[symbol],                 # e.g. "BTC/USD" — order.symbol carries the slash for crypto
    limit=500,                        # page size; default 50 is too small for history
    direction="desc",                 # newest first
)
raw = self._trading_client.get_orders(filter=request)  # wrap in _retry like get_open_orders
```

- `QueryOrderStatus.CLOSED` is the correct enum member — same enum already used with `.OPEN` at
  L409. `[VERIFIED: src/alpaca_client.py L406-411]`. `.CLOSED` value confirmed by alpaca-py enum
  `{OPEN, CLOSED, ALL}` `[ASSUMED: alpaca-py enum]` — the planner should have the implementer
  smoke-import `QueryOrderStatus.CLOSED` in Wave 0.
- **Symbol format:** `_parse_order` returns `order.symbol` which for crypto is `"BTC/USD"` (with
  slash), matching the `alpaca_trades.symbol` column. Filter `symbols=[row_symbol]` directly. Do
  NOT strip the slash here (slash-stripping is only for `close_position`, L385).
- **Pagination:** alpaca-py `get_orders` returns a single page bounded by `limit`. For a paper
  account with modest history, `limit=500` + `direction="desc"` is sufficient. If more coverage is
  needed, add `after=<entry.filled_at>` to bound the window to orders created after the entry
  filled. Recommend passing `after` = entry `filled_at` (minus a small skew) to shrink the result
  set and naturally exclude pre-entry orders.

**Matching heuristic (recommended):** among the returned CLOSED orders, keep those that are:
1. opposite side to the entry (entry `buy` → close `sell`; entry `sell`/short → close `buy`),
2. `status` filled (or `filled_qty > 0`),
3. `filled_at` **after** the entry's `filled_at`,

then pick the **earliest** such order (nearest close after entry). Use its `filled_avg_price` as
`exit_fill` and `filled_qty` as the close qty.

**Failure / ambiguity modes to report as `unresolvable` (leave row unchanged):**
- **No matching close found** — position closed but no opposite CLOSED order in the returned window
  (e.g. closed via `close_position`/liquidation that Alpaca records differently, or beyond the
  page). Report, do not guess.
- **Multiple partial closes** — several opposite fills summing to the entry qty. v1 heuristic: if
  the earliest opposite fill's `filled_qty` ≈ entry `filled_qty` (within a small tolerance) treat
  as the single close; otherwise flag `unresolvable` (partial-close aggregation is out of scope —
  note it as a known gap, consistent with the deferred "activities feed" idea).
- **Ambiguous multiple full closes** for the same symbol (re-entered & re-closed) — the "earliest
  filled after entry.filled_at" rule disambiguates; if `after` bounding is used the set is already
  narrowed.

---

## 2. Stale-candidate query (two new read-only `db.py` functions) — HIGH confidence

Add to `src/db.py` (all existing queries are per-bot and parameterized — follow the exact style of
`get_pending_alpaca_orders`, L133-148). Postgres, psycopg, `%s` placeholders, `dict_row` factory.

```python
def get_stale_alpaca_candidates(bot_id: str, older_than_minutes: int = 30) -> list[dict]:
    """Non-terminal rows WITH an order_id, older than a guard window — Phase-14 backfill set.

    status IN ('open','submitted') AND order_id IS NOT NULL AND timestamp older than the
    guard window (avoid racing live in-flight orders). Idempotent: a row that reaches a
    terminal status drops out of this set automatically on re-run.
    """
    with connection() as conn:
        return conn.execute(
            """
            SELECT id, order_id, symbol, side, qty, entry_price,
                   filled_qty, filled_avg_price, order_type, status, timestamp
            FROM alpaca_trades
            WHERE bot_id = %s
              AND status IN ('open', 'submitted')
              AND order_id IS NOT NULL
              AND timestamp::timestamptz < NOW() - (%s || ' minutes')::interval
            ORDER BY timestamp ASC
            """,
            (bot_id, str(older_than_minutes)),
        ).fetchall()


def count_unresolvable_alpaca_rows(bot_id: str) -> int:
    """Count non-terminal rows with NO order_id (pre-Phase-11 legacy residue — unresolvable)."""
    with connection() as conn:
        return conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM alpaca_trades
            WHERE bot_id = %s
              AND status IN ('open', 'submitted')
              AND order_id IS NULL
            """,
            (bot_id,),
        ).fetchone()["n"]
```

Notes:
- The `timestamp::timestamptz < NOW() - interval` pattern is proven in-repo
  (`get_recent_loss_symbols`, L151-165, uses `closed_at::timestamptz >= NOW() - (%s || ' hours')::interval`).
  `[VERIFIED: src/db.py L161]`.
- Guard window: env-driven, e.g. `BACKFILL_GUARD_MINUTES` (default 30). Follows the repo's
  env-config idiom (`LIMIT_ORDER_TIMEOUT_S`, `RECONCILIATION_TOLERANCE_USD`).
- Select must return `entry_price`, `filled_qty`, `filled_avg_price`, `side`, `symbol`, `order_id`,
  `status` — everything the resolution ladder needs without a second query.

---

## 3. Reuse surface — recommendation: extract one small pure helper — HIGH confidence

**`_classify` (Phase 11, `src/bot_thread.py` L262-277):** it is already a pure static-ish method
(reads only the `order` dict) mapping a parsed order to `(db_status, pnl)`:
- `filled` OR `filled_qty>0` → `("open", None)`
- `canceled`/`cancelled`/`expired`/`rejected` with 0 fill → `(status, 0)`
- in-flight → `(None, None)`

It is bound to `BotThread` but has no `self` dependency beyond the `_TERMINAL_NONPOSITION`
frozenset. **Smallest-diff recommendation:** do NOT instantiate a `BotThread` in a script. Extract
the classification into a module-level pure function (e.g. `src/order_resolution.py::classify_order(order) -> tuple[str|None, int|None]`)
and have `BotThread._classify` delegate to it (one-line change, keeps Phase-11 tests green). The
backfill script imports the pure function. This avoids importing the heavy `BotThread` (which pulls
`alpaca_orchestrator`, learning loop, etc.) into a standalone script.

- Alternative (also acceptable, even smaller diff): the script constructs a throwaway
  `BotThread(BotConfig(...))` exactly as `tests/test_order_resolution.py::_bot()` does (L130-132) and
  calls `bot._classify(order)`. This works today but couples the script to the full BotThread import
  graph. Prefer the extracted helper.

**`realized_pnl` (Phase 12, `src/pnl.py`):** call exactly as the monitor does
(`src/alpaca_orchestrator.py` L303-313) `[VERIFIED]`:

```python
from src.pnl import realized_pnl
from src.fee_gate import TAKER_FEE

entry_fill = float(row["filled_avg_price"] or row["entry_price"])  # fall back to entry_price if fill missing
exit_fill  = float(close_order["filled_avg_price"])
qty        = float(row["filled_qty"] or row["qty"])
side       = row["side"]                                            # 'buy' → long, 'sell'/'short' → short
fees       = (entry_fill * qty + exit_fill * qty) * TAKER_FEE       # same formula the monitor logs
realized   = realized_pnl(side, entry_fill, exit_fill, qty, TAKER_FEE)
```

- `TAKER_FEE` source: `from src.fee_gate import TAKER_FEE` (= `float(os.environ.get("TAKER_FEE","0.0025"))`).
  `[VERIFIED: src/fee_gate.py L16]`. Same constant the Phase-12 monitor uses — fee consistency is
  automatic as long as the script imports the same symbol (do NOT hardcode 0.0025).
- `realized_pnl` already nets fees on both legs internally; `fees` is written separately to the
  `fees` column only (it is NOT double-subtracted). Mirror the monitor exactly. `[VERIFIED: src/alpaca_orchestrator.py L305-313]`.

---

## 4. Write path — HIGH confidence

**Exact mutation:** `logger.update_alpaca_trade(trade_id, status, exit_price, pnl, fees)` where
`logger` is a per-bot `TradeLogger`. TradeLogger binds `bot_id`; it delegates to
`db.update_alpaca_trade(bot_id, trade_id, status, exit_price, pnl, fees)`
`[VERIFIED: src/trade_logger.py L40-44, src/db.py L101-122]`.

Resolved-close write (mirrors Phase-12 monitor L308-314 exactly):
```python
logger.update_alpaca_trade(trade_id, status="closed", exit_price=exit_fill, pnl=realized, fees=fees)
```
Terminal non-position write (entry canceled/rejected/expired, 0 fill):
```python
logger.update_alpaca_trade(trade_id, status, pnl=0)   # status ∈ {canceled, rejected, expired}
```

- `db.update_alpaca_trade` auto-stamps `closed_at` when status ∈
  `{closed, stopped, target_hit, canceled, expired, rejected}` `[VERIFIED: src/db.py L109-113]` —
  no need to set it manually.
- **Idempotency is structural:** the candidate query (§2) only returns `status IN ('open','submitted')`.
  A row written to `closed`/`canceled`/etc. no longer matches, so a re-run never re-touches it. No
  explicit guard needed — but the script must select candidates fresh at the start of each bot's
  pass. A row left `unchanged` (still-open position) or `unresolvable` (no close found) stays
  `open`/`submitted` and WILL be re-examined next run — correct, it may resolve later. This is the
  intended behavior, not a bug.

---

## 5. Per-bot key sourcing + bot enumeration — HIGH confidence (reuse Phase-13 driver verbatim)

`src/reconciliation.py` already provides the exact pattern the script must reuse
`[VERIFIED: src/reconciliation.py L51-93]`:

- `_enabled_bot_ids()` (L51-59): `SELECT bot_id FROM bots WHERE enabled = TRUE ORDER BY bot_id` —
  source of truth, not an A/B hardcode.
- `_client_for_bot(bot_id)` (L62-93): builds ONE `AlpacaClient` from
  `ALPACA_API_KEY_{id}` / `ALPACA_SECRET_KEY_{id}` (dashboard env-suffix pattern), falling back to
  the `bots`-row keys, raising if neither present. **Never reads bare `ALPACA_API_KEY`** — enforces
  the one-account-per-bot hard rule.

**Recommendation:** import and reuse `reconciliation._enabled_bot_ids` and
`reconciliation._client_for_bot` directly (or, if the planner prefers not to import underscored
helpers, lift both into a shared `src/bot_accounts.py` in a tiny refactor and have both call sites
use it). Simplest smallest-diff: import them as-is. The backfill also needs a per-bot `TradeLogger`:
`TradeLogger(bot_id=bot_id)` (accepts any non-empty string, L23-26).

---

## 6. Entrypoint shape — HIGH confidence (match `scripts/reconcile.py`)

`scripts/reconcile.py` (L1-36) is the template: thin `main()` delegating to a `src/` driver,
printing a per-bot table, returning an exit code. Backfill adds argparse for `--apply`/`--dry-run`.

```python
# scripts/backfill_trades.py
import argparse, sys
from src.backfill import backfill   # new driver in src/backfill.py

def main() -> int:
    ap = argparse.ArgumentParser(description="One-shot stale-trade backfill (PNL-05).")
    ap.add_argument("--apply", action="store_true",
                    help="Actually write resolved rows. Default: dry-run (no writes).")
    args = ap.parse_args()
    apply = args.apply            # dry-run is the default (Decision 6)

    results = backfill(apply=apply)   # list[(bot_id, counts_dict)]
    print(f"{'Bot':<6} {'Resolved':>9} {'Unchanged':>10} {'Unresolvable':>13} {'Residue':>8}")
    print("-" * 50)
    totals = {"resolved": 0, "unchanged": 0, "unresolvable": 0, "residue": 0}
    for bot_id, c in results:
        for k in totals: totals[k] += c[k]
        print(f"{bot_id:<6} {c['resolved']:>9} {c['unchanged']:>10} {c['unresolvable']:>13} {c['residue']:>8}")
    print("-" * 50)
    print(f"{'ALL':<6} {totals['resolved']:>9} {totals['unchanged']:>10} "
          f"{totals['unresolvable']:>13} {totals['residue']:>8}")
    if not apply:
        print("\nDRY RUN — no rows written. Re-run with --apply to persist.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- The driver `src/backfill.py` holds the per-bot loop + resolution ladder (mirrors
  `reconciliation.reconcile` / `reconcile_bot_live` structure). Keep the pure resolution decision
  (`resolve_stale_row(row, entry_order, live_symbols, close_order) -> ("resolved"|"unchanged"|"unresolvable", write_kwargs|None)`)
  separate from I/O so it is unit-testable with zero network (see §7).
- `residue` = `count_unresolvable_alpaca_rows(bot_id)` (NULL order_id); reported separately from
  `unresolvable` (order_id present but no findable close).

---

## 7. Test approach — HIGH confidence (reuse `test_order_resolution.py` conventions)

Zero-network fakes exactly like `tests/test_order_resolution.py` (`FakeLogger`, `FakeAlpacaClient`,
`_order`, `_pending_row` — L31-143). Extend `FakeAlpacaClient` with a scripted
`get_closed_orders(symbol)` and `get_positions()` returning `_parse_order`/position-shaped dicts.
Make the pure `resolve_stale_row` the primary unit under test. New file
`tests/test_backfill.py`. Concrete test names:

| Test | Scenario | Assert |
|------|----------|--------|
| `test_entry_canceled_terminalizes_pnl_zero` | entry order `canceled`, 0 fill | row → `canceled`, pnl=0, no close lookup |
| `test_entry_rejected_terminalizes_pnl_zero` | entry `rejected`, 0 fill | row → `rejected`, pnl=0 |
| `test_entry_expired_terminalizes_pnl_zero` | entry `expired`, 0 fill | row → `expired`, pnl=0 |
| `test_filled_position_gone_close_found_resolves` | entry filled, symbol NOT in live positions, opposite CLOSED order found | row → `closed`, `exit_price=close.filled_avg_price`, `pnl==realized_pnl(...)`, `fees` set |
| `test_filled_still_open_unchanged` | entry filled, symbol IN live positions | row untouched, counted `unchanged` |
| `test_no_order_id_is_residue` | non-terminal row, `order_id` NULL | not in candidate set; `count_unresolvable_alpaca_rows` counts it |
| `test_close_not_findable_unresolvable` | entry filled, position gone, no opposite CLOSED order | row untouched, counted `unresolvable` |
| `test_realized_pnl_matches_phase12_formula` | known fills | `pnl` equals `realized_pnl(side,entry,exit,qty,TAKER_FEE)` and `fees==(entry*qty+exit*qty)*TAKER_FEE` |
| `test_short_entry_close_pnl_sign` | side=`sell`, exit < entry | positive realized (short profit) |
| `test_idempotent_rerun_noop` | run twice on same fakes; 2nd run sees only terminal rows | 2nd pass writes nothing (candidate set empty) |
| `test_dry_run_writes_nothing` | `apply=False` with a resolvable row | `FakeLogger.update_alpaca_trade` never called; counts still computed |
| `test_multiple_closes_earliest_after_entry_selected` | two opposite CLOSED orders | earliest `filled_at` after entry chosen |
| `test_partial_close_qty_mismatch_unresolvable` | close `filled_qty` ≠ entry `filled_qty` | counted `unresolvable`, row untouched |

Plus a **DATABASE_URL-gated integration guard** (skip when unset, matching repo convention for
Postgres-touching tests):
```python
@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="needs Postgres")
def test_stale_candidate_query_shape():
    # insert an old submitted row w/ order_id + an old open row w/ NULL order_id,
    # assert get_stale_alpaca_candidates returns the first, excludes the NULL-order_id one,
    # and count_unresolvable_alpaca_rows counts the NULL-order_id row.
```

Run: `pytest tests/test_backfill.py -x -q` (quick, < 30s, zero network). Full suite before phase
gate.

### Validation Architecture
| Property | Value |
|----------|-------|
| Framework | pytest (in-repo; `tests/test_order_resolution.py`, `tests/test_reconciliation.py`) |
| Config file | none dedicated — pytest discovers `tests/test_*.py` |
| Quick run | `pytest tests/test_backfill.py -x -q` |
| Full suite | `pytest -q` |
| Sampling | per task commit: `pytest tests/test_backfill.py -q`; phase gate: full suite green |

**Wave 0 gaps:** `tests/test_backfill.py` (new) — covers PNL-05. Fakes copied/extended from
`tests/test_order_resolution.py`. No framework install needed.

---

## 8. Gotchas / Common Pitfalls

- **Partial fills:** entry `filled_qty` may be < `qty`. Use `filled_qty` (not `qty`) for the P&L
  qty, and match the close on `filled_qty`. Multiple partial closes are out of scope → mark
  `unresolvable` when a single close doesn't match the entry qty. Do NOT sum-aggregate closes in v1.
- **Multiple closes for a re-entered symbol:** the "earliest opposite fill after entry.filled_at"
  rule + optional `after=entry.filled_at` request bound disambiguates. Without the time bound you
  risk matching a later cycle's close.
- **TAKER_FEE consistency:** import `from src.fee_gate import TAKER_FEE` — never hardcode `0.0025`.
  Guarantees the same fee the Phase-12 monitor applied; keeps reconciliation (Phase 13) delta
  shrinking rather than introducing a new source of drift.
- **Guard window racing live orders:** the guard window (default 30 min) is essential — a row
  submitted seconds ago may still be legitimately in-flight; resolving it prematurely races the live
  bot's own resolver. Make it env-configurable and default conservatively.
- **NEVER delete/reset rows (CLAUDE.md hard rule):** the script only ever `UPDATE`s status/pnl/
  exit_price/fees. No `DELETE`, no `TRUNCATE`. `update_alpaca_trade` is UPDATE-only `[VERIFIED]`.
- **Dry-run default:** `--apply` must be explicitly passed to write. Dry-run must still perform all
  reads and compute the same counts so the operator can preview exactly what `--apply` would do.
- **Symbol slash:** `order.symbol` for crypto is `"BTC/USD"` (matches the DB `symbol` column and the
  `symbols=[...]` filter). Only `close_position` strips the slash — do not strip it in the CLOSED
  query.
- **`filled_avg_price` fallback:** legacy stale rows may have `filled_avg_price` NULL/0 even though
  filled. Fall back to `entry_price` for `entry_fill` (the monitor does the same, L303). The exit
  fill must come from the close order's `filled_avg_price`; if that is 0/NULL, treat as
  `unresolvable`.
- **One-account-per-bot:** reuse `_client_for_bot`; never construct a client from bare
  `ALPACA_API_KEY`. Two bots sharing an account corrupts attribution (CLAUDE.md).

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---------|-------------|-------------|-----|
| Order → status/pnl classification | new state machine | Phase-11 `_classify` (extract to pure helper) | already tested, terminal-set canonical |
| Realized P&L math | inline arithmetic | `src/pnl.realized_pnl` | single source of truth, fee-netting, side-aware |
| Fee rate | literal `0.0025` | `src.fee_gate.TAKER_FEE` | env-driven, matches Phase 12 |
| Per-bot Alpaca client | bare-key client | `reconciliation._client_for_bot` | enforces one-account-per-bot |
| Bot enumeration | A/B/C/D hardcode | `reconciliation._enabled_bot_ids` | reads `bots` table source of truth |
| Row mutation | raw SQL in script | `TradeLogger.update_alpaca_trade` | auto-stamps `closed_at`, bot-scoped |

## Environment Availability

| Dependency | Required by | Available | Notes |
|------------|-------------|-----------|-------|
| Postgres (`DATABASE_URL`) | candidate query, writes | runtime | integration test gated on it |
| Alpaca paper account per bot | order/position lookups | runtime (per-bot keys) | script reads live Alpaca; no network in unit tests |
| alpaca-py 0.43.2 | `GetOrdersRequest`/`QueryOrderStatus.CLOSED` | ✓ (already imported in `alpaca_client.py`) | verify `.CLOSED` import in Wave 0 |

No new packages. No schema change. No package-legitimacy audit needed (no installs).

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|-------|---------|---------------|
| A1 | `QueryOrderStatus.CLOSED` is a valid member in alpaca-py 0.43.2 | §1 | Low — Wave-0 smoke import catches it; `.OPEN` from same enum already used |
| A2 | `get_orders(filter=GetOrdersRequest(...))` returns a single `limit`-bounded page (no auto-pagination) | §1 | Medium — if history exceeds `limit`, some closes missed → more `unresolvable`; mitigate with `after=entry.filled_at` bound |
| A3 | crypto `order.symbol` carries the slash (`"BTC/USD"`) in CLOSED-order results, matching the DB column | §1 | Medium — mismatch → 0 matches → all filled rows go `unresolvable`; verify with one real order in Wave 0 |

## Sources

### Primary (HIGH — verified in-repo this session)
- `src/alpaca_client.py` — `get_order` L401-404, `get_open_orders`/`GetOrdersRequest`/`QueryOrderStatus` L406-417, `_parse_order` L421-439, `close_position` L382-389.
- `src/pnl.py` — `realized_pnl` full file.
- `src/fee_gate.py` — `TAKER_FEE` L16.
- `src/bot_thread.py` — `_classify` L262-277, `_resolve_pending_orders` L279-335, `_TERMINAL_NONPOSITION` L236.
- `src/db.py` — `update_alpaca_trade` L101-122, `get_pending_alpaca_orders` L133-148, `get_open_alpaca_positions` L125-130, `get_recent_loss_symbols` (interval pattern) L151-165.
- `src/trade_logger.py` — `update_alpaca_trade` L40-44, bot_id binding L23-33.
- `src/reconciliation.py` — `_enabled_bot_ids` L51-59, `_client_for_bot` L62-93, driver L96-143.
- `src/alpaca_orchestrator.py` — Phase-12 close write L303-316.
- `scripts/reconcile.py` — entrypoint shape L1-36.
- `tests/test_order_resolution.py` — fakes + conventions L31-343.

### Secondary
- alpaca-py `QueryOrderStatus`/`GetOrdersRequest` semantics — training knowledge (A1–A3 flagged).

## Metadata
- Standard stack: HIGH — all reuse targets read directly.
- Closing-order lookup: MEDIUM-HIGH — mechanism verified, enum `.CLOSED` value + pagination flagged (A1–A3).
- Pitfalls: HIGH — grounded in the actual monitor/resolver code.
- Research date: 2026-07-10 · Valid until: ~2026-08-10 (stable internal codebase).
