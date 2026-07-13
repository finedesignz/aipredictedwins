---
phase: 17
slug: per-symbol-performance
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-12
updated: 2026-07-12
---

# Phase 17 — Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.3.5 |
| **Quick run** | `python -m pytest tests/test_symbol_stats.py -q` |
| **DB run** | `DATABASE_URL=<local pg> python -m pytest tests/test_symbol_stats.py -q` (case 14; MUST be run for real — the SELECT has no other execution path) |
| **Full suite** | `python -m pytest tests/ dashboard/api/tests/ -q` — **baseline 373 passed, 9 skipped** |
| **Fakes** | zero-network, zero-DB. Fixtures are plain `dict`s (psycopg3 `row_factory=dict_row`, `src/db.py:29` — so a fixture dict IS a row). `FakeLogger` / `FakeAlpacaClient` conventions from `tests/test_universe.py:1-16`, `tests/test_pnl.py` are the precedent; Phase 17 needs **no Alpaca fake at all** (it makes zero network calls). |

## Validation Architecture (TUNE-02)

Pure aggregator in `src/symbol_stats.py` (zero I/O, unit-tested on fixtures), one read-only SELECT
`src/db.py::get_resolved_trades` on top, thin CLI `scripts/symbol_report.py` above that.
**No write path exists anywhere in the diff — that is itself a test (case 16).**

| # | Case | Test | Proves |
|---|------|------|--------|
| 1 | win = `pnl > 0` | `test_win_definition_positive` | mirrors `get_alpaca_accuracy` (`src/db.py:228`) — definition cannot drift |
| 2 | **`pnl == 0.0` is a LOSS, not a win and not "excluded"** | `test_zero_pnl_is_a_loss` | CONTEXT decision 2 — flat is not a win after fees (`pnl` is already fee-net) |
| 3 | negative `pnl` is a loss and `avg_loss` is carried **negative** | `test_avg_loss_is_negative` | sign discipline — the precondition for case 4 |
| 4 | **`expectancy == realized_pnl / trades`** — asserted against BOTH expressions (`win_rate*avg_win + (1-win_rate)*avg_loss` and `sum(pnl)/n`) with `pytest.approx`, on a mixed win/loss/zero fixture | `test_expectancy_invariant` | THE load-bearing invariant. Catches sign drift, NULL mishandling, and denominator bugs in one assertion. |
| 5 | `realized_pnl == sum(pnl)` — **fees are NOT subtracted again**; `total_fees == sum(fees)` is reported separately; NULL `fees` counts as 0 into `total_fees` and into `null_fees` | `test_fees_not_double_subtracted` | `src/pnl.py:28` already returned `gross - fees`; double-subtracting fabricates a loss on every trade |
| 6 | `MIN_SAMPLE = 5`: a cell with 4 trades is stamped `sample="insufficient"` | `test_min_sample_threshold` | CONTEXT decision 3 |
| 7 | **an `insufficient` cell is STILL PRESENT in the returned list** (with full stats) and is merely excluded from the winner/loser ranking | `test_insufficient_is_marked_not_hidden` | hiding it would hide a TRUMP-shaped leak — the exact failure mode the guard must not cause |
| 8 | `min_sample` is a kwarg (module constant `MIN_SAMPLE` is the default) — passing `min_sample=10` re-stamps the same fixture | `test_min_sample_is_a_kwarg` | Phase 18 can raise it without editing this module |
| 9 | **`BTC/USD` and `BTCUSD` rows collapse into ONE cell** keyed `BTCUSD`, `trades` = the sum; the first-seen raw spelling is preserved as `display` | `test_normalization_collapses_slash` | `src/universe.py:17` is the group key — grouping raw halves every BTC sample |
| 10 | **terminal-status filter: a `rejected` row (which `src/bot_thread.py:309` writes with `pnl=0`) fed to `aggregate()` yields `trades == 0` and `losses == 0`** — likewise `canceled`, `cancelled`, `expired`, `open`, `submitted` | `test_nonposition_terminal_never_counts` | **A Phase-15 gate block must NEVER score as a loss.** Belt (SQL `WHERE`) and braces (the pure function defends itself). |
| 11 | **NULL `pnl` on a `closed`/`stopped`/`target_hit` row is EXCLUDED from `trades`/`wins`/`losses`/`realized_pnl`/`expectancy` AND counted into `null_pnl`** — it is never coerced to `0.0` (i.e. never becomes a case-2 loss) | `test_null_pnl_excluded_and_counted` | CONTEXT decision 7 — the anti-`get_alpaca_accuracy` rule (`src/db.py:228,259` coerce with `or 0`; a resolution bug must not read as break-even) |
| 11b | a cell whose rows are ALL NULL-pnl → `trades == 0`, `null_pnl == n`, every ratio `0.0`, `sample == "insufficient"`, and the cell is still emitted | `test_all_null_pnl_cell` | the defect is loud, not silent |
| 12 | window filter: `get_resolved_trades(since=...)` emits `"timestamp"::timestamptz >= %s` (never a raw TEXT compare), and rows entered before the window are absent | `test_window_casts_text_timestamp` | `src/db_schema.sql:28` is `timestamp TEXT`; a lexicographic compare mis-filters silently. Windowing is on **entry** time (CONTEXT decision 6), never `closed_at`. |
| 13 | **empty-input safety**: `aggregate([])` → `[]`; a cell with 0 wins → `avg_win == 0.0`; 0 losses → `avg_loss == 0.0`; 0 trades → `win_rate`/`expectancy` `== 0.0`. **No `ZeroDivisionError` anywhere.** | `test_empty_and_zero_denominators` | every denominator guarded, as `src/db.py:236-238` already does |
| 14 | **DB-gated real SQL**: `@pytest.mark.skipif(not os.environ.get("DATABASE_URL"))` — `get_resolved_trades()` executes against real Postgres, returns dicts with the exact expected keys, and the `::timestamptz` cast + status filter run without error | `test_get_resolved_trades_sql` | the SQL is otherwise never executed by any test (pattern: `tests/test_universe.py:422-428`) |
| 15 | roll-ups: the same `aggregate()` with `key=("symbol",)` and `key=("bot_id",)` produces the all-bots-per-symbol and per-bot rows; per-bot `realized_pnl` equals `sum(pnl)` over the same fixture | `test_rollup_by_key` | one code path, three groupings (CONTEXT decision 2); the deferred per-side/per-score breakdown is a kwarg, not a rewrite |
| 16 | **read-only fence**: static-source guard — `src/symbol_stats.py`, `src/db.py::get_resolved_trades` and `scripts/symbol_report.py` contain no `INSERT`/`UPDATE`/`DELETE`/`ALTER`, and `scripts/symbol_report.py` defines no `--apply` flag | `test_phase17_is_read_only` | CONTEXT scope fence — grep-verifiable, enforced by a test rather than a reviewer's memory |
| 17 | annotation: a cell whose symbol is in `cfg.quarantined` is stamped `already_quarantined=True`; a symbol blocked `off_universe`/`meme`/`untradeable` is stamped `off_universe=True` — matched through `normalize()` on BOTH sides, via `src/effective_universe.py::resolve_universe` (never re-derived) | `test_annotation_from_resolve_universe` | CONTEXT decision 8 — annotate, don't decide |
| 18 | the report **ranks** by expectancy over `sufficient` cells only, and emits **no** quarantine verdict (no "quarantine"/"disable" string in the output) | `test_no_verdict_emitted` | Phase 18 pulls the trigger, not Phase 17 |

**Wave 0 gap:** `tests/test_symbol_stats.py` **does not exist**. It is created **RED before
implementation** — the `ImportError` on `from src.symbol_stats import aggregate, MIN_SAMPLE` is the
load-bearing proof (same convention as `tests/test_pnl.py:11`). Also new: `src/symbol_stats.py`,
`src/db.py::get_resolved_trades`, `scripts/symbol_report.py`. No framework install needed.

### Why case 10 exists (the loudest trap)

`src/bot_thread.py:309`, `:317`, `:332` all call
`logger.update_alpaca_trade(trade_id, "rejected", pnl=0)`. A `rejected` row therefore carries
`pnl = 0` — **not NULL**. Under the locked win definition (`pnl > 0` is a win; `pnl == 0.0` is a loss,
case 2), any `rejected` row that reaches `aggregate()` is scored as a **loss with zero P&L**.
Post-Phase-15 the gate produces `rejected` rows for exactly the symbols an operator quarantined. Left
unfiltered, a quarantined symbol accrues a fake losing record, Phase 18 sees "evidence," quarantines
more, and the loop closes. Case 10 pins the filter at both layers.

### Why case 11 exists (the anti-`get_alpaca_accuracy` rule)

`src/db.py:228` (`(r["pnl"] or 0) > 0`) and `src/db.py:259` (`(r["pnl"] or 0.0)`) coerce NULL to zero
and cannot even distinguish NULL from a genuine `0.0`. On a **position-closed** row a NULL `pnl` is a
resolution defect that Phases 11–14 were supposed to eliminate. Coercing it to `0.0` would make a
broken row read as a break-even trade — the exact class of lie this milestone exists to kill. Phase 17
excludes it (`row["pnl"] is None`), counts it, and prints a loud `null_pnl_total` summary line. A
non-zero count is a **finding for Phase 18/20**, not something Phase 17 fixes.

### Known limitation (carry into VERIFICATION.md)

A per-bot roll-up from case 15 will **not** equal `db.get_realized_pnl(bot_id)` when any NULL-pnl rows
exist, because `get_realized_pnl` coerces them to `0.0`. That divergence is **correct and intended**;
the report should print both numbers side by side so the gap is visible rather than reconciled away.

## Nyquist Compliance

- TUNE-02 → cases 1–18.
- `nyquist_compliant` flips true when the suite passes (18/18 with a real `DATABASE_URL`, 0 skipped),
  the full suite is ≥ 373 passed, and `EVIDENCE.md` has been generated from the real DB — read-only,
  both `--window 90` and full-history, with the `null_pnl_total` line present (even if zero).
- **All DB evidence is read-only against the prod/local trade log. Phase 17 writes NO rows, ever.**
  The only file it writes is `.planning/phases/17-per-symbol-performance/EVIDENCE.md`.
