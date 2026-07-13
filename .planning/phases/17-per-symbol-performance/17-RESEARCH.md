# Phase 17: Per-Symbol Performance Analysis (TUNE-02) — Research

**Researched:** 2026-07-12
**Revised:** 2026-07-12 — **Revision 2.** Plan-check found **two core factual claims in Revision 1 were
FALSE** against the repo. Both are corrected below and re-verified at file:line.
**Domain:** Read-only aggregation over `alpaca_trades` — one SELECT in `src/db.py`, one pure module
`src/symbol_stats.py`, one CLI `scripts/symbol_report.py`
**Confidence:** HIGH (every claim below re-read at the cited file:line in this repo; no external deps, no
new packages, no migration)

---

## ⚠ CORRECTIONS — Revision 1 was WRONG about two things

### C1 — "the terminal-status filter keeps fabricated zero-P&L rows out" — **FALSE**

`src/alpaca_orchestrator.py:167-176` writes a **position-closed** row carrying a **sentinel zero**:

```python
if alpaca_sym and alpaca_sym not in live_symbols:
    log.info("[MONITOR] %s not in Alpaca positions — marking closed (externally exited)", sym)
    self.logger.update_alpaca_trade(
        trade_id=trade["id"], status="closed",
        exit_price=trade.get("entry_price", 0), pnl=0.0,      # <- 0.0, NOT NULL
    )
```

Every position that exited **outside the bot's own close path** (manual close, Alpaca-side liquidation, a
restart that lost track of it) becomes `status="closed", pnl=0.0`. It **passes** the
`status IN ('closed','stopped','target_hit')` filter, and because the value is `0.0` and not NULL, a
`null_pnl` counter never sees it. The same sentinel shape appears at `src/bot_c/strategy.py:393` and
`src/trend_strategy.py:172`:

```python
pnl = (current_price - entry) * q if entry > 0 else 0.0
logger.update_alpaca_trade(row["id"], status="closed", exit_price=current_price, pnl=pnl)
```

Under Revision 1's rule (`pnl == 0.0` is a LOSS), **every externally-exited position would have been
scored as a fake zero-P&L loss** — a fabricated losing record the status filter cannot catch.

**FIX (supersedes 17-CONTEXT decision 2):** `pnl == 0.0` on a position-closed row goes into a **`zero_pnl`
bucket** — **excluded** from `wins`/`losses`/`trades`/`expectancy`, **counted** per cell, and printed as a
loud `zero_pnl_total` beside `null_pnl_total`. A genuine flat trade is **indistinguishable** from the
sentinel, so neither may be scored. CONTEXT decision 2 assumed the only zero-pnl writer was the `rejected`
path; the code falsifies that.

### C2 — "`alpaca_trades.pnl` is net of fees" — **FALSE at two of four writers**

There are **FOUR** live position-closed writers, not two:

| Writer | `pnl` stored | `fees` arg | Result |
|--------|--------------|-----------|--------|
| `src/alpaca_orchestrator.py:316-318` | `realized_pnl(...)` | **passed** | **NET** |
| `src/backfill.py:83-86` | `realized_pnl(...)` | **passed** | **NET** |
| `src/bot_c/strategy.py:393-395` | `(px - entry) * q` | **NOT passed** | **GROSS**, `fees` → **NULL** |
| `src/trend_strategy.py:172-173` | `(px - entry) * q` | **NOT passed** | **GROSS**, `fees` → **NULL** |

`src/db.py:101-107` declares `fees: float | None = None`; `:118` writes whatever it got. A writer that
omits `fees` lands **NULL** in the column.

Consequences: `realized_pnl = SUM(pnl)` **silently mixes gross and net**, and `total_fees = SUM(fees)`
reports **$0 drag for exactly the bots whose P&L is overstated** (Bot C / trend). Revision 1's rationale —
"a missing fee is not a data lie about the P&L, because `pnl` was already computed net wherever it exists"
— is **backwards**. **NULL `fees` on a position-closed row is the TELL that `pnl` is GROSS.**

**FIX:** a **counted** row with `fees IS NULL` increments **`gross_pnl_rows`** on its cell. It still counts
as a win/loss (it IS real P&L) and contributes `0.0` to `total_fees`, but the cell is **flagged**, a loud
`gross_pnl_rows_total` is printed, and EVIDENCE.md states plainly that those rows' `realized_pnl` is **not
fee-adjusted**. **Still never subtract fees** (`src/pnl.py:28` already returned `gross - fees` at the two
writers that pass them — subtracting again would double-charge those rows). Just stop claiming the number
is uniformly net. Phase 17 does **not** fix the writers: that is a bot-behavior change, out of scope. A
non-zero `gross_pnl_rows_total` is a **finding for Phase 18/20**.

### C3 (prod safety) — the DB-gated test must use `TEST_DATABASE_URL`, never `DATABASE_URL`

The real-SQL case **SEEDS rows**. `DATABASE_URL` is **PROD** (Coolify Postgres). Gating the seeding test on
`DATABASE_URL` would insert synthetic trades into the live trade log. **Gate on `TEST_DATABASE_URL` ONLY,
and assert at runtime that `TEST_DATABASE_URL != DATABASE_URL`.** Separately: **EVIDENCE.md MAY read prod —
SELECT-only, via `get_resolved_trades` / `get_realized_pnl` — never via the seeding test.**

### C4 (recorded, not fixed) — a FOURTH status-set spelling is live in the entry cooldown

`src/db.py:201` `get_recent_loss_symbols` filters `status IN ('closed', 'stopped')` — it **drops
`'target_hit'`**, so a symbol that exited at a target is invisible to the re-entry cooldown. Phase 17
changes no bot behavior; record it in EVIDENCE.md as a **Phase-18/20 finding**.

---

## Summary

Phase 17 is the first phase entitled to compute statistics from the trade log, because Phases 11–14 made
the log trustworthy. Every ingredient exists: `alpaca_trades.pnl`/`fees` (`src/db.py:101-122`, migration
`016`), `src/universe.py:17` `normalize()` as the group key, `src/effective_universe.py:115`
`resolve_universe()` for the annotation. **No new dependency, no new column, no migration, no view.**

Four traps, all confirmed in code:

1. **A `rejected` row carries `pnl = 0`, NOT NULL** (`src/bot_thread.py:309,317,332`). Post-Phase-15 a gate
   block is exactly what produces one. The terminal-status filter is what stands between the report and a
   fabricated loss column for every quarantined symbol.
2. **A `closed` row can ALSO carry `pnl = 0.0`** (C1 — the external-exit sentinel). The status filter does
   **not** catch this one. → `zero_pnl` bucket, never scored.
3. **`pnl` is NOT uniformly net of fees** (C2). NULL `fees` ⇒ probably GROSS `pnl`. → `gross_pnl_rows`
   disclosure; never subtract fees.
4. **`timestamp` is `TEXT`** (`src/db_schema.sql:28`). The window filter **and the ORDER BY** need
   `"timestamp"::timestamptz` (precedent `src/db.py:168`, `:204`), never a lexicographic compare.

**Primary recommendation:** `db.get_resolved_trades(bot_id=None, since=None)` — one parameterized read-only
SELECT filtered to the position-closed terminal set — feeding `symbol_stats.aggregate(rows, min_sample=5)`,
a pure function that normalizes, buckets (win / loss / zero_pnl / null_pnl), flags `gross_pnl_rows`, and
stamps `sample: sufficient|insufficient`; `scripts/symbol_report.py` prints markdown + writes
`EVIDENCE.md`. Mirror `scripts/backfill_trades.py` for the CLI shape, **minus `--apply`, which must not
exist**.

## Architectural Responsibility Map

| Capability | Primary Tier | Rationale |
|------------|-------------|-----------|
| Terminal-status filtering + window slice | Database (one SELECT in `src/db.py`) | SQL selects. Mirrors the `get_alpaca_accuracy` / `get_realized_pnl` status set verbatim so the definition lives once. |
| Symbol normalization (group key) | Shared domain (`src/universe.py::normalize`) | Already the gate's canonicalizer; re-deriving forks the key. |
| Win/loss/zero/null bucketing, fee qualification, sample guard, expectancy | Pure Python (`src/symbol_stats.py`) | Python decides. Pure ⇒ unit-testable on fixtures with zero DB. |
| Quarantine / off-universe annotation | Shared domain (`src/effective_universe.py::resolve_universe`) | The gate's own answer; Phase 17 annotates, never re-derives. |
| Presentation (markdown, JSON, EVIDENCE.md) | CLI (`scripts/symbol_report.py`) | Analysis artifact, not a dashboard surface (Phase 19 owns the headline). |
| **Deciding what to quarantine** | **Phase 18 — NOT this phase** | Report may rank; it may not verdict. |

---

## 1. The read-only query — `db.get_resolved_trades`

**Terminal sets, read from code (do not invent yet another spelling):**

| Set | Members | Source |
|---|---|---|
| Position-closed (**the sample**) | `'closed'`, `'stopped'`, `'target_hit'` | `src/db.py:215` (`get_alpaca_accuracy`), `:256-257` (`get_realized_pnl`) |
| Terminal non-position (**never a trade**) | `'canceled'`, `'cancelled'`, `'expired'`, `'rejected'` | `src/order_resolution.py:11` `_TERMINAL_NONPOSITION` |
| Non-terminal | `'open'`, `'submitted'` | `src/db.py:151-191` |
| **(C4 — a FOURTH, divergent spelling, live in the cooldown)** | `'closed'`, `'stopped'` | `src/db.py:201` `get_recent_loss_symbols` — **drops `target_hit`**. Not fixed here; reported. |

**Schema** (`src/db_schema.sql:24-51`): `pnl` and `fees` are `DOUBLE PRECISION` **NULLable**; `timestamp`
and `closed_at` are **TEXT**. [VERIFIED: codebase]

**The query (plan of record — note the ORDER BY cast, W1):**

```python
def get_resolved_trades(bot_id: str | None = None, since=None) -> list[dict]:
    """Position-closed rows for per-symbol stats (TUNE-02). READ-ONLY.

    Terminal set mirrors get_alpaca_accuracy/get_realized_pnl exactly:
    ('closed','stopped','target_hit'). Non-position terminals
    (canceled/cancelled/expired/rejected) are NOT trades — a Phase-15 gate block
    writes a 'rejected' row with pnl=0 (bot_thread.py:309), which would otherwise
    score as a LOSS.

    NOTE: a 'closed' row may ALSO carry pnl=0.0 — the external-exit sentinel at
    alpaca_orchestrator.py:167-176 (also bot_c/strategy.py:393,
    trend_strategy.py:172). SQL cannot distinguish that from a real flat trade,
    so symbol_stats buckets it into zero_pnl. NULL pnl is returned as-is, never
    coerced (db.py:228,259 coerce; this must NOT).
    """
    sql = [
        "SELECT bot_id, symbol, asset_class, side, status, pnl, fees, "
        '       "timestamp" AS entry_ts, closed_at',
        "FROM alpaca_trades",
        "WHERE status IN ('closed', 'stopped', 'target_hit')",   # src/db.py:215
    ]
    params: list = []
    if bot_id:
        sql.append("AND bot_id = %s")
        params.append(bot_id)
    if since is not None:                                  # datetime or ISO str
        sql.append('AND "timestamp"::timestamptz >= %s')   # TEXT column — MUST cast
        params.append(since)
    sql.append('ORDER BY "timestamp"::timestamptz ASC')    # W1 — not a lexicographic TEXT sort
    with connection() as conn:
        return conn.execute("\n".join(sql), tuple(params)).fetchall()
```

- `%s` parameterization only — **never** f-string `bot_id` or `since`.
- `connection()` yields psycopg3 `dict` rows (`row_factory=dict_row`, `src/db.py:29`) — so `aggregate()`
  takes plain dicts and test fixtures ARE rows. That is what makes the pure function testable with zero DB.
- Windowing is on `"timestamp"` (**entry** time, CONTEXT decision 6) — a trade belongs to the regime that
  entered it.

## 2. Fee semantics — **MIXED**, and the report must say so (C2)

- `realized_pnl` = `SUM(pnl)`. **NEVER `SUM(pnl) - SUM(fees)`** — the orchestrator/backfill rows are
  already net (`src/pnl.py:28`), so subtracting again double-charges them.
- `total_fees` = `SUM(fees)` (NULL → `0.0`) — **drag disclosure only, and INCOMPLETE**: the Bot-C and trend
  writers pass no fees at all.
- **`fees IS NULL` on a counted row ⇒ that row's `pnl` is probably GROSS** ⇒ `gross_pnl_rows += 1`. Print
  `gross_pnl_rows_total`. EVIDENCE.md must say: *the realized_pnl for these rows is not fee-adjusted.*
- `TAKER_FEE` (`src/fee_gate.py:16`) is reference only — Phase 17 recomputes nothing.

## 3. Normalization — the group key

`src/universe.py:17-23`: `normalize(symbol) -> (symbol or "").strip().upper().replace("/", "")`.
Alpaca-sourced rows are slashless, config-sourced rows are slashed. **Group on
`normalize(row["symbol"])`**; keep the first-seen raw spelling as `display` (the pattern
`src/effective_universe.py:151-157` uses). Grouping raw splits BTC into two fake cells, halves both
samples, and hides BTC's P&L behind `insufficient`. [VERIFIED: codebase]

## 4. `symbol_stats.aggregate` — the pure core

```python
MIN_SAMPLE = 5      # module constant, overridable via kwarg (CONTEXT decision 3)

def aggregate(rows, min_sample: int = MIN_SAMPLE, key=("bot_id", "symbol")) -> list[dict]: ...
```

Per-cell fields: `bot_id`, `symbol` (normalized), `display`, `asset_class`, `trades`, `wins`, `losses`,
`win_rate`, `realized_pnl`, `total_fees`, `avg_win`, `avg_loss`, `expectancy`, `best`, `worst`,
`first_trade`, `last_trade`, **`zero_pnl`**, `null_pnl`, **`gross_pnl_rows`**, `null_fees`, `sample`.

**Bucketing — a position-closed row lands in exactly ONE bucket:**

| Bucket | Condition | Counted? | Why |
|---|---|---|---|
| win | `pnl > 0` | yes | mirrors `get_alpaca_accuracy` (`src/db.py:228`) |
| loss | `pnl < 0` | yes | — |
| **zero_pnl** | `pnl == 0.0` | **NO** | **C1** — indistinguishable from the external-exit sentinel (`alpaca_orchestrator.py:167-176`). Scoring it as a loss fabricates a losing record on every externally-exited position. |
| **null_pnl** | `pnl is None` | **NO** | a resolution defect; coercing it to `0.0` (what `db.py:228,259` do with `or 0`) makes a broken row read as break-even |

| Rule | Definition |
|---|---|
| `trades` | rows whose `pnl` is **not None and not 0.0** (= `wins + losses`) |
| `realized_pnl` | `sum(pnl)` over counted rows |
| `avg_win` | `sum(pnl>0)/wins`, `0.0` when `wins == 0` |
| `avg_loss` | `sum(pnl<0)/losses`, `0.0` when `losses == 0` — **carried NEGATIVE** |
| `expectancy` | `win_rate*avg_win + (1-win_rate)*avg_loss` — **INVARIANT: `== realized_pnl / trades`** |
| `gross_pnl_rows` | counted rows with `fees is None` (**C2** — `pnl` probably GROSS) |
| `total_fees` | `sum(fees)`, NULL → `0.0` (**incomplete — see `gross_pnl_rows`**) |
| `sample` | `"sufficient"` if `trades >= min_sample` else `"insufficient"` — cell is **still emitted** |
| zero denominators | every ratio `0.0`; `aggregate([]) == []`; no `ZeroDivisionError` |

Use `row["pnl"] is None` and `row["pnl"] == 0.0` **explicitly**. The `or 0` idiom cannot even distinguish
NULL from a genuine `0.0` — precisely the bug C1 exposes.

**Roll-ups:** the same `aggregate()` with `key=("symbol",)` / `key=("bot_id",)`. A per-bot roll-up will
**not** equal `db.get_realized_pnl(bot_id)` when NULL-pnl **or zero-pnl** rows exist (that function coerces
NULL to `0.0` and sums sentinel zeros). **Print both + the delta.** Do not reconcile; do not modify
`get_realized_pnl`.

## 5. Annotation — `already_quarantined` / `off_universe` (CONTEXT decision 8)

`src/effective_universe.py:115-203` `resolve_universe(cfg, ...)` returns
`blocked: [{symbol, reason, open_positions, recent_trades}]` with
`reason ∈ {quarantined, off_universe, meme, untradeable}` (`:164-170` — the gate's own answer). Build `cfg`
per bot via `BotConfig.from_row(row)` over `SELECT * FROM bots` — **without** the `enabled = TRUE` filter (a
disabled bot with historical trades must still be annotated); a cell whose bot row is missing is stamped
`annotation: "unavailable"`, never a silent blank. Index `blocked` by `normalize(symbol)`; match through
`normalize()` on **both** sides.

The report **ranks** by `expectancy` over **`sufficient` cells only**. It **must not** emit a "quarantine
this" verdict — Phase 18 decides.

## 6. The CLI — `scripts/symbol_report.py`

Mirror `scripts/backfill_trades.py` (module docstring with usage lines, `argparse`, `main() -> int`,
`sys.exit(main())`, fixed-width `print` table):

```
python scripts/symbol_report.py                      # all bots, FULL HISTORY (default)
python scripts/symbol_report.py --bot A --window 90
python scripts/symbol_report.py --json
python -m scripts.symbol_report
```
Flags: `--bot`, `--window <days>` (`type=int`), `--min-sample` (default `5`), `--json`.
**`--apply` does not exist. There is no write path.**
`--window` computes `since = datetime.now(timezone.utc) - timedelta(days=N)`; **default is full history** (a
short default would starve the sample guard). Run **both** `--window 90` and the default for evidence.

Summary lines (always printed, even at zero): `null_pnl_total`, **`zero_pnl_total`**,
**`gross_pnl_rows_total`**, `null_fees_total`; the per-bot `symbol_stats realized_pnl` vs
`db.get_realized_pnl` vs `delta` comparison; and the C4 note.

## 7. Migration needed?

**No.** (CONTEXT decision 5.) Highest existing migration is `018`; **`019` stays free.** A SQL VIEW would
freeze the terminal-status set and the bucketing rules in a second place and they would drift.

---

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---|---|---|---|
| Symbol group key | inline `.upper().replace("/","")` | `src.universe.normalize` (`:17`) | one canonicalizer, shared with the gate |
| Terminal-status set | a new tuple literal | copy `src/db.py:215` **and cite it** | this repo already has FOUR spellings (C4) — do not add a fifth |
| Realized P&L | recompute from fills | read the stored `alpaca_trades.pnl` | Phase 12 owns the math |
| Fee-netting | `pnl - fees` | `pnl` **as stored** + a `gross_pnl_rows` flag | two writers netted; two never did (C2) |
| Zero-pnl rows | score as a loss | the `zero_pnl` bucket | C1 — the external-exit sentinel |
| NULL-pnl handling | `pnl or 0.0` | `if row["pnl"] is None: null_pnl += 1; continue` | `or 0` cannot distinguish NULL from a real `0.0` |
| Quarantine/universe status | re-deriving set math | `resolve_universe` (`:115`) | the gate's answer |
| Bot enumeration | `("A","B")` | `SELECT * FROM bots` (no `enabled` filter — §5) | bots C/D/E exist; disabled bots still have history |
| CLI scaffolding | a new pattern | copy `scripts/backfill_trades.py` (minus `--apply`) | established convention |

## Common Pitfalls

1. **A Phase-15 gate block scores as a LOSS.** `rejected` rows carry `pnl=0` (`bot_thread.py:309`). Filter
   in SQL **and** re-filter in `aggregate()`. Assert `aggregate(only_nonposition_rows) == []` — an *empty
   list*, not "every emitted cell has trades==0" (which passes vacuously on `[]`).
2. **(C1) An external-exit sentinel scores as a LOSS.** `closed` + `pnl=0.0` passes the status filter.
   Bucket `pnl == 0.0` into `zero_pnl`; never score it.
3. **(C2) Claiming `realized_pnl` is net.** Two of four writers store GROSS `pnl` with NULL `fees`. Flag
   `gross_pnl_rows`; never subtract fees.
4. **`"timestamp"::timestamptz` omitted** — in the WHERE **and** the ORDER BY. A lexicographic TEXT compare
   mis-filters/mis-sorts silently.
5. **Grouping on the raw `symbol`** — splits BTC in half.
6. **MIN_SAMPLE hides the leak.** `insufficient` suppresses the **verdict**, not the **row**.
7. **`expectancy` sign drift** — a positive `avg_loss` makes expectancy always ≥ 0 and always wrong. The
   `expectancy == realized_pnl / trades` invariant catches it.
8. **A vacuous read-only fence.** The grep test must carry a **positive control** (assert the sliced source
   is non-empty and contains `SELECT bot_id, symbol`) **plus a self-test** proving the regex fires against
   `update_alpaca_trade` — otherwise an empty slice passes green while `db.py` is full of INSERT/UPDATE
   (`:70`, `:118`, `:283`, `:347`).
9. **(C3) Seeding prod.** The real-SQL test SEEDS rows: gate it on `TEST_DATABASE_URL` only, and assert
   `TEST_DATABASE_URL != DATABASE_URL`.

## Anti-Patterns to Avoid

- **A SQL `GROUP BY` doing the aggregation** — it buries the bucketing rules in a string no unit test can
  reach. SQL selects, Python decides.
- **Adding a dashboard panel** — Phase 19 owns the headline.
- **Emitting a "quarantine XYZ" verdict** — rank, annotate, stop.
- **Importing `src.db` into `symbol_stats.py`** — a layering violation that blocks fixture-only tests.
- **"Fixing" the gross-pnl writers or `get_recent_loss_symbols`** — bot-behavior changes. Report them.

## Environment Availability

| Dependency | Required by | Available |
|---|---|---|
| psycopg3 + psycopg_pool | the one SELECT | ✓ (`src/db.py:14-16`) |
| `src/universe.py::normalize` | group key | ✓ (Phase 15) |
| `src/effective_universe.py::resolve_universe` | annotation | ✓ (Phase 16) |
| `alpaca_trades.pnl`/`fees` | the data | ✓ (Phase 12, migration 016) |
| pytest 8.3.5 | tests | ✓ |
| **LOCAL** Postgres via `TEST_DATABASE_URL` | the one DB-gated SQL test | conditional — skipif; **never `DATABASE_URL`** |
| Alpaca SDK / network | — | **not used** — Phase 17 makes zero network calls |

**No new package** → Package Legitimacy Audit **N/A**.

## Validation Architecture

Full case table: `.planning/phases/17-per-symbol-performance/17-VALIDATION.md` (**Revision 2**).
Quick run `python -m pytest tests/test_symbol_stats.py -x -q`; full suite
`python -m pytest tests/ dashboard/api/tests/ -q` — **baseline 373 passed / 9 skipped**.

**Wave 0 gaps:** `tests/test_symbol_stats.py` (RED first — the `ImportError` on `src.symbol_stats` is the
proof), `src/symbol_stats.py`, `src/db.py::get_resolved_trades`, `scripts/symbol_report.py`.

## Security Domain

| ASVS | Applies | Control |
|---|---|---|
| V4 Access control | yes | **Read-only by construction.** No write path in the new code; the fence is grep-verifiable **with a positive control + a self-test**. |
| V5 Input validation | yes | `--bot` / `--window` reach SQL **only** as psycopg `%s` params. `--window` is `type=int`. |
| Secret leakage | yes | Report fields enumerated explicitly — **no `**row` splat** (a `bots` row carries alpaca keys). EVIDENCE.md is committed to git. |
| Prod integrity | yes | The seeding test is gated on `TEST_DATABASE_URL` and asserts it `!= DATABASE_URL`. |

| Threat | STRIDE | Mitigation |
|---|---|---|
| SQL injection via `--bot` | Tampering | parameterized `%s` |
| Accidental prod-row mutation | Tampering | no write path; non-vacuous grep fence; the seeding test can never point at prod |
| Fabricated losses (gate blocks / external-exit sentinels) | Repudiation | status filter (SQL **and** Python) **plus** the `zero_pnl` bucket |
| Overstated P&L read as net | Repudiation | `gross_pnl_rows` disclosure |
| Secrets in `EVIDENCE.md` | Information disclosure | explicit field list; artifact grepped for key/secret/token before commit |

## Assumptions Log

| # | Claim | Risk if wrong |
|---|---|---|
| A1 | Non-position terminals never carry real P&L | They never held a position by definition (`order_resolution.py:11`). The SQL filter is correct either way. |
| A2 | **A `closed` row with `pnl == 0.0` cannot be distinguished from the external-exit sentinel** | If a genuine flat trade exists, it is excluded from `trades` and counted into `zero_pnl`. **That is the intended conservative choice** — the alternative fabricates a loss on every externally-exited position (C1). |
| A3 | **NULL `fees` on a counted row ⇒ `pnl` is GROSS** | Verified for the two writers that omit `fees` (`bot_c/strategy.py:393`, `trend_strategy.py:172`). Pre-Phase-12 rows may also carry NULL fees with a net `pnl` — in which case `gross_pnl_rows` over-reports, the safe direction: it flags for review, it does not alter a number. |
| A4 | Full-suite baseline 373 passed / 9 skipped | Re-run at Wave 0 to confirm. |

## Sources (all re-read at file:line this session)

- `src/alpaca_orchestrator.py:167-176` — **the external-exit sentinel: `status="closed", pnl=0.0`** (C1)
- `src/alpaca_orchestrator.py:310-318` — the NET writer (`pnl=realized`, `fees=fees`)
- `src/bot_c/strategy.py:388-396` — **GROSS `pnl`, no `fees` arg** (C2)
- `src/trend_strategy.py:166-174` — **GROSS `pnl`, no `fees` arg** (C2)
- `src/backfill.py:80-86` — the other NET writer
- `src/db.py:101-122` — `update_alpaca_trade` (`fees` defaults to `None`, written as NULL)
- `src/db.py:194-208` — `get_recent_loss_symbols`, `status IN ('closed','stopped')` (**C4**)
- `src/db.py:211-241` — `get_alpaca_accuracy` (the status set; the `or 0` coercion NOT to copy)
- `src/db.py:246-259` — `get_realized_pnl` (the terminal set of record; coerces NULL to 0.0)
- `src/bot_thread.py:309,317,332` — `rejected` rows carry `pnl=0`
- `src/order_resolution.py:11` — `_TERMINAL_NONPOSITION`
- `src/pnl.py:10-28` — `gross - fees`
- `src/db_schema.sql:24-51` — `timestamp TEXT`; `pnl`/`fees` NULLable
- `src/universe.py:17-23`, `src/effective_universe.py:115-203`
- `scripts/backfill_trades.py:1-46` — CLI convention

**Research date:** 2026-07-12 · **Revision 2** · **Valid until:** 2026-08-11 (invalidated by any change to
the terminal-status set, the `update_alpaca_trade` call sites, `src/pnl.py`, or `alpaca_trades`)
