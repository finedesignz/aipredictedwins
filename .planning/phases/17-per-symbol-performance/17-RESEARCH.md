# Phase 17: Per-Symbol Performance Analysis (TUNE-02) — Research

**Researched:** 2026-07-12
**Domain:** Read-only aggregation over `alpaca_trades` — one SELECT in `src/db.py`, one pure module `src/symbol_stats.py`, one CLI `scripts/symbol_report.py`
**Confidence:** HIGH (everything below is read from this repo at the cited file:line; no external deps, no new packages, no migration)

## Summary

Phase 17 is the first phase entitled to compute statistics from the trade log, because Phases 11–14
made the log trustworthy. Every ingredient already exists: `alpaca_trades.pnl` holds fill-derived,
fee-net realized P&L (`src/pnl.py:10-28`, persisted via `src/db.py:101-122`), `alpaca_trades.fees`
holds the gross fee, `src/universe.py:17` `normalize()` is the group-by key, and
`src/effective_universe.py:115` `resolve_universe()` supplies the `already_quarantined` /
`off_universe` annotation. There is **no new dependency, no new column, no migration, no view**.

Three real traps, all confirmed in code:

1. **A `rejected` row carries `pnl = 0`, NOT NULL.** `src/bot_thread.py:309,317,332` writes
   `logger.update_alpaca_trade(trade_id, "rejected", pnl=0)` on three failure paths. Under the locked
   win definition (`pnl > 0` is a win; `pnl == 0.0` is a loss), a `rejected` row that leaked into the
   sample would count as a **loss** — and post-Phase-15 a gate block is exactly what produces a
   `rejected` row. The terminal-status filter (`status IN ('closed','stopped','target_hit')`) is not a
   nicety; it is the thing standing between the report and a fabricated loss column.
2. **`alpaca_trades.pnl` is already NET of fees.** `src/pnl.py:19-28` returns `gross - fees`, and the
   two writers (`src/alpaca_orchestrator.py:310-318`, `src/backfill.py:83-84`) compute `fees` and
   `realized` from the same expression and store both. So `realized_pnl = SUM(pnl)` is the net number;
   `total_fees = SUM(fees)` is **informational drag, and must NEVER be subtracted again**. Double-
   subtracting fees is the single easiest way to make this report lie.
3. **`timestamp` is `TEXT`** (`src/db_schema.sql:28`). Any window filter needs
   `"timestamp"::timestamptz` (precedent `src/db.py:168`, `src/db.py:204`), never a raw string compare.

**Primary recommendation:** `db.get_resolved_trades(bot_id=None, since=None)` — one parameterized
read-only SELECT filtered to the position-closed terminal set — feeding
`symbol_stats.aggregate(rows, min_sample=5)`, a pure function that normalizes, groups, and stamps
`sample: sufficient|insufficient`; `scripts/symbol_report.py` prints markdown + writes `EVIDENCE.md`.
Mirror `scripts/backfill_trades.py` for the CLI shape, minus `--apply` (which must not exist).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Terminal-status filtering + window slice | Database (one SELECT in `src/db.py`) | — | SQL selects. Mirrors `get_alpaca_accuracy`/`get_realized_pnl` status set verbatim so the definition lives once. |
| Symbol normalization (group-by key) | Shared domain (`src/universe.py::normalize`) | — | `BTC/USD` vs `BTCUSD` — already the gate's canonicalizer; re-deriving it here forks the key. |
| Win/loss/expectancy math, sample guard, NULL accounting | Pure Python (`src/symbol_stats.py`) | — | Python decides. Pure ⇒ unit-testable on fixtures with zero DB, per Phases 12/13. |
| Quarantine / off-universe annotation | Shared domain (`src/effective_universe.py::resolve_universe`) | — | The gate's own answer; Phase 17 annotates, never re-derives. |
| Presentation (markdown table, JSON, EVIDENCE.md) | CLI (`scripts/symbol_report.py`) | — | Analysis artifact, not a dashboard surface (RUN-02/Phase 19 owns the headline). |
| **Deciding what to quarantine** | **Phase 18 — NOT this phase** | — | Report may rank; it may not verdict. |

---

## 1. The read-only query — `db.get_resolved_trades`

**Terminal sets, read from code (do not invent a third spelling):**

| Set | Members | Source |
|---|---|---|
| Position-closed (**the sample**) | `'closed'`, `'stopped'`, `'target_hit'` | `src/db.py:215` (`get_alpaca_accuracy`), `src/db.py:256-257` (`get_realized_pnl`, whose docstring at `:249-252` is explicit that summing `'closed'` alone drops every stop/target exit) |
| Terminal non-position (**never a trade**) | `'canceled'`, `'cancelled'`, `'expired'`, `'rejected'` | `src/order_resolution.py:11` `_TERMINAL_NONPOSITION`; full terminal list also at `src/db.py:111` |
| Non-terminal | `'open'`, `'submitted'` | `src/db.py:151-172`, `:175-191` |

**Schema** (`src/db_schema.sql:24-51`): `id, source_id, bot_id, timestamp TEXT, symbol, asset_class,
side, qty, entry_price, mirofish_prob, market_sentiment, target_price, stop_loss, status, exit_price,
pnl, closed_at TEXT, simulation_id, notes, order_id, order_type, filled_qty, filled_avg_price, fees`.
`pnl` and `fees` are both `DOUBLE PRECISION` **NULLable**. [VERIFIED: codebase]

**The query (plan of record):**

```python
def get_resolved_trades(bot_id: str | None = None, since=None) -> list[dict]:
    """Position-closed rows for per-symbol stats (TUNE-02). READ-ONLY.

    Terminal set mirrors get_alpaca_accuracy/get_realized_pnl exactly:
    ('closed','stopped','target_hit'). Non-position terminals
    (canceled/expired/rejected) are NOT trades — a Phase-15 gate block writes a
    'rejected' row with pnl=0 (bot_thread.py:309), which would otherwise score
    as a LOSS. NULL pnl is returned as-is, never coerced (see symbol_stats).
    """
    sql = [
        "SELECT bot_id, symbol, asset_class, side, status, pnl, fees, "
        '       "timestamp" AS entry_ts, closed_at',
        "FROM alpaca_trades",
        "WHERE status IN ('closed', 'stopped', 'target_hit')",
    ]
    params: list = []
    if bot_id:
        sql.append("AND bot_id = %s")
        params.append(bot_id)
    if since is not None:                     # datetime or ISO str
        sql.append('AND "timestamp"::timestamptz >= %s')
        params.append(since)
    sql.append('ORDER BY "timestamp" ASC')
    with connection() as conn:
        return conn.execute("\n".join(sql), tuple(params)).fetchall()
```

Notes:
- `timestamp` is a **SQL reserved-ish word** and is quoted throughout the codebase
  (`dashboard/api/routes/bots.py:93-104`); quote it here too.
- `%s` parameterization only — never f-string `bot_id`.
- `connection()` yields psycopg3 rows as `dict` (`row_factory=dict_row`, `src/db.py:29`), so
  `aggregate()` takes plain dicts and the fixtures in tests are plain dicts. That is what makes the
  pure function testable with zero DB.
- **Windowing is on `"timestamp"` (entry time), per CONTEXT decision 6** — a trade belongs to the
  regime that entered it. `closed_at` is also TEXT (`src/db.py:204` casts it) — do not sort on it.

## 2. `pnl` semantics — net of fees. Do not double-subtract.

`src/pnl.py:10-28`:
```python
fees  = (entry_fill * qty + exit_fill * qty) * taker_fee
return gross - fees          # <- stored into alpaca_trades.pnl
```
Both writers store the pair: `src/alpaca_orchestrator.py:310-318` and `src/backfill.py:83-84` compute
`fees = (entry_fill*qty + exit_fill*qty) * TAKER_FEE` and `realized = realized_pnl(...)`, then
`update_alpaca_trade(status=..., pnl=realized, fees=fees)` (`src/db.py:101-122` persists both columns).
`TAKER_FEE = float(os.environ.get("TAKER_FEE", "0.0025"))` (`src/fee_gate.py:16`). [VERIFIED: codebase]

**Therefore:**
- `realized_pnl` (this report) = `SUM(pnl)` = already net. ✅
- `total_fees` = `SUM(fees)` = **drag disclosure only**. Report it beside `realized_pnl`; never
  `realized_pnl - total_fees`. Say so in the module docstring and pin it with a test.
- `fees` may be **NULL** on rows closed before Phase 12 / by the non-fill close paths. Treat NULL fees
  as `0.0` for the `total_fees` sum (a missing fee is not a data lie about the P&L, because `pnl` was
  already computed net wherever it exists) but count them in a `null_fees` field so the drag number is
  honestly qualified. **This is different from NULL `pnl`, which is excluded — see §4.**

## 3. Normalization — the group-by key

`src/universe.py:17-23`:
```python
def normalize(symbol): return (symbol or "").strip().upper().replace("/", "")
```
`BTC/USD` / `btc/usd` / `BTCUSD` → `BTCUSD`; total on `None`/`""`. Alpaca-sourced rows are slashless,
config-sourced rows are slashed (`tests/test_universe.py:6-10`; `src/copytrade_thread.py:388`
normalizes for exactly this reason). **Group on `normalize(row["symbol"])`.** Keep the first-seen raw
spelling as `display` (the pattern `src/effective_universe.py:151-157` already uses) so the report
renders `BTC/USD` while grouping `BTCUSD`. Grouping on the raw column would split BTC into two fake
symbols and halve both samples — the exact failure the MIN_SAMPLE guard would then hide. [VERIFIED: codebase]

## 4. `symbol_stats.aggregate` — the pure core

```python
MIN_SAMPLE = 5      # module constant, overridable via kwarg (CONTEXT decision 3)

def aggregate(rows, min_sample: int = MIN_SAMPLE, key=("bot_id", "symbol")) -> list[dict]: ...
```

Per-cell fields (CONTEXT decision 2): `bot_id`, `symbol` (normalized), `display`, `asset_class`,
`trades`, `wins`, `losses`, `win_rate`, `realized_pnl`, `total_fees`, `avg_win`, `avg_loss`,
`expectancy`, `best`, `worst`, `first_trade`, `last_trade`, `null_pnl`, `sample`.

**Locked definitions — pin each with a test:**

| Rule | Definition | Why |
|---|---|---|
| Win | `pnl > 0` | Mirrors `get_alpaca_accuracy` (`src/db.py:228`: `(r["pnl"] or 0) > 0`) so the definition cannot drift. |
| Loss | `pnl <= 0`, **including `pnl == 0.0`** | Flat is not a win after fees. Also: `pnl` is already fee-net, so a true `0.0` means the fees ate the whole move. |
| `trades` | rows with **non-NULL** `pnl` in the cell | NULL pnl is excluded from every statistic (below). |
| `realized_pnl` | `sum(pnl)` over non-NULL | Already net of fees. |
| `avg_win` | `sum(pnl for pnl>0) / wins`, `0.0` when `wins == 0` | — |
| `avg_loss` | `sum(pnl for pnl<=0) / losses`, `0.0` when `losses == 0` — **carried negative** | Sign discipline is what makes the invariant hold. |
| `expectancy` | `win_rate*avg_win + (1-win_rate)*avg_loss` | **INVARIANT: `expectancy == realized_pnl / trades`** — algebraically identical; the unit test asserts both expressions with `pytest.approx`. If they diverge, the sign convention or the NULL handling broke. |
| `sample` | `"sufficient"` if `trades >= min_sample` else `"insufficient"` | Cell is still **reported** (hiding it hides a TRUMP-shaped leak), just never callable a winner/loser. |
| Empty cell / zero trades | every ratio `0.0`, never `ZeroDivisionError` | Guard every denominator, as `src/db.py:236-238` already does. |

**NULL `pnl` on a position-closed row (CONTEXT decision 7 — the anti-`get_alpaca_accuracy` rule):**
`get_alpaca_accuracy` coerces with `r["pnl"] or 0` (`src/db.py:228,230`) and `get_realized_pnl` with
`(r["pnl"] or 0.0)` (`src/db.py:259`). **Phase 17 must NOT.** A NULL `pnl` on a `closed`/`stopped`/
`target_hit` row is a *resolution defect* (post-Phase-14 it should not exist); coercing it to 0.0 makes
a broken row read as a break-even trade — the exact class of lie this milestone exists to kill.
Handling: **exclude it from `trades`/`wins`/`losses`/`realized_pnl`/`expectancy`, count it into
`null_pnl` per cell, and sum a loud `null_pnl_total` summary line in the report.** Non-zero ⇒ a finding
handed to Phase 18/20, not fixed here.

Note the `or 0` idiom is ALSO wrong for a legitimate `0.0` (Python falsy) — but since `0.0` and NULL
both coerce to `0`, `get_alpaca_accuracy` cannot distinguish them at all. Phase 17 uses
`row["pnl"] is None` explicitly. [VERIFIED: codebase]

**Roll-ups** (CONTEXT decision 2): the same `aggregate()` invoked with a different group key —
`("bot_id","symbol")` (cells), `("symbol",)` (all-bots per-symbol), `("bot_id",)` (per-bot). Make the
key a kwarg so the deferred per-confluence-score / per-side breakdowns (CONTEXT deferred) are a kwarg,
not a rewrite. A per-bot roll-up computed this way must equal `db.get_realized_pnl(bot_id)` **only up
to the NULL-pnl rows** — that discrepancy is a feature, and is worth an assertion in the report
(`realized_pnl + (null_pnl_total rows) == get_realized_pnl`), since `get_realized_pnl` coerces.

## 5. Annotation — `already_quarantined` / `off_universe` (CONTEXT decision 8)

`src/effective_universe.py:115-203` `resolve_universe(cfg, *, exposure=None, exposure_loaded=True,
meme=None, untradeable=None) -> dict` returns `allowlist`, `quarantined`, `effective`,
`blocked: [{symbol, reason, open_positions, recent_trades}]`, `starvation`, `leak`, `shadow_applied`,
`shadow_sets_loaded`, `exposure_loaded`. `reason ∈ {quarantined, off_universe, meme, untradeable}`
(`:164-170` — the gate's own `entry_allowed`, never re-derived).

For the report: build `cfg` per bot with `BotConfig.from_row(row)` over a `SELECT ... FROM bots`, call
`resolve_universe(cfg)` (no `exposure` needed — Phase 17 does not do leak detection), and index
`blocked` by `normalize(symbol)` to stamp each cell with `already_quarantined` (reason
`quarantined`) and `off_universe` (reason `off_universe` / `meme` / `untradeable`). Symbol-key match
**must** go through `normalize()` on both sides.

The report **ranks** by `expectancy` (sufficient cells only). It **must not** emit a "quarantine this"
verdict — that is Phase 18.

## 6. The CLI — `scripts/symbol_report.py`

Mirror `scripts/backfill_trades.py` exactly (module docstring with usage lines, `argparse`, `main()
-> int`, `sys.exit(main())`, fixed-width `print` table, importable-logic-lives-in-`src`):

```
python scripts/symbol_report.py                      # all bots, full history
python scripts/symbol_report.py --bot A --window 90
python scripts/symbol_report.py --json
python -m scripts.symbol_report
```
Flags: `--bot`, `--window <days>`, `--min-sample` (default `5`), `--json`.
**`--apply` does not exist. There is no write path.** Backfill's `--apply`/dry-run split is the shape
to mirror *structurally*; the write half is deliberately absent.
`--window` computes `since = datetime.now(timezone.utc) - timedelta(days=N)` and passes it to
`get_resolved_trades`; **default is full history** (CONTEXT decision 6 — a short default would starve
the sample guard). Recommend running both `--window 90` and default in the evidence pass.

Bot enumeration: `src/reconciliation.py:51-59` `_enabled_bot_ids()` (`SELECT bot_id FROM bots WHERE
enabled = TRUE ORDER BY bot_id`) is the house convention — **not** an `A`/`B` hardcode, and **not**
`dashboard/api/db.py`'s `KNOWN_BOTS = ("A","B","C","D")` (which omits E). But note `get_resolved_trades`
with `bot_id=None` already returns every bot's rows in one query; bot enumeration is only needed for
the §5 `bots`-row annotation. [VERIFIED: codebase]

Output artifact: `.planning/phases/17-per-symbol-performance/EVIDENCE.md` (markdown table + summary
lines). Writing a `.planning/` file is not a prod-DB write and is in scope.

## 7. Migration needed?

**No.** (CONTEXT decision 5.) `pnl` + `fees` → `dashboard/api/migrations/016_realized_pnl_fees.sql`
(mirrored `src/db_schema.sql:49-50`); `order_id`/`order_type`/`filled_*` → `015` (`:44-48`);
`quarantined_symbols` → `018`. Highest existing is `018`; next free is `019` — **and it stays free.**
A SQL VIEW would freeze the terminal-status set and the win definition in a second place and they
would drift. [VERIFIED: codebase]

---

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---|---|---|---|
| Symbol comparison / group key | `.upper()` / `.replace("/","")` inline | `src.universe.normalize` (`src/universe.py:17`) | One canonicalizer, shared with the gate. A private copy silently forks when the gate changes. |
| Terminal-status set | a new tuple literal | copy the literal from `src/db.py:215` / `:256-257` **and cite it in a comment** | Three spellings of the same set is how `'closed'`-only bugs are born. |
| Realized P&L | recompute from fills | read the stored `alpaca_trades.pnl` | Phase 12 owns the math (`src/pnl.py`). CONTEXT fence: Phase 17 does not recompute. |
| Fee-netting | `pnl - fees` | `pnl` **as stored** | `src/pnl.py:28` already returned `gross - fees`. Subtracting again double-charges every trade. |
| Quarantine/universe status | re-deriving set math | `src.effective_universe.resolve_universe` (`:115`) | The gate's answer. Annotating with a re-derivation is the Phase-16 lie in a new file. |
| NULL-pnl handling | `pnl or 0.0` | `if row["pnl"] is None: null_pnl += 1; continue` | CONTEXT decision 7. The `or 0` idiom cannot even distinguish NULL from a real `0.0`. |
| Bot enumeration | `("A","B")` | `reconciliation._enabled_bot_ids()` (`:51`) | Bots C/D/E exist; `KNOWN_BOTS` omits E. |
| CLI scaffolding | a new pattern | copy `scripts/backfill_trades.py` | Established convention; keeps the diff reviewable. |

## Common Pitfalls

### Pitfall 1 — a Phase-15 gate block scores as a LOSS
**What goes wrong:** `src/bot_thread.py:309,317,332` write `status='rejected', pnl=0`. Under `pnl > 0
is a win`, a `rejected` row with `pnl=0` is a **loss**. Post-Phase-15, every gate-blocked entry
produces one. Include them and every quarantined symbol acquires a fake losing record — which Phase 18
would then act on, quarantining more symbols, producing more rejected rows. A feedback loop of lies.
**Avoid:** filter `status IN ('closed','stopped','target_hit')` **in the SQL**, and assert it in a test
that feeds a `rejected`/`canceled`/`expired`/`open`/`submitted` row to `aggregate()` and demands
`trades == 0`. Belt (SQL) and braces (pure function): `aggregate()` should also defensively ignore
non-position-terminal rows, because it is the unit under test.
**Warning sign:** a quarantined symbol shows a suspiciously round `0.00` avg loss and a trade count
matching the number of gate blocks.

### Pitfall 2 — double-subtracting fees
See §2. `pnl` is net. `total_fees` is disclosure. Pin with a test whose fixture has known `pnl` and
`fees` and asserts `realized_pnl == sum(pnl)` exactly (not `sum(pnl) - sum(fees)`).

### Pitfall 3 — `"timestamp"::timestamptz` omitted
`src/db_schema.sql:28` is `timestamp TEXT NOT NULL`. A `WHERE timestamp >= %s` against a `datetime`
param is a text/timestamptz comparison — psycopg will either error or (worse, with an ISO-string param)
do a **lexicographic** compare that happens to work for same-format ISO strings and silently mis-filter
the moment a row has a different offset spelling or a `Z` suffix. Cast: `"timestamp"::timestamptz >= %s`
(`src/db.py:168` and `:204` are the precedents). Same for `closed_at`.

### Pitfall 4 — grouping on the raw `symbol`
`BTC/USD` and `BTCUSD` become two cells, each with half the sample, each likely `insufficient`, and
BTC's −$479 disappears from the "sufficient" ranking entirely. `normalize()` both sides. (§3)

### Pitfall 5 — MIN_SAMPLE hides the leak
`sample: "insufficient"` must **suppress the verdict, not the row**. TRUMP with 2 trades and −$300 is
precisely the thing the audit needs to see. Print insufficient cells (greyed/asterisked), exclude them
only from the winner/loser ranking. A test asserts an `insufficient` cell is present in the output list.

### Pitfall 6 — `expectancy` sign drift
If `avg_loss` is stored positive, `expectancy` silently becomes `win_rate*avg_win + (1-wr)*|avg_loss|`
— a number that is always ≥ 0 and always wrong. The `expectancy == realized_pnl / trades` invariant
catches it immediately; that is why it is the load-bearing test.

### Pitfall 7 — writing to the prod DB
CONTEXT fence: the diff must contain **zero** `INSERT|UPDATE|DELETE|ALTER` outside `tests/`. A verifier
will grep for it. `get_resolved_trades` is a `SELECT`; the script has no `--apply`.

## Anti-Patterns to Avoid

- **A SQL `GROUP BY` doing the aggregation.** It puts the win definition, the terminal set and the
  normalization into a SQL string that no unit test can reach. SQL selects, Python decides (CONTEXT 1).
- **Adding a dashboard panel.** Phase 19 (RUN-02) owns the headline; a panel here collides with it and
  drags UI risk into an analysis phase (CONTEXT 4).
- **Emitting a "quarantine XYZ" verdict.** Rank, annotate, stop. Phase 18 decides (CONTEXT 8).
- **`from src.db import ...` at module scope in `symbol_stats.py`.** It must stay pure and importable
  with no `DATABASE_URL` (`src/db.py:22` does `os.environ["DATABASE_URL"]` — but lazily, in
  `_create_pool`, so importing `src.db` is safe; importing it into the *pure* module is still a
  layering violation and blocks fixture-only tests). Keep `symbol_stats.py` I/O-free.

## Environment Availability

| Dependency | Required by | Available | Version | Fallback |
|---|---|---|---|---|
| psycopg3 + psycopg_pool | the one SELECT | ✓ | `src/db.py:14-16` | — |
| `src/universe.py::normalize` | group key | ✓ | Phase 15, merged | — |
| `src/effective_universe.py::resolve_universe` | annotation | ✓ | Phase 16, merged | — |
| `src/pnl.py`, `alpaca_trades.pnl`/`fees` | the data | ✓ | Phase 12 (migration 016) | — |
| pytest | tests | ✓ | 8.3.5 | — |
| Postgres (`DATABASE_URL`) | the one DB-gated SQL test | conditional | — | pure fixture tests always run (skipif, per `tests/test_universe.py:422-428`) |
| Alpaca SDK / network | — | **not used** | — | N/A — Phase 17 makes zero network calls |

**Missing deps with no fallback:** none. **No new package** → Package Legitimacy Audit is **N/A**.

## Validation Architecture

### Test framework
| Property | Value |
|---|---|
| Framework | pytest 8.3.5 |
| Config | `tests/conftest.py` (fixtures only); DB tests gated on `DATABASE_URL` / `TEST_DATABASE_URL` |
| Quick run | `python -m pytest tests/test_symbol_stats.py -x -q` |
| Full suite | `python -m pytest tests/ dashboard/api/tests/ -q` — **baseline 373 passed / 9 skipped** |

### Requirement → test map
| Req | Behavior | Type | Command | Exists? |
|---|---|---|---|---|
| TUNE-02 | win = `pnl>0`; `pnl==0.0` is a loss | unit | `pytest tests/test_symbol_stats.py -k win_definition -x` | ❌ Wave 0 |
| TUNE-02 | `expectancy == realized_pnl / trades` | unit | `pytest tests/test_symbol_stats.py -k expectancy -x` | ❌ Wave 0 |
| TUNE-02 | MIN_SAMPLE=5 → `insufficient`, row still present | unit | `pytest tests/test_symbol_stats.py -k sample -x` | ❌ Wave 0 |
| TUNE-02 | `BTC/USD` + `BTCUSD` collapse to one cell | unit | `pytest tests/test_symbol_stats.py -k normal -x` | ❌ Wave 0 |
| TUNE-02 | `rejected`/`canceled` row never counts as a loss | unit | `pytest tests/test_symbol_stats.py -k terminal -x` | ❌ Wave 0 |
| TUNE-02 | NULL pnl excluded AND counted (not 0.0) | unit | `pytest tests/test_symbol_stats.py -k null_pnl -x` | ❌ Wave 0 |
| TUNE-02 | `realized_pnl == sum(pnl)` (fees not double-subtracted) | unit | `pytest tests/test_symbol_stats.py -k fees -x` | ❌ Wave 0 |
| TUNE-02 | empty input → no ZeroDivisionError | unit | `pytest tests/test_symbol_stats.py -k empty -x` | ❌ Wave 0 |
| TUNE-02 | `get_resolved_trades` real SQL (cast + status filter) | integration | `DATABASE_URL=... pytest tests/test_symbol_stats.py -k resolved_trades_sql -x` | ❌ Wave 0 |
| TUNE-02 | read-only: no `INSERT/UPDATE/DELETE/ALTER` in the diff | static | `pytest tests/test_symbol_stats.py -k readonly -x` | ❌ Wave 0 |

### Sampling rate
- Per task commit: `python -m pytest tests/test_symbol_stats.py -x -q`
- Per wave merge: `python -m pytest tests/ dashboard/api/tests/ -q` (must be ≥ 373 passed)
- Phase gate: full suite green + `EVIDENCE.md` generated from the real DB (read-only) before `/gsd-verify-work`

### Wave 0 gaps
- [ ] `tests/test_symbol_stats.py` — **does not exist**. Created RED before implementation (ImportError on `src.symbol_stats` is the load-bearing proof, per `tests/test_pnl.py:11`).
- [ ] `src/symbol_stats.py` — new pure module.
- [ ] `src/db.py::get_resolved_trades` — new SELECT.
- [ ] `scripts/symbol_report.py` — new CLI.
- [ ] No framework install needed.

## Security Domain

| ASVS | Applies | Control |
|---|---|---|
| V2 Authentication | no | CLI, local operator; no new surface. |
| V4 Access control | yes | **Read-only by construction.** No write path exists in the new code; the fence is grep-verifiable. |
| V5 Input validation | yes | `--bot` / `--window` reach SQL **only** as psycopg `%s` params. Never f-string `bot_id` or `since` into the query. `--window` is `int` via `argparse type=int`. |
| V6 Cryptography | no | None. |
| Secret leakage | yes | The report prints symbols/P&L only. It touches **no Alpaca keys** (no Alpaca client is constructed) and `EVIDENCE.md` is committed to git — assert no key material can reach it. |

| Threat | STRIDE | Mitigation |
|---|---|---|
| SQL injection via `--bot` | Tampering | parameterized `%s` (house idiom) |
| Accidental prod-row mutation | Tampering | no write path; grep gate `INSERT\|UPDATE\|DELETE\|ALTER` outside tests |
| Secrets committed in `EVIDENCE.md` | Information disclosure | no client, no env dump; report fields are enumerated explicitly, no `**row` splat |

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|---|---|---|
| A1 | Non-position terminals (`canceled`/`expired`/`rejected`) all carry either NULL or `0` pnl and never a real P&L | §1 / Pitfall 1 | If a `canceled` row somehow carried real P&L it would be dropped from the sample. Low risk — they never held a position by definition (`src/order_resolution.py:11`). The SQL filter is correct either way. |
| A2 | `fees` is NULL on pre-Phase-12 closed rows | §2 | Only affects the `total_fees` drag figure, never `realized_pnl`. Mitigated by the `null_fees` counter. |
| A3 | Post-Phase-14 the NULL-pnl-on-closed-row count is ~0 | §4 | If non-zero it is a **finding**, not a bug in this phase — which is exactly why it is reported loudly rather than coerced. |
| A4 | Full-suite baseline is 373 passed / 9 skipped | Validation | If the real baseline differs, the wave-merge gate threshold shifts. Re-run `python -m pytest tests/ dashboard/api/tests/ -q` at Wave 0 to confirm. |

## Open Questions

1. **Does the `bots` table still have rows for bots with historical trades but now disabled?**
   `_enabled_bot_ids()` filters `enabled = TRUE`, so a disabled bot's cells would get no
   quarantine annotation (its trades still appear — `get_resolved_trades(bot_id=None)` does not filter
   on `bots`). Recommendation: annotate from `SELECT ... FROM bots` **without** the `enabled` filter,
   and mark cells whose bot row is missing as `annotation: unavailable` rather than silently blank.
2. **`MEME_CRYPTO` / `_ALPACA_UNTRADEABLE` as a shadow quarantine** (handed over from Phase 16, Open
   Question 1). `resolve_universe` surfaces them as `reason ∈ {meme, untradeable}` on confluence bots
   only (`src/effective_universe.py:167-170`). Phase 17 should annotate them **as `off_universe`** and
   note the distinction in the report; whether to migrate them into `quarantined_symbols` is Phase 18's
   call (CONTEXT deferred).

## Sources

### Primary (HIGH — read at file:line in this repo, this session)
- `src/db.py:14-16,22-37,101-122,151-172,175-191,204,211-241,246-259` — connection/dict_row, terminal sets, `get_alpaca_accuracy` NULL coercion, `get_realized_pnl`, `::timestamptz` precedent
- `src/db_schema.sql:24-51` — `alpaca_trades` (`timestamp TEXT` at `:28`; `pnl` `:40`; `fees` `:50`)
- `src/pnl.py:10-28` — fee-net realized P&L (`gross - fees`)
- `src/fee_gate.py:16` — `TAKER_FEE`
- `src/backfill.py:22-23,83-84,131-143` — the `fees`+`pnl` writer; `_enabled_bot_ids()` usage
- `src/alpaca_orchestrator.py:297,310-318` — the other `fees`+`pnl` writer
- `src/bot_thread.py:309,317,332` — **`rejected` rows carry `pnl=0`, not NULL**
- `src/order_resolution.py:11` — `_TERMINAL_NONPOSITION`
- `src/universe.py:17-23,26-51` — `normalize`, `entry_allowed`
- `src/effective_universe.py:95-203` — `resolve_universe` signature + return keys
- `src/reconciliation.py:51-59,62-74` — `_enabled_bot_ids`, per-bot key sourcing
- `scripts/backfill_trades.py:1-46` — CLI convention (dry-run default, `--apply`, `main() -> int`)
- `tests/test_pnl.py:1-30` — pure-fixture + RED-first convention
- `.planning/phases/17-per-symbol-performance/17-CONTEXT.md` — locked decisions
- `.planning/phases/16-effective-universe-dashboard/16-RESEARCH.md` — the gate/shadow-set analysis this phase inherits

### Secondary / Tertiary
None. No web search was required — this phase is entirely internal to the repo.

## Metadata

**Confidence breakdown**
- Terminal-status set + query shape: **HIGH** — both existing aggregates read line-by-line.
- `pnl` is fee-net: **HIGH** — `src/pnl.py:28` plus both call sites.
- `rejected` rows carry `pnl=0`: **HIGH** — three literal call sites in `bot_thread.py`.
- Normalization key: **HIGH** — `src/universe.py:17`, already the gate's canonicalizer.
- `timestamp TEXT`: **HIGH** — `src/db_schema.sql:28`, with two existing cast precedents.
- Test conventions + baseline: **HIGH** / **MEDIUM** — conventions read; baseline count is A4.

**Research date:** 2026-07-12
**Valid until:** 2026-08-11 (internal-only; invalidated by any change to the terminal-status set, `src/pnl.py`, or `alpaca_trades`)
