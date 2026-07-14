# Phase 20 — Verification & E2E Reconciliation — RESEARCH

**Researched:** 2026-07-13 · **Domain:** trade-log/broker reconciliation, test-seam coverage, read-only prod verification
**Requirements:** VERIFY-01, VERIFY-02 · **Milestone:** v1.1 (FINAL phase)
**Confidence:** HIGH on code claims (every one re-verified at `file:line` this session, one executed live);
MEDIUM on the live prod magnitudes (they were NOT re-read from prod — see the Assumptions Log).

---

## Summary

Phase 20 asks whether phases 11–19 actually reconcile against real money. The answer, verified: the
**machinery is sound, the arithmetic is honest, and two real defects remain** — one of which is a
loaded gun.

I independently confirmed or refuted every CONTEXT claim. **Four confirmed, one confirmed-but-with-wrong-line-numbers,
one materially REFUTED, and one CONTEXT inference chain broken.** The headline:

1. **The `src/backfill.py` slash bug is REAL and I PROVED it by executing it.** A genuinely-held
   `BTC/USD` position, against a real-shaped slashless Alpaca `get_positions()` payload, resolves as
   **`closed` with a fabricated −$20.45 P&L**. This is not a reading of the code; it is the code's
   actual output. An `--apply` run today corrupts every held position. This is the highest-stakes
   claim in the phase and it is CONFIRMED.
2. **CONTEXT's "mirror is non-negotiable" for `e2e_verify.py` is now OBSOLETE.** `AIPW_DB_READONLY=1`
   (already shipped, `src/db.py:22-23`, `:37`, `:49-56`) both skips `_bootstrap_schema()` **and** sets
   `default_transaction_read_only=on` at the libpq layer — **enforced by Postgres (SQLSTATE 25006), not
   client convention**, and already pinned by `tests/test_db_readonly.py`. It satisfies the locked
   constraint ("never write to prod") *more strongly* than the mirror. Recommend it as the primary path.
3. **The `paper_trades_completed` bug is real but CONTEXT's numbers are NOT established.** The
   `COUNT(*)` is genuinely unfiltered (`settings.py:36` — line number correct). But CONTEXT's
   "655 → ~260" arithmetic conflates **two different populations** and cannot be trusted as a
   prediction. See the refutation below. The *fix* is right regardless; the *predicted magnitude* is not.
4. The **$8,720 delta really is a fixed level offset**, and the formula proves it. Confirmed.
5. **VERIFY-01 is genuinely ~80% covered.** I re-checked each clause against real test files. Do not
   pile on redundant unit tests. The four seams (G1–G4) are the real gaps — and I found that
   `tests/test_backfill.py:199` *actively encodes the bug* in its fixture.

**Primary recommendation:** Fix the backfill slash bug with `src/universe.normalize` (the exact helper
the monitor already uses) and pin it with a test that FAILS on today's `main`. Build `e2e_verify.py`
against prod directly under `AIPW_DB_READONLY=1`, not a mirror. Fix `settings.py:36` to the canonical
RESOLVED predicate but **report the measured before/after counts rather than asserting 655→260.**

---

## User Constraints (from CONTEXT.md)

### Locked Decisions

1. **E2E check = read-only script + committed report**, not a pytest test and not a dashboard route.
   `scripts/e2e_verify.py`, SELECT-only, no `--apply`, no write flag. Output committed to
   `20-EVIDENCE.md`. Exits non-zero on FAIL.
2. **"Within tolerance" is RELABELLED, never silenced.** `RECONCILIATION_TOLERANCE_USD` stays at **$25**
   on the all-time row and keeps breaching forever. **Widening the tolerance to make it green is BANNED.**
   New: an ANCHORED window (`reconciliation_anchor` table, `T0` = Phase-20 deploy) with
   `tolerance_window = max(25.0, 0.005 * abs(alpaca_realized_window))`. The legacy offset is SURFACED
   (`legacy_offset_usd`) next to the check, never hidden.
3. **The 395 rows are NOT TOUCHED.** No `UPDATE`, no `DELETE`, no `--apply`, no backfill run. The
   backfill is FIXED, TESTED, and LEFT UNARMED behind a blocking human checkpoint. A dry-run
   recovery-ceiling count IS in scope; running the repair is NOT.
4. **The `paper_trades_completed` gate bug IS fixed here.** `COUNT(*)` → the canonical RESOLVED
   predicate. **The gate will read WORSE. That is correct and it is NOT to be tuned back.**
5. **VERIFY-01's coverage bar = the four seams (G1–G4)**, not more unit tests. Plus a traceability
   matrix in `20-EVIDENCE.md`. Target: full suite green, **zero new skips**.
6. **Write-allowlist:** `reconciliation_anchor` (new), `reconciliation` (existing), `src/backfill.py`
   (code only), `settings.py` (predicate), tests / `scripts/e2e_verify.py` / `.planning/`. **Forbidden:**
   any `alpaca_trades` mutation, any `bots` config knob, any tolerance widening, any Coolify env change.

### Claude's Discretion

- The internal structure of `scripts/e2e_verify.py`, its JSON schema, and its table layout.
- How the anchor is read/written and where the windowed math lives (module boundary).
- Test case decomposition within G1–G4.

### Deferred Ideas (OUT OF SCOPE)

- The authorized backfill itself · fee backfill (643/655 rows carry `fees IS NULL`) · backdating `T0`
- A `/api/reconciliation` route or SSE push · alerting on a *windowed* breach
- **The entry-knob retune (TUNE-01) — Phase 21. Do not re-open.**

---

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| VERIFY-01 | Unit/integration tests cover order-state resolution, realized-P&L math *with fees*, universe rejection, and the reconciliation check | Coverage audit below proves all four clauses are ALREADY covered at unit level. The genuine gaps are the four *seams* G1–G4. |
| VERIFY-02 | An E2E check on live/paper data shows resolution rate and P&L reconciliation *within tolerance* after the fix | UNACHIEVABLE on the all-time window (proven arithmetically below). ACHIEVABLE on the post-`T0` anchored window. Closes as **VERIFY-02 (scoped)**. |

---

## CONTEXT Claim Verification

Every claim independently confirmed or refuted. **Verdicts are mine, from this session's tool output.**

| # | CONTEXT Claim | Verdict | Evidence |
|---|---|---|---|
| C1 | `settings.py:33-36` computes `paper_trades_completed` as a bare `COUNT(*)` over ALL `alpaca_trades` rows | **CONFIRMED** (line number exact) | `settings.py:36` is literally `SELECT COUNT(*) AS n FROM alpaca_trades WHERE bot_id IN (...)` — no status filter, no P&L filter. Surfaced at `:192` `paper_trades_completed=total_trades`. |
| C2 | ...so the gate counts non-trades. CONTEXT: **655 → ~260** | **BUG CONFIRMED · NUMBERS REFUTED** | `submitted`/`rejected` rows are provably written (`src/bot_thread.py:362,376,382`; `:309,317,332`), so `COUNT(*)` **does** count non-trades. But the "655 → ~260" arithmetic is broken — see **R1** below. |
| C3 | `src/backfill.py:147` builds `live_symbols` slash-STRIPPED; `:71`/`:154` compare a slashed `row["symbol"]`; an `--apply` run TODAY corrupts held positions | **CONFIRMED — PROVEN BY EXECUTION** (line numbers off by one) | See **the proof** below. Actual lines: `:148` builds `live_symbols`, NOTE at `:71`, compare at `:72`, second compare at `:155`. |
| C4 | `src/db.py:44` `get_pool()` calls `_bootstrap_schema()` (DDL), so any `src.db` import against prod WRITES | **CONFIRMED as a hazard · but MITIGATED** (line number off) | `get_pool()` is at `:49`; the bootstrap call at `:53-54`. **It is already guarded**: `if not _readonly(): _bootstrap_schema()`. See **R2**. |
| C5 | The reconciliation delta is a FIXED LEVEL OFFSET, not an ongoing bug | **CONFIRMED** | `src/reconciliation.py:33-35`. Both sides cumulative-since-inception. Proof below. |
| C6 | The four VERIFY-01 clauses are already unit-covered by phases 11–19 | **CONFIRMED** | Coverage audit below — all four clauses map to real, passing test files. |
| C7 | Migration **020** is the next free number | **CONFIRMED** | `dashboard/api/migrations/` tops out at `019_runtime_heartbeat.sql`. `020` is free. |
| C8 | Full-suite baseline **488 passed / 29 skipped** | **CONFIRMED** | `pytest tests/ dashboard/api/tests/ -q` → `488 passed, 29 skipped`. ⚠️ **Bare `pytest` does NOT work** — it collects `vendor/TradingAgents/` and dies with 14 collection errors. There is no `pytest.ini`/`testpaths`. Always pass the two paths explicitly. |

### R1 — REFUTATION: the "655 → ~260" projection conflates two populations

CONTEXT asserts the live `paper_trades_completed: 655` is "*the total row count of the table*" and that
the fix yields "*~260*" (= 655 − 395). **Both halves of that inference are unsound.**

- **Different bot sets.** `dashboard/api/db.py:19` → `KNOWN_BOTS = ("A", "B", "C", "D")`. The dashboard's
  `COUNT(*)` runs over **A/B/C/D**. Phase 17's EVIDENCE 655 figure is explicitly *"655 **position-closed**
  rows, bots **A / B / C / E**"* (`17-.../EVIDENCE.md:6`). **`D` vs `E` — not the same population.**
- **Different status filters.** EVIDENCE's 655 is already filtered to `status IN ('closed','stopped','target_hit')`
  (`src/db.py:315-322` `get_resolved_trades`). The dashboard's 655 is *unfiltered*. Two different queries
  returning the same integer is a coincidence CONTEXT read as an identity.
- **It cannot be an identity.** `submitted` and `rejected` rows demonstrably exist (`bot_thread.py:362,376,382`),
  and open positions exist (the bots hold unrealized P&L). So `COUNT(*)` over all statuses **must strictly
  exceed** the position-closed count. If both truly read 655, at most one is what CONTEXT thinks it is.
- Likewise `unresolved: 395` (`settings.py:47-53`, over A/B/C/**D**) is *not* necessarily the same 395 as
  EVIDENCE's `zero_pnl_total` (over A/B/C/**E**).

**Consequence for the plan:** the *fix* at `settings.py:36` is correct and independently justified by the
code (an unfiltered `COUNT(*)` is a gate-honesty bug, full stop). But **the plan must NOT hardcode, assert,
or "verify" the 655→260 transition.** `e2e_verify.py` must *measure and report* the before/after counts per
bot. Any test that asserts a specific magnitude here is asserting a number nobody has verified.

### R2 — REFUTATION: the mirror is no longer required (`AIPW_DB_READONLY=1` supersedes it)

CONTEXT Decision 1 locks *"**mirror**, same recipe as Phase 17. Non-negotiable."* That was true when Phase 17
wrote it. **It is no longer the only path, and it is no longer the best one.** `src/db.py`:

```python
def _readonly() -> bool:                                          # :22-23
    return os.environ.get("AIPW_DB_READONLY", "") == "1"

def _create_pool() -> ConnectionPool:                             # :26
    pool = ConnectionPool(conninfo=url, ..., kwargs={
        "row_factory": dict_row,
        # libpq `options` applies to EVERY connection the pool hands out and
        # is enforced by Postgres (SQLSTATE 25006) — not a client convention.
        **({"options": "-c default_transaction_read_only=on"} if _readonly() else {}),   # :37
    }, open=True)

def get_pool() -> ConnectionPool:                                 # :49
    global _pool
    if _pool is None:
        _pool = _create_pool()
        if not _readonly():        # :53  ← the DDL trap is ALREADY closed
            _bootstrap_schema()    # :54
    return _pool
```

`AIPW_DB_READONLY=1` therefore delivers **both** halves of what the mirror was invented to provide:
(a) `_bootstrap_schema()` never runs, and (b) *every* statement on *every* pooled connection is refused by
**Postgres itself** if it mutates. Already pinned by `tests/test_db_readonly.py` cases 23–25, including a
server-side probe asserting `psycopg.errors.ReadOnlySqlTransaction` on a `CREATE TABLE`.

The locked *constraint* is **"never write to prod."** The mirror was one means to that end; `AIPW_DB_READONLY=1`
is a stricter one (the mirror still requires a human to hand-run `SELECT` dumps, and a fat-fingered
`DATABASE_URL` there points a *writable* pool at prod). **This is not relitigating Decision 1 — it satisfies
its intent more strongly.** Recommend: `e2e_verify.py` runs directly against prod with `AIPW_DB_READONLY=1`
**enforced by the script itself** (see the fence design below); the Phase-17 mirror stays available as a fallback.

---

## The Proof: `src/backfill.py` resolves a HELD position as CLOSED with fabricated P&L

This is the highest-stakes claim in the phase. I did not merely read it — **I executed it.**

`src/alpaca_client.py:140-157` `get_positions()` returns `pos.symbol` **raw** from the Alpaca SDK. That is
**slashless** for crypto — confirmed by the codebase's own comment at `:384-385`:

```python
def close_position(self, symbol: str) -> dict:
    # Alpaca position endpoint uses symbol without slash (PEPEUSD not PEPE/USD)
    close_symbol = symbol.replace("/", "")
```

`src/backfill.py:148` builds the membership set straight from that, unnormalized, and `:72` / `:155` compare
a **slashed** `row["symbol"]` against it. Executed against today's `main`:

```
normalize: BTCUSD BTCUSD
HELD position, close order found ->  ('resolved', {'status':'closed','exit_price':80.0,'pnl':-20.45,'fees':0.45})
HELD position, no close order    ->  ('unresolvable', None)
control (slashed live_symbols)   ->  ('unchanged', None)
```

A **live, held, open** `BTC/USD` position — with Alpaca reporting it as held, in Alpaca's real slashless
shape — is resolved as **`closed` with an invented −$20.45 loss**. With no close order it is marked
`unresolvable` (`pnl = NULL`), which drops it out of `get_open_alpaca_positions` (`src/db.py:128`) and kills
its stop-loss, take-profit and exit advisor **while the position is still live at Alpaca**.

**The `unchanged` arm is unreachable in production.** CONTEXT's characterization is exactly right and, if
anything, understated.

**Why the existing test suite does not catch it — and this is the damning part:**

```python
# tests/test_backfill.py:193-199  (currently PASSING)
def test_backfill_still_open_unchanged():
    ...
    outcome, kw = resolve_stale_row(row, entry, live_symbols={"BTC/USD"}, close_order=None)
```

The fixture feeds **`{"BTC/USD"}` — slashed.** Alpaca never returns that. **The test encodes the bug rather
than catching it**, and it passes green. This is G3, and it is why a "fixed" backfill could otherwise ship
with the bug intact.

**The fix** is the helper the monitor already uses — `src/universe.normalize` (`src/universe.py:17`), applied
to **both** sides, exactly as `src/alpaca_orchestrator.py:142-143` does:

```python
norm_live = {normalize(s) for s in live_symbols}
if normalize(row.get("symbol")) in norm_live:
    return {}          # genuinely held
```

`normalize("BTC/USD") == normalize("BTCUSD") == "BTCUSD"` — verified. Both call sites (`:72` in the pure
function and `:155` in the driver) must be normalized; fixing only one leaves the driver still issuing a
pointless `get_closed_orders` hunt for a held symbol.

⚠️ **The `live_symbols is None` third door.** `src/alpaca_orchestrator.py:133-134` returns early when
`get_positions()` **failed** (`None` ≠ "nothing is held"). `src/backfill.py:148` coerces a failure to an
empty set via `or []` — so an Alpaca outage makes **every** position look vanished. The fix must preserve
`None` and abort the bot's backfill rather than resolve against an empty set. **This is a second latent
landmine in the same function and CONTEXT does not mention it.**

---

## The Fixed Level Offset — arithmetic confirmed

`src/reconciliation.py:16-42`, verified verbatim:

```python
alpaca_realized_pnl = (equity - starting_equity) - unrealized_pnl   # :33
delta               = trade_log_pnl - alpaca_realized_pnl           # :34
within_tolerance    = abs(delta) <= tolerance                       # :35
```

Both sides are **cumulative since inception**. The 395 sentinel rows carry `pnl = 0.0`, contributing exactly
**zero** to `trade_log_pnl`, while Alpaca's `equity - starting_equity` already contains their true outcome.
Therefore `delta ≈ −(sum of the 395 unrecorded outcomes)`, a **constant**.

Let a future trade be perfectly recorded: it adds `x` to `trade_log_pnl` and `x` to `(equity - starting_equity)`.
`delta` is unchanged. **The offset is invariant under all future correct behavior.** `abs(delta) <= $25` on
the all-time window is therefore unsatisfiable for A/B/C **forever**, absent a write to the 395 rows.

This is the formal justification for **VERIFY-02 (scoped)**, and it is sound. `_tolerance()` at `:45-46`
reads `RECONCILIATION_TOLERANCE_USD` (default `25.0`) — the env knob that **must not be widened**.

**Windowed math — and why the anchor table is the ONLY way.** I checked the entire `AlpacaClient` surface
(`src/alpaca_client.py`): `get_account`, `get_positions`, `get_tradeable_assets`, `get_latest_price`,
`get_bars`, `place_market_order`, `place_limit_order`, `close_position`, `cancel_order`, `get_order`,
`get_open_orders`, `get_closed_orders`. **There is NO account-activities call and NO portfolio-history call**
(`grep` for `activit|portfolio_history|GetPortfolioHistory` across `src/` → nothing). So there is **no way to
ask Alpaca "what did you realize since T0"** directly.

`get_closed_orders(symbol, after=...)` (`:419`) is per-symbol and order-shaped — usable for the backfill's
recovery-ceiling hunt, but it cannot produce an account-level realized-P&L figure without re-deriving every
fill pair (which is precisely the fabrication this milestone exists to eliminate).

**Therefore the windowed Alpaca realized P&L MUST be derived from a stored snapshot**, which is exactly what
`reconciliation_anchor` is for — and this **independently vindicates CONTEXT Decision 2's design**:

```
alpaca_realized_window = (equity_now - equity_T0) - (unrealized_now - unrealized_T0)
trade_log_window       = trade_log_pnl_now - trade_log_pnl_T0
delta_window           = trade_log_window - alpaca_realized_window
tolerance_window       = max(25.0, RECONCILIATION_TOLERANCE_PCT * abs(alpaca_realized_window))
```

Note this is just `reconcile_bot` with `starting_equity := equity_T0` and both other terms differenced — so
it should **reuse `reconcile_bot`**, not re-implement the formula. A second copy of the subtraction is a
second place for a sign error.

---

## VERIFY-01 Coverage Audit — what is genuinely MISSING

Re-verified against real files. **Do not propose redundant tests for the "covered" rows.**

| VERIFY-01 clause | Covered by | Verdict |
|---|---|---|
| order-state resolution | `tests/test_order_resolution.py`, `tests/test_external_exit_resolution.py` | **COVERED** |
| realized-P&L math *with fees* | `tests/test_pnl.py`, `tests/test_close_pnl.py`, `tests/test_fee_gate.py` | **COVERED** |
| universe rejection | `tests/test_universe.py`, `tests/test_universe_resolution.py`, `tests/test_effective_universe.py` | **COVERED** |
| the reconciliation check | `tests/test_reconciliation.py`, `dashboard/api/tests/test_portfolio_win_rate.py` | **COVERED (unit)** |
| no-prod-write / no-risk-drift fences | `tests/test_phase19_fences.py`, `tests/test_db_readonly.py` | **COVERED** |

**The four genuine gaps — all *seams between* modules, not modules:**

- **G1 — no end-to-end chain test.** Nothing drives submit → fill → external exit → `resolve_stale_row` →
  resolved row → `get_realized_pnl` → `reconcile_bot` as one chain against fakes. Every link is tested; the
  **joins** are not. A sign error or unit mismatch at any join survives the current 488.
- **G2 — `paper_trades_completed` has NO test at all.** Nothing asserts a `submitted`/`rejected` row is
  excluded. **That is exactly why the bug shipped.**
- **G3 — the backfill's symbol normalization is not merely untested, it is MIS-tested.**
  `tests/test_backfill.py:199` feeds slashed `{"BTC/USD"}`, a payload Alpaca never emits. The new case must
  feed **slashless** `{"BTCUSD"}` and **must FAIL on today's `main`** (it currently returns `resolved`/−$20.45).
  A G3 test that passes before the fix is not testing the bug.
- **G4 — nothing tests the reconciliation *window*.** `reconcile_bot` is tested as pure arithmetic; the
  anchored window, the `max($25, 0.5%)` tolerance, and `INSUFFICIENT_SAMPLE` are not expressible today.

---

## Deliverable Specs

### 1. `scripts/e2e_verify.py` — SELECT-only E2E check

Shape copies `scripts/symbol_report.py` (repo-root `sys.path` shim, `--json`, `--bot`, no write flag).

**Read-only enforcement — three independent layers, because one is a convention and two are not:**

1. **Self-enforced env.** The script sets `os.environ["AIPW_DB_READONLY"] = "1"` **before the first
   `src.db` import** (module import order matters — `get_pool()` latches `_pool` on first call). This makes
   the guarantee a property of the *script*, not of how someone remembered to invoke it.
2. **Server-side.** That flag routes into libpq `options=-c default_transaction_read_only=on`
   (`src/db.py:37`), so Postgres refuses any mutation with SQLSTATE 25006 — and `_bootstrap_schema()` is
   skipped (`src/db.py:53`).
3. **Static fence.** A test greps the script's source for mutating SQL / write flags and asserts absence,
   with a positive control (VALIDATION case 12), plus a **self-test that proves the fence fires** on a
   deliberately-mutating fixture (case 13) — a fence that has never failed is a fence nobody has tested.

**Queries (all `SELECT`):** per enabled bot — the anchor row; `get_realized_pnl`; the RESOLVED / unresolved
counts over `timestamp >= T0`; the raw `COUNT(*)` and the RESOLVED count (to *measure* the paper-gate delta
rather than assume it); and live Alpaca `get_account` + `get_positions` via `reconciliation._client_for_bot`
(one account per bot, raises on a keyless bot — `src/reconciliation.py:62-93`).

**Output:** machine-readable JSON block + human table; per bot: `resolution_rate_post_t0`, `delta_window`,
`tolerance_window`, `within_tolerance_window`, `resolved_post_t0`, `verdict` ∈ `PASS | FAIL | INSUFFICIENT_SAMPLE`,
`legacy_offset_usd` (+ its authorization note), and the all-time row labelled `legacy: true`.
**Exit non-zero on FAIL *and* on `INSUFFICIENT_SAMPLE`** — the latter is explicitly **not a PASS**.

**Note:** the script needs live Alpaca creds and prod `DATABASE_URL`, which is precisely why CONTEXT
Decision 1 correctly keeps it **out of pytest**. It must never become a skipped CI test.

### 2. Migration `020_reconciliation_anchor.sql` + the `src/db_schema.sql` mirror

`020` confirmed free. Follow the additive idempotent shape of `017_reconciliation.sql`:
`CREATE TABLE IF NOT EXISTS`, **no** `bot_id` CHECK (migration 009 dropped it for C/D), no DROP/DELETE,
safe to apply twice and safe to apply *before* the code deploys.

```sql
CREATE TABLE IF NOT EXISTS reconciliation_anchor (
    bot_id         TEXT PRIMARY KEY,
    anchored_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    equity         DOUBLE PRECISION NOT NULL,
    unrealized_pnl DOUBLE PRECISION NOT NULL,
    trade_log_pnl  DOUBLE PRECISION NOT NULL
);
```

⚠️ **The mirror gap is REAL and CONTEXT is right to flag it.** `src/db_schema.sql` (the bootstrap) declares 13
tables and **does** already carry `reconciliation` (`:215`) and `runtime_heartbeat` (`:231`) — i.e. prior phases
*did* remember to mirror. **`reconciliation_anchor` must be added to `src/db_schema.sql` too**, or every
fresh-DB bootstrap (and every test DB) comes up missing the table while prod has it. Migration-only = a table
that exists in prod and nowhere else.

**Write discipline:** the anchor is written **once per bot, on first run**, via `INSERT ... ON CONFLICT (bot_id)
DO NOTHING` — **not** an UPSERT. `DO NOTHING` is load-bearing: an UPSERT would silently re-anchor `T0` to
"now" on every run, permanently resetting the window to zero samples and making the check vacuously green.
That is the same class of self-defeating move as widening the tolerance. Re-anchoring must require an explicit,
separate, human-authorized action.

### 3. `settings.py:36` — the paper-gate fix

Replace the unfiltered `COUNT(*)` with the canonical RESOLVED predicate already used at `settings.py:47-51`,
`portfolio.py:87`/`:127`, and defined at `src/db.py:95` (`is_resolved`):

```sql
status IN ('closed','stopped','target_hit') AND pnl IS NOT NULL AND pnl <> 0
```

`total_rows` and `unresolved` are already on the payload (`settings.py:51`), so the drop stays explainable on
the surface that shows it. **Per R1: report the measured before/after; do not assert 655→260.** The gate
reading worse is the intended outcome.

### 4. Backfill fix + dry-run recovery ceiling (UNARMED)

Normalize both sides with `src/universe.normalize` at `:72` and `:155`; preserve the `None` sentinel from
`get_positions()` (do not coerce to `set()`). Then produce the **recovery ceiling**: `backfill(apply=False)`
(`src/backfill.py:132`, dry-run is the DEFAULT; the only write is gated at `:164` by `if outcome == "resolved"
and apply`) returns per-bot `{resolved, unchanged, unresolvable, residue}`. **`resolved` under dry-run IS the
recovery ceiling** — how many of the 395 Alpaca can still answer for.

The exact command, to be **documented and NOT run**:

```bash
python -c "from src.backfill import backfill; print(backfill(apply=False))"   # dry-run: writes NOTHING
```

⚠️ Even the dry-run imports `src.db` → `get_pool()` → `_bootstrap_schema()` unless `AIPW_DB_READONLY=1` is set.
But the dry-run must reach the *real* prod rows, and `_client_for_bot` needs live keys. Run it with
`AIPW_DB_READONLY=1` so the DDL is skipped and Postgres refuses any accidental write.

**The `--apply` command is written into the plan as a documented, human-authorized future step. Phase 20 does
not run it.** `tests/test_phase19_fences.py` already calls `src/backfill.py` "a LOADED GUN" — it stays holstered.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Symbol normalization in backfill | a local `.replace("/","")` | `src.universe.normalize` (`universe.py:17`) | It is the monitor's helper (`alpaca_orchestrator.py:142`). A second normalizer is a second thing to drift. |
| Windowed reconciliation math | a new subtraction | `reconcile_bot` with `starting_equity := equity_T0` | A second copy of the formula is a second place for a sign error. |
| Read-only prod access | a mirror + hand-run SELECT dumps | `AIPW_DB_READONLY=1` | Server-enforced (SQLSTATE 25006), already tested, closes the DDL trap. |
| Per-bot Alpaca client | a bare `ALPACA_API_KEY` read | `reconciliation._client_for_bot` (`:62-93`) | Enforces one-account-per-bot; **raises** on a keyless bot. |
| The RESOLVED predicate | a fresh `WHERE` clause | `src/db.py:95` `is_resolved` / the existing SQL | Five reader sites already agree; a sixth spelling is drift. |

---

## Common Pitfalls (phase-specific)

1. **Widening the tolerance to turn the breach green.** Banned outright. The breach IS the finding.
2. **UPSERTing the anchor.** Re-anchors `T0` every run → window always empty → check passes vacuously.
   Use `ON CONFLICT DO NOTHING`.
3. **Writing a G3 test that passes before the fix.** If it doesn't fail on today's `main`, it isn't testing
   the bug. `tests/test_backfill.py:199` is the cautionary tale.
4. **Asserting `655 → 260`.** Nobody has verified those are the same population. Measure; don't assert (R1).
5. **Treating `INSUFFICIENT_SAMPLE` as a pass.** It is not. Exit non-zero.
6. **Coercing `get_positions() → None` to an empty set.** An Alpaca outage then "vanishes" the whole book.
7. **Running bare `pytest`.** Collects `vendor/` → 14 errors. Use `pytest tests/ dashboard/api/tests/`.
8. **Forgetting the `src/db_schema.sql` mirror.** Migration-only table = absent from every fresh DB and test DB.

---

## Environment Availability

| Dependency | Required by | Available | Notes |
|---|---|---|---|
| `pytest` + suite | G1–G4 | ✓ | 488 passed / 29 skipped, 8.45s (explicit paths) |
| `src.universe.normalize` | backfill fix | ✓ | `universe.py:17`, verified idempotent on both shapes |
| `AIPW_DB_READONLY` | `e2e_verify.py` | ✓ | `src/db.py:22-23,37,53`; pinned by `tests/test_db_readonly.py` |
| Prod `DATABASE_URL` | `e2e_verify.py` run | ✗ (not in this session) | Executor supplies; **read-only only** |
| Live Alpaca keys (A/B/C) | `e2e_verify.py`, anchor write | ✗ (not in this session) | Per-bot via `_client_for_bot`; never bare keys |
| Postgres (test) | `_needs_db` cases | conditional | Drives part of the existing 29 skips |

---

## Assumptions Log

| # | Claim | Risk if wrong |
|---|---|---|
| A1 | Live prod magnitudes (Bot A $8,720.31 / B $1,610.22 / C $2,039.64; 655; 395; 34.6%) are taken from CONTEXT and were **NOT re-read from prod this session** (no prod creds; and reading prod is not required to *specify* the work). | Low for the design — the offset argument is structural and holds for any values. **The plan must not hardcode these numbers**; `e2e_verify.py` measures them. |
| A2 | The 655/395 in CONTEXT's live table refer to the A/B/C/**D** dashboard population, not Phase 17's A/B/C/**E** population. | This is the basis of R1. If the executor can query prod, **measuring both counts is the first thing to do.** |
| A3 | Alpaca's order-history retention horizon truncates the oldest sentinels (CONTEXT's claim; not verified against Alpaca docs). | Only affects the *expected* recovery ceiling. The dry-run **measures** it, so nothing depends on the assumption. |

---

## Open Questions

1. **What does the paper gate actually read after the fix?** Unknown and unknowable without prod. Resolution:
   `e2e_verify.py` reports before/after per bot. Do not predict.
2. **Is Bot D or Bot E in the reconciled population?** `KNOWN_BOTS` says D; Phase 17 evidence says E.
   Resolution: `reconciliation._enabled_bot_ids()` reads the `bots` table (source of truth) — use it, and let
   the report state which bots it found rather than assuming.

---

## Sources

**Primary (HIGH — read at `file:line` this session):** `src/backfill.py` (full), `src/alpaca_client.py:140-157,382-391,419`,
`src/alpaca_orchestrator.py:112-161`, `src/reconciliation.py:1-100`, `src/db.py:15-60,90-100,315-337`,
`dashboard/api/routes/settings.py:28-58,188-198`, `dashboard/api/db.py:19`, `src/bot_thread.py:303-332,362-382`,
`src/universe.py:17`, `src/db_schema.sql`, `dashboard/api/migrations/017,019`, `tests/test_backfill.py`,
`tests/test_db_readonly.py`, `tests/test_phase19_fences.py`, `dashboard/api/tests/test_routes.py:218-232`,
`scripts/symbol_report.py:1-40`, `.planning/phases/17-per-symbol-performance/EVIDENCE.md:1-33`.

**Executed (HIGHEST — behavior, not reading):** `resolve_stale_row` against a slashless `live_symbols`
(the −$20.45 fabrication); `normalize()` on both symbol shapes; `pytest tests/ dashboard/api/tests/` (488/29).

**Confidence:** Code claims **HIGH** (verified, one executed). Prod magnitudes **LOW** (CONTEXT-sourced, A1).
Design **HIGH** (the no-activities-API finding independently forces the anchor design).
