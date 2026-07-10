# Phase 13 — Alpaca Reconciliation Check — CONTEXT

*Milestone v1.1 · captured 2026-07-10 · mode: --auto (YOLO, decisions auto-selected)*

## Domain

The dashboard's headline P&L is trusted only if the summed trade-log realized P&L matches what
Alpaca actually booked. This phase adds a **reconciliation routine** that, per bot, compares
`sum(trade-log realized P&L)` against the bot's Alpaca account realized P&L and, when the delta
exceeds a tolerance, logs it and writes a reconciliation flag (consumed by the dashboard in
Phase 19).

**Requirement owned:** PNL-03.

## Grounding (from code scout)

- `src/alpaca_client.py::get_account` (L122-136) returns `equity`, `portfolio_value`, `cash`.
- `get_positions` (L140-155) returns each open position's `unrealized_pnl`.
- Alpaca has **no direct "realized P&L" field.** Derive it:
  `alpaca_realized_pnl = (equity − starting_equity) − sum(unrealized_pnl of open positions)`.
- `starting_equity` per bot lives on the `bots` table (`src/db_schema.sql` L11,
  `DOUBLE PRECISION NOT NULL DEFAULT 100000.0`) — the reconciliation baseline. Do NOT hardcode
  100000; read the bot's row.
- Trade-log realized P&L = `sum(pnl)` over `alpaca_trades` rows in a terminal *position-closed*
  state for that bot — the Phase-12-corrected `pnl`. **CORRECTED (research):** the position-closed
  set is `status IN ('closed','stopped','target_hit')` (all carry real pnl), NOT `'closed'` alone —
  `db.get_alpaca_accuracy` and `equity.py::_build_db_series` already use this three-state set;
  summing `'closed'` alone drops every stop/target exit and falsely breaches. Add
  `db.get_realized_pnl(bot_id)` over the three states. Non-position terminal rows
  (canceled/rejected/expired) have pnl=0 and are naturally excluded.
- One Alpaca account per bot (hard rule) — reconcile each bot against its own account.

## Decisions (locked — auto-selected recommended defaults)

1. **Reconciliation routine.** New `src/reconciliation.py` with a pure comparison helper
   `reconcile_bot(trade_log_pnl, equity, starting_equity, unrealized_pnl, tolerance)` returning a
   small result object `{trade_log_pnl, alpaca_realized_pnl, delta, within_tolerance, tolerance}`.
   A thin driver assembles the inputs from `TradeLogger`/`AlpacaClient` per bot. The math helper is
   unit-testable to the cent, independent of live API.
2. **Tolerance is config/env-driven.** `RECONCILIATION_TOLERANCE_USD` (env, sensible default e.g.
   `25.0` absolute dollars; optionally a pct floor). Reversible, no code change to retune.
3. **Persist a reconciliation flag.** Add a `reconciliation` table (or a small set of columns) that
   records the latest per-bot result: `bot_id, checked_at, trade_log_pnl, alpaca_realized_pnl,
   delta, within_tolerance, tolerance`. Migration is the next numbered SQL file —
   **`017_reconciliation.sql`** (015=Phase11, 016=Phase12) — additive/idempotent
   (`CREATE TABLE IF NOT EXISTS`), mirrored in `src/db_schema.sql`. **Not alembic.** The dashboard
   headline consumes this in Phase 19 (out of scope here — this phase only writes it + a log line).
4. **Log on breach.** When `within_tolerance` is false, emit a WARNING via the existing logger and
   (optionally) the existing notifier/alerter path — reuse, do not invent a new channel. Within
   tolerance → INFO.
5. **Runnable per-bot check.** Provide a small entrypoint (script/CLI, e.g.
   `scripts/reconcile.py` or a `python -m` hook) that runs the check against the two live paper
   accounts and prints a per-bot delta + pass/fail line (success criterion 3). Read-only against
   Alpaca; writes only the reconciliation flag row.

## Scope discipline (fences)

- Does NOT change how P&L is computed (Phase 12) or how orders resolve (Phase 11).
- Does NOT backfill stale rows (Phase 14).
- Does NOT render anything on the dashboard — Phase 19 consumes the flag. This phase only computes,
  logs, and persists it.
- Does NOT touch universe (Phase 15) or retune (Phase 18); risk invariants untouched.

## Canonical refs (MANDATORY reading for research/plan)

- `.planning/REQUIREMENTS.md` — PNL-03.
- `.planning/phases/13-alpaca-reconciliation-check/` — this CONTEXT.
- `src/alpaca_client.py` — `get_account` (L122), `get_positions` (L140).
- `src/trade_logger.py` / `src/db.py` — how to sum closed-trade `pnl` per bot; `bots` row
  `starting_equity`; existing per-bot query patterns.
- `src/db_schema.sql` — `bots` table (L11), `alpaca_trades`; where to mirror the new table.
- `dashboard/api/migrations/` — numbering (next free = `017`), `run_migrations.py`.
- `src/notifier.py` / `src/alerter.py` — existing alert channel to reuse on breach.
- CLAUDE.md — numbered-migration rule, one-account-per-bot.

## Deferred ideas (not this phase)

- Historical time-series of reconciliation deltas — only the latest per bot for now.
- Alpaca `portfolio_history` / activity-feed based realized P&L — equity-minus-unrealized is
  sufficient and simpler for paper; revisit if it proves inaccurate in Phase 20 E2E.
