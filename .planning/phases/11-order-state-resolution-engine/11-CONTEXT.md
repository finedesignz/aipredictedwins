# Phase 11 — Order-State Resolution Engine — CONTEXT

*Milestone v1.1 · captured 2026-07-09 · mode: --auto (YOLO, decisions auto-selected)*

## Domain

Every order a bot submits must reach a **recorded terminal state**. Today a trade row is written
with status `open` at submission time; it is only ever moved off `open` when `PositionMonitor`
later closes a live Alpaca *position*. Any order that does not become a held position — an unfilled
or partially-filled limit order, a canceled/rejected/expired order — leaves a permanently-`open`
row that never resolves. The 2026-07-06 audit measured this: only ~30 of ~300 submitted orders per
bot resolve. This phase fixes the resolution mechanism so the log reflects reality.

**Requirements owned:** PNL-01 (every order → terminal state, no silent drops), PNL-04 (root-cause
fix so resolution rate ≈100% going forward). PNL-02 (realized-P&L-from-fills) is Phase 12;
PNL-05 (backfill of existing stale rows) is Phase 14 — **out of scope here**, this phase fixes the
forward mechanism only.

## Root cause (from code scout — confirms the audit)

- `src/bot_thread.py` logs the trade immediately after `place_limit_order`/`place_market_order`
  with the order's `status` ("submitted"/"accepted"), and the DB row lands as `status='open'`
  (lines ~698, ~890). No fill confirmation is required.
- `src/alpaca_client.py` `place_limit_order` returns as soon as the order is *submitted*; a limit
  order that never crosses is left resting. There is `get_open_orders` / `cancel_order` machinery
  but the bot loop does not reconcile submitted orders against fills.
- `PositionMonitor` (in the alpaca path) resolves rows by watching live *positions*
  (`get_open_alpaca_positions` → DB `status='open'`). No position ever exists for an unfilled
  order, so that row is unreachable and stays `open` forever.

## Decisions (locked — auto-selected recommended defaults)

1. **Introduce an explicit order-lifecycle poll.** After submission, the owning bot loop (or a
   dedicated resolver pass in `bot_thread`) polls the order via `get_order`/`get_open_orders`
   until it reaches an Alpaca terminal order state (`filled`, `partially_filled`+done, `canceled`,
   `expired`, `rejected`). The DB row transitions accordingly:
   - `filled` → row becomes a real open **position** (stays `open`, now genuinely held; Phase 12
     computes realized P&L on close).
   - `canceled`/`expired`/`rejected`/unfilled-at-timeout → row moves to a terminal
     **non-position** status (new status value, e.g. `canceled`) with `pnl=0` — never left `open`.
2. **New terminal statuses, additive.** Add distinct terminal states for orders that never became
   positions so they are excluded from "open position" queries and from win/loss stats. Do NOT
   overload `closed` (which means "position closed with P&L"). Migration is a numbered SQL file —
   next free `dashboard/api/migrations/NNN_*.sql` (check the dir for the next number) AND the
   `src/db_schema.sql` mirror if the trades table is defined there. **Not alembic.**
3. **Unfilled-limit timeout.** A resting limit order that has not filled within a bounded window
   (config, default aligned to the scan cadence — e.g. cancel-and-mark after one scan cycle) is
   canceled via `cancel_order` and its row terminalized. This both frees capital and resolves the
   row. Threshold is env/config-driven and reversible.
4. **Idempotent + crash-safe.** Resolution keyed on the Alpaca `order_id` (persist it on the row).
   A restarted bot must be able to re-poll in-flight orders from the DB, so `order_id` must be
   stored at submission. Re-running resolution on an already-terminal row is a no-op.
5. **No silent drops.** Every submission path (long entry, short entry, and any exit order) writes
   a row with `order_id` and is subject to resolution. Rejections/exceptions during submit are
   logged AND recorded as a terminal `rejected` row, never dropped.
6. **Scope discipline.** This phase changes *when/how rows reach a terminal state*. It does NOT
   recompute historical P&L (Phase 12), does NOT backfill existing stuck rows (Phase 14), and does
   NOT touch the universe gate (Phase 15).

## Canonical refs (full paths — MANDATORY reading for research/plan)

- `.planning/REQUIREMENTS.md` — PNL-01, PNL-04 (and the audit baseline).
- `.planning/PROJECT.md` — "Current Milestone: v1.1" audit evidence.
- `CLAUDE.md` (repo) — numbered-SQL-migration rule, one-account-per-bot, live path = BotThread +
  PositionMonitor.
- `src/bot_thread.py` — submission + logging sites (~L660–900), monitor startup (~L281).
- `src/alpaca_client.py` — `place_market_order`, `place_limit_order`, `get_open_orders`,
  `cancel_order`, `get_order` (if present), `_parse_order` (~L296–430).
- `src/trade_logger.py` — `log_alpaca_trade`, `update_alpaca_trade`, `get_open_alpaca_positions`.
- `src/db.py` + `src/db_schema.sql` — trades table schema + `update_alpaca_trade` SQL.
- `dashboard/api/migrations/` — location + numbering for the schema migration.

## Code context (reusable assets)

- Order plumbing already exists: `get_open_orders`, `cancel_order`, `_parse_order` in
  `alpaca_client.py` — extend, don't reinvent. Add a `get_order(order_id)` if missing.
- `trade_logger.update_alpaca_trade(trade_id, status, exit_price, pnl)` is the existing mutation
  point — the resolver calls it; may need to persist/lookup `order_id`.
- `PositionMonitor` stays responsible for *position* exits; this phase is about *order* resolution
  up to the point a fill becomes a position.

## Deferred ideas (not this phase)

- Realized P&L from actual fills incl. fees — Phase 12 (PNL-02).
- Reconciliation vs Alpaca account P&L — Phase 13 (PNL-03).
- Backfill/repair of existing stale `open` rows — Phase 14 (PNL-05).
- Websocket/trade-update stream instead of polling — note for a future optimization; polling is
  sufficient and simpler for the current scan cadence.
