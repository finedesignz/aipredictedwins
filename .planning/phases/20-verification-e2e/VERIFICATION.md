---
phase: 20-verification-e2e
verified: 2026-07-14T07:35:00Z
status: passed
score: 12/12 must-haves verified
verifier: gsd-verifier (independent, goal-backward)
commits_verified: 1aabe06..f1e6e29
scope: plans 20-01..20-06 + 20-08 (20-07 deliberately NOT executed — credentials gate + 395-row authorization checkpoint)
warnings:
  - "src/db.py stale docstring: still claims trend_strategy.py:172-173 and bot_c/strategy.py:393-395 store a GROSS pnl with no fees arg. 20-08 fixed both. Doc drift only — no behavior impact."
  - "The `positions is None` arm (backfill.py:163, e2e_verify.py:155) is defensive-only: AlpacaClient.get_positions() RAISES after 3 retries and never returns None. An Alpaca outage therefore aborts the backfill with an exception (still fail-closed, zero writes) rather than emitting counts['error']='positions_unavailable'. Safety property holds; the labelled distinction is unreachable with the real client."
---

# Phase 20: Verification & E2E Reconciliation — Verification Report

**Goal:** VERIFY-01 (the backfill/paper-gate/P&L writers tell the truth) + VERIFY-02 (an anchored, unfakeable E2E reconciliation check).
**Verified:** 2026-07-14 · independent, goal-backward, adversarial. SUMMARY.md claims were not used as evidence.
**Verdict:** **SHIP**

## Priority 1 — The loaded gun (backfill)

| # | Truth | Status | Evidence (executed, not read) |
|---|-------|--------|------------------------------|
| 1 | Both compare sites normalize via `src.universe.normalize`, against the REAL slashless shape | **PASS** | `alpaca_client.py:146` → `"symbol": pos.symbol` (raw, `BTCUSD` for crypto). `backfill.py:80-81` normalizes live set AND row; `backfill.py:173,180` normalizes driver-side. Ran a 16-cell symbol matrix (`BTC/USD`/`BTCUSD`/`btc/usd`/` BTC/USD ` × `BTCUSD`/`BTC/USD`/`btcusd`/` BTCUSD`) through `resolve_stale_row` with a matching close order present: **0 leaks — all 16 return `unchanged`.** |
| 2 | The OLD code really was armed and lethal | **PASS** | Loaded `f6fa89c^:src/backfill.py` and ran the real Alpaca shape: `resolve_stale_row(row BTC/USD, filled, ["BTCUSD"], close)` → `('resolved', {status:'closed', pnl: -10.475})`. **The old backfill closed a HELD position with a fabricated loss.** Old driver contained `or []`; old resolver raised `TypeError` on `None`. |
| 3 | The corrected tests genuinely fail against the OLD backfill | **PASS** | Swapped `src/backfill.py` for the pre-fix file and ran `tests/test_backfill.py`: **8 failed, 17 passed** — incl. `test_held_position_real_alpaca_shape_is_unchanged`, `test_symbol_shape_matrix`, `test_get_positions_none_aborts_the_bot`, `test_resolve_stale_row_treats_None_live_symbols_as_the_SAFE_arm`. Restored. Not a tautological RED. |
| 4 | The `None` sentinel is PRESERVED (never `or []`) | **PASS** | `backfill.py:162-171` — bare `client.get_positions()`, explicit `if positions is None: … continue`. No `or []` anywhere in `src/backfill.py`. `resolve_stale_row` short-circuits `live_symbols is None → unchanged` BEFORE any membership test (line 75-76), proven by direct call with a close order present. |
| 5 | No remaining path resolves a held/open position as closed | **PASS** | Adversarial inputs constructed and executed: held (any shape) → `unchanged`; Alpaca-down (`None`) → `unchanged`; in-flight entry → `unchanged`; gone + no close → `unresolvable`; empty real book + no close → `unresolvable`. Only `filled + genuinely absent + a qty-matched, time-ordered opposite close` resolves. The `_QTY_TOLERANCE` guard (2%) and strict `filled_at >` ordering hold. |
| 6 | `counts["error"] = "positions_unavailable"` distinguishes outage from empty book | **PARTIAL → PASS (safety), WARNING (labelling)** | The branch exists and sets `error` + `residue` and `continue`s (line 168-172), and `test_get_positions_none_aborts_the_bot` passes. **But** `AlpacaClient.get_positions()` never returns `None` — `_retry` re-raises after 3 attempts (`alpaca_client.py:45-63`). A real outage therefore raises out of `backfill()` — no rows touched, fail-closed, still safe. The distinction is delivered by a crash, not by the field. Filed as WARNING, not a blocker: **the dangerous outcome (silent book-wide close) is impossible on both paths.** |
| 7 | Backfill is still UNARMED | **PASS** | `scripts/backfill_trades.py` is referenced by NOTHING outside itself and `tests/test_phase19_fences.py` (which asserts it is the only armed `--apply` entrypoint). Zero hits in Dockerfile / docker-compose / .github / cron / any orchestrator or dashboard module. `src/backfill.py` is imported by `alpaca_orchestrator.py:32` for the PURE resolver (`resolve_stale_row`, `_match_close`) only — the live monitor reuses the same, now-fixed decision function. **No `--apply` run has occurred.** |

## Priority 2 — 20-08 touches live trading code

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 8 | The changes alter only what is RECORDED, never a decision | **PASS** | `trend_strategy.py:163-189` — the `for row in logger.get_open_alpaca_positions()` loop sits AFTER `alpaca.place_market_order(...)` succeeded and is wrapped in its own `try/except` that only `log.warning`s. `bot_c/strategy.py:386-419` — identical shape: order placed at 386, DB-marking loop at 404-417. **Nothing branches on `pnl` or `fees`; no `if pnl`, no early return, no order call inside either loop.** Entry paths untouched. |
| 9 | Long path unbroken, short sign now correct | **PASS** | Both sites call `realized_pnl(side, entry, current_price, q, TAKER_FEE)` with the ROW's actual side. `src/pnl.py`: short `(entry-exit)*qty - fees`, long `(exit-entry)*qty - fees`. Executed: long 100→90 = **-10.0**; short 100→90 = **+10.0**. The old inline formula was long-only-signed (a short's win recorded as a loss). |
| 10 | No double-counting of fees | **PASS** | `realized_pnl` already subtracts fees → `pnl` is NET. `fees` is written alongside as an informational column. `db.get_realized_pnl` (`db.py:299-312`) is `SELECT pnl … ; sum(r["pnl"] or 0.0)` — **it does not read or subtract `fees`.** No double count. |
| 11 | Historical rows untouched | **PASS** | `git diff 7d9be73..f1e6e29 -- src/ dashboard/ scripts/` contains **zero** `UPDATE`/`DELETE`/`DROP`/`TRUNCATE` SQL. The only new `INSERT` is `INSERT INTO reconciliation_anchor … ON CONFLICT (bot_id) DO NOTHING`. Migration 020 is `CREATE TABLE IF NOT EXISTS` only. **The 395 sentinel rows are byte-identical.** |

## Priority 3 — Can a PASS be manufactured?

| # | Truth | Status | Evidence (executed) |
|---|-------|--------|---------------------|
| 12 | A widened tolerance cannot manufacture green | **PASS** | Ran `RECONCILIATION_TOLERANCE_USD=100000 python scripts/e2e_verify.py` → printed `TOLERANCE_OVERRIDE — REFUSING TO GRADE AGAINST A TAMPERED RULER`, graded **no** bot, emitted the word PASS **nowhere**, **exit 2**. Same with `--json` (`"error": "TOLERANCE_OVERRIDE", "bots": []`, exit 2) and with `RECONCILIATION_TOLERANCE_PCT=9` (exit 2). The abort happens in `main()` **before** `build_report()` — prod is never queried. |
| — | Any OTHER lever? | **PASS** | `MIN_WINDOW_SAMPLE = 20` and `RESOLUTION_RATE_BAR = 0.95` are module constants — `grep os.environ src/reconciliation.py` returns ONLY the two tolerance readers and the per-bot Alpaca keys. `exit_code()`: `INSUFFICIENT_SAMPLE → 1`, `NO_ANCHOR → 1`, any `error → 1`, empty bots → 1. **Neither can be coerced into a pass.** No `--apply`/`--write`/`--fix`/`--tolerance` flag is defined. |
| — | `AIPW_DB_READONLY=1` set before the first `src` import | **PASS** | `os.environ["AIPW_DB_READONLY"] = "1"` precedes `from src import db` in source line order. `db._readonly()` gates BOTH the libpq `options=-c default_transaction_read_only=on` (`db.py:38-42`) and `_bootstrap_schema()` (`db.py:52-56`), both latched on first `get_pool()`. `tests/test_e2e_verify_fences.py` (6 passed, 0 skips) statically asserts the line order and self-tests that the fence fires. **No write path exists: no INSERT/UPDATE/DELETE/DDL in the script, and Postgres would reject one with 25006.** |
| — | `e2e_verify.py` never calls `ensure_anchor` | **PASS** | `grep -rn ensure_anchor scripts/` → **no hits in e2e_verify.py**. Only `src/reconciliation.py:180,275` (manager's writable path) and tests. The fence test asserts `"ensure_anchor" not in src`. A missing T0 reports `NO_ANCHOR` and exits 1. |

## Also verified

| Item | Status | Evidence |
|------|--------|----------|
| Migration 020 + `db_schema.sql` mirror both present | **PASS** | `dashboard/api/migrations/020_reconciliation_anchor.sql` + `src/db_schema.sql:239-255` (`CREATE TABLE IF NOT EXISTS reconciliation_anchor`). Bootstrap DBs and test DBs get the table. |
| `ON CONFLICT (bot_id) DO NOTHING` | **PASS** | `db.py:439` inside `write_reconciliation_anchor`. Never `DO UPDATE` — T0 cannot be re-anchored to "now" (which would make the window vacuously green). `ensure_anchor` is read-or-create and returns an existing anchor unchanged. |
| Zero new skips | **PASS** | New fence files: `test_e2e_verify_fences.py` 6 passed / 0 skipped; `test_phase19_fences.py` no skip markers. The 5 `+skip` diff lines are prose in docstrings. |
| Constants unmoved | **PASS** | `DEFAULT_TOLERANCE_USD = 25.0` (reconciliation.py:13), `paper_trades_target: int = 50` / `win_rate_target: float = 40.0` (models.py:184/186), `mode: str = "paper"`. The 20-04 gate change makes the gate **stricter** (`paper_trades_completed = resolved`, raw count demoted to a reported `total_rows`) — it does not open it. |
| Phase 18/19 killer fixes intact | **PASS** | `any_alive` escape: **zero hits in `src/`** (still deleted). `bots.py` still derives status from thread liveness. `is_resolved` predicate still canonical in `db.py`. All Phase-19 fence tests pass. |
| Full suite | **PASS** | `python -m pytest tests/ dashboard/api/tests/ -q` → **541 passed, 29 skipped**, 0 failed. Phase-20 files alone: 77 passed, 2 skipped (both pre-existing). |
| 20-07 not executed | **CONFIRMED (intended)** | `20-07-PLAN.md` present, no SUMMARY, no commit. The backfill was never run with `--apply`. Held behind the credentials gate + 395-row authorization checkpoint, as briefed. |

## Warnings (non-blocking)

1. **Stale docstring — `src/db.py` (~line 331).** Still asserts that `bot_c/strategy.py:393-395` and `trend_strategy.py:172-173` "store a GROSS pnl and pass no fees arg" and that "NULL fees is the TELL that pnl is gross." 20-08 fixed both writers; new closes carry NET pnl + fees. The NULL-fees TELL is now a HISTORICAL marker only. Fix the comment before it misleads the next reader into distrusting fresh rows.
2. **`positions_unavailable` is unreachable with the real client** (see truth 6). Either give `get_positions()` a `None`-on-failure contract or drop the label and document that an outage aborts by exception. **Zero risk today** — both paths are fail-closed.

## Ship verdict

> **SHIP.** The backfill's trigger is disarmed and the disarming is proven, not asserted: against the real slashless shape Alpaca actually returns, the pre-fix resolver closed a HELD BTC position with a fabricated `-10.475` loss, and the post-fix resolver returns `unchanged` across all 16 symbol-shape permutations, with the `None` outage sentinel preserved and no `or []` anywhere. Eight corrected tests fail against the old file — the RED was real. The gun is also still unloaded: `scripts/backfill_trades.py` is wired into nothing and has never been run with `--apply`. 20-08 touches live exit writers but only the DB-marking loop that runs *after* `place_market_order` — nothing branches on `pnl`, the long path is unchanged, the short sign is now correct, and `get_realized_pnl` sums `pnl` without re-subtracting `fees`, so there is no double count and not one historical row was mutated. The verification check cannot be made to lie: a widened tolerance aborts at exit 2 before prod is even queried and prints no verdict; `INSUFFICIENT_SAMPLE` and `NO_ANCHOR` both exit non-zero; `MIN_WINDOW_SAMPLE` and the resolution bar are constants with no env lever; `AIPW_DB_READONLY=1` is fenced by source line order into a Postgres-enforced read-only pool; and the script never anchors itself. 541 passed, 29 skipped, zero new skips. Two documentation-grade warnings, no blockers. Proceed — and hold 20-07 exactly where it is.

---
_Verified independently: Claude (gsd-verifier). Not committed — orchestrator bundles._
