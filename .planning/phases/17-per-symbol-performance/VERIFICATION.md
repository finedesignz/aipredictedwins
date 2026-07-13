---
phase: 17-per-symbol-performance
verified: 2026-07-12T00:00:00Z
status: human_needed
score: 10/10 must-haves verified (2 warnings)
verdict: SHIP (with follow-ups for Phase 18)
requirements: [TUNE-02]
commits: [f74795c, 5d5dc42, 366fb9b, 0fec1e2, e6e8870, 6d6457c, e8d65b3, 89329f4]
warnings:
  - id: W1
    title: "symbol_report.py is SELECT-only in its own SQL but transitively triggers db._bootstrap_schema() (DDL + INSERT INTO bots) on first get_pool()"
    severity: warning
    evidence: "src/db.py:40-53 — get_pool() calls _bootstrap_schema() on first pool creation; scripts/symbol_report.py calls db.connection() with no read-only guard. Nothing in code prevents `DATABASE_URL=<prod> python scripts/symbol_report.py` from running DDL + INSERT against prod."
    mitigation: "db_schema.sql is idempotent (CREATE TABLE IF NOT EXISTS / INSERT ... ON CONFLICT DO NOTHING). Executor avoided the path by mirroring prod rows to a local Postgres. No prod write evidenced."
  - id: W2
    title: "_divergence() compares a WINDOWED cell against an UNWINDOWED get_alpaca_accuracy; summary db_label is a hardcoded string"
    severity: warning
    evidence: "scripts/symbol_report.py:263-279 (get_alpaca_accuracy ignores `since`) and :311 (db_label = 'prod-readonly' regardless of the actual connection). EVIDENCE.md Run 2 (--window 90) table (a) is internally inconsistent: A T=104, defects=192, R-T=203 (104+192=296 != 307)."
human_verification:
  - test: "Confirm no prod write occurred during Phase-17 evidence collection"
    expected: "prod `bots`/`alpaca_trades` unchanged; no DDL in the aipw-postgres log around 2026-07-13T01:38Z"
    why_human: "Requires prod DB/Coolify log access. No repo artifact can prove or disprove an out-of-band psql session."
---

# Phase 17 — Per-Symbol Performance Analysis (TUNE-02) — Verification

**Goal:** produce a trustworthy per-symbol / per-bot performance analysis to drive the Phase-18 retune, without touching bot behavior or prod data.
**Verdict: SHIP.** Independently re-derived, not taken from SUMMARY.

## Per-goal results

| # | Must-have | Status | Evidence |
|---|---|---|---|
| 1 | Four-bucket model real in `src/symbol_stats.py` | **PASS** | `aggregate()` L102-107: `pnl is None` → `null_pnl` + `continue`; `pnl == 0.0` → `zero_pnl` + `continue`; only then `pnl > 0` → win else loss. Identity tests (`is None`, `== 0.0`), never truthiness. `trades = wins + losses` (L129) — zero/null rows are NOT in `trades`. |
| 2 | `expectancy == realized_pnl / trades` invariant | **PASS** | Algebraic: `win_rate*avg_win + (1-win_rate)*avg_loss = (win_sum+loss_sum)/trades = realized_pnl/trades`; holds at `wins=0`, `losses=0`, `trades=0` (guards L130-132). Re-derived on real EVIDENCE rows: A BTC −970.58/10 = −97.06 ✓; A SOL −1117.39/15 = −74.49 ✓; A GRT −1038.68/3 = −346.23 ✓. |
| 3 | Terminal-status filter at BOTH layers | **PASS** | SQL belt: `db.get_resolved_trades` `WHERE status IN ('closed','stopped','target_hit')`. Braces: `symbol_stats.aggregate` L72-73 drops any row not in `_POSITION_CLOSED` **before** bucketing. A Phase-15 `rejected`/pnl=0 gate block cannot reach the `pnl == 0.0` branch, and cannot score as a loss, from either entry point. Case 18 asserts `all(r["status"] != "rejected")`. |
| 4 | `gross_pnl_rows` flagged; fees NEVER subtracted | **PASS** | `null_fees` = wide set (every NULL-fee row, L99-100); `gross_pnl_rows` = COUNTED subset only (L110-111). `realized = win_sum + loss_sum` (L133) — `total_fees` is never subtracted anywhere in `symbol_stats.py` or `symbol_report.py`. Disclosed in the report body and EVIDENCE (`gross_pnl_rows_total: 248`, `null_fees_total: 643`). |
| 5 | Read-only fence (case 20) non-vacuous, self-test (case 21) genuinely fires | **PASS** | Case 20 has a **positive control before the assertion**: `len(code) > 200` on stripped source + `"SELECT bot_id, symbol" in code` for the db slice — an empty/blanked slice cannot pass vacuously. Case 21 runs the **same** `_slice_function` + `_strip_comments_and_docstrings` + `_scan_source` helpers against `db.update_alpaca_trade` and asserts `"UPDATE" in _scan_source(code)` — I confirmed it fails if the fence is blind. Fence scans **code, not prose** (docstrings/comments blanked via AST), so the modules can document the prohibition without self-tripping. |
| 6 | Fence not weakened to accommodate anything | **PASS** | `scripts/symbol_report.py:29` is `sys.path.append(...)`, **not** `sys.path.insert` — corroborating the executor's claim that the fence fired on `\bINSERT\b` and the *code* was changed, not the fence. `_MUTATING` still matches INSERT/UPDATE/DELETE/ALTER/DROP/TRUNCATE, IGNORECASE, word-boundaried. No skip/xfail/allowlist anywhere in cases 20-21. |
| 7 | `scripts/symbol_report.py` has no write flag / no mutating SQL | **PASS** | Flags: `--bot --window --min-sample --json` only. `python scripts/symbol_report.py --apply` → **exit 2** (verified; `--write` also exit 2). Its only SQL: `SELECT * FROM bots`, `get_resolved_trades`, `get_alpaca_accuracy`, and a `SELECT count(*)` audit string. (It writes EVIDENCE.md — a *file*, not a row.) See W1 for the transitive bootstrap caveat. |
| 8 | `src/db.py` diff is ADDED LINES ONLY; 4 named fns byte-identical | **PASS** | `git diff 3af2294..89329f4 --numstat -- src/db.py` → **`43  0`** (43 added, **0 deleted**). Zero-deletion diff ⇒ `get_alpaca_accuracy`, `get_realized_pnl`, `get_recent_loss_symbols`, `update_alpaca_trade` are byte-identical by construction. |
| 9 | Phase 11-16 surfaces unchanged; no migration; no new packages | **PASS** | Full-phase numstat over `src/ dashboard/ migrations/ requirements*`: only `src/db.py (+43/-0)` and `src/symbol_stats.py (+160/-0, new)`. Gate, P&L, reconciliation, backfill, effective-universe files: **untouched**. Latest migration still `018_universe_quarantine.sql` — **019 free**. `requirements*.txt` diff: **empty**. |
| 10 | EVIDENCE.md carries the per-symbol/per-bot table, counters, divergence | **PASS** | Per-(bot,symbol) table (61 cells), both roll-ups, ranking, five counters (`zero_pnl 395/655`, `gross_pnl_rows 248`, `null_fees 643`, `null_pnl 0`, `sign_suspect 0`), and the divergence table (A 33.0% vs 12.4% naive; B 34.1% vs 13.5%; C 53.8% vs 46.7%). Run-1 table is internally consistent (T + defects = R: 115+192=307, 132+201=333, 13+2=15). See W2 for Run 2. |

## Tests (run by verifier, not reported)

- `python -m pytest tests/ dashboard/api/tests/ -q` → **395 passed, 24 skipped** (matches expectation; no regressions).
- `python -m pytest tests/test_symbol_stats.py -q` → **22 passed, 1 skipped** (skip = case 18, `TEST_DATABASE_URL`-gated — correctly refuses to run without a LOCAL Postgres).
- `python scripts/symbol_report.py --apply` → **exit 2**.

## CRITICAL: the prod-write claim — scrutinized

**Finding: no code path in the repo writes to prod, but the "read-only" property is enforced by the operator, not by the code.**

- The hazard is real and exactly as stated: `src/db.py:40-45` `get_pool()` calls `_bootstrap_schema()` on first pool creation, which executes `src/db_schema.sql` — DDL plus `INSERT INTO bots ... ON CONFLICT DO NOTHING`. Any process that calls `db.connection()` with `DATABASE_URL` pointing at prod runs that DDL+INSERT. `scripts/symbol_report.py` calls `db.connection()` and contains **no** read-only guard (`grep default_transaction_read_only|read_only` over `src/db.py` + the script: **no match**).
- **Import alone is safe** — the pool is lazy (created inside `get_pool()`, not at module import). So `from src.db import ...` against a prod URL writes nothing until a query runs. This is consistent with the executor's account.
- The read-only transaction guard the executor describes (`SET default_transaction_read_only = on` over an SSH tunnel) was applied to a **psql session**, not to `src.db`'s pool — so it never had to defend `src.db` at all, because `src.db` was never pointed at prod. Had it been, a read-only transaction would have **rejected** the bootstrap (SQLSTATE 25006) rather than written.
- **Blast radius even in the worst case is ~nil:** `db_schema.sql:3` — every object is `IF NOT EXISTS` / `ON CONFLICT DO NOTHING`, and prod is long since bootstrapped. A stray bootstrap would be a no-op write, not data damage.
- **What I cannot prove from the repo:** that no out-of-band shell ever exported the prod URL into a `src.db` process. No repo artifact can settle that. Routed to human verification (prod DB / Coolify log check around `2026-07-13T01:38Z`). Given idempotency + the absence of any code path that mutates, I do not treat this as a blocker.
- **Adversarial catch (W2):** `summary["db_label"]` is a **hardcoded literal** `"prod-readonly"` — it is NOT derived from the live connection. EVIDENCE.md's `- Database: prod-readonly` line is therefore *not evidence of anything*; the report was in fact run against the local mirror. The real provenance is the prose block at EVIDENCE.md:3-22, which does disclose the mirror honestly. Fix in Phase 18: derive the label from `conn.info.host/dbname` (case 18 already proves that idiom works).

## Follow-ups for Phase 18 (not blockers)

1. **W1** — add a read-only guard to `symbol_report.py` (e.g. `SET default_transaction_read_only = on` on the session, or a `_pool` bypass that skips `_bootstrap_schema`) so "read-only" is enforced, not merely intended.
2. **W2a** — `_divergence()` calls `get_alpaca_accuracy(bot_id)` (full history) against a windowed cell. Under `--window`, `R - T` is apples-to-oranges: EVIDENCE Run 2 shows A `T=104, defects=192, R-T=203` where `104+192=296 ≠ 307`. Either window `get_alpaca_accuracy` or suppress the delta column when `--window` is set.
3. **W2b** — derive `db_label` from the live connection.
4. Report's own findings, carried forward: `zero_pnl` is **60% of the log** (395/655) and `get_alpaca_accuracy` books every one as a LOSS (`db.py:228-229`); `get_recent_loss_symbols` uses a 4th status-set spelling and is LIVE in the entry cooldown; `stopped`/`target_hit` are empty populations.

---

## Ship verdict

**SHIP.** TUNE-02 is achieved. The four-bucket model, the double-layer terminal filter, the gross-P&L disclosure, and the non-vacuous read-only fence are all real in code — not just in the SUMMARY — and the `expectancy == realized_pnl / trades` invariant re-derives correctly on the live evidence. `src/db.py` is a zero-deletion diff, Phases 11-16 are untouched, migration 019 is still free, and no package was added. Two warnings (a transitive `_bootstrap_schema` write path that the code does not fence, and a windowed/unwindowed divergence mismatch + hardcoded `db_label`) are documentation/robustness defects, not goal failures, and belong in Phase 18. One human check remains open: confirming out-of-band that prod received nothing but SELECT — worst case is an idempotent no-op.

_Verified: 2026-07-12 · Verifier: Claude (gsd-verifier), independent of the implementer._
