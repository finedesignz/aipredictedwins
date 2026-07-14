# Phase 20 — E2E Verification Evidence (VERIFY-01, VERIFY-02)

**The backfill was NOT run. Nothing was written to the production database.**
Every number below is a SELECT-only measurement taken against prod on 2026-07-14.

---

## §1 Provenance

| Field | Value |
|---|---|
| `generated_at` | `2026-07-14T07:27:40.538538+00:00` (UTC) |
| DB host | prod Postgres `gqbwdxfm2lagmsv4h0496swp:5432` (Coolify internal), reached read-only over an SSH port-forward; the script reported `db_host: 127.0.0.1:15432` (the local tunnel end) |
| Credentials | fetched at run time from Coolify app `zkkw8wocws84gg4woc8kcoc4` (per-bot `ALPACA_API_KEY_{A,B,C}` / `ALPACA_SECRET_KEY_{A,B,C}` + `DATABASE_URL`), held in-process only. **No credential is written into this file or any committed file.** No bare `ALPACA_API_KEY` was used — one Alpaca account per bot, hard rule. |
| Git rev | `f1e6e29` (Phase-20 deploy live in prod; migration `020` applied 2026-07-14 07:17:25 UTC) |
| `tolerance_usd` | **`25.0` — source: `default`** |
| `tolerance_pct` | **`0.005` — source: `default`** |
| `tolerance_override` | **`false`** |
| `taker_fee` | **`0.0025` — source: `default`** |
| Reproduce | `python scripts/e2e_verify.py --json` |

**Why the tolerance line exists.** `_tolerance()` / `_tolerance_pct()` read `os.environ` **at call time**
(`src/reconciliation.py:47-48`), so a Coolify `RECONCILIATION_TOLERANCE_USD=100000` would turn **both** the
all-time row and the window green with nothing in any committed file to show it. It was checked directly:
neither `RECONCILIATION_TOLERANCE_USD`, `RECONCILIATION_TOLERANCE_PCT` nor `TAKER_FEE` is set on the Coolify
service, and none was set in the run environment. **The breach below is graded against the unmodified $25
ruler.**

**Read-only, in three independent layers** (one is a convention; two are not):
1. `scripts/e2e_verify.py:62` sets `AIPW_DB_READONLY=1` **before the first `src` import** — pool creation
   latches on first call, so setting it in `main()` or a shell wrapper would be too late.
2. That flag routes into libpq `options=-c default_transaction_read_only=on` (`src/db.py:38`), so **Postgres
   itself** refuses every mutation (SQLSTATE 25006), and `_bootstrap_schema()`'s DDL is skipped
   (`src/db.py:56`).
3. A static fence (`tests/test_e2e_verify_fences.py`) greps the source; the script defines no `--apply`,
   no `--write`, no `--fix` and no `--tolerance` flag.

---

## §2 T0 anchor + the E2E reconciliation report

`T0` is written **only** by `ensure_anchor` inside the manager's hourly reconcile tick, in prod, running
Phase-20 code. It was written for all three bots at ~07:18:5x UTC on 2026-07-14. **The window opened today.**

| Bot | T0 (anchored_at, UTC) | equity @ T0 | trade_log_pnl @ T0 |
|---|---|---|---|
| A | 2026-07-14 07:18:49.699103+00:00 | 82,284.48 | −8,995.21 |
| B | 2026-07-14 07:18:51.098237+00:00 | 95,419.65 | −2,970.13 |
| C | 2026-07-14 07:18:52.557635+00:00 | 100,000.00 | +2,039.64 |

### The windowed verdict — and the all-time (legacy) row beside it

| Bot | **Windowed verdict** | resolved / unresolved post-T0 | delta_window | tolerance_window | **ALL-TIME delta (`legacy: true`)** | tolerance | within_tol | **`legacy_offset_usd`** |
|---|---|---|---|---|---|---|---|---|
| A | **INSUFFICIENT_SAMPLE** | 0 / 0 | $0.00 | $25.00 | **$8,720.31** | $25.00 | **false** | **$8,720.31** |
| B | **INSUFFICIENT_SAMPLE** | 0 / 0 | $0.00 | $25.00 | **$1,610.22** | $25.00 | **false** | **$1,610.22** |
| C | **INSUFFICIENT_SAMPLE** | 0 / 0 | $7,457.43 | $37.29 | **$9,497.07** | $25.00 | **false** | **$2,039.64** |

`bots_found: A, B, C` — read from the `bots` table, the source of truth, not from a hardcoded list.
**Exit code 1.**

**INSUFFICIENT_SAMPLE IS NOT A PASS.** `MIN_WINDOW_SAMPLE = 20` resolved post-T0 trades **per bot**; every
bot has **0**, because the anchor is ~9 minutes old at the time of the run. The window is open and counting.
It has **not earned a verdict**, and none is claimed for it here. It was not widened, coerced, or retried
until it produced a sample.

**Bot C's `delta_window` of $7,457.43 (> its $37.29 tolerance) is NOT a windowed failure** — it cannot be,
with 0 resolved trades in the window. `trade_log_window` is $0.00 while `alpaca_realized_window` is
−$7,457.43: the account's realized side moved after T0 with no corresponding resolved trade row. With a
sample of zero this is an artifact of a 9-minute window, not a signal. It is recorded here verbatim and is
**a specific thing the dated follow-up run must re-check**, not something to explain away today.

**The all-time breach is the finding, and it is permanent.** Both sides of `reconcile_bot` are
cumulative-since-inception. The 395 sentinel rows contribute **exactly zero** to `trade_log_pnl`, while
Alpaca's `equity − starting_equity` **already contains their true outcome**. The difference is therefore a
**fixed level offset**: every future perfectly-recorded trade adds the same amount to *both* sides and leaves
it intact. `abs(delta) <= $25` on the all-time window is **unsatisfiable, forever**, absent an authorized
write to the historical rows. It has **not** been made green by widening a tolerance — the tolerance is still
$25 and §1 proves it.

Bot A's $8,720.31 is consistent with the original audit (the log said **+$1,296** while the account was
**−14.34%**) — the offset is the sum of ~192 unrecorded exits.

**The post-T0 window is fee-clean by construction.** Plan 20-08 fixed the two live GROSS-P&L writers
(`src/trend_strategy.py:172-173`, `src/bot_c/strategy.py:400-402`) and shipped in the **same deploy** that
wrote `T0`. Rows written before the deploy are not fee-clean, and they are outside the window by definition.

### Dated follow-up (the only thing that can produce a windowed verdict)

Not before **2026-07-28** (≥20 resolved trades/bot; days-to-weeks at current cadence):

```bash
python scripts/e2e_verify.py --json      # exit 0 == every enabled bot's window reconciles
```

---

## §3 VERIFY-01 traceability matrix

| Clause | Test file(s) |
|---|---|
| order-state resolution | `tests/test_order_resolution.py`, `tests/test_external_exit_resolution.py` |
| realized-P&L math **with fees** | `tests/test_pnl.py`, `tests/test_close_pnl.py`, `tests/test_fee_gate.py`, `tests/test_gross_pnl_writers.py` (Phase 20 — the two LIVE writers) |
| universe rejection | `tests/test_universe.py`, `tests/test_universe_resolution.py`, `tests/test_effective_universe.py` |
| the reconciliation check | `tests/test_reconciliation.py`, `dashboard/api/tests/test_portfolio_win_rate.py` |
| **G1** e2e reconciliation seam | `tests/test_e2e_reconciliation.py` |
| **G2** paper-gate seam | `dashboard/api/tests/test_paper_gate.py` |
| **G3** backfill seam | `tests/test_backfill.py` |
| **G4** windowed reconciliation seam | `tests/test_reconciliation.py` (windowed) |

Suite: **541 passed / 29 skipped** (`python -m pytest tests/ dashboard/api/tests/ -q`).
**Skips did NOT increase — 29, unchanged from baseline** (VALIDATION case 41, owned by this plan: no test can
assert this property from inside the suite). `tests/test_phase19_fences.py` green, including case 38 (**the
backfill stays UNARMED**) and fence F20-KILLER (Phase 19's `_check_bots_down(alive_before)` fix intact).

---

## §4 The dry-run recovery ceiling — **the backfill can repair NONE of the 395**

```
AIPW_DB_READONLY=1 python -c "from src.backfill import backfill; print(backfill(apply=False))"
BOT A {"resolved": 0, "unchanged": 0, "unresolvable": 0, "residue": 0}
BOT B {"resolved": 0, "unchanged": 0, "unresolvable": 0, "residue": 0}
BOT C {"resolved": 0, "unchanged": 0, "unresolvable": 0, "residue": 0}
```

**No bot carries `error: "positions_unavailable"`. Alpaca answered for all three**, so no bot is
`CEILING UNAVAILABLE` and these zeros are real zeros, not an outage masquerading as one. (Had any bot's
`get_positions()` returned `None`, its ceiling would be printed here as **`CEILING UNAVAILABLE — Alpaca
positions call failed`**, because a `0` there would mean *unknown*, not *nothing to repair*.)

**Recovery ceiling: 0 of 395, for all three bots.** But the reason matters more than the number, and it is
not the reason an operator would assume:

| Bot | unresolved rows (`pnl IS NULL OR pnl = 0`) | status | rows carrying an `order_id` |
|---|---|---|---|
| A | 192 | **all `closed`** | **0** |
| B | 201 | **all `closed`** | **0** |
| C | 2 | **all `closed`** | **0** |
| **total** | **395** | | **0** |

The backfill's candidate set is `status IN ('open','submitted') AND order_id IS NOT NULL`
(`src/db.py:186-207`). **All 395 sentinel rows are `status='closed'` with `order_id IS NULL`.** They match
**neither** predicate — not one of them is even selected. Alpaca's history ladder is keyed by
`get_order(row["order_id"])`; with no `order_id` there is nothing to look up.

**So `resolved: 0` here does not mean "the ceiling is low." It means the shipped backfill is not aimed at
these rows at all, and authorizing it would repair exactly nothing.** The legacy offset in §2 is **not
reachable by the currently-shipped repair tool.** Recovering it would need a *different* mechanism —
matching closed rows to Alpaca fills by `(symbol, qty, timestamp)` rather than by `order_id` — which does not
exist, is not in Phase 20's scope, and would be a new plan with its own authorization.

**The dry run wrote nothing, structurally:** `apply=False` is the default; the only write site is gated by
`and apply` (`src/backfill.py:164`); it ran under `AIPW_DB_READONLY=1`, so Postgres would have refused a
write with SQLSTATE 25006 regardless.

### Defect found while taking this measurement (NOT fixed here — out of scope, and it is a blocker on §7)

`src/backfill.py:153` calls `TradeLogger(bot_id)` **positionally**. `TradeLogger.__init__`'s first positional
parameter is **`db_path`**, not `bot_id` (`src/trade_logger.py:18`). The loop's `bot_id` is therefore silently
discarded into `db_path` (which is ignored), and the logger falls back to the **`BOT_ID` env var**. On a
dry run this is harmless (the logger is constructed but never used). **Under `--apply` it means every repaired
row would be attributed to whatever `BOT_ID` the environment happens to carry — not to the bot being
processed.** The dry run above only completed because `BOT_ID=A` was set to satisfy the constructor.
**This must be fixed before any `--apply` run is authorized.** It is recorded, not patched: this plan changes
`.planning/` only.

---

## §5 The paper gate — MEASURED before/after

| Bot | `total_rows` (what the gate read BEFORE) | `resolved_rows` (what it reads AFTER) | excluded |
|---|---|---|---|
| A | 307 | 115 | 192 |
| B | 333 | 132 | 201 |
| C | 15 | 13 | 2 |
| **total** | **655** | **260** | **395** |

**This is a REAL MEASUREMENT of `paper_trades_completed`, not a projection** — the live dashboard value moved
from **655 (old)** to **260 (new)**, a delta of **exactly −395**, which is precisely the sentinel count. The
earlier "~260" figure was a *prediction* that RESEARCH R1 refuted on its reasoning (different bot sets, different
status filters); it is superseded here by the measured value, which happens to agree.

`win_rate: 34.6` — **below the 40% paper gate.** `unresolved: 395`.

**The gate now reads WORSE. That is the fix working, and it is NOT to be tuned back.** The bots have not
completed 655 verifiable paper trades; they completed 260 whose P&L is actually known. The gate is now
counting the truth. Live trading stays blocked — correctly.

---

## §6 Phase 19's two `human_needed` items — discharged

Both confirmed against the live deploy: manager alive, **bots_alive 3/3** (A, B, C running,
`thread_alive: true`; Bot E disabled), `alerts_configured: true`, **no alert errors** — the live UI renders and
real SES delivery is configured and erroring nowhere.

---

## §7 BLOCKING HUMAN CHECKPOINT — the write to historical production trade rows

**Phase 20 did NOT run this. The 395 rows are byte-identical to how it found them.**

Two things a decision-maker must weigh, both established above:

1. **The shipped backfill would repair 0 of the 395 rows** (§4). They are `closed` with `order_id IS NULL`;
   the tool selects only `open`/`submitted` rows *with* an `order_id`. **Authorizing it today would accomplish
   nothing.**
2. **It also carries an unfixed bot-attribution defect** (§4) that only manifests under `--apply`.

The command, documented and **unrun**:

```bash
# NOT run by Phase 20. Do NOT run under AIPW_DB_READONLY=1 — that flag is what has been
# protecting these rows (Postgres refuses the write, SQLSTATE 25006).
python -c "from src.backfill import backfill; print(backfill(apply=True))"
```

**Rollback:** `alpaca_trades` has **no soft-delete**. The ONLY rollback is a **PRE-WRITE `SELECT` snapshot** of
`(id, status, exit_price, pnl, fees)` for every row the dry run reports as `resolved`, saved **outside the
database**, and a row-by-row restore from it. With the current ceiling of 0, that snapshot would be empty —
which is itself the tell that this command has nothing to do.

**No agent will run this without an explicit "authorize backfill".** Silence, ambiguity, or "sounds good" is a
DECLINE. If declined or deferred: nothing else changes — the legacy offset stands, is reported per bot, the
all-time reconciliation keeps breaching at the unchanged $25 tolerance, and VERIFY-02 stays closed on the
post-T0 windowed scope alone.
