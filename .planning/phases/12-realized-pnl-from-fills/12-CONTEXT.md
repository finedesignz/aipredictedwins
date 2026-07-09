# Phase 12 — Realized P&L From Fills — CONTEXT

*Milestone v1.1 · captured 2026-07-09 · mode: --auto (YOLO, decisions auto-selected)*

## Domain

Every closed trade must record realized P&L computed from **actual fill prices and quantities,
net of fees/slippage** — never the intended/limit/quote price. Phase 11 fixed *when* a row reaches
a terminal state; this phase fixes *what number* the close writes into `pnl` and `exit_price`.

**Requirement owned:** PNL-02.

## Root cause (from code scout — confirmed)

- `src/alpaca_orchestrator.py` `PositionMonitor._check_positions` (L204-211) computes
  `trade_pnl = (current_price - entry_price) * qty` (side-aware) using **`current_price`**, a live
  quote fetched for the threshold ladder — NOT the price the position actually closed at.
- The close itself (`self.alpaca.close_position(symbol)`, L289) **returns a dict containing the
  real exit `filled_avg_price`** (see `alpaca_client.close_position` → `_parse_order`, L382/L432)
  but the return value is discarded.
- The stored `exit_price` is set to `current_price` (L293), again the quote, not the fill.
- **Entry** uses the DB `entry_price` (the target/limit), even though Phase 11 now persists the
  entry `filled_avg_price` on the row — so both legs of the P&L can and should come from fills.
- **No fees are deducted.** `src/fee_gate.py` already defines `TAKER_FEE` and `SLIPPAGE_BUFFER`
  (imported in `bot_thread.py` L61) — the same constants must be applied to realized P&L so the
  logged number matches what Alpaca actually books (prep for the Phase 13 reconciliation).

## Decisions (locked — auto-selected recommended defaults)

1. **Realized P&L = fills, both legs, net of fees.** On close, compute
   `realized_pnl = (exit_fill - entry_fill) * filled_qty  (side-aware) − fees`, where:
   - `entry_fill` = the row's persisted `filled_avg_price` (Phase 11 column); fall back to
     `entry_price` only if the fill price is missing/zero (legacy rows), and log when it does.
   - `exit_fill` = `filled_avg_price` from the `close_position()` return dict; fall back to the
     live `current_price` only if the close dict lacks a fill price, and log the fallback.
   - `fees` = `TAKER_FEE` applied to **both** entry and exit notional
     (`entry_fill*qty + exit_fill*qty) * TAKER_FEE`), reusing `src/fee_gate.py` constants. Slippage
     is already captured by using real fills, so do not double-count `SLIPPAGE_BUFFER` in the P&L.
2. **Store the real exit fill as `exit_price`.** `update_alpaca_trade` is called with
   `exit_price = exit_fill` (not the quote) and `pnl = realized_pnl`.
3. **Persist fees for reconciliation.** Add a `fees` REAL/NUMERIC column so Phase 13 can reconcile
   gross vs net. Migration is the next numbered SQL file — **`016_realized_pnl_fees.sql`**
   (015 is taken by Phase 11) — additive/idempotent `ADD COLUMN IF NOT EXISTS fees`, mirrored in
   `src/db_schema.sql`. **Not alembic.** `exit_price`/`pnl` columns already exist.
4. **Single source of truth for the math.** Put the realized-P&L computation in one small pure
   helper (e.g. `src/pnl.py::realized_pnl(side, entry_fill, exit_fill, qty, taker_fee)`) so it is
   unit-testable to the cent and reused anywhere close-P&L is computed (Phase 14 backfill will
   reuse it). The monitor calls the helper; it does not inline the arithmetic.
5. **No silent behavior change to exits.** The exit *trigger* ladder (hard_stop/max_hold/ATR) is
   untouched — only the P&L *number* and `exit_price` written on close change. `total_pnl`
   accumulation continues to use the new realized figure.

## Scope discipline (fences)

- Does NOT re-check order resolution (Phase 11) or recompute historical rows (Phase 14 backfill).
- Does NOT reconcile against Alpaca account P&L (Phase 13).
- Does NOT touch the universe gate (Phase 15) or retune thresholds (Phase 18).
- Hardcoded risk invariants (max 5%/pos, quarter-Kelly 0.25, 20% DD stop) are untouched.

## Canonical refs (MANDATORY reading for research/plan)

- `.planning/REQUIREMENTS.md` — PNL-02 + audit baseline.
- `src/alpaca_orchestrator.py` — `PositionMonitor` P&L computation (~L200-300, close at L287-300).
- `src/alpaca_client.py` — `close_position` (L382) + `_parse_order` (`filled_avg_price` L432).
- `src/fee_gate.py` — `TAKER_FEE`, `SLIPPAGE_BUFFER`.
- `src/db.py` — `update_alpaca_trade` (L101-120, sets exit_price/pnl/closed_at), `log_alpaca_trade`
  (persists entry `filled_avg_price`), `src/db_schema.sql` mirror.
- `dashboard/api/migrations/` — numbering (next free = `016`), `run_migrations.py`.

## Deferred ideas (not this phase)

- Per-leg fee/slippage attribution beyond a single `fees` total — only if Phase 13 needs it.
- Funding/borrow costs for shorts — crypto paper shorts don't accrue; revisit if live.
