# Phase 11: Order-State Resolution Engine — Research

**Researched:** 2026-07-09
**Domain:** Alpaca order lifecycle reconciliation (alpaca-py 0.43.2), Postgres schema migration, crash-safe polling
**Confidence:** HIGH

## Summary

Today a trade row is INSERTed with `status='open'` the instant an order is *submitted* — the
Alpaca `order_id` is thrown away and no fill confirmation is required (`src/bot_thread.py`
→ `src/db.py::log_alpaca_trade`, which has no `order_id` column). The only mechanism that ever
moves a row off `open` is `PositionMonitor` (`src/alpaca_orchestrator.py::_check_all_positions`),
which resolves rows against **live Alpaca positions**. An order that never becomes a held
position — a resting/unfilled limit order, or a canceled/rejected/expired order — is unreachable
by that reconciliation and stays `open` forever. This is the ~90%-unresolved root cause (PNL-04).

The fix (locked in CONTEXT): persist `order_id` at submission, write the row in a new pre-terminal
`submitted` status, and add an **order-resolution pass** to the bot cycle that polls each pending
order via a new `get_order(order_id)` (backed by alpaca-py `TradingClient.get_order_by_id`) and
transitions the row to a terminal state — `open` (genuine position) on fill, or a new terminal
non-position status (`canceled`/`rejected`/`expired`) with `pnl=0` otherwise. Resting limit orders
past a timeout are `cancel_order`'d and terminalized. Everything is keyed on `order_id` so a
restarted bot re-polls in-flight orders from the DB, and re-running on a terminal row is a no-op.

**Primary recommendation:** Add `order_id` (+ `filled_qty`, `filled_avg_price`) columns via
migration `015_order_state_resolution.sql`, introduce a `submitted` pre-terminal status and
`canceled`/`rejected`/`expired` terminal statuses, add `AlpacaClient.get_order(order_id)`, and add
a `_resolve_pending_orders()` pass at the top of the `BotThread` scan loop (crash-safe, idempotent,
DB-driven).

## User Constraints (from CONTEXT.md)

### Locked Decisions

1. **Explicit order-lifecycle poll.** After submission, the owning bot loop (a resolver pass in
   `bot_thread`) polls each order via `get_order`/`get_open_orders` until it reaches an Alpaca
   terminal order state (`filled`, `canceled`, `expired`, `rejected`; `partially_filled` resolved
   when done). Row transitions: `filled` → stays `open` as a genuine held position (Phase 12 does
   realized P&L on close); `canceled`/`expired`/`rejected`/unfilled-at-timeout → terminal
   **non-position** status (e.g. `canceled`) with `pnl=0`, never left `open`.
2. **New terminal statuses, additive.** Distinct terminal states for orders that never became
   positions, so they are excluded from "open position" queries and win/loss stats. Do NOT overload
   `closed` (which means "position closed with P&L"). Migration = numbered SQL file, next free
   `dashboard/api/migrations/NNN_*.sql`, mirrored in `src/db_schema.sql`. **Not alembic.**
3. **Unfilled-limit timeout.** A resting limit order unfilled within a bounded window (config,
   default aligned to scan cadence — cancel-and-mark after ~one scan cycle) is `cancel_order`'d and
   its row terminalized. Env/config-driven and reversible.
4. **Idempotent + crash-safe.** Keyed on Alpaca `order_id` (persisted on the row at submission). A
   restarted bot re-polls in-flight orders from the DB. Re-running resolution on a terminal row is a
   no-op.
5. **No silent drops.** Every submission path (long entry, short entry, any exit order) writes a row
   with `order_id` and is subject to resolution. Submit rejections/exceptions are logged AND recorded
   as a terminal `rejected` row, never dropped.
6. **Scope discipline.** Changes *when/how rows reach a terminal state* only. Does NOT recompute
   historical P&L (Phase 12), does NOT backfill existing stuck rows (Phase 14), does NOT touch the
   universe gate (Phase 15).

### Claude's Discretion

- Exact placement of the resolver pass (new pass inside `BotThread` loop vs extending
  `PositionMonitor`) — research recommends the `BotThread` scan loop (see Architecture).
- Timeout config name/default and status-value naming.

### Deferred Ideas (OUT OF SCOPE)

- Realized P&L from actual fills incl. fees — Phase 12 (PNL-02).
- Reconciliation vs Alpaca account P&L — Phase 13 (PNL-03).
- Backfill/repair of existing stale `open` rows — Phase 14 (PNL-05).
- Websocket / trade-update stream instead of polling — future optimization; polling is sufficient
  for the current scan cadence.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PNL-01 | Every submitted order transitions to a terminal state and is recorded — no silent drops | New `submitted`→terminal state machine + `order_id` persistence + exception path writes `rejected` row (see State Machine, Code Examples) |
| PNL-04 | Root cause of unresolved trades identified + fixed so resolution rate ≈100% forward | Root cause = `order_id` discarded + `PositionMonitor` only resolves against live *positions*; fix = order-resolution poll pass keyed on `order_id` (see Root Cause, Architecture) |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Submit order + capture `order_id` | `BotThread` scan loop (`bot_thread.py`) | `AlpacaClient` | Submission already lives here; only needs to persist the returned `order_id` |
| Resolve submitted → terminal | `BotThread` resolver pass | `AlpacaClient.get_order` | Must re-poll from DB on restart; belongs in the owning bot's crash-safe loop, not the position monitor |
| Single-order fetch / cancel | `AlpacaClient` | alpaca-py `TradingClient` | Thin SDK wrapper; `get_open_orders`/`cancel_order` already there, add `get_order` |
| Position exit (post-fill) | `PositionMonitor` | — | Unchanged: monitors *positions* (`status='open'`), not orders |
| Row state persistence | `src/db.py` + schema | migration `015` | Numbered-SQL migration rule (CLAUDE.md) |

## Root Cause (verified in code)

`[VERIFIED: codebase]` **`order_id` is never persisted.** `src/db.py::log_alpaca_trade` (L65-92)
INSERTs `alpaca_trades` with no `order_id` column — the `order` dict returned by
`place_market_order`/`place_limit_order` (which *does* contain `order_id`, `status`, `filled_qty`,
`filled_avg_price` via `_parse_order`, `alpaca_client.py` L417-434) is only logged, never stored.

`[VERIFIED: codebase]` **Row lands as `status='open'` at submit.** `alpaca_trades.status DEFAULT
'open'` (`src/db_schema.sql` L34); `log_alpaca_trade` never sets status. No fill confirmation.
`bot_thread.py` L647 (long) and L841 (short) call `log_alpaca_trade` immediately after submit.

`[VERIFIED: codebase]` **`PositionMonitor` only resolves against live positions.**
`_check_all_positions` (`alpaca_orchestrator.py` L142-172) reads `get_open_alpaca_positions()`
(rows where `status='open'`) and reconciles against `alpaca.get_positions()`. An unfilled order has
no position, so:
- If the reconcile fetch succeeds, the row is marked `closed` with `exit_price=entry_price, pnl=0`
  (L159-170) — technically resolved but **mis-attributed as a closed P&L trade** and pollutes
  win/loss stats. This is exactly why CONTEXT forbids overloading `closed`.
- If the fetch fails or the monitor isn't running (`live_symbols is None`), the row stays `open`.

`[VERIFIED: codebase]` **Entries are market orders; exits use `close_position`.** `bot_thread`
entries call `place_market_order` (L641, L839). Crypto market orders are GTC and usually fill
near-instantly, but can still be `rejected` (insufficient buying power, min-notional) or partially
fill. `place_limit_order` exists (`alpaca_client.py` L334) and is in-scope per Decision 5 (any exit
order / future limit entries). The resolver must handle both order types generically off `order_id`.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| alpaca-py | 0.43.2 (pinned, CLAUDE.md) | Order submit/poll/cancel via `TradingClient` | Already the project SDK |
| psycopg (via `src/db.py`) | existing | Postgres on Coolify | Project DB layer, `connection()` context mgr |

No new packages. **Package Legitimacy Audit: N/A — no external packages installed this phase.**

### Alpaca order lifecycle (alpaca-py 0.43.2)

`[CITED: alpaca.markets/sdks/python/api_reference/trading]` `TradingClient.get_order_by_id(order_id)`
returns a single `Order` by id — this is the single-order poll the resolver needs (no such wrapper
exists in `alpaca_client.py` yet; **add `get_order(order_id)`**). `get_orders(filter=...)` lists.

`[CITED: docs.alpaca.markets/us/docs/orders-at-alpaca]` `OrderStatus` enum
(`alpaca.trading.enums.OrderStatus`) values: `NEW, PARTIALLY_FILLED, FILLED, DONE_FOR_DAY, CANCELED,
EXPIRED, REPLACED, PENDING_CANCEL, PENDING_REPLACE, PENDING_REVIEW, ACCEPTED, PENDING_NEW,
ACCEPTED_FOR_BIDDING, STOPPED, REJECTED, SUSPENDED, CALCULATED, HELD`.

**Terminal states (no further updates):** `FILLED`, `CANCELED`, `EXPIRED`, `REJECTED`
`[CITED: docs.alpaca.markets/us/docs/orders-at-alpaca]`. An order can be canceled via API up until
it reaches `filled`/`canceled`/`expired`.

**Non-terminal / in-flight:** `NEW, ACCEPTED, PENDING_NEW, ACCEPTED_FOR_BIDDING, PENDING_REVIEW,
PARTIALLY_FILLED, HELD, CALCULATED` (keep polling; for limit orders, apply the timeout).

`[CITED: forum.alpaca.markets partially-filled]` A `partially_filled` order that is then canceled
comes back as `canceled` with `filled_qty > 0` — the resolver should treat `filled_qty > 0` as a
genuine (partial) position even on a `canceled` terminal state. For this phase (Decision 1) map:
`filled_qty >= qty` → `open` position; `filled_qty == 0` + terminal → non-position terminal status;
`0 < filled_qty < qty` + terminal → **position** (`open`) sized to `filled_qty` (Phase 12 handles
the P&L math; this phase just must not drop it).

**Note:** `_parse_order` already extracts `filled_qty` and `filled_avg_price` — persist these too so
Phase 12 has fill data without another API round-trip.

## Architecture Patterns

### System Architecture Diagram

```
BotThread._scan_loop  (every CYCLE_SLEEP_SECONDS)
  │
  ├─ [NEW] _resolve_pending_orders()      ◄── runs FIRST each cycle, and once at startup
  │     │   SELECT id, order_id, symbol, qty, side, timestamp
  │     │   FROM alpaca_trades WHERE bot_id=? AND status='submitted'
  │     │
  │     ├─ for each pending row:
  │     │     order = alpaca.get_order(order_id)          # TradingClient.get_order_by_id
  │     │     status = order["status"]
  │     │     ├─ filled / partial(done, filled_qty>0)  → update status='open'  (becomes position)
  │     │     ├─ canceled/expired/rejected             → update status=<terminal>, pnl=0
  │     │     ├─ still open + limit + age>timeout       → cancel_order(order_id) → status='canceled'
  │     │     └─ still open + within timeout            → leave 'submitted' (re-poll next cycle)
  │     └─ (order_id missing / get_order 404) → status='rejected', pnl=0   (no silent drop)
  │
  ├─ technical scan → risk gate → size
  └─ submit order:
        order = alpaca.place_market_order(...)   # or place_limit_order
        log_alpaca_trade({..., order_id=order["order_id"],
                          status='submitted',
                          filled_qty, filled_avg_price})
        (on exception → log_alpaca_trade({..., status='rejected', pnl=0}))

PositionMonitor (unchanged)  ── resolves status='open' rows against live Alpaca positions
```

### State machine (the contract)

```
                 submit ok            fill (get_order)
   [submit] ──────────────► submitted ─────────────────► open  ──(PositionMonitor)──► closed/stopped
      │                        │  cancel/expire/reject         (Phase 12 = realized P&L)
      │ submit raises          │  or limit timeout→cancel
      ▼                        ▼
   rejected  ◄────────────  canceled / expired / rejected   (terminal, pnl=0, non-position)
```

- `submitted` — **NEW pre-terminal status.** Row has `order_id`, not yet a position, invisible to
  `PositionMonitor` (which queries `status='open'`).
- `open` — genuine held position (post-fill). Monitor owns exit.
- `canceled` / `expired` / `rejected` — **NEW terminal non-position statuses.** `pnl=0`, excluded
  from open-position queries and from win/loss accuracy.
- `closed` / `stopped` / `target_hit` — unchanged, mean "position closed with realized P&L".

### Idempotency & crash safety

- Resolution reads pending rows **from the DB** every cycle → a restarted process re-polls all
  in-flight `submitted` orders. No in-memory queue.
- Re-polling a row already moved off `submitted` is impossible (the SELECT filters `status='submitted'`)
  → naturally a no-op. Guard the UPDATE with `WHERE status='submitted'` for a belt-and-suspenders
  compare-and-set against concurrent monitor writes.
- `order_id` UNIQUE-ish per bot: the same Alpaca order maps to one row; resolving twice is safe.

### Recommended placement — `BotThread` loop, NOT `PositionMonitor`

`PositionMonitor` is a fast (60s) *position*-exit loop reasoning about live holdings; order
resolution is a slower cycle-cadence *pre-position* concern that must re-poll from the DB on
restart. Keeping them separate preserves the CONTEXT boundary ("`PositionMonitor` stays responsible
for *position* exits"). Add `_resolve_pending_orders()` called at the top of `_scan_loop` (before the
technical scan) in `src/bot_thread.py` (scan loop wait at L360), and once immediately after
`monitor.start()` (L284) so a crashed-mid-cycle bot resolves in-flight orders before doing new work.

### Anti-Patterns to Avoid

- **Overloading `closed`** for unfilled orders — pollutes win/loss stats and realized-P&L sums
  (this is the current monitor bug). Use the new terminal statuses.
- **In-memory pending-order list** — lost on restart; violates Decision 4. Drive off the DB.
- **Blocking wait for fill inside submit** — don't `sleep`-poll a limit order to fill inside the
  submission call; return to the loop and let the next resolver pass handle it (crash-safe).
- **Silent `except`** on submit — must write a `rejected` row (Decision 5).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Single-order status fetch | Custom REST call | `TradingClient.get_order_by_id` (wrap as `AlpacaClient.get_order`) | SDK handles auth/retry/parsing |
| Order cancel | Custom REST | existing `AlpacaClient.cancel_order` | Already present (`cancel_order_by_id`) |
| Open-order list | Custom REST | existing `AlpacaClient.get_open_orders` | Already present |
| Terminal-state classification | String guessing | `OrderStatus` enum terminal set | Alpaca-defined, stable |

## Schema Change (exact)

**Next migration number:** latest present is `014_intraday_learning_dims.sql` (two `009_*` exist but
max is 014) → **`dashboard/api/migrations/015_order_state_resolution.sql`**. Mirror in
`src/db_schema.sql` (the `alpaca_trades` DDL, L20-40).

Required, additive (nullable — safe on existing rows):

```sql
-- 015_order_state_resolution.sql  (idempotent, additive)
ALTER TABLE alpaca_trades ADD COLUMN IF NOT EXISTS order_id         TEXT;
ALTER TABLE alpaca_trades ADD COLUMN IF NOT EXISTS filled_qty       DOUBLE PRECISION;
ALTER TABLE alpaca_trades ADD COLUMN IF NOT EXISTS filled_avg_price DOUBLE PRECISION;
CREATE INDEX IF NOT EXISTS idx_alpaca_trades_bot_order ON alpaca_trades (bot_id, order_id);
-- pending-resolution lookup (partial index on the hot 'submitted' path)
CREATE INDEX IF NOT EXISTS idx_alpaca_trades_pending
  ON alpaca_trades (bot_id, status) WHERE status = 'submitted';
```

- `closed_at` **already exists** (schema L37) — no add needed; extend `update_alpaca_trade`'s
  `closed_at` trigger set to include the new terminal statuses (see below).
- `status` is free-text `TEXT DEFAULT 'open'` (no enum/CHECK) → new status strings need **no**
  constraint change. The `bot_id` CHECK was already dropped (`009_drop_bot_id_check.sql`) so C/D work.

**`src/db.py` changes:**
- `log_alpaca_trade`: add `order_id`, `filled_qty`, `filled_avg_price`, and accept an explicit
  `status` (default `'submitted'`) to the INSERT column list.
- `update_alpaca_trade`: broaden the `closed_at` set to
  `status in ("closed","stopped","target_hit","canceled","expired","rejected")` (L102-106) so
  terminal order states get a resolution timestamp.
- Add a `get_pending_alpaca_orders(bot_id)` → `SELECT ... WHERE bot_id=%s AND status='submitted'`.
- `get_open_alpaca_positions` (status='open') is unchanged and now correctly excludes `submitted`.

## Common Pitfalls

### Pitfall 1: `submitted` rows counted as open positions for dedup/exposure
**What goes wrong:** existing dedup / exposure logic (`bot_thread.py` L413,
`get_open_alpaca_positions`) counts only `status='open'`. A `submitted` (in-flight) order is now
invisible to that count → the bot could double-submit the same symbol before the order fills.
**How to avoid:** include `submitted` rows in the pre-submit dedup/exposure check (query both
`open` and `submitted`), OR run `_resolve_pending_orders()` first each cycle so most fills promote to
`open` before the scan. Recommend both.
**Warning signs:** two rows for the same symbol within one cycle.

### Pitfall 2: partial fills dropped
**What goes wrong:** `partially_filled` then canceled returns `canceled` with `filled_qty>0`;
naively mapping `canceled`→non-position loses a real position.
**How to avoid:** branch on `filled_qty>0` → treat as `open` position regardless of terminal label.

### Pitfall 3: market orders that "instantly fill" still need a poll
**What goes wrong:** assuming market orders are always `filled` at submit and writing `open`
directly re-introduces silent drops on the reject path.
**How to avoid:** always write `submitted` + `order_id`; let the resolver classify — even a
same-cycle poll will read `filled` immediately for a good market order.

### Pitfall 4: limit-order timeout races the cancel
**What goes wrong:** you decide to cancel a stale limit order, but it fills between your decision and
the `cancel_order` call; `cancel_order` returns failure and you mislabel the row `canceled`.
**How to avoid:** after `cancel_order`, re-`get_order` and classify on the *fresh* status
(fill wins over cancel). Never assume the cancel succeeded.

## Code Examples

### Add single-order fetch (src/alpaca_client.py)
```python
# Source: alpaca.markets/sdks/python/api_reference/trading — TradingClient.get_order_by_id
def get_order(self, order_id: str) -> dict:
    """Fetch a single order by Alpaca order id (for lifecycle resolution)."""
    order = _retry(self._trading_client.get_order_by_id, order_id=order_id)
    return self._parse_order(order)   # already returns status, filled_qty, filled_avg_price
```

### Resolver classification (conceptual, in bot_thread)
```python
TERMINAL_NONPOSITION = {"canceled", "expired", "rejected"}

def _classify(order: dict, row: dict, limit_timeout_reached: bool) -> tuple[str, float | None]:
    status = order["status"].lower()          # str(OrderStatus) -> e.g. 'OrderStatus.FILLED'
    status = status.split(".")[-1]            # normalize enum-repr to bare value
    filled = order.get("filled_qty", 0) or 0
    if status == "filled" or filled > 0:
        return "open", None                   # genuine (possibly partial) position
    if status in TERMINAL_NONPOSITION:
        return status, 0.0                    # terminal, pnl=0
    if limit_timeout_reached:                 # resting limit past window -> cancel then re-check
        return "cancel-then-recheck", None
    return "submitted", None                  # still in flight, re-poll next cycle
```

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `alpaca_trades` rows with `status='open'` that are really unfilled/never-position (the audit's stuck rows) | **None this phase** — backfill is Phase 14 (PNL-05). Phase 11 fixes forward mechanism only. |
| Live service config | Alpaca open orders resting on the broker (per-bot paper accounts) not tracked in DB | Forward: resolver cancels stale limits. Existing resting orders = Phase 14 concern. |
| OS-registered state | None — resolution is in-process (BotThread), no cron/scheduler | None |
| Secrets/env vars | New config key for limit-timeout (e.g. `LIMIT_ORDER_TIMEOUT_S`, default = profile `scan_interval_s`) — additive, per orchestrator service | Add to Coolify env per bot; default is safe if unset |
| Build artifacts | None | None |

**Migration deploy note:** `015_*.sql` must run against the shared Coolify Postgres before the new
code deploys (columns referenced by INSERT). Additive/nullable → safe, no data rewrite, no DROP.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing `tests/` suite, e.g. `test_risk_*.py`) |
| Config file | none dedicated — pytest discovery on `tests/` |
| Quick run command | `python -m pytest tests/test_order_resolution.py -x -q` |
| Full suite command | `python -m pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PNL-01 | Submitted market order that fills → row `open` with `order_id` | unit | `pytest tests/test_order_resolution.py::test_filled_becomes_open -x` | ❌ Wave 0 |
| PNL-01 | Canceled order → terminal `canceled`, pnl=0, not `open`/`closed` | unit | `pytest tests/test_order_resolution.py::test_canceled_terminalizes -x` | ❌ Wave 0 |
| PNL-01 | Rejected order → terminal `rejected`, pnl=0 | unit | `pytest tests/test_order_resolution.py::test_rejected_terminalizes -x` | ❌ Wave 0 |
| PNL-01 | Submit raises exception → row written `rejected` (no silent drop) | unit | `pytest tests/test_order_resolution.py::test_submit_exception_records_rejected -x` | ❌ Wave 0 |
| PNL-01 | Partial fill then canceled (`filled_qty>0`) → `open` position, not dropped | unit | `pytest tests/test_order_resolution.py::test_partial_fill_kept -x` | ❌ Wave 0 |
| PNL-04 | Resting limit unfilled past timeout → `cancel_order` called, row `canceled` | unit | `pytest tests/test_order_resolution.py::test_limit_timeout_cancels -x` | ❌ Wave 0 |
| PNL-04 | Restart re-polls `submitted` rows from DB (crash-safe) | integration | `pytest tests/test_order_resolution.py::test_restart_repolls_pending -x` | ❌ Wave 0 |
| PNL-04 | Re-running resolver on terminal row = no-op (idempotent) | unit | `pytest tests/test_order_resolution.py::test_resolver_idempotent -x` | ❌ Wave 0 |
| PNL-01/04 | Simulated unfilled limit order reaches a terminal state end-to-end | integration | `pytest tests/test_order_resolution.py::test_unfilled_limit_terminalizes_e2e -x` | ❌ Wave 0 |

Use a fake `AlpacaClient` (mock `get_order`/`cancel_order`/`place_*_order` returning scripted
`_parse_order`-shaped dicts) against a test Postgres (or the existing DB test fixture) — no live
Alpaca calls. Assert on `alpaca_trades.status`, `order_id`, `pnl`, `closed_at`.

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_order_resolution.py -x -q`
- **Per wave merge:** `python -m pytest -q`
- **Phase gate:** full suite green + a live/paper smoke run showing a submitted order reaching a
  terminal state (resolution-rate spot check) before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_order_resolution.py` — all cases above (covers PNL-01, PNL-04)
- [ ] Test fixture: fake AlpacaClient with scriptable order-status sequence
- [ ] Test fixture: isolated `alpaca_trades` rows (reuse existing DB test setup if present)

## Security Domain

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | yes | `order_id` treated as opaque string from Alpaca; parameterized SQL (psycopg `%s`) — already used |
| V6 Cryptography | no | No crypto/secrets introduced; Alpaca keys already in Coolify env |
| V2/V3/V4 | no | No auth/session/access-control surface in this phase |

| Pattern | STRIDE | Mitigation |
|---------|--------|------------|
| SQL injection via order_id/status | Tampering | Parameterized queries only (existing `src/db.py` pattern) |
| Mis-attributed P&L inflating stats | Repudiation | Terminal non-position statuses excluded from win/loss + P&L sums |

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Log `open` at submit, resolve only via live positions | Persist `order_id`, poll order lifecycle to terminal state | Unfilled/canceled/rejected orders resolve → ~100% resolution |
| Polling order status | (future) trade-update websocket stream | Deferred; polling sufficient at 30-min/2-min scan cadence |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `str(OrderStatus.FILLED)` renders as `'OrderStatus.FILLED'` (needs `.split('.')[-1]` normalize); `_parse_order` does `str(getattr(order,'status'))` | Code Examples | Low — classification uses substring/lower; verify actual repr in first test |
| A2 | Crypto market orders can be `rejected`/partially fill (not always instant `filled`) | Root Cause | Low — must handle regardless per Decision 5 |
| A3 | Limit-timeout default = profile `scan_interval_s` is sensible | Secrets/env | Low — config-driven, reversible |

## Open Questions

1. **Should `submitted` rows count toward per-cycle dedup/exposure immediately?**
   - Known: current dedup counts only `status='open'`.
   - Recommendation: yes — include `submitted` in the pre-submit check to prevent double-submits;
     confirm with planner (small query change).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| alpaca-py | order poll/cancel | ✓ (project dep) | 0.43.2 | — |
| Postgres (Coolify) | schema migration | ✓ | — | — |
| Alpaca paper accounts A–D | live smoke test | ✓ (per-bot) | — | mock in unit tests |

## Sources

### Primary (HIGH)
- `src/bot_thread.py`, `src/alpaca_client.py`, `src/alpaca_orchestrator.py`, `src/db.py`,
  `src/db_schema.sql`, `dashboard/api/migrations/` — codebase (VERIFIED root cause + schema)
- [docs.alpaca.markets — Orders at Alpaca](https://docs.alpaca.markets/us/docs/orders-at-alpaca) — terminal states
- [alpaca-py trading API reference](https://alpaca.markets/sdks/python/api_reference/trading/orders.html) — `get_order_by_id`, `OrderStatus`
- [alpaca-py enums reference](https://alpaca.markets/sdks/python/api_reference/trading/enums.html) — `OrderStatus` values

### Secondary (MEDIUM)
- [Alpaca forum — partially filled returned as canceled](https://forum.alpaca.markets/t/partially-filled-order-returned-as-canceled-in-get-all-orders-api/18610) — partial-fill terminal behavior

## Metadata

**Confidence breakdown:**
- Root cause: HIGH — verified directly in code
- Schema/migration path: HIGH — schema + migrations dir read, additive/nullable
- Alpaca order lifecycle: HIGH — official docs + SDK reference
- Architecture placement: HIGH — matches CONTEXT boundary + existing loop structure

**Research date:** 2026-07-09
**Valid until:** ~2026-08-09 (stable; alpaca-py pinned)

## RESEARCH COMPLETE
</content>
</invoke>
