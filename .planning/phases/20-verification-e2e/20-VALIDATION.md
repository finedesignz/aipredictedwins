# Phase 20 — Verification & E2E Reconciliation — VALIDATION

**Requirements:** VERIFY-01, VERIFY-02 · **Baseline:** `pytest tests/ dashboard/api/tests/ -q` → **488 passed, 29 skipped**
**Target:** all baseline cases still green + the cases below · **ZERO new skips.**

> ⚠️ **Bare `pytest` does NOT work in this repo** — it collects `vendor/TradingAgents/` and dies with 14
> collection errors (there is no `pytest.ini` / `testpaths`). Always run:
> `python -m pytest tests/ dashboard/api/tests/ -q`

> **A new test that skips is a new test that does not exist.** No case below may require prod credentials.
> `scripts/e2e_verify.py` is deliberately **not** a pytest test (it needs live Alpaca + prod DB); it is
> validated here by a **static fence** (case 12) and a **fence self-test** (case 13), both of which run offline.

---

## Wave 0 — the gap that must be closed FIRST

**W0-1 — `tests/test_backfill.py:199` currently encodes the bug.** `test_backfill_still_open_unchanged`
feeds `live_symbols={"BTC/USD"}` — **slashed** — a payload Alpaca never emits (`get_positions()` returns
`pos.symbol` raw = `"BTCUSD"`, per `src/alpaca_client.py:140-157` and the comment at `:384-385`). The test
passes green **because** it mirrors the defect. It must be **corrected to the real Alpaca shape**, not merely
supplemented — leaving it as-is preserves a green test that certifies broken behavior.

**No new test file is required for Wave 0**; `tests/test_backfill.py`, `tests/test_reconciliation.py`, and
`tests/test_phase19_fences.py` all exist. New files: `tests/test_e2e_reconciliation.py` (G1),
`dashboard/api/tests/test_paper_gate.py` (G2).

---

## G3 — The backfill slash bug (HIGHEST STAKES)

**These cases MUST FAIL on today's `main`.** A G3 case that passes before the fix is not testing the bug.
Verified pre-fix behavior (executed this session): a held `BTC/USD` against `live_symbols={"BTCUSD"}` returns
`('resolved', {'status':'closed','exit_price':80.0,'pnl':-20.45,'fees':0.45})` — **a fabricated loss on a live
position.**

| # | Case | Assertion | Pre-fix |
|---|---|---|---|
| **1** | **Held position, real Alpaca shape, close order available** — `row["symbol"]="BTC/USD"`, `live_symbols={"BTCUSD"}`, `close_order` present | `resolve_stale_row(...) == ("unchanged", None)`. **A held position is NEVER resolved as `closed`, and NEVER carries a fabricated `pnl`.** | **MUST FAIL** (returns `resolved`, `pnl=-20.45`) |
| **2** | Held position, real Alpaca shape, **no** close order | `== ("unchanged", None)` — **not** `unresolvable`. Marking it `unresolvable` writes `pnl=NULL`, dropping it from `get_open_alpaca_positions` (`src/db.py:128`) and killing its stop/target/exit-advisor **while live at Alpaca**. | **MUST FAIL** (returns `unresolvable`) |
| **3** | Symbol-shape matrix — both sides, all four combinations: row `BTC/USD`\|`BTCUSD` × live `BTC/USD`\|`BTCUSD` | All four → `"unchanged"`. Normalization is applied to **both** sides, via `src.universe.normalize` (not a local `.replace`). | 2 of 4 fail |
| **4** | **Genuinely vanished** position (regression guard) — `row["symbol"]="BTC/USD"`, `live_symbols={"ETHUSD"}`, close order present | `== ("resolved", {...})` with correct realized P&L + fees. **Positive control:** the fix must not make the backfill inert — it must still resolve real closes. | passes (must keep passing) |
| **5** | Driver-level normalization — `backfill(apply=False)` with a held symbol | The driver's second compare (`src/backfill.py:155`) is also normalized: **no `get_closed_orders` call is issued** for a held symbol. Fixing only `:72` leaves the driver hunting closes for held positions. | **MUST FAIL** |
| **6** | **The `None` third door** (landmine NOT in CONTEXT) — `client.get_positions()` returns `None` (Alpaca outage) | The bot's backfill **aborts / leaves rows unchanged**. It MUST NOT coerce `None` → `set()` (`src/backfill.py:148`'s `or []`), which would resolve **every** position as vanished and terminate the whole live book. Mirrors `src/alpaca_orchestrator.py:133-134`. | **MUST FAIL** |
| **7** | **Dry-run writes nothing** (fence) | `backfill(apply=False)` issues **zero** mutating SQL — no `update_alpaca_trade`, no `UPDATE`/`DELETE` on `alpaca_trades`. Assert via a spy on `TradeLogger.update_alpaca_trade` (call count == 0) **and** a mutating-SQL spy on the connection. | passes (must keep passing) |
| **8** | **Recovery ceiling is computable** | Dry-run returns per-bot `{resolved, unchanged, unresolvable, residue}`; `resolved` is the recovery-ceiling count. Assert the shape against fakes (no prod). | new |

---

## G2 — The paper gate excludes non-trades

`dashboard/api/routes/settings.py:36` is a bare `COUNT(*)` with **no status filter and no P&L filter**;
`submitted`/`rejected` rows are provably written (`src/bot_thread.py:362,376,382`; `:309,317,332`).
**New file: `dashboard/api/tests/test_paper_gate.py`.**

| # | Case | Assertion | Pre-fix |
|---|---|---|---|
| **9** | Non-trade rows are excluded | Seed a bot with rows: 3 × `closed` w/ real `pnl`, 1 × `submitted`, 1 × `rejected` (`pnl=0`), 1 × `open`, 2 × `closed` w/ `pnl=0.0` (sentinel), 1 × `closed` w/ `pnl=NULL`. → **`paper_trades_completed == 3`.** | **MUST FAIL** (returns 9) |
| **10** | **Static fence — the bare `COUNT(*)` never returns.** Same idiom as `test_routes.py:224`'s `100_000.0` fence. | `"SELECT COUNT(*) AS n FROM alpaca_trades"` **not in** `settings.py` source; **and** a positive control (`"paper_trades_completed="` **is** present) so the fence cannot pass vacuously. | **MUST FAIL** |
| **11** | The gate reading WORSE is not "fixed" back | `paper_trades_completed` derives from the **canonical** RESOLVED predicate (`status IN ('closed','stopped','target_hit') AND pnl IS NOT NULL AND pnl <> 0`, `src/db.py:95`), and `paper_trades_target` stays **50**, `win_rate_target` stays **40.0**. | new |

> **DO NOT assert `655 → 260`.** Research **R1** refuted that arithmetic: `KNOWN_BOTS = ("A","B","C","D")`
> (`dashboard/api/db.py:19`) while Phase 17's 655/395 figures cover **A/B/C/E** *position-closed* rows —
> two different populations. The **fix** is justified by the code; the **magnitude** is unverified.
> `e2e_verify.py` **measures** before/after. Any case asserting a specific live count is asserting a number
> nobody has confirmed.

---

## `scripts/e2e_verify.py` is SELECT-only

| # | Case | Assertion |
|---|---|---|
| **12** | **Static fence** | `scripts/e2e_verify.py` source contains **no** `UPDATE`/`DELETE`/`INSERT`/`DROP`/`ALTER` against `alpaca_trades`, **no** `--apply`, and **no** `apply=True`. **Positive control:** the scanned slice is non-empty and contains a known-present token (e.g. `"reconcile"`) — copies the `tests/test_phase19_fences.py` idiom, which runs a positive control precisely so a fence cannot pass vacuously. |
| **13** | **The fence self-test — PROVE THE FENCE FIRES** | Run the case-12 fence function against a **deliberately-mutating fixture string** (`"UPDATE alpaca_trades SET pnl = 0"`) and assert it **raises / returns False**. *A fence that has never failed is a fence nobody has tested.* |
| **14** | **The script self-enforces read-only** | `scripts/e2e_verify.py` sets `AIPW_DB_READONLY=1` **before** the first `src.db` import (import order is load-bearing — `get_pool()` latches `_pool` on first call). Assert the token appears in source **ahead of** the `src.db` import line, so the guarantee is a property of the script, not of how it was invoked. |
| **15** | **No DDL on import** (regression guard on `src/db.py:53`) | With `AIPW_DB_READONLY=1`, `get_pool()` does **not** call `_bootstrap_schema()`. Already covered by `tests/test_db_readonly.py` case 23 — assert it still holds (this is the guarantee `e2e_verify.py` rests on). |
| **16** | `INSUFFICIENT_SAMPLE` and `FAIL` both exit **non-zero** | The CLI's exit code is non-zero for `FAIL` **and** for `INSUFFICIENT_SAMPLE`. **`INSUFFICIENT_SAMPLE` is NOT a PASS.** |

---

## G4 — The windowed reconciliation math

Extends `tests/test_reconciliation.py`. Reuses `reconcile_bot` (`src/reconciliation.py:16-42`) with
`starting_equity := equity_T0` — **not** a second copy of the subtraction.

| # | Case | Assertion |
|---|---|---|
| **17** | Window arithmetic | `alpaca_realized_window = (equity_now - equity_T0) - (unrealized_now - unrealized_T0)`; `trade_log_window = trade_log_pnl_now - trade_log_pnl_T0`; `delta_window = trade_log_window - alpaca_realized_window`. Cent-exact on a hand-computed fixture. |
| **18** | A losing **open** position raises derived realized | Signed `unrealized` handled correctly across the window (negative `unrealized_now` **increases** `alpaca_realized_window`) — the sign trap `reconcile_bot`'s docstring already calls out. |
| **19** | Tolerance floor | `alpaca_realized_window = $100` → `tolerance_window == max(25.0, 0.005*100) == 25.0`. The **$25 floor** binds on small windows. |
| **20** | Tolerance band | `alpaca_realized_window = $100_000` → `tolerance_window == 500.0` (0.5%). The **relative band** binds on large windows. |
| **21** | Boundary is inclusive | `abs(delta_window) == tolerance_window` → `within_tolerance is True` (matches `reconcile_bot`'s inclusive `<=`). |
| **22** | **`INSUFFICIENT_SAMPLE` is not a PASS** | With **19** post-`T0` resolved trades → verdict `INSUFFICIENT_SAMPLE`, **even when `abs(delta_window) == 0`**. A perfect delta on a thin sample is still not a pass. At **20** → verdict is `PASS`/`FAIL` on the math. |
| **23** | Resolution-rate bar | `resolved / (resolved + unresolved)` over rows with `timestamp >= T0` and terminal status. `< 0.95` → **FAIL**; `>= 0.95` → passes the clause. |
| **24** | **The tolerance CANNOT be widened to force a PASS** (fence) | `RECONCILIATION_TOLERANCE_USD` default is **25.0** (`src/reconciliation.py:12`) and `RECONCILIATION_TOLERANCE_PCT` default is **0.005**. Static-assert both defaults in source; assert **no** committed config/env file raises either. *Widening a tolerance until the breach disappears is the single most tempting dishonest move in this phase and it is BANNED.* |
| **25** | **`legacy_offset_usd` is surfaced, never hidden** | The windowed payload carries `legacy_offset_usd` (the all-time delta at `T0`) **and** its authorization note, and the all-time row is emitted with `legacy: true`. Assert both keys present and non-suppressed. *A number excluded from a check must be visible next to the check, or the exclusion is a lie of omission.* |
| **26** | The all-time breach is **expected**, not a fresh failure | An all-time `within_tolerance: false` alongside a windowed `PASS` yields an overall **PASS** (the legacy offset is reported, not counted as a regression). |

---

## The anchor table + the schema mirror

| # | Case | Assertion |
|---|---|---|
| **27** | Migration is additive + idempotent | `020_reconciliation_anchor.sql` uses `CREATE TABLE IF NOT EXISTS`; contains **no** `DROP`/`DELETE`/`ALTER`/`UPDATE`; **no** `bot_id` CHECK constraint (migration 009 dropped it for C/D). Applying it **twice** is a no-op. Mirrors `017_reconciliation.sql`. |
| **28** | **The `src/db_schema.sql` mirror exists** | `reconciliation_anchor` appears in **`src/db_schema.sql`** as well as in the migration. *A migration-only table is absent from every fresh-DB bootstrap and every test DB — it would exist in prod and nowhere else.* Assert by parsing `CREATE TABLE` names out of `src/db_schema.sql` (which already correctly mirrors `reconciliation` at `:215` and `runtime_heartbeat` at `:231`). |
| **29** | **The anchor is written ONCE — `ON CONFLICT DO NOTHING`, never an UPSERT** | Writing the anchor twice must **not** move `T0`. Assert: second write leaves `anchored_at`/`equity`/`unrealized_pnl`/`trade_log_pnl` **unchanged**; assert the source contains `DO NOTHING` and **not** `DO UPDATE`. *An UPSERT would silently re-anchor `T0` to "now" on every run, resetting the window to zero samples and making the check vacuously green — the same class of self-defeating move as widening the tolerance.* |
| **30** | The anchor uses **per-bot** Alpaca keys | The anchor writer sources its client from `reconciliation._client_for_bot` (`:62-93`) — never a bare/shared `ALPACA_API_KEY`. A keyless bot **raises**. (One account per bot — hard rule.) |

---

## G1 — The end-to-end chain (the seam nothing tests)

**New file: `tests/test_e2e_reconciliation.py`.** One fake-driven chain — submit → partial fill → external
exit → `resolve_stale_row` → resolved row → `get_realized_pnl` → `reconcile_bot` → `within_tolerance`.
Asserts the **joins**, not the links (every link is already unit-tested; a sign error *at a join* survives
the current 488).

| # | Case | Assertion |
|---|---|---|
| **31** | **Full chain, LONG** | submit → fill → external exit → resolved row → `get_realized_pnl` → `reconcile_bot` → `within_tolerance is True`. The trade log's realized P&L **agrees with the Alpaca-derived figure to the cent** across the whole chain. |
| **32** | **Full chain, SHORT** | Same, side `sell`. Catches a sign inversion that a long-only chain cannot. (Phase 17 EVIDENCE flags sign-inverted shorts on the fee-less rows — this is the seam that would have caught it.) |
| **33** | **Fees carry through the join with the right sign** | Fees **reduce** realized P&L on both sides. A gross-vs-net mismatch at the `resolve_stale_row` → `get_realized_pnl` join is caught. (VERIFY-01's "realized-P&L math **with fees**" clause, at the seam.) |
| **34** | **Slashed / slashless shapes survive the chain** | A row written slashed (`BTC/USD`) and an Alpaca payload returned slashless (`BTCUSD`) reconcile correctly end-to-end. This is G3's bug, caught at the chain level. |
| **35** | **A `pnl = NULL` (unresolvable) row is excluded from BOTH numerator and denominator** | It is **not booked as a loss**. Assert it moves neither `get_realized_pnl` nor the win-rate denominator — the exact defect Phase 19's RESOLVED predicate (`src/db.py:95`) exists to prevent, asserted here **through the chain** rather than on the predicate alone. |
| **36** | **A `pnl = 0.0` sentinel row is likewise excluded** | The historical sentinel shape does not become a loss anywhere in the chain. |

---

## Fences — the things this phase must NOT do

Extends `tests/test_phase19_fences.py` (which already calls `src/backfill.py` **"a LOADED GUN"**). Every fence
runs a **positive control** first so it cannot pass vacuously.

| # | Case | Assertion |
|---|---|---|
| **37** | **No prod trade-data write anywhere in the phase** | The `_TRADE_WRITER_ALLOWLIST` (`src/db.py`, `dashboard/api/routes/positions.py`) is **unchanged**. `scripts/e2e_verify.py` does **not** join it. No new module writes `UPDATE`/`DELETE` on `alpaca_trades`. |
| **38** | **The backfill stays UNARMED** | No committed code, script, migration, CI step or entrypoint invokes `backfill(apply=True)`. The 395 rows are untouched. |
| **39** | **The hardcoded risk rules are untouched** | Max 5% bankroll/position, quarter-Kelly, 20% drawdown stop, limit-orders-only, 50 paper trades, max 3 correlated positions, max 10 sims/cycle — all unchanged. |
| **40** | **No `bots` config knob moved** | `min_confluence`, `kelly_fraction`, `quarantined_symbols` unchanged — **that is Phase 21.** No retune here. |
| **41** | **Zero new skips** | `pytest tests/ dashboard/api/tests/ -q` → skipped count is **still 29**. Every new case above runs offline against fakes. |

---

## Exit criteria

- [ ] **Cases 1, 2, 5, 6, 9, 10 FAIL on today's `main`** (verified pre-fix), and pass after. *If they pass before the fix, they are not testing the bug.*
- [ ] Full suite green: **488 baseline + new cases, 29 skipped (unchanged).**
- [ ] `scripts/e2e_verify.py` runs SELECT-only against prod under `AIPW_DB_READONLY=1`; output committed to `20-EVIDENCE.md` with a provenance header (source, read-only proof, reproduce command).
- [ ] `20-EVIDENCE.md` carries the **VERIFY-01 traceability matrix** (clause → test file → case names) and the **dry-run recovery-ceiling** count per bot.
- [ ] `legacy_offset_usd` reported per bot with its authorization note; all-time row labelled `legacy: true`.
- [ ] The **blocking human checkpoint** for the backfill is surfaced with its exact `--apply` command and rollback — **and not executed.**
- [ ] VERIFY-02 closed as **VERIFY-02 (scoped)** in `.planning/REQUIREMENTS.md`, in the same "PARTIAL, and here is exactly why" register TUNE-01 uses — not silently ticked.
