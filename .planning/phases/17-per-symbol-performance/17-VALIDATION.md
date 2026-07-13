---
phase: 17
slug: per-symbol-performance
status: revised
revision: 2
revision_reason: "plan-check BLOCKERS B1-B6 + W1-W3 — two RESEARCH factual claims were FALSE against the repo"
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-12
updated: 2026-07-12
---

# Phase 17 — Validation Strategy

## Revision 2 — what changed and why (every claim re-verified at file:line)

| ID | Was | Truth (verified) | Consequence |
|----|-----|------------------|-------------|
| **B1** | "the terminal-status filter keeps fabricated zero-P&L rows out" | **FALSE.** `src/alpaca_orchestrator.py:167-176` marks externally-exited positions `status="closed", pnl=0.0` — a *position-closed* row carrying a **sentinel zero, not NULL**. Same shape at `src/bot_c/strategy.py:393` and `src/trend_strategy.py:172` (`pnl = (px-entry)*q if entry > 0 else 0.0`). | Under the old "`pnl == 0.0` is a LOSS" rule, **every externally-exited position becomes a fake zero-P&L loss**, and the status filter cannot stop it (the row IS `closed`). **New rule: `pnl == 0.0` on a position-closed row goes to a `zero_pnl` bucket — EXCLUDED from wins/losses/expectancy, counted, printed loudly.** This SUPERSEDES 17-CONTEXT decision 2's "`pnl == 0.0` is a loss": that decision rested on the false premise that the only zero-pnl writer was the `rejected` path. |
| **B2** | "`alpaca_trades.pnl` is net of fees at every writer" | **FALSE.** There are **FOUR** live position-closed writers, not two. `src/alpaca_orchestrator.py:316-318` and `src/backfill.py:83-86` pass `pnl=realized_pnl(...)` **and** `fees=` → **NET**. `src/bot_c/strategy.py:393-395` and `src/trend_strategy.py:172-173` pass a **GROSS** `pnl` and **NO `fees` arg** → `fees` lands **NULL** (`src/db.py:101-107` defaults it to `None`; `:118` writes it). | `realized_pnl = sum(pnl)` **silently mixes gross and net**, and `total_fees` reports **$0 drag for exactly the bots whose P&L is overstated**. RESEARCH §2's old rationale ("a missing fee is not a data lie about the P&L") was **backwards**: **NULL `fees` on a position-closed row is the TELL that `pnl` is GROSS.** New rule: count those rows into `gross_pnl_rows` per cell + a loud summary, and state in EVIDENCE.md that their `realized_pnl` is **not fee-adjusted**. Still **never subtract fees** — just stop claiming the number is net. |
| **B3** | case 14 gated on `DATABASE_URL` (**= PROD**) while it **SEEDS rows** | A suite run with `DATABASE_URL` pointed at Coolify prod Postgres would **INSERT synthetic trades into the live trade log**. | Case 14 is gated on **`TEST_DATABASE_URL` ONLY** and asserts at runtime that `TEST_DATABASE_URL != DATABASE_URL` (skip/fail otherwise). **The seeding test NEVER touches prod.** Separately: EVIDENCE.md (17-04 Task 2) **may** read prod — **SELECT-only**, via `get_resolved_trades` / `get_realized_pnl` — **never via the seeding test**. That split is now explicit. |
| **B4** | case 12 assigned to no task, and typed "pure" | A **pure** test cannot verify a SQL cast. | Case 12 is **folded into case 14(c)** (real SQL: a 200-day-old row excluded, a fresh one included) **plus** a source-grep in Task 3 asserting `"timestamp"::timestamptz >= %s` appears inside `get_resolved_trades`. |
| **B5** | case 16 sliced `get_resolved_trades` out of `db.py`, then regexed for INSERT/UPDATE | If the slice came back **empty**, the fence matched nothing and **passed vacuously** — while `db.py` is full of `INSERT`/`UPDATE` (`:70`, `:118`, `:283`, `:347`). A Phase-15-B4-class fake. | Case 16 now asserts the slice is **non-empty** AND contains a **positive control** (`"SELECT bot_id, symbol" in body`) **before** the negative regex, plus a **self-test**: the same fence applied to `update_alpaca_trade` must **FAIL**, proving the regex fires. |
| **B6** | case 10's primary assertion ("for every emitted cell (if any), trades==0") | **Vacuous** — passes trivially on `[]`. | Now asserts `aggregate(nonposition_rows_only) == []` **explicitly**, KEEPS the mixed 3-of-7 assertion, and adds the B1 sentinel case. |
| **W1** | `ORDER BY "timestamp" ASC` | Lexicographic TEXT sort. | `ORDER BY "timestamp"::timestamptz ASC`. |
| **W3** | case 18 grepped for verdict strings no impl would ever emit | Unfalsifiable. | Case 18 now asserts the **ranking section contains ONLY `sample == "sufficient"` cells** (a worst-expectancy `insufficient` cell is absent from the ranking while present in the full table). |
| **W2** | — | `src/db.py:201` `get_recent_loss_symbols` filters `status IN ('closed','stopped')` — a **fourth** spelling of the status set (drops `'target_hit'`), **live in the entry cooldown**. | **Not fixed here** (Phase 17 changes no bot behavior). Recorded in EVIDENCE.md as a **finding for Phase 18/20**. |

**Cleared by plan-check, no change:** `get_resolved_trades` shadows no existing query (strict superset of
`get_alpaca_accuracy` / `get_realized_pnl`); `MIN_SAMPLE=5` is applied where Phase 18 reads it; nothing
else in the diff mutates prod or calls Alpaca.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.3.5 |
| **Quick run** | `python -m pytest tests/test_symbol_stats.py -q` |
| **DB run** | `TEST_DATABASE_URL=<LOCAL pg> python -m pytest tests/test_symbol_stats.py -q` (case 14 — **gated on `TEST_DATABASE_URL` ONLY, never `DATABASE_URL`**. The test SEEDS rows; pointing it at prod would insert synthetic trades into the live log. It asserts `TEST_DATABASE_URL != DATABASE_URL` and skips/fails otherwise.) |
| **Full suite** | `python -m pytest tests/ dashboard/api/tests/ -q` — **baseline 373 passed, 9 skipped** |
| **Fakes** | zero-network, zero-DB. Fixtures are plain `dict`s (psycopg3 `row_factory=dict_row`, `src/db.py:29` — a fixture dict IS a row). Phase 17 needs **no Alpaca fake at all** (zero network calls). |

## Validation Architecture (TUNE-02)

Pure aggregator `src/symbol_stats.py` (zero I/O, fixture-tested), one read-only SELECT
`src/db.py::get_resolved_trades` on top, thin CLI `scripts/symbol_report.py` above that.
**No write path exists anywhere in the diff — that is itself a test (case 16, now non-vacuous).**

### The four buckets — a position-closed row lands in exactly one

| Bucket | Condition | Counted in trades/wins/losses/expectancy? | Reported as |
|--------|-----------|-------------------------------------------|-------------|
| **win** | `pnl > 0` | yes (win) | — |
| **loss** | `pnl < 0` | yes (loss) | — |
| **zero_pnl** (B1) | `pnl == 0.0` | **NO** — indistinguishable from the external-exit sentinel (`alpaca_orchestrator.py:167-176`) | `zero_pnl` per cell + `zero_pnl_total` |
| **null_pnl** | `pnl IS NULL` | **NO** — a resolution defect | `null_pnl` per cell + `null_pnl_total` |

Orthogonal flag (B2): a **counted** row with **`fees IS NULL`** is a **`gross_pnl_rows`** row — its `pnl`
is probably **GROSS** (`bot_c/strategy.py:393`, `trend_strategy.py:172` store gross, pass no fees). It
still counts as a win/loss (it is real P&L), but the cell's `realized_pnl` is **not fully fee-adjusted**
and the report must say so.

| # | Case | Test | Proves |
|---|------|------|--------|
| 1 | win = `pnl > 0` | `test_win_definition_positive` | mirrors `get_alpaca_accuracy` (`src/db.py:228`) — definition cannot drift |
| 2 | **`pnl == 0.0` on a position-closed row is NEITHER a win NOR a loss — it goes to `zero_pnl`** (B1; supersedes CONTEXT decision 2) | `test_zero_pnl_is_bucketed_not_a_loss` | `alpaca_orchestrator.py:167-176` writes `status="closed", pnl=0.0` for EVERY externally-exited position; scoring it as a loss fabricates a losing record the status filter cannot catch |
| 2b | **a `closed` row with `pnl=0.0` must NOT appear in `losses`** — the literal B1 fixture (external-exit sentinel), plus the `entry_price == 0` shape from `bot_c/strategy.py:393` / `trend_strategy.py:172` | `test_external_exit_sentinel_not_a_loss` | the exact rows those three writers emit |
| 3 | negative `pnl` is a loss; `avg_loss` carried **negative** | `test_avg_loss_is_negative` | sign discipline — precondition for case 4 |
| 4 | **`expectancy == realized_pnl / trades`** — BOTH expressions (`win_rate*avg_win + (1-win_rate)*avg_loss` and `sum(pnl)/n`) with `pytest.approx`, on a fixture mixing wins, losses, a `0.0`, and a NULL (zeros and NULLs excluded from BOTH sides) | `test_expectancy_invariant` | THE load-bearing invariant. Catches sign drift, NULL/zero mishandling, and denominator bugs in one assertion. |
| 5 | `realized_pnl == sum(pnl)` — **fees are NOT subtracted again**; `total_fees == sum(fees)` reported separately | `test_fees_not_double_subtracted` | `src/pnl.py:28` already returned `gross - fees` on the two writers that pass fees; double-subtracting fabricates a loss on every trade |
| 5b | **`fees IS NULL` on a counted row → `gross_pnl_rows += 1`** — that row's `pnl` is probably GROSS; it still counts as a win/loss, contributes `0.0` to `total_fees`, and the cell is flagged | `test_null_fees_means_gross_pnl` | **B2** — `bot_c/strategy.py:393-395` / `trend_strategy.py:172-173` store gross `pnl` and pass NO `fees`. NULL fees is the TELL, not a harmless gap; `total_fees` must not read as "this bot paid $0 drag". |
| 6 | `MIN_SAMPLE = 5`: a 4-trade cell → `sample="insufficient"` | `test_min_sample_threshold` | CONTEXT decision 3 |
| 7 | **an `insufficient` cell is STILL PRESENT in the returned list** (full stats), merely excluded from the ranking | `test_insufficient_is_marked_not_hidden` | hiding it would hide a TRUMP-shaped leak |
| 8 | `min_sample` is a kwarg (`MIN_SAMPLE` is the default) — `min_sample=10` re-stamps the same fixture | `test_min_sample_is_a_kwarg` | Phase 18 can raise it without editing this module |
| 9 | **`BTC/USD` + `BTCUSD` + `btc/usd` collapse into ONE cell** keyed `BTCUSD`; first-seen raw spelling kept as `display` | `test_normalization_collapses_slash` | `src/universe.py:17` is the group key — grouping raw halves every BTC sample |
| 10 | **non-vacuous terminal filter (B6): `aggregate(rows_of_only_rejected/canceled/cancelled/expired/open/submitted) == []`** — an EMPTY list, asserted explicitly. PLUS the mixed fixture: 3 `closed` + 4 `rejected` on one symbol → `trades == 3` | `test_nonposition_terminal_never_counts` | **A Phase-15 gate block (`rejected`, `pnl=0`, `bot_thread.py:309`) must NEVER score as a loss.** Belt (SQL `WHERE`) + braces (the pure function defends itself). |
| 11 | **NULL `pnl` on a `closed`/`stopped`/`target_hit` row is EXCLUDED from `trades`/`wins`/`losses`/`realized_pnl`/`expectancy` AND counted into `null_pnl`** — never coerced to `0.0` | `test_null_pnl_excluded_and_counted` | CONTEXT decision 7 — the anti-`get_alpaca_accuracy` rule (`src/db.py:228,259` coerce with `or 0`) |
| 11b | a cell whose rows are ALL NULL-pnl → `trades == 0`, `null_pnl == n`, every ratio `0.0`, `sample == "insufficient"`, cell still emitted | `test_all_null_pnl_cell` | the defect is loud, not silent |
| 12 | **FOLDED (B4)** — the window/cast behavior is verified by **case 14(c)** (real SQL) **plus** a source-grep asserting `"timestamp"::timestamptz >= %s` appears inside `get_resolved_trades` | *(14c + the Task-3 grep)* | a **pure** test cannot verify a SQL cast — the old case 12 was untestable as specified. `src/db_schema.sql:28` is `timestamp TEXT`; a lexicographic compare mis-filters silently. |
| 13 | **empty/zero safety**: `aggregate([])` → `[]`; 0 wins → `avg_win == 0.0`; 0 losses → `avg_loss == 0.0`; 0 trades → `win_rate`/`expectancy` `== 0.0`. **No `ZeroDivisionError` anywhere.** | `test_empty_and_zero_denominators` | every denominator guarded, as `src/db.py:236-238` already does |
| 14 | **DB-gated real SQL — `TEST_DATABASE_URL` ONLY (B3)**: `@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"))` **plus** an in-test assertion `TEST_DATABASE_URL != DATABASE_URL` (**this test SEEDS rows — it must never touch prod**). Asserts: (a) exact key set; (b) a seeded `rejected` row is ABSENT (the status filter runs in SQL); **(c)** `since=now-90d` excludes a 200-day-old row and includes a fresh one (the `::timestamptz` cast executes against the TEXT column); (d) `bot_id="A"` filters; (e) a seeded `closed` row with `pnl=NULL` comes back `None`, not `0.0` | `test_get_resolved_trades_sql` | the SQL is otherwise never executed by any test |
| 15 | roll-ups: the same `aggregate()` with `key=("symbol",)` / `key=("bot_id",)` yields all-bots-per-symbol and per-bot rows | `test_rollup_by_key` | one code path, three groupings |
| 16 | **read-only fence, non-vacuous (B5)**: for each of `src/symbol_stats.py`, `scripts/symbol_report.py`, and the `get_resolved_trades` body sliced from `src/db.py` — **first** assert the source is **non-empty** and (for the slice) contains the **positive control** `"SELECT bot_id, symbol"`, **then** assert no `INSERT`/`UPDATE`/`DELETE`/`ALTER`/`DROP`/`TRUNCATE` (comment lines stripped first). `scripts/symbol_report.py` defines no `--apply`. **Self-test: the same fence applied to `update_alpaca_trade` (`src/db.py:101-122`) must FAIL** — proving the regex fires. | `test_phase17_is_read_only` + `test_readonly_fence_actually_fires` | an empty slice must not pass vacuously — `db.py` contains INSERT/UPDATE at `:70`, `:118`, `:283`, `:347` |
| 17 | annotation: a cell in `cfg.quarantined` → `already_quarantined=True`; a symbol blocked `off_universe`/`meme`/`untradeable` → `off_universe=True` — matched through `normalize()` on BOTH sides, via `src/effective_universe.py::resolve_universe`, never re-derived | `test_annotation_from_resolve_universe` | CONTEXT decision 8 — annotate, don't decide |
| 18 | **the ranking section contains ONLY `sample == "sufficient"` cells** (W3): an `insufficient` cell with the WORST expectancy is absent from the ranking yet present in the full table. Asserted structurally on the ranked cell list — not by grepping for verdict words an impl would never emit. | `test_ranking_is_sufficient_only` | Phase 18 pulls the trigger, not Phase 17 — and the assertion is falsifiable |

**Wave 0 gap:** `tests/test_symbol_stats.py` **does not exist**. Created **RED before implementation** —
the `ImportError` on `from src.symbol_stats import aggregate, MIN_SAMPLE` is the load-bearing proof.
Also new: `src/symbol_stats.py`, `src/db.py::get_resolved_trades`, `scripts/symbol_report.py`. No
framework install needed.

### Why case 10 exists (the gate-block trap)

`src/bot_thread.py:309`, `:317`, `:332` call `logger.update_alpaca_trade(trade_id, "rejected", pnl=0)`.
Post-Phase-15 the gate emits one such row per blocked entry — for exactly the symbols an operator
quarantined. Left unfiltered, a quarantined symbol accrues a fake losing record, Phase 18 acts on that
"evidence," quarantines more, and the loop closes. Case 10 pins the filter at both layers — **and now
asserts an empty list, so it cannot pass vacuously.**

### Why cases 2/2b exist (B1 — the trap the status filter does NOT catch)

`src/alpaca_orchestrator.py:167-176`:
```
if alpaca_sym and alpaca_sym not in live_symbols:
    self.logger.update_alpaca_trade(trade_id=trade["id"], status="closed",
                                    exit_price=trade.get("entry_price", 0), pnl=0.0)
```
Every position that exited **outside** the bot's own close path (manual close, Alpaca-side liquidation, a
restart that lost track) is written **`status="closed"`, `pnl=0.0`** — a position-closed row that
**passes the terminal-status filter** and carries a **sentinel zero, not NULL**. Under the original
"`pnl == 0.0` is a loss" rule, every one becomes a fake zero-P&L loss and `null_pnl` never sees it.
`src/bot_c/strategy.py:393` and `src/trend_strategy.py:172` emit the same shape whenever `entry_price`
is 0. **Therefore `pnl == 0.0` is bucketed, not scored.** This is the one place Phase 17 deviates from
17-CONTEXT decision 2 — because that decision rested on a premise the code falsifies.

### Why case 5b exists (B2 — `pnl` is NOT uniformly net of fees)

Four live position-closed writers:

| Writer | `pnl` | `fees` |
|--------|-------|--------|
| `src/alpaca_orchestrator.py:316-318` | `realized_pnl(...)` → **NET** | passed |
| `src/backfill.py:83-86` | `realized_pnl(...)` → **NET** | passed |
| `src/bot_c/strategy.py:393-395` | `(px - entry) * q` → **GROSS** | **not passed → NULL** (`src/db.py:107` default) |
| `src/trend_strategy.py:172-173` | `(px - entry) * q` → **GROSS** | **not passed → NULL** |

So `sum(pnl)` mixes gross and net, and `total_fees` reads **$0 drag for exactly the bots whose P&L is
overstated**. Phase 17 does **not** fix the writers (that would change bot behavior — out of scope) and
does **not** subtract fees. It **discloses**: `gross_pnl_rows` per cell, `gross_pnl_rows_total` in the
summary, and an explicit EVIDENCE.md sentence that those rows' `realized_pnl` is not fee-adjusted. A
non-zero count is a **finding for Phase 18/20**.

### Known limitations (carry into VERIFICATION.md and EVIDENCE.md)

1. A per-bot roll-up will **not** equal `db.get_realized_pnl(bot_id)` when NULL-pnl **or zero-pnl** rows
   exist — `get_realized_pnl` coerces NULL to `0.0` and counts sentinel zeros. The divergence is
   **correct and intended**: print both numbers plus the delta side by side. Do not reconcile it away;
   do not modify `get_realized_pnl`.
2. **(W2)** `src/db.py:201` `get_recent_loss_symbols` filters `status IN ('closed','stopped')` — a
   **fourth** spelling of the status set (drops `'target_hit'`), **live in the entry cooldown**. Phase 17
   changes no bot behavior; record it in EVIDENCE.md as a **Phase-18/20 finding**.

## Nyquist Compliance

- TUNE-02 → cases 1-18 (19 tests: the numbered cases plus 2b, 5b, 11b, and the fence self-test; case 12
  folded into 14c + a source grep).
- `nyquist_compliant` flips true when: the suite passes with a **LOCAL `TEST_DATABASE_URL`** (case 14 not
  skipped), the full suite is ≥ 373 passed, and `EVIDENCE.md` has been generated — both `--window 90` and
  full-history — with the `null_pnl_total`, `zero_pnl_total` and `gross_pnl_rows_total` lines present
  (even when zero).
- **Read/write split (B3) — stated explicitly:**
  - **The seeding test (case 14) runs against `TEST_DATABASE_URL` ONLY, asserted `!= DATABASE_URL`. It
    NEVER touches prod.**
  - **EVIDENCE.md MAY be generated against prod — but SELECT-only**, through `get_resolved_trades` /
    `get_realized_pnl`, which contain no write path (case 16 proves it). The script has no `--apply` and
    issues no INSERT/UPDATE/DELETE/ALTER.
  - The only file Phase 17 writes is `.planning/phases/17-per-symbol-performance/EVIDENCE.md`.
