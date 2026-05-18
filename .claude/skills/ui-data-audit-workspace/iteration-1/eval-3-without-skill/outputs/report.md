# Loading & Error State Audit (No Skill) — AI Predicted Wins Dashboard

## Summary Table

| Page / Component | Loading | Error | Notes |
|---|---|---|---|
| Login | PASS | PASS | Button text + disabled; inline red error messages |
| Overview (/) | PARTIAL | MISSING | Hero KPI has pulse skeleton; metric cards show "--" (no pulse); no error banner |
| Bots (/bots) | MISSING | MISSING | `loading` flag never read; empty-state shown during load; toggle errors swallowed |
| Positions (/positions) | PASS | MISSING | Per-tab loading; `error` never read |
| Signals (/signals) | PASS | MISSING | Spinner shown; falls through to misleading empty state on error |
| Trades (/trades) | PASS | MISSING | Spinner shown; falls through to misleading empty state on error |
| Risk Gate (/risk-gate) | PASS | MISSING | Spinner shown; falls through to misleading empty state on error |
| Settings (/settings) | PARTIAL | MISSING | Skeleton shown but gets **stuck forever** on persistent API error |
| ActivityFeed | PASS | PARTIAL | "Loading..." + reconnecting dot; no retry button |
| EquityCurve | MISSING | MISSING | No skeleton; benchmark failures are completely silent |
| ChatSidebar | PASS | PASS | Streaming cursor + inline error messages |
| AuthGuard | PASS | PASS | Full-screen loading; redirects on 401; safe fallback on network error |
| useAPI hook | PASS | PASS | Sets `error` string and redirects on 401 — but most pages never read `error` |

## Key Finding: `error` from `useAPI` Is Almost Never Read

The `useAPI` hook correctly returns `{ data, loading, error, refetch }`, but 6 of 7 pages destructure only `data` and `loading`, discarding `error` entirely. This means API failures are invisible to users across most of the app.

## Issues by Priority

### High — Must Fix Before Ship

1. **Settings page stuck on skeleton**: `loading` becomes false but `settings` stays null on error → infinite skeleton. `dashboard/web/app/settings/page.tsx`
2. **Bots page: loading state missing**: `loading` never read; "No bots configured" shown during load. `dashboard/web/app/bots/page.tsx`
3. **Overview: no error handling**: Portfolio/equity failures show `"--"` which looks like zero data. `dashboard/web/app/page.tsx`

### Medium — Polish

4. Signals, Trades, Risk Gate: misleading empty state on API error (all 3 pages)
5. Positions: no error state on either fetch
6. EquityCurve: no loading skeleton; benchmark failures silent
7. Bots `handleToggle` errors swallowed (no try/catch)

### Low — Nice to Have

8. Overview metric cards use `"--"` placeholder instead of animated pulse
9. ActivityFeed has no manual retry button
10. EquityCurve benchmark fetch failures (SPY/BTC) silent
