# Phase 14 — Stale-Trade Backfill & Repair — CONTEXT

*Milestone v1.1 · captured 2026-07-10 · mode: --auto (YOLO, decisions auto-selected)*

## Domain

Phases 11–12 fixed the **forward** mechanism (orders resolve; closed trades carry fill-based P&L).
The historical log is still polluted: ~90% of legacy rows are stuck non-terminal (`open`/`submitted`)
from before the fix. This phase is a **one-shot, idempotent backfill script** that walks those
stale rows and resolves each against Alpaca order/position history, writing realized P&L via the
Phase-12 path, and reports counts (resolved / unresolvable / unchanged).

**Requirement owned:** PNL-05.

## Grounding (from code scout)

- `src/alpaca_client.py::get_order(order_id)` (L401-404) fetches ANY order by id via
  `get_order_by_id` regardless of status → gives the entry order's current terminal state +
  `filled_avg_price`/`filled_qty` (reuse for entry resolution, same as Phase 11).
- `get_open_orders` (L406) uses `GetOrdersRequest(status=QueryOrderStatus.OPEN)`. A **CLOSED**-status
  query (`GetOrdersRequest(status=QueryOrderStatus.CLOSED, symbols=[...])`) is the mechanism to find
  the *closing* order for a filled entry whose position is no longer open — the researcher must
  confirm the exact request shape + how to match it to the entry (symbol + side opposite + time
  after entry).
- Phase 11 gave `db.get_pending_alpaca_orders` (submitted rows) and the resolver classification;
  Phase 12 gave the pure `src/pnl.py::realized_pnl(side, entry_fill, exit_fill, qty, taker_fee)`
  helper and the `fees` column. **Reuse both** — do not reimplement resolution or P&L math.
- Terminal position-closed statuses in use: `closed`/`stopped`/`target_hit` (Phase 13 finding);
  non-position terminals: `canceled`/`rejected`/`expired` (pnl=0).

## Decisions (locked — auto-selected recommended defaults)

1. **One-shot script, not a runtime loop.** `scripts/backfill_trades.py` (matches the
   `scripts/reconcile.py` / `scripts/check_trades.py` convention). Read-mostly against Alpaca;
   writes only resolved rows via the existing `update_alpaca_trade` / Phase-12 close path. Per-bot
   Alpaca account keys (never bare/shared) — same sourcing the Phase-13 driver uses.
2. **Candidate set = genuinely stale rows.** Select `alpaca_trades` rows in a non-terminal state
   (`status IN ('open','submitted')`) with an `order_id`, older than a small guard window (avoid
   racing live in-flight orders — e.g. entry timestamp older than N minutes, config-driven). Rows
   without an `order_id` (pre-Phase-11 legacy) are **unresolvable** — count + report, never guess.
3. **Resolution ladder per row (reuse Phase 11 + 12):**
   - `get_order(order_id)` → entry order terminal state.
   - Entry `canceled`/`rejected`/`expired`, 0 filled → terminal non-position status, pnl=0.
   - Entry `filled`/partially-filled: it became a position. Check current live positions; if still
     open → leave `open` (genuinely held; not stale) and count **unchanged**. If no longer open →
     find the closing order via the CLOSED-status query; if found, compute realized P&L with
     `pnl.realized_pnl(entry_fill, exit_fill, filled_qty, TAKER_FEE)` and write
     `status='closed'`, `exit_price=exit_fill`, `pnl`, `fees` via the Phase-12 update path.
   - Closing order not findable in Alpaca history → **unresolvable** (report, leave unchanged).
4. **Idempotent.** Re-running changes nothing: only rows still in the candidate stale set are
   touched; already-terminal rows are skipped. Keyed on `order_id`. Safe to run repeatedly.
5. **Report counts.** The script prints and logs `resolved / unresolvable / unchanged` totals per
   bot and overall, plus the irreducible residue (no order_id or no Alpaca history) — success
   criterion 3.
6. **Dry-run by default.** `--apply` flag to actually write; default lists what WOULD change
   (safe on a live DB). Reversible/inspectable before mutating historical rows.

## Scope discipline (fences)

- Does NOT change the forward resolver (Phase 11) or the P&L formula (Phase 12) — reuses them.
- Does NOT reconcile against account totals (Phase 13) — though after backfill the Phase-13 delta
  should shrink (a nice side effect, not this phase's assertion).
- Does NOT touch universe (Phase 15) or retune (Phase 18); risk invariants untouched.
- No schema change expected (columns from 011/016 suffice). If any is needed it is the next number
  `018_*.sql`, additive/idempotent, mirrored — but prefer none.

## Canonical refs (MANDATORY reading for research/plan)

- `.planning/REQUIREMENTS.md` — PNL-05.
- `src/alpaca_client.py` — `get_order` (L401), `get_open_orders`/`GetOrdersRequest` (L406), close.
- `src/pnl.py` — `realized_pnl` (Phase 12 helper to reuse).
- `src/bot_thread.py` — Phase-11 `_classify`/`_resolve_pending_orders` (resolution logic to reuse).
- `src/db.py` / `src/trade_logger.py` — `update_alpaca_trade` (fees kwarg), `get_pending_alpaca_orders`,
  a stale-row query to add; how to enumerate rows per bot.
- `scripts/reconcile.py`, `scripts/check_trades.py` — entrypoint + per-bot key sourcing convention.
- CLAUDE.md — numbered migration rule, one-account-per-bot, NEVER delete/reset DB rows.

## Deferred ideas (not this phase)

- Alpaca account **activities** feed (fills/fees ledger) for exact historical fees — use TAKER_FEE
  estimate consistent with Phase 12 unless the activities feed proves easy; revisit in Phase 20.
- Backfilling pre-`order_id` legacy rows via fuzzy symbol/time matching — too lossy; leave as
  reported residue.
