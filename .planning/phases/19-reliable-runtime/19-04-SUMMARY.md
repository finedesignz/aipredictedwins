---
phase: 19-reliable-runtime
plan: 04
subsystem: reporting
tags: [run-02, resolved-predicate, paper-gate]
requires: [19-02]
provides: [is_resolved-at-five-sites, unresolved-count, starting_equity-derived]
key-files:
  modified:
    - src/db.py
    - dashboard/api/routes/portfolio.py
    - dashboard/api/routes/settings.py
    - dashboard/api/models.py
metrics:
  commit: 47766c4
---

# Phase 19 Plan 04: The Honest Numbers Summary

`RESOLVED := pnl IS NOT NULL AND pnl <> 0`. One predicate, five reader sites.

`0.0` is NOT NULL, so Phase 18's `AND pnl IS NOT NULL` passed the ~395 historical
`pnl = 0.0` external-exit sentinels straight through, and every reader then scored
`(pnl or 0) > 0 → False` and booked them as **losses**. `src/db.py:228`'s own comment admitted
it: *"A genuine 0.00 close is still counted — only NULL is excluded."* Phase 18 fixed the
WRITER, not the READER.

## The five sites

| # | Site | Change |
|---|------|--------|
| 1 | `portfolio.py` closed-trades query (the HEADLINE) | `AND pnl IS NOT NULL AND pnl <> 0`; failing terminal rows counted as `unresolved` |
| 2 | `settings.py` closed_rows (**THE PAPER GATE**) | same predicate + `unresolved` |
| 3 | `src/db.py::get_alpaca_accuracy` | selects terminal rows unfiltered, partitions on `is_resolved`; `unresolved` is ADDITIVE (all nine existing keys keep their names — research N6) |
| 4 | `portfolio.py` daily-P&L query (research N7) | had **NO pnl filter at all**; now shares the predicate |
| 5 | `settings.py:65` `equity = 100_000.0 * len(bot_ids) + total_pnl` | **DELETED** |

`unresolved` is reported BESIDE wins/losses, never folded into them.

The `$100k` hardcode is replaced by summing `starting_equity` from the `bot_rows` the route
**already fetches** (a `SELECT *`), with a `100_000.0` fallback firing only for a `bot_id`
with no row — mirroring `src/db.py:322-331`. **Note for the record:** 19-VALIDATION case 22
phrases this as "via `db.get_starting_equity`", but the dashboard's `db` module is NOT
`src.db`, and importing `src.db` into a route would open a **second connection pool**. The
observable assertion — equity derives from `bots.starting_equity`, and the literal is gone —
is satisfied without the cross-import. `grep -c "100_000.0 \* len(" dashboard/api/routes/settings.py` → **0**.

## The gate may now read WORSE

`mode="paper"`, `win_rate_target=40.0`, `equity_target=_LIVE_THRESHOLD` and the gate
comparison are **untouched** (fence F3). A worse reading is the CORRECT outcome of an honest
readout and must not be tuned away. The gate is NOT unlocked.

Cost, stated plainly: a genuinely exactly-break-even trade is now dropped from the win rate.
With crypto fills and fees that is a measure-zero event, and the alternative is booking 395
fabricated zeros as real losses in the gate that guards live trading. Post-Phase-18 the writer
emits NULL, never 0.0, so the `<> 0` arm is a **historical-row filter with a shrinking blast
radius**.

## REQUIRES HUMAN AUTHORIZATION

**The ~395 `pnl = 0.0` rows in the production `alpaca_trades` table were NOT repaired.**

They were **READ AROUND**: no `UPDATE`, no `DELETE`, no backfill, not one write. They remain
byte-identical in the prod trade log. Every figure in this phase excludes them from the
win-rate numerator and denominator and from the realized sums, and reports them as an
`unresolved` count instead.

**`src/backfill.py` exists and is a LOADED GUN.** It must not be pointed at prod. Repairing
historical production trade data — resolving those sentinels to real P&L, or nulling them — is
an irreversible mutation of the trade log and requires **explicit human authorization**. It is
flagged here, not done.

Evidence: `git diff src/backfill.py` is **EMPTY** for the whole phase. Fence F1 asserts that
`backfill` is imported by no module under `src/bot_manager.py`, `dashboard/api/routes/`, or
`dashboard/api/main.py`, and that the set of modules writing to `alpaca_trades` is unchanged
from the frozen allowlist (`src/db.py`, `dashboard/api/routes/positions.py`).

## Verification

- Cases **13, 14** GREEN (pure, no DB). The static halves of **15, 16, 18, 17, 22** GREEN.
- `tests/test_symbol_stats.py` + `tests/test_trade_logger_shim.py` GREEN — the accuracy dict
  stayed additive; consumers index by key.
- `grep -c "pnl <> 0" dashboard/api/routes/portfolio.py` → 3 (win rate, unresolved count, daily).
- `git diff -- src/db.py dashboard/api/routes/ | grep -iE "^\+.*(UPDATE|DELETE|INSERT).*alpaca_trades"` → **nothing**.
- No route imports `src.db` — no second connection pool.

## Deviations from Plan

**1.** `unresolved` is counted with a companion `COUNT(*)` over the same window rather than by
selecting the raw rows and partitioning in Python (the plan permitted either; this is the
smaller diff and keeps the resolved-row list clean).

**2.** `PortfolioData.unresolved` and `SettingsData.unresolved` were added here (default `0`)
as the plan allowed, since 19-06 had not yet landed.

## Self-Check: PASSED
