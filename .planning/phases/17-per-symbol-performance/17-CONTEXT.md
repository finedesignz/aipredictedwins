# Phase 17 — Per-Symbol Performance Analysis — CONTEXT

*Milestone v1.1 · captured 2026-07-12 · mode: --auto (YOLO, decisions auto-selected)*

## Domain

The 2026-07-06 audit asserted winners (UNI, ADA, SOL, XRP, CRV) and losers (BTC 0-for-12 −$479,
AVAX, TRUMP, FIL) — but that claim was made against a trade log that was **not trustworthy**:
orders were never re-checked (open-but-stale rows), P&L was estimated rather than derived from
fills, and no reconciliation existed. Phases 11–14 fixed exactly that: `src/order_resolution.py`
classifies terminal states, `src/pnl.py::realized_pnl` computes P&L from fills + fees,
`src/reconciliation.py` checks the sum against Alpaca, and `src/backfill.py` repaired the stale
residue. **Phase 17 is the first phase entitled to compute statistics from that data**, and its only
job is to produce defensible per-symbol / per-bot evidence.

Phase 15 shipped the `bots.quarantined_symbols` column (config-driven, zero-code-change quarantine)
and Phase 16 surfaced the effective universe. Both are levers with nothing yet loaded into them.
Phase 17 produces the ammunition; **Phase 18 (TUNE-01/TUNE-03) pulls the trigger.**

**Requirement owned:** TUNE-02 (per-symbol / per-bot performance analysis drives the retune, rather
than uniform thresholds).

## Grounding (from code scout)

- `src/db.py:211` `get_alpaca_accuracy(bot_id, last_n)` — the existing aggregate. Filters
  `status IN ('closed','stopped','target_hit')`, guards `pnl or 0.0`, and already selects `symbol`
  and `asset_class` — but aggregates **bot-wide only**. It is the shape to follow, not to modify.
- `src/db.py:246` `get_realized_pnl(bot_id)` (Phase 13) — canonical statement of the
  **position-closed terminal set**: `('closed','stopped','target_hit')`. Its docstring is explicit
  that summing `'closed'` alone drops every stop/target exit. Phase 17 MUST use the same set.
- `src/order_resolution.py:11` `_TERMINAL_NONPOSITION = {'canceled','cancelled','expired',
  'rejected'}` — rows that never held a position. `src/db.py:111` shows the full terminal list
  (position-closed ∪ non-position). Non-position terminals carry `pnl = NULL` and are **not trades**
  for win-rate purposes; counting them would dilute every symbol's stats and (post-Phase-15) a
  gate-`rejected` row would even show up as a "loss".
- `src/pnl.py:10` `realized_pnl(...)` — pure fill-based P&L (Phase 12). Already persisted into
  `alpaca_trades.pnl` + `fees` (migration `016_realized_pnl_fees.sql`). Phase 17 reads the stored
  `pnl`; it does **not** recompute it.
- `src/db_schema.sql:24-51` `alpaca_trades` — `symbol`, `asset_class`, `side`, `status`, `pnl`,
  `fees`, `closed_at`, and **`timestamp TEXT`** (`:28`). Any time-window filter therefore needs
  `"timestamp"::timestamptz` (precedent: `src/db.py:168`, `dashboard/api/routes/bots.py:93-104`).
  `closed_at` is TEXT too (`src/db.py:204` casts it).
- `src/bot_config.py` — `quarantined_symbols` / `quarantined` (Phase 15). This is the column
  Phase 18 will populate **from this phase's output**.
- `src/universe.py` — `normalize(symbol)` (`BTC/USD` → `BTCUSD`). Alpaca-sourced rows and
  config-sourced rows disagree on the slash; grouping on the raw `symbol` column would split
  `BTC/USD` and `BTCUSD` into two fake symbols. **Group on the normalized key.**
- `src/effective_universe.py:115` `resolve_universe(...)` (Phase 16) — the per-bot tradeable set;
  useful for annotating a symbol as already-quarantined/already-blocked in the report.
- `dashboard/api/migrations/` — 015 (P11), 016 (P12), 017 (P13), 018 (P15). **Next free number is
  `019`.** Numbered SQL, additive/idempotent, mirrored into `src/db_schema.sql` — NOT alembic.
- `tests/` — `test_pnl.py`, `test_reconciliation.py`, `test_order_resolution.py` set the convention:
  pure functions tested on in-memory fixtures with fake doubles (`FakeLogger` / `FakeAlpacaClient`),
  no live DB.

## Decisions (locked — auto-selected recommended defaults)

1. **Aggregation lives in a pure module `src/symbol_stats.py` + one read-only query in `src/db.py`.**
   Split of concerns, mirroring Phases 12/13:
   - `db.get_resolved_trades(bot_id=None, since=None) -> list[dict]` — a single **read-only SELECT**
     over `alpaca_trades` (`symbol, asset_class, side, status, pnl, fees, closed_at, bot_id`),
     filtered to the position-closed terminal set, with an optional
     `"timestamp"::timestamptz >= %s` window. No writes, ever.
   - `symbol_stats.aggregate(rows, min_sample=5) -> list[SymbolStat]` — **pure**, no I/O, takes rows
     and returns per-`(bot_id, symbol)` stats. Aggregating in Python (not SQL `GROUP BY`) is what
     lets the same function be unit-tested on fixtures and lets the normalization + sample guard be
     one testable code path rather than SQL string. SQL selects, Python decides.
2. **Metrics per `(bot_id, normalized_symbol)`, plus a per-symbol all-bots roll-up and a per-bot
   roll-up:** `trades`, `wins`, `losses`, `win_rate`, `realized_pnl` (sum of stored `pnl`),
   `total_fees`, `avg_win`, `avg_loss`, `expectancy` (`win_rate*avg_win + (1-win_rate)*avg_loss`,
   loss carried negative — must equal `realized_pnl / trades`, which is the unit-test invariant),
   `best`/`worst`, `first_trade` / `last_trade`. A win is `pnl > 0`; ~~`pnl == 0.0` is a loss (flat is
   not a win after fees)~~ — stated so the definition cannot drift from `get_alpaca_accuracy`.

   > **⚠ SUPERSEDED IN PART (Revision 2, plan-check B1) — the "`pnl == 0.0` is a loss" clause is VOID.**
   > `src/alpaca_orchestrator.py:169-176` writes `status='closed', pnl=0.0` for **every externally-exited
   > position** (same sentinel shape at `src/bot_c/strategy.py:393` and `src/trend_strategy.py:172` when
   > `entry_price == 0`). Those rows are *position-closed*, so the terminal-status filter does **not**
   > drop them, and the value is `0.0` — not NULL — so a `null_pnl` counter never sees them. A genuine
   > flat trade is therefore **indistinguishable from a sentinel**. Scoring `pnl == 0.0` as a loss would
   > fabricate a losing record for every externally-exited position — the exact class of lie this
   > milestone exists to kill.
   >
   > **Amended rule: `pnl == 0.0` on a position-closed row goes to a `zero_pnl` bucket — NEVER a win,
   > NEVER a loss, NOT counted in `trades`; counted and printed as `zero_pnl_total`.** The rest of
   > decision 2 (win = `pnl > 0`; the expectancy invariant; the metric list) stands unchanged.
   >
   > This decision was locked on the premise that the only zero-pnl writer was the `rejected` path
   > (`src/bot_thread.py:309`). The code falsifies that premise. See `17-VALIDATION.md` Revision 2 (B1)
   > and `17-RESEARCH.md` Revision 2 (C1).
   >
   > **Corollary (plan-check B2, also superseding the parenthetical "after fees"):** `alpaca_trades.pnl`
   > is **NOT uniformly net of fees**. `src/bot_c/strategy.py:393-395` and `src/trend_strategy.py:172-173`
   > store a **GROSS** `pnl` and pass **no `fees`** arg (so `fees` lands NULL, `src/db.py:101-107,118`).
   > Only `src/alpaca_orchestrator.py:316-318` and `src/backfill.py:83-86` store a fee-net `pnl`. Rows
   > with `fees IS NULL` are flagged `gross_pnl_rows` and disclosed; fees are still **never** subtracted.
3. **Minimum-sample guard: `MIN_SAMPLE = 5` resolved trades.** A `(bot, symbol)` cell with fewer is
   still **reported** (hiding it would hide a leak like TRUMP) but is stamped
   `sample: "insufficient"` and is **NEVER eligible to be called a winner or a loser**. Phase 18 may
   only act on `sample: "sufficient"` cells. 5 is deliberately low — the whole dataset is thin; the
   guard exists to stop a 1-for-2 symbol masquerading as evidence, not to gate real signal. The
   threshold is a module constant + a function kwarg so Phase 18 can raise it without an edit here.
4. **Output = a CLI/report artifact, not a dashboard surface.** `scripts/symbol_report.py`
   (mirroring `scripts/backfill_trades.py` from Phase 14) prints a markdown table to stdout and
   writes `.planning/phases/17-per-symbol-performance/EVIDENCE.md`. Flags: `--bot`, `--window`,
   `--min-sample`, `--json`. **Read-only by construction: the script opens no write path, and
   `--apply` does not exist.** No dashboard work: RUN-02 (Phase 19) owns the headline numbers, and
   adding a panel here would collide with it and drag UI risk into an analysis phase.
5. **No migration, no view.** Everything needed is already columns on `alpaca_trades`. A SQL VIEW
   would freeze the terminal-status set and the win definition in two places (SQL + Python) and they
   would drift. If a migration ever proves necessary it is `019_*.sql`, additive + mirrored into
   `src/db_schema.sql` — but the locked answer is **none**.
6. **Time window: full history is the default, with a `--window <days>` slice (recommend running
   both 90d and all-time).** The dataset is small; defaulting to a short window would starve the
   sample guard. Windowing filters on `"timestamp"::timestamptz` (entry time — a trade belongs to
   the regime that entered it), never on the raw TEXT column.
7. **NULL `pnl` on a position-closed row is a data defect, not a zero.** Post-Phase-14 it should not
   exist. It is **excluded from the stats** and **counted into a `null_pnl` field per cell + a loud
   summary line** in the report. Silently coercing it to 0.0 (which `get_alpaca_accuracy` does)
   would let a resolution bug read as a break-even trade — the exact class of lie this milestone is
   about. If the count is non-zero, that is a finding for Phase 18/20, not something Phase 17 fixes.
8. **Annotate, don't decide.** Each cell carries `already_quarantined` / `off_universe` (via
   `src/effective_universe.py`) so Phase 18 sees at a glance which losers are already handled and
   which are live. The report may **rank** by expectancy; it may **not** emit a "quarantine this"
   verdict.

## Scope discipline (fences)

- **READ-ONLY. Phase 17 changes NO bot behavior.** It does not touch the gate (15), sizing, the
  confluence threshold, Kelly, exits, the risk gate, or the P&L math (12). Zero edits to
  `src/bot_thread.py`, `src/position_sizer.py`, `src/technical_signals.py`, `src/pnl.py`.
- **It MUST NEVER write to the prod DB.** No INSERT/UPDATE/DELETE, no migration, no
  `quarantined_symbols` write. The only new DB code is one SELECT. A verifier should be able to grep
  the diff for `INSERT|UPDATE|DELETE|ALTER` and find nothing outside tests.
- **It does NOT decide what to quarantine or retune** — that is Phase 18 (TUNE-01/TUNE-03), which
  consumes this phase's evidence and owns the `quarantined_symbols` write + the backtest validation.
- Does not re-derive P&L from Alpaca, does not call Alpaca at all, does not re-run reconciliation
  (13) or backfill (14).
- No dashboard/UI changes (Phase 19 owns the honest headline).
- Risk invariants (max 5% per position, quarter-Kelly, 20% drawdown stop, 50-trade paper gate)
  untouched.

## Canonical refs (MANDATORY reading for research/plan)

- `.planning/REQUIREMENTS.md` — TUNE-02 (owned); TUNE-01/TUNE-03 (Phase 18 — read to see what
  evidence Phase 18 needs, then stop).
- `.planning/phases/11-order-state-resolution-engine/`, `12-realized-pnl-from-fills/`,
  `13-alpaca-reconciliation-check/`, `14-stale-trade-backfill-repair/` — why the data is now
  trustworthy, and what "resolved" means.
- `.planning/phases/15-universe-hard-gate/15-CONTEXT.md` — the `quarantined_symbols` lever this
  evidence loads.
- `src/db.py:211` (`get_alpaca_accuracy`), `src/db.py:246` (`get_realized_pnl`) — the terminal-status
  set and the win definition to mirror exactly.
- `src/order_resolution.py:11` — `_TERMINAL_NONPOSITION`.
- `src/pnl.py`, `src/db_schema.sql:24-51` (`alpaca_trades`, `timestamp TEXT`).
- `src/universe.py` (`normalize`), `src/effective_universe.py:115` (`resolve_universe`).
- `scripts/backfill_trades.py` — the CLI entrypoint convention (dry-run-safe default).
- `tests/test_pnl.py`, `tests/test_reconciliation.py` — pure-function + fake-double test conventions.
- CLAUDE.md — numbered SQL migrations (next free `019`), `"timestamp"::timestamptz`, one Alpaca
  account per bot, never mutate prod rows without explicit permission.

## Deferred ideas (not this phase)

- Auto-quarantine (a symbol that goes N-for-M is quarantined automatically) — Phase 18 decides
  policy; this phase only supplies the N and the M.
- Per-**confluence-score** and per-**side** (long/short) breakdowns feeding the Kelly retune — likely
  Phase 18 research; the pure `aggregate()` is designed so a new group-by key is a kwarg, not a
  rewrite.
- Folding `MEME_CRYPTO` / `_ALPACA_UNTRADEABLE` into `quarantined_symbols` (handed over from
  Phase 16) — a config change Phase 18 should make once the evidence says so.
- Surfacing per-symbol stats on the dashboard — after Phase 19 owns the honest headline.
