# UI Data Audit — AI Predicted Wins (Signals Page)
Audited: 2026-04-10
Pages reviewed: 1 (Signals page — /signals)

## Summary

| Page | Endpoints | Shape | Fields | Loading | Error | Empty | Mock | Params | Overall |
|------|-----------|-------|--------|---------|-------|-------|------|--------|---------|
| Signals | ✅ | ⚠️ | ⚠️ | ✅ | ⚠️ | ✅ | ❌ | ✅ | ❌ |

Legend: ✅ PASS  ⚠️ WARN  ❌ FAIL

---

## Signals Page — /signals

| Check | Status | Notes |
|-------|--------|-------|
| Endpoint exists | PASS | `GET /api/signals` is registered in `dashboard/api/routes/signals.py` and mounted in `main.py` via `app.include_router(signals.router, dependencies=[Depends(verify_token)])` |
| Response shape | WARN | The backend `Envelope` wrapper `{"data": [...], "meta": {...}}` is correctly unwrapped by `useAPI` → `apiFetch` → `response.data`. However, the `SignalRecord` Pydantic model in `models.py` (lines 110–117) defines `ema_bullish: bool` and `vwap_bullish: bool`, while the actual route returns dicts with `ema_signal: str` and `vwap_signal: str` (matching the frontend). The model is never used by the route handler so there is no runtime error, but it is internally inconsistent. |
| Rendered fields | WARN | All 8 fields accessed in `SignalTable.tsx` (`symbol`, `ema_signal`, `adx_value`, `rsi_value`, `volume_spike`, `vwap_signal`, `confluence_score`, `action`) exist in the `Signal` type and the placeholder payload. However `adx_signal` is present in the `Signal` type and returned by the API but has no column in `SignalTable.tsx` — it is silently ignored. |
| Loading state | PASS | `page.tsx` lines 32–36: while `loading` is true, a centred card with "Loading signals..." is displayed. `useAPI` initialises `loading: true` and sets it to `false` in its `finally` block. |
| Error state | WARN | `page.tsx` line 9 destructures `{ data: signals, loading }` — the `error` field returned by `useAPI` is discarded. If the API call fails, the page silently falls through to `<SignalTable data={[]} />`, showing the empty-state message with no explanation. |
| Empty state | PASS | `SignalTable.tsx` lines 118–126: when `data.length === 0` a card reading "No signal data available. Waiting for the next scan cycle." is rendered. The page passes `signals ?? []` so null is also handled. |
| No mock data | FAIL | `dashboard/api/routes/signals.py` lines 19–126: the entire response body is a hardcoded `_PLACEHOLDER_SIGNALS` array of 8 static objects with fixed indicator values (e.g. `adx_value: 28.5`, `rsi_value: 55.2`). Two TODO comments in the file make this explicit. The only dynamic value is `scanned_at`, set to `datetime.now()` on each request — making the data look live when it never changes. |
| Query params | PASS | Frontend calls `useAPI<Signal[]>("/api/signals", 30000)` with no query params. Backend `get_signals()` takes no parameters. Consistent on both sides. |

---

## Issues requiring action

### Critical (FAIL)
- **Signals page / backend — hardcoded placeholder data**: `dashboard/api/routes/signals.py` lines 21–126.

### Warnings (WARN)
- **`SignalRecord` model inconsistent with route**: `dashboard/api/models.py` lines 110–117.
- **Error state not surfaced**: `dashboard/web/app/signals/page.tsx` line 9. `error` is destructured but discarded.
- **`adx_signal` field returned but never displayed**: `dashboard/web/components/signals/SignalTable.tsx` has no column for it.
