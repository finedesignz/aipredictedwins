---
phase: 17
slug: per-symbol-performance
status: revised
revision: 3
revision_reason: "plan-check Rev-3 blockers: prod pool fence (B1), the delta is identically zero (B2), the fence self-trips on prose (B3), CONTEXT amended in place (B4) + W1-W5"
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-12
updated: 2026-07-12
---

# Phase 17 — Validation Strategy

## Revision 3 — the four remaining blockers (each re-verified at file:line)

| ID | Was | Truth (verified this session) | Consequence |
|----|-----|-------------------------------|-------------|
| **R3-B1** (CRITICAL, prod safety) | case 14 asserted `TEST_DATABASE_URL != DATABASE_URL` (env **strings**) before seeding | **That is not a fence.** `src/db.py:18` `_pool` is a **process-global**; `src/db.py:22` `_create_pool()` reads `os.environ["DATABASE_URL"]` **ONCE**; `src/db.py:40-45` `get_pool()` only builds it `if _pool is None`. Three existing `DATABASE_URL`-gated tests already drive `src.db` in the same pytest process (`tests/test_db.py:10`, `tests/test_reconciliation.py:165`, `tests/test_backfill.py:466`). In a full-suite run with `DATABASE_URL=prod`, **the pool is already bound to PROD before case 14 runs**. Monkeypatching the env var afterwards does nothing. There is no conftest guard. The Phase-16 precedent (`tests/test_effective_universe.py:342`) only works because it rebinds env *before importing* `dashboard/api/db.py` — a **different module with its own uninitialized pool**. It does not transfer to `src.db`. | **Case 14 must rebind the POOL and prove it on the LIVE CONNECTION.** Fixture: assert the two URLs differ → **close `src.db._pool`, set it to `None`** → set `DATABASE_URL=TEST_DATABASE_URL` → open a connection and **assert `conn.info.dbname` and `conn.info.host` match the parsed `TEST_DATABASE_URL`** (POSITIVE CONTROL on the live connection, **before the first INSERT**) → teardown closes the pool and resets `_pool = None` so the test pool never leaks. **An env-string comparison is not a prod fence.** |
| **R3-B2** | EVIDENCE.md printed a per-bot `symbol_stats realized_pnl` vs `db.get_realized_pnl` **delta** as the "known limitation" | **The delta is IDENTICALLY ZERO and can never fire.** `src/db.py:252-259`: `get_realized_pnl = sum((r["pnl"] or 0.0) ...)` over the **same** status set. A NULL row contributes `0.0`; a sentinel zero contributes `0.0`. `symbol_stats` **excludes** both — removing exactly `0.0` and `0.0`. So `delta == 0.0` **always**. An operator reading `delta = 0.00` concludes the data is clean — the exact lie this milestone kills. **The real divergence is in the COUNTS:** `src/db.py:228-229` `wins = sum(1 for r in rows if (r["pnl"] or 0) > 0); losses = resolved - wins` — **every sentinel zero and every NULL is booked as a LOSS** in the number the dashboard shows; `avg_pnl` (`:238`) divides by `resolved`, which includes them. | **Replace the pnl delta with the COUNT/RATE divergence.** Per bot, print: `symbol_stats trades = T | get_alpaca_accuracy resolved = R | R - T = zero_pnl + null_pnl`, and `symbol_stats win_rate` vs `get_alpaca_accuracy win_rate` (**the latter counts zeros and NULLs as LOSSES**). State plainly that `realized_pnl` **agrees** with `get_realized_pnl` **by construction** — the defect is in the **DENOMINATOR**, not the sum. New test (case 17). |
| **R3-B3** | 17-04's action told the executor to state "there is no `--apply`" **in the module docstring**, while case 16 asserted the literal token `--apply` appears **nowhere** in the file; and the fence stripped only `#` lines, not docstrings | **Mutually unsatisfiable, and the fence is a prose-detector.** A docstring naming the token makes the grep return ≥1 and fails case 16. Likewise every plan tells the executor to explain the `INSERT`/`UPDATE`/`DELETE` prohibition **in module docstrings** — which the negative regex would then fire on. The fence would fail on a **comment**, not a write path. | **(a)** The docstring says *"read-only: defines no write flag and issues no mutating SQL"* — **without the literal token**; **and** case 16 asserts on the **argparse surface**: `re.search(r'add_argument\(\s*["\']--(apply|write|fix|delete)', src) is None`. **(b)** The fence **strips docstrings** (`ast` module/class/function docstrings, or triple-quoted blocks) **as well as `#` lines** before the negative regex. A fence that fires on prose is not a write-path detector. |
| **R3-B4** | 17-CONTEXT.md decision 2 still read, unqualified, "`pnl == 0.0` is a loss ... stated so the definition cannot drift" | CONTEXT is the **canonical locked-decision record**. A Phase-18 planner or a verifier checking Phase 17 against its CONTEXT would read a rule the code falsifies — and either flag the impl as violating a locked decision, or re-adopt "zero is a loss" for the retune. | **DONE — `17-CONTEXT.md` decision 2 is amended IN PLACE** (annotated, not deleted): the "`pnl == 0.0` is a loss" clause is struck and marked `⚠ SUPERSEDED IN PART (Rev 2, B1)` with the `alpaca_orchestrator.py:169-176` citation and the `zero_pnl` rule; the B2 fee corollary is appended. The rest of decision 2 stands. |

### Warnings fixed in Revision 3

| ID | Issue (verified) | Fix |
|----|------------------|-----|
| **R3-W1** | `gross_pnl_rows` and `null_fees` were the **same set by construction** (both = counted rows with `fees IS NULL`) — a redundant counter that can never differ. | **Redefined so they CAN differ:** `null_fees` = **ALL** position-closed rows in the cell with `fees IS NULL` (including `zero_pnl` and `null_pnl` rows); `gross_pnl_rows` = the **COUNTED subset** (win/loss rows only) — the ones whose `realized_pnl` contribution is un-fee-adjusted. `gross_pnl_rows <= null_fees` always, and they diverge exactly when a defect row also lacks fees. Pinned by case 7. |
| **R3-W2** | **The gross writers also ignore `side`.** `src/bot_c/strategy.py:391-395` and `src/trend_strategy.py:172-173` compute `(current_price - entry) * q` with **no side handling** — unlike `src/pnl.py:10` `realized_pnl(side, ...)`. On any **short / sell-entry** row the **SIGN IS INVERTED**, and B2 keeps those rows **counted as wins/losses**. A losing short reads as a winner. | 17-04 Task 2 runs `SELECT count(*) FROM alpaca_trades WHERE fees IS NULL AND side <> 'buy' AND status IN ('closed','stopped','target_hit')`. **Non-zero ⇒ a Phase-18/20 finding of a WORSE class than "gross"** (a sign inversion, not a magnitude error) — recorded loudly in EVIDENCE.md as `sign_suspect_rows`. Phase 17 does not fix it (bot-behavior change) and does not silently correct the sign. |
| **R3-W3** | The test count did not reconcile (Rev 2 said 19; the specified functions numbered 22). | **23 test functions**, enumerated below. The count is derived from the list, not asserted separately. |
| **R3-W4** | **`'stopped'` and `'target_hit'` have ZERO writers.** Every `update_alpaca_trade` call site (`alpaca_orchestrator.py:171,313`; `backfill.py:166`; `bot_c/strategy.py:394`; `bot_thread.py:309,317,332,338`; `trend_strategy.py:173`) writes only `'closed'` or `'rejected'`; `bot_thread.py:338`'s `db_status` comes from `order_resolution.classify_order`, whose vocabulary is order-state, not `stopped`/`target_hit`. Every row Phase 17 sees will be **`'closed'`**. | Terminal set stays `('closed','stopped','target_hit')` — it mirrors the two existing aggregates and costs nothing. But EVIDENCE.md **must note the `stopped`/`target_hit` populations are EMPTY**, so Phase 18 does not reason about exit classes that do not exist (and nobody reads "no stop-outs" as a performance fact). |
| **R3-W5** | Bare `pytest` cannot import `scripts.symbol_report` — there is **no `scripts/__init__.py`, no `pytest.ini`/`setup.cfg`/`pyproject.toml`** in the repo. | **Every command is `python -m pytest`, run from the repo root** (which puts the root on `sys.path`, making `scripts` importable as a PEP-420 namespace package). Pinned in every plan's verify block and acceptance criteria. |

**Carried unchanged from Revision 2 (checker re-confirmed each at file:line):** B1 `zero_pnl` bucket ·
B2 `gross_pnl_rows` · B4 case-12 fold · B5 fence positive control + self-test · B6 non-vacuous empty-list
case · W1 `ORDER BY "timestamp"::timestamptz` · W3 structural `rank_cells` assertion.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.3.5 |
| **Quick run** | `python -m pytest tests/test_symbol_stats.py -q` — **`python -m pytest`, from the repo root** (R3-W5) |
| **DB run** | `TEST_DATABASE_URL=<LOCAL pg> python -m pytest tests/test_symbol_stats.py -q` — case 18 only. **Gated on `TEST_DATABASE_URL`, and it REBINDS `src.db._pool` and proves the live connection's `info.dbname`/`info.host` before its first INSERT (R3-B1). An env-string check is NOT sufficient: `src/db.py:18,40-45` caches a process-global pool bound at first use, and `tests/test_db.py`, `tests/test_reconciliation.py`, `tests/test_backfill.py` may have already bound it to PROD.** |
| **Full suite** | `python -m pytest tests/ dashboard/api/tests/ -q` — **baseline 373 passed, 9 skipped** |
| **Fakes** | zero-network, zero-DB. Fixtures are plain `dict`s (psycopg3 `row_factory=dict_row`, `src/db.py:29` — a fixture dict IS a row). No Alpaca fake (zero network calls). |

## Validation Architecture (TUNE-02)

Pure aggregator `src/symbol_stats.py` (zero I/O, fixture-tested), one read-only SELECT
`src/db.py::get_resolved_trades` on top, thin CLI `scripts/symbol_report.py` above that.
**No write path exists anywhere in the diff — that is itself a test (case 20, non-vacuous AND
docstring-immune).**

### The four buckets — a position-closed row lands in exactly one

| Bucket | Condition | Counted in trades/wins/losses/expectancy? | Reported as |
|--------|-----------|-------------------------------------------|-------------|
| **win** | `pnl > 0` | yes (win) | — |
| **loss** | `pnl < 0` | yes (loss) | — |
| **zero_pnl** | `pnl == 0.0` | **NO** — indistinguishable from the external-exit sentinel (`alpaca_orchestrator.py:169-176`) | `zero_pnl` + `zero_pnl_total` |
| **null_pnl** | `pnl IS NULL` | **NO** — a resolution defect | `null_pnl` + `null_pnl_total` |

Fee flags (R3-W1 — now genuinely distinct sets):

| Flag | Definition | Meaning |
|------|-----------|---------|
| `null_fees` | **ALL** rows in the cell with `fees IS NULL` (incl. zero_pnl / null_pnl rows) | how much of the cell has no fee data at all |
| `gross_pnl_rows` | the **COUNTED subset** (win/loss rows only) with `fees IS NULL` | **their `pnl` is probably GROSS** (`bot_c/strategy.py:393-395`, `trend_strategy.py:172-173` store gross, pass no fees) ⇒ this cell's `realized_pnl` is **not fully fee-adjusted** |

`gross_pnl_rows <= null_fees` always. `total_fees` is **incomplete** drag disclosure — and is **never**
subtracted from `realized_pnl`.

## The 23 test functions

| # | Test | Proves |
|---|------|--------|
| 1 | `test_win_definition_positive` | win = `pnl > 0` — mirrors `get_alpaca_accuracy` (`src/db.py:228`) |
| 2 | `test_zero_pnl_is_bucketed_not_a_loss` | **`pnl == 0.0` on a position-closed row is NEITHER win NOR loss NOR a trade → `zero_pnl`** (B1) |
| 3 | `test_external_exit_sentinel_not_a_loss` | the literal `alpaca_orchestrator.py:169-176` fixture (+ the `entry_price == 0` shape from `bot_c`/`trend`): `losses` excludes it |
| 4 | `test_avg_loss_is_negative` | `avg_loss` carried NEGATIVE — the precondition for the invariant |
| 5 | `test_expectancy_invariant` | **`expectancy == realized_pnl / trades`** — both expressions, `pytest.approx`, on a fixture containing a `0.0` and a `None` (both excluded from BOTH sides) |
| 6 | `test_fees_not_double_subtracted` | `realized_pnl == sum(pnl)` EXACTLY; `total_fees` reported separately, never subtracted |
| 7 | `test_null_fees_vs_gross_pnl_rows` | **B2 + R3-W1:** a COUNTED row with `fees is None` → `gross_pnl_rows == 1`; a `zero_pnl`/`null_pnl` row with `fees is None` → counts into `null_fees` but **NOT** `gross_pnl_rows`. Asserts `gross_pnl_rows < null_fees` on a fixture with both — proving they are **distinct sets**, not the same counter twice. |
| 8 | `test_min_sample_threshold` | `MIN_SAMPLE == 5`; 4 trades → `insufficient`. **Plus the B1 interaction:** a 5-row cell containing 1 sentinel zero has `trades == 4` → `insufficient`. |
| 9 | `test_insufficient_is_marked_not_hidden` | the `insufficient` cell is STILL in the returned list (hiding it hides a leak) |
| 10 | `test_min_sample_is_a_kwarg` | `min_sample=10` re-stamps the same fixture — Phase 18 raises it without an edit here |
| 11 | `test_normalization_collapses_slash` | `BTC/USD` + `BTCUSD` + `btc/usd` → ONE cell keyed `BTCUSD`, `display == "BTC/USD"` |
| 12 | `test_nonposition_terminal_never_counts` | **`aggregate(only_rejected/canceled/cancelled/expired/open/submitted_rows) == []`** — an EMPTY LIST (B6, non-vacuous). Plus 3 `closed` + 4 `rejected` → `trades == 3`, `zero_pnl == 0` (dropped BEFORE bucketing). |
| 13 | `test_null_pnl_excluded_and_counted` | NULL `pnl` excluded from every statistic, counted into `null_pnl`, `zero_pnl == 0` (**`None` and `0.0` are DIFFERENT buckets**) |
| 14 | `test_all_null_pnl_cell` | an all-NULL cell → `trades == 0`, every ratio `0.0`, `insufficient`, **still emitted** |
| 15 | `test_empty_and_zero_denominators` | `aggregate([]) == []`; every denominator guarded; no `ZeroDivisionError` |
| 16 | `test_rollup_by_key` | `key=("symbol",)` / `("bot_id",)` through the SAME function; defect counters roll up as sums |
| 17 | **`test_naive_accuracy_divergence`** (**NEW — R3-B2**) | on a fixture with 1 sentinel zero + 1 NULL: **`resolved - trades == zero_pnl + null_pnl`** and **`win_rate != naive_win_rate`**, where `naive_win_rate` reproduces `get_alpaca_accuracy`'s arithmetic (`src/db.py:228-229`: `wins = sum(1 for r if (pnl or 0) > 0)`, `losses = resolved - wins`) — i.e. **every zero and every NULL is booked as a LOSS** in the number the dashboard shows. Also asserts `realized_pnl == sum((r["pnl"] or 0.0) for r in rows)` — **the SUMS agree by construction; the divergence is in the DENOMINATOR.** |
| 18 | `test_get_resolved_trades_sql` | **the real SQL, `TEST_DATABASE_URL`-gated (R3-B1).** Rebinds `src.db._pool` and asserts the LIVE connection's `info.dbname`/`info.host` match the parsed `TEST_DATABASE_URL` **before the first INSERT**; resets `_pool` on entry and exit. Then: (a) exact key set; (b) a seeded `rejected` row is ABSENT; (c) `since=now-90d` excludes a 200-day-old row and includes a fresh one (the `::timestamptz` cast runs against the TEXT column); (d) `bot_id="A"` filters; (e) a `pnl=NULL` row returns `None`, not `0.0`. |
| 19 | `test_window_cast_is_in_the_sql` | static half of the folded case 12: the `get_resolved_trades` body contains BOTH `"timestamp"::timestamptz >= %s` AND `ORDER BY "timestamp"::timestamptz` (Rev-2 W1) |
| 20 | `test_phase17_is_read_only` | **the fence (B5 + R3-B3).** Strips `#` lines **AND docstrings** before the regex — a fence that fires on prose is a prose-detector, not a write-path detector. Positive control FIRST (source non-empty; the `db.py` slice contains `SELECT bot_id, symbol`), THEN the negative regex `\b(INSERT\|UPDATE\|DELETE\|ALTER\|DROP\|TRUNCATE)\b`. **The `--apply` check is on the ARGPARSE SURFACE**: `re.search(r'add_argument\(\s*["\']--(apply\|write\|fix\|delete)', src) is None`. |
| 21 | `test_readonly_fence_actually_fires` | **the self-test:** the SAME helper applied to `update_alpaca_trade` (`src/db.py:101-122`) **MUST match** (it contains `UPDATE`). Green from day one. Without it, an empty slice passes vacuously while `db.py` carries INSERT/UPDATE at `:70`, `:118`, `:283`, `:347`. |
| 22 | `test_annotation_from_resolve_universe` | `already_quarantined` / `off_universe` READ from `resolve_universe` (`src/effective_universe.py:115`), matched through `normalize()` on BOTH sides — annotate, don't decide |
| 23 | `test_ranking_is_sufficient_only` | **structural (Rev-2 W3):** `all(c["sample"] == "sufficient" for c in rank_cells(cells))`; the worst-expectancy `insufficient` cell is ABSENT from the ranking and PRESENT in the full table |

**Wave 0 gap:** `tests/test_symbol_stats.py` does not exist. Created **RED before implementation** — the
`ImportError` on `from src.symbol_stats import aggregate, MIN_SAMPLE` is the load-bearing proof. Also new:
`src/symbol_stats.py`, `src/db.py::get_resolved_trades`, `scripts/symbol_report.py`. No framework install.

### Why case 18's POOL fence exists (R3-B1 — the one that could have written to prod)

`src/db.py`:
```python
_pool: ConnectionPool | None = None          # :18  — PROCESS-GLOBAL

def _create_pool() -> ConnectionPool:
    url = os.environ["DATABASE_URL"]         # :22  — read ONCE, at first use

def get_pool() -> ConnectionPool:            # :40
    global _pool
    if _pool is None:                        # :42  — cached forever after
        _pool = _create_pool()
```
`tests/test_db.py:10`, `tests/test_reconciliation.py:165` and `tests/test_backfill.py:466` are all
`DATABASE_URL`-gated and all drive `src.db` **in the same pytest process**. So in a full-suite run with
`DATABASE_URL=<prod>`, `_pool` is **already bound to prod** by the time case 18 executes. Asserting that two
env **strings** differ, then monkeypatching `DATABASE_URL`, changes **nothing** — `_pool is not None`, so
`_create_pool()` is never called again, and the seed INSERTs land **in the live trade log**.

The fence must act on the **pool**, and prove itself on the **live connection**:

1. `assert os.environ["TEST_DATABASE_URL"] != os.environ.get("DATABASE_URL")` (necessary, not sufficient)
2. close `src.db._pool` if open; `src.db._pool = None`
3. `os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]`
4. open a connection and **assert `conn.info.dbname` / `conn.info.host` equal the parsed
   `TEST_DATABASE_URL`** — the POSITIVE CONTROL, **before any INSERT**
5. teardown: close the pool, `_pool = None` (so the test pool never leaks into the other DB-gated tests)

The Phase-16 precedent (`tests/test_effective_universe.py:342`) does **not** transfer: it rebinds env
before importing `dashboard/api/db.py`, a **different module** with its own, still-uninitialized pool.

### Why case 17 exists (R3-B2 — the delta that could never fire)

`src/db.py:252-259` `get_realized_pnl` sums `(r["pnl"] or 0.0)` over the **same** status set. A NULL row
contributes `0.0`; a sentinel zero contributes `0.0`. `symbol_stats` excludes both — removing exactly
`0.0 + 0.0`. **The pnl delta is therefore identically zero**, and printing it as a "known limitation" would
tell an operator the data is clean. The genuine divergence is in the **counts**:

`src/db.py:228-229`:
```python
wins   = sum(1 for r in rows if (r["pnl"] or 0) > 0)
losses = resolved - wins            # <- every sentinel zero AND every NULL is a LOSS
```
plus `avg_pnl = total_pnl / resolved` (`:238`), whose denominator includes them. **That** is what the
dashboard shows. So the report prints, per bot:

```
symbol_stats trades = T | get_alpaca_accuracy resolved = R | R - T = zero_pnl + null_pnl
symbol_stats win_rate = X% | get_alpaca_accuracy win_rate = Y%   (Y counts zeros and NULLs as LOSSES)
realized_pnl agrees with get_realized_pnl BY CONSTRUCTION — the defect is in the DENOMINATOR, not the sum.
```

### Why the fence must strip docstrings (R3-B3)

The plans instruct the executor to explain the read-only rule and the `rejected`/sentinel traps **in module
docstrings**. Those docstrings necessarily contain the words `INSERT`, `UPDATE`, `DELETE` and `--apply`. A
fence that greps raw text (stripping only `#` lines) would **fail on that prose**, while a real
`conn.execute("UPDATE ...")` hidden in an f-string could still slip past. Strip `#` lines **and** docstrings
first; assert `--apply`'s absence on the **argparse surface** (`add_argument("--apply", ...)`), not on raw
text; keep the self-test (case 21) as proof the regex still fires.

## Known limitations — carry verbatim into EVIDENCE.md and VERIFICATION.md

1. **Count/rate divergence, not a P&L divergence (R3-B2).** `realized_pnl` **agrees** with
   `db.get_realized_pnl` by construction. `get_alpaca_accuracy`'s `resolved`, `losses`, `win_rate` and
   `avg_pnl` **book every sentinel zero and every NULL as a LOSS**. Print `R - T`, both win rates, and say
   which is which. Do **not** modify `get_alpaca_accuracy` or `get_realized_pnl` (bot/dashboard behavior).
2. **Sign-suspect rows (R3-W2).** `bot_c/strategy.py:393` / `trend_strategy.py:172` compute
   `(current_price - entry) * q` with **no `side` handling** (unlike `src/pnl.py:10`). On a **short /
   sell-entry** row the **sign is inverted** — and those rows are still counted as wins/losses. Report
   `sign_suspect_rows` =
   `SELECT count(*) FROM alpaca_trades WHERE fees IS NULL AND side <> 'buy' AND status IN ('closed','stopped','target_hit')`.
   **Non-zero ⇒ a Phase-18/20 finding of a WORSE class than "gross"** (a losing short reads as a winner).
3. **`stopped` / `target_hit` are EMPTY populations (R3-W4).** No writer emits them. Every row Phase 17
   sees will be `'closed'`. Say so, so Phase 18 does not reason about exit classes that do not exist.
4. **`get_recent_loss_symbols` (Rev-2 W2).** `src/db.py:201` filters `status IN ('closed','stopped')` — a
   fourth status-set spelling that drops `'target_hit'`, live in the entry cooldown. Reported, not fixed.

## Nyquist Compliance

- TUNE-02 → the **23** test functions above.
- `nyquist_compliant` flips true when: the suite passes with a **LOCAL `TEST_DATABASE_URL`** (case 18 not
  skipped, its live-connection positive control green), the full suite is ≥ 373 passed, and `EVIDENCE.md`
  has been generated — both `--window 90` and full-history — carrying `null_pnl_total`, `zero_pnl_total`,
  `gross_pnl_rows_total`, `null_fees_total`, `sign_suspect_rows`, the count/rate divergence block, and the
  `stopped`/`target_hit` empty-population note (each present even when zero).
- **Read/write split — explicit:**
  - **The seeding test (case 18) rebinds `src.db._pool` to `TEST_DATABASE_URL` and proves the live
    connection before its first INSERT. It can NEVER write to prod.**
  - **EVIDENCE.md MAY be generated against prod — SELECT-only**, via `get_resolved_trades` /
    `get_realized_pnl` / `get_alpaca_accuracy`, none of which contain a write path (case 20 proves it).
  - The only file Phase 17 writes is `.planning/phases/17-per-symbol-performance/EVIDENCE.md`.
- **All commands are `python -m pytest`, run from the repo root** (R3-W5).
