---
phase: 20-verification-e2e
plan: 08
subsystem: strategies
tags: [fees, realized-pnl, sign-fix, live-code]
requires: [20-02]
provides: [fee-clean-post-t0-window]
affects: [src/trend_strategy.py, src/bot_c/strategy.py]
key-files:
  modified: [src/trend_strategy.py, src/bot_c/strategy.py]
decisions:
  - "Both sites are POST-place_market_order DB-marking loops — ONLY WHAT IS RECORDED changed, never an entry or exit decision"
  - "No historical row repaired. No migration. No .sql in the diff."
metrics:
  diff: "2 files, 30 insertions, 4 deletions"
completed: 2026-07-13
---

# Phase 20 Plan 08: both LIVE exit writers record NET realized P&L with fees

## NO HISTORICAL ROW WAS REPAIRED

No migration. No `UPDATE`. No `DELETE`. **`git diff --name-only` contains no `.sql` file.**
The 643 rows already carrying `fees IS NULL` stay exactly as they are — repairing them is a
**write to production trade data** and remains behind 20-07's blocking human authorization.

## The two call sites

```diff
+from src.fee_gate import TAKER_FEE
+from src.pnl import realized_pnl

+            side = row.get("side") or "buy"
             entry = float(row.get("entry_price") or 0)
             q     = float(row.get("qty") or 0)
-            pnl = (current_price - entry) * q if entry > 0 else 0.0
+            fees = (entry * q + current_price * q) * TAKER_FEE
+            pnl  = (realized_pnl(side, entry, current_price, q, TAKER_FEE)
+                    if entry > 0 else 0.0)
             logger.update_alpaca_trade(
                 row["id"], status="closed", exit_price=current_price, pnl=pnl,
+                fees=fees,
             )
```

Applied identically at `src/trend_strategy.py:172-173` and `src/bot_c/strategy.py:400-402`.
Both use the **same helper pair `src/backfill.py:84-85` already uses** — never a second,
drifting fee formula. `git diff --stat`: **2 files, 30 insertions, 4 deletions.**

## Proven against the pre-fix writers (stash / restore)

| | BEFORE (`main`) | AFTER |
|---|---|---|
| `fees` | **`None`** — the TELL that pnl is gross (src/db.py:331) | `(entry*qty + exit*qty) * TAKER_FEE` = **$275.00** |
| long | **`10000.0`** (GROSS) | **`9725.0`** (NET) |
| **short** | **`-10000.0`** — a **PROFIT booked as a LOSS** | **`+9725.0`** — correct sign |

```
W1/W4  AssertionError: the exit writer records NO fees  /  assert None is not None
W2/W5  AssertionError: gross P&L recorded (10000.0) instead of net (9725.0)
W3/W6  AssertionError: a PROFITABLE short was recorded as a LOSS (-10000.0) — sign inverted
```

All six GREEN after. `grep "(current_price - entry) \* q"` → **0** in both files.

## Why this had to ship WITH T0

The post-`T0` anchored window is the **only evidence VERIFY-02 has**, and these two writers
pushed fee-less gross P&L **straight into it**. `TAKER_FEE = 0.0025`, so a round trip costs
~0.5% of **NOTIONAL**, while `window_tolerance` is 0.5% of **REALIZED** — quantities that
differ by 10-100x. $50k of turnover producing $500 realized leaves a ~**$250** fee residue
against a **$25** tolerance. **The known bias structurally exceeded the tolerance.**

Without this fix Phase 20 would have shipped a reconciliation check **biased to fail** and
then read its own failure as a finding. That is not verification — it is manufacturing an
artifact and then measuring it. `T0` is the Phase-20 deploy and this fix rides in the **same
deploy**, so the window is **fee-clean from its first row**.

## Blast radius: what is RECORDED, never what is DECIDED

Both sites are **post-`place_market_order` DB-marking loops**. The order is already placed
and logged before the P&L is computed, and **nothing branches on `pnl`**. No entry, no exit,
no dispatch, no order logic moved.

**Intended side effect:** a flat trade now records `pnl = -fees` instead of `0.0`, so it
becomes **RESOLVED** rather than an unresolved sentinel. This is correct — a flat trade still
paid fees.

## Deviations from Plan

**[Rule 1 - Bug]** My first `tests/test_gross_pnl_writers.py` fixture constructed `BotConfig`
without its required `label`/`alpaca_api_key`/`alpaca_secret_key`, so W1/W2/W3 were failing
with a **`TypeError` — a fixture error, not the real defect.** A test that fails for the wrong
reason proves nothing. Fixed, then re-verified RED by stashing the source fix: all six now
fail for the **right** reason against `main` and pass after.

## Self-Check: PASSED
- `tests/test_gross_pnl_writers.py` — 7 passed (6 cases + the non-vacuity control)
- `git diff --name-only | grep .sql` → **0**
- Suite: skipped count still **29**
