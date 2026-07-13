---
phase: 18
plan: 04
subsystem: metrics-db
requirements: [TUNE-01]
key-files:
  modified: [src/db.py, dashboard/api/routes/portfolio.py, dashboard/api/routes/settings.py, scripts/symbol_report.py]
commits: [ccab4f1]
---

# Phase 18 Plan 04: the three win-rate denominators + AIPW_DB_READONLY Summary

`AND pnl IS NOT NULL` added to the closed-trades WHERE at **all three** sites:

| Site | Drives |
|---|---|
| `src/db.py::get_alpaca_accuracy` | the bot's own log + `scripts/symbol_report.py` |
| `dashboard/api/routes/portfolio.py` | the dashboard HEADLINE (does not call `get_alpaca_accuracy`) |
| `dashboard/api/routes/settings.py` | the PAPER-GATE readout (`win_rate` vs `win_rate_target=40.0`) |

One clause each. The arithmetic (`losses = resolved - wins`) is now correct because the
denominator is. A genuine `0.00` close is STILL counted — only NULL is excluded. The returned
dict shape is unchanged (`src/alpaca_orchestrator.py:577`/`:1254` read it by key).
`get_recent_loss_symbols` left alone (a NULL already fails `pnl < 0` in SQL).

`AIPW_DB_READONLY=1` → `get_pool()` skips `_bootstrap_schema()` (which executes CREATE TABLE +
INSERT INTO bots against whatever `DATABASE_URL` names) AND every pooled connection carries
libpq `options=-c default_transaction_read_only=on`, so a write raises SQLSTATE 25006
server-side. Unset = byte-identical to today. The flag appears in `src/db.py` only; it is set by
analysis scripts in their process env — never by a bot or the dashboard.

## Deviations from Plan

None. `scripts/symbol_report.py:239` prose corrected (Phase 18 DOES change `get_alpaca_accuracy`;
the R−T divergence column it prints will shrink — that gap IS the sentinel+NULL defect).

## Self-Check: PASSED
