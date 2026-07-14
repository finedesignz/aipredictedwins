# Phase 20 — Verification & E2E Reconciliation — PLAN INDEX

**Requirements:** VERIFY-01, VERIFY-02 · **Milestone:** v1.1 (FINAL phase)
**Baseline:** `python -m pytest tests/ dashboard/api/tests/ -q` → **488 passed, 29 skipped**
⚠️ Bare `pytest` dies on `vendor/TradingAgents/` (14 collection errors, no `pytest.ini`/`testpaths`).
**Always pass the two paths explicitly.**

## Wave structure

| Wave | Plans | Autonomous | Owns |
|------|-------|------------|------|
| 1 | 20-01, 20-02 | yes, yes | the RED suite (tests only — no `src/` change) |
| 2 | 20-03, 20-04, 20-05, 20-08 | yes ×4 | the four fixes (disjoint files → fully parallel) |
| 3 | 20-06 | yes | `scripts/e2e_verify.py` |
| 4 | 20-07 | **no** (two blocking checkpoints) | pre-flight credential/window gate → `20-EVIDENCE.md` + REQUIREMENTS → the backfill authorization |

No two plans in the same wave share a file.

## Plans

| Plan | Wave | Objective | Files |
|------|------|-----------|-------|
| **20-01** | 1 | RED: G3 (the backfill slash bug + the `None` door) and G2 (the paper gate). **CORRECTS `tests/test_backfill.py:199`, which encodes the bug.** Cases 1, 2, 5, 6, 9, 10 must FAIL on `main`. | `tests/test_backfill.py`, `dashboard/api/tests/test_paper_gate.py` |
| **20-02** | 1 | RED: G4 (the anchored window), the anchor/schema-mirror contract, G1 (the E2E chain), and the `e2e_verify.py` SELECT-only fences — **including a self-test proving the fence FIRES.** | `tests/test_reconciliation.py`, `tests/test_e2e_reconciliation.py`, `tests/test_e2e_verify_fences.py`, `tests/test_phase19_fences.py` |
| **20-03** | 2 | Fix `src/backfill.py`: normalize BOTH compare sites via `src.universe.normalize`; preserve the `None` sentinel. **Leaves it UNARMED — no entrypoint, no `--apply`, no run.** | `src/backfill.py` |
| **20-04** | 2 | `paper_trades_completed` = the canonical RESOLVED count (no new SQL — settings.py:43-49 already runs it). `total_rows` stays reported. **The gate reads WORSE. Intended.** | `dashboard/api/routes/settings.py`, `dashboard/api/models.py` |
| **20-05** | 2 | Migration `020_reconciliation_anchor.sql` + the `src/db_schema.sql` **mirror** + the anchor read/write (`ON CONFLICT DO NOTHING`) + `reconcile_window` / `window_tolerance` / `ensure_anchor`. | `dashboard/api/migrations/020_*.sql`, `src/db_schema.sql`, `src/db.py`, `src/reconciliation.py` |
| **20-08** | 2 | **Fix the two LIVE fee-less GROSS-P&L writers** (`src/trend_strategy.py:172-173`, `src/bot_c/strategy.py:400-402`) — they push gross, long-only-signed P&L straight into the post-`T0` window that IS Phase 20's only evidence. Ships in the same deploy as `T0` → the window is **fee-clean by construction**. | `src/trend_strategy.py`, `src/bot_c/strategy.py` |
| **20-06** | 3 | `scripts/e2e_verify.py` — SELECT-only, self-sets `AIPW_DB_READONLY=1` **before** the first `src.db` import, no `--apply`, **no tolerance flag**. Prints the **EFFECTIVE tolerance + its source** and **fails loudly on an env override**. Non-zero exit on FAIL / INSUFFICIENT_SAMPLE / NO_ANCHOR (incl. `table_absent`). | `scripts/e2e_verify.py` |
| **20-07** | 4 | **Pre-flight GATE** (per-bot creds + prod DB; and: has the window even opened?) → the two READ-ONLY measurements → `20-EVIDENCE.md` → VERIFY-02 as **PARTIAL (scoped)**, on the ACTUAL state. **BLOCKING checkpoint** on the historical-row backfill. | `.planning/phases/20-verification-e2e/20-EVIDENCE.md`, `.planning/REQUIREMENTS.md` |

## The six things that must not happen

1. **The backfill is NOT run.** The historical rows are NOT touched. `--apply` is documented, never
   executed. It sits behind a blocking human checkpoint (20-07 Task 3).
2. **No tolerance is widened — INCLUDING VIA AN ENV VAR.** `RECONCILIATION_TOLERANCE_USD` stays $25.
   `_tolerance()` reads `os.environ` at CALL TIME, so a Coolify var is a lever **no committed-file grep
   can see**: `e2e_verify.py` prints the EFFECTIVE tolerance + its source and **fails loudly** on any
   override. The all-time row keeps breaching forever, relabelled `legacy: true`. **THE BREACH IS THE
   FINDING.**
3. **The anchor is never UPSERTed.** `ON CONFLICT (bot_id) DO NOTHING`. An UPSERT re-anchors `T0` every
   run → an empty window → a vacuously green check.
4. **`INSUFFICIENT_SAMPLE` is not a PASS.** < 20 post-`T0` resolved trades exits non-zero, even at a
   perfect zero delta. Neither is `NO_ANCHOR`.
5. **`NOT_RUN` closes nothing.** Credentials are a BLOCKING pre-flight gate (20-07 Task 0). The final
   phase of the milestone does not close green having measured nothing.
6. **The window's verdict is never claimed before the window opens.** `T0` is written by the manager's
   reconcile tick, after migration 020 + deploy. Until then every bot reads `NO_ANCHOR / table_absent`,
   and REQUIREMENTS.md takes **Branch B** (*not yet achieved*), never Branch A's "Achieved" language.

## Facts RESEARCH established by EXECUTION (not by reading)

- **`src/backfill.py` is a loaded gun.** A HELD `BTC/USD` position, against Alpaca's real slashless
  `get_positions()` payload, resolves TODAY as
  `('resolved', {'status':'closed','exit_price':80.0,'pnl':-20.45,'fees':0.45})` — **a live position
  closed with a fabricated loss.** The `unchanged` arm is UNREACHABLE in production.
- **The test suite encodes the bug.** `tests/test_backfill.py:199` feeds `live_symbols={"BTC/USD"}` —
  slashed, a payload Alpaca never emits — so it passes green by mirroring the defect. Wave 0 CORRECTS it.
- **Second landmine:** `backfill.py:148`'s `or []` coerces a FAILED `get_positions()` (`None`) to an empty
  set. An Alpaca outage would vanish the entire book. The monitor guards this; the backfill does not.
- **REFUTED — the "655 → ~260" projection.** `KNOWN_BOTS = ("A","B","C","D")` (unfiltered `COUNT(*)`) vs
  Phase 17's A/B/C/**E** *position-closed* figures — different bot sets AND different status filters. The
  `settings.py:36` bug is real; the magnitude is **measured**, never asserted.
- **REFUTED — the "prod mirror" recipe.** `AIPW_DB_READONLY=1` (Phase 19) already skips
  `_bootstrap_schema()` AND sets `default_transaction_read_only=on` at libpq, **enforced by Postgres
  (SQLSTATE 25006)**, pinned by `tests/test_db_readonly.py`. It satisfies "never write to prod" more
  strongly than a mirror.
- **No activities / portfolio-history call exists on `AlpacaClient`** (the full surface was enumerated).
  This **forces** the `reconciliation_anchor` snapshot design — it is not a preference.
- **The post-`T0` window is contaminated at source, and the bias EXCEEDS the tolerance.**
  `src/trend_strategy.py:172-173` and `src/bot_c/strategy.py:400-402` both write
  `pnl = (current_price - entry) * q` with **no `fees=`** — on LIVE dispatch paths (`bot_thread.py:552`,
  `:561`). `TAKER_FEE = 0.0025`, so round-trip fees are ~0.5% of **NOTIONAL**, while `window_tolerance`
  is 0.5% of **REALIZED** — quantities that differ by 10-100x. $50k of turnover producing $500 realized
  leaves a **~$250** residue against a **$25** tolerance. Plan **20-08** fixes both writers, in the same
  deploy as `T0`. Without it, Phase 20 would ship a check **biased to fail** and read its failure as a
  finding.
