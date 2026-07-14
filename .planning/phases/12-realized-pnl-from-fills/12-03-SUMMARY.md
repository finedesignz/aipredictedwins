---
phase: 12-realized-pnl-from-fills
plan: 03
subsystem: monitor
tags: [pnl-02, close-path, fills]
requires: [12-01, 12-02]
provides: [realized-close-pnl]
key-files:
  modified:
    - src/alpaca_orchestrator.py
    - tests/test_order_resolution.py
metrics:
  commits: c19dc5e, af79503
reconstructed: true
reconstructed-note: "Written 2026-07-14 during the v1.1 milestone archive. The implementer never wrote a SUMMARY for this plan; this one is reconstructed from the plan, the two commits above, the close block on disk, and VERIFICATION.md. Nothing here is asserted beyond that evidence."
---

# Phase 12 Plan 03: The Close Block Stops Booking the Quote Summary

## What changed

`PositionMonitor._check_positions()`'s close block used to throw away `close_position()`'s return
value and store the **live quote** as the exit price and a quote-derived, fee-free `trade_pnl` as the
P&L. Commit `c19dc5e` (`feat(12-03): wire monitor close to realized_pnl + fills + fees`) replaced that
with the real numbers (+24/−5 lines, one file):

- `result = self.alpaca.close_position(symbol)` — the return value is now captured.
- `exit_fill = result.get("filled_avg_price") or 0`; `if exit_fill <= 0` → fall back to
  `current_price` **and log a warning**.
- `entry_fill = trade.get("filled_avg_price") or 0`; `if entry_fill <= 0` → fall back to `entry_price`
  **and log a warning** (legacy rows predating the fill capture).
- `fees = (entry_fill*qty + exit_fill*qty) * TAKER_FEE`;
  `realized = realized_pnl(side, entry_fill, exit_fill, qty, TAKER_FEE)`.
- `update_alpaca_trade(trade_id=..., status="closed", exit_price=exit_fill, pnl=realized, fees=fees)`.
- `self.total_pnl += realized` (was `+= trade_pnl`), and `alert_position_closed(...)` now reports the
  same realized figure it stores.

The two `<= 0` guards are the point: a zero fill from Alpaca would otherwise have booked a fake −100%
loss. Both fallbacks are logged, never silent.

**Deliberately untouched** (and confirmed untouched in the diff): the quote-derived `pnl_pct` /
`trade_pnl` that drive the exit ladder and the display lines, the ladder's precedence
(hard_stop → max_hold → ATR trail → ATR stop), and the external-exit reconciliation stub, which has no
fill data available and still writes `pnl=0.0`. `SLIPPAGE_BUFFER` is not referenced in the close block.
Only the **stored** number changed; no exit trigger moved.

Commit `af79503` extended the Phase-11 `FakeLogger` double in `tests/test_order_resolution.py` with the
additive `fees=None` kwarg so it stayed call-compatible with the new signature.

## Verification

- `pytest tests/test_close_pnl.py tests/test_pnl.py -q` → **11 passed** (all 10 validation cases plus
  `test_total_pnl_uses_realized`), per VERIFICATION.md.
- `pytest tests/ -q` → **310 passed, 2 skipped**, per VERIFICATION.md's independent run.
- Phase VERIFICATION.md (2026-07-10): **PASSED, 5/5 must-haves, PNL-02 SATISFIED, ship verdict SHIP.**

## Deviations

None visible in the commit. The close block matches the plan's action list line for line, including
leaving the external-exit stub alone.

**Known limitation, recorded not fixed:** that external-exit stub (`pnl=0.0` when a position vanishes
from Alpaca without the monitor closing it) is the shape that produced the 395 historical
`pnl = 0.0` sentinel rows later diagnosed in Phases 19 and 20. Phase 12 fixed the **monitor-driven**
close path only; the sentinel rows it did not create and did not repair were handled read-side in
Phase 19 and measured in Phase 20.

## Self-Check: PASSED (reconstructed)

The close block on disk (`src/alpaca_orchestrator.py`, `realized_pnl` imported at module top) matches
the description above; commits `c19dc5e` and `af79503` are present in `main`; VERIFICATION.md records
the phase PASSED.
