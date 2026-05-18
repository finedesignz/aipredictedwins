# Dashboard UI Data Audit (No Skill)
**Date:** 2026-04-10 | **Project:** AI Predicted Wins

## Summary

| Page | Status | Key Issue |
|---|---|---|
| Overview (/) | Mostly working | Double benchmark fetch; cache bug |
| Trades (/trades) | Working | `pnl_percent` always null |
| Positions (/positions) | Mostly working | Minor type mismatches |
| Signals (/signals) | **Broken** | Hardcoded placeholder data only |
| Risk Gate (/risk-gate) | **Broken** | Reads Kalshi table, not Alpaca trades; type mismatches |
| Settings (/settings) | Partially broken | `sqlite_db` vs `database` health key mismatch |
| Bots (/bots) | Working | Full CRUD correctly wired |
| Login (/login) | Working | Cookie auth, redirect logic correct |
| Chat sidebar | Conditionally working | Requires `claude` CLI binary in container |
| Activity feed | Working | Polling (intentional, SSE dropped for Cloudflare compat) |

## Page-by-Page Findings

### Overview (/)
**Bugs:**
1. **Double benchmark fetch.** `page.tsx` fetches SPY+BTC and passes as props to `EquityCurve`, but `EquityCurve` ignores those props and self-fetches internally. 4 wasted API calls per render.
2. **Benchmark cache ignores `since` parameter.** Changing day range returns stale cached data until 5-min TTL.

### Trades (/trades)
**Bugs:**
1. `pnl_percent` always null — `trades.py` line 79 hardsets `r["pnl_percent"] = None`.
2. `status` enum incomplete — API returns `"stopped"` and `"target_hit"` not in frontend type.

### Positions (/positions)
**Bugs:**
1. `exit_price.toFixed(2)` called unconditionally — renders `$0.00` instead of `--` when zero.
2. `id` type mismatch: frontend expects `string`, API returns integer.

### Signals (/signals)
**BROKEN — hardcoded fake data.** `routes/signals.py` never reads from DB. Returns 8 hardcoded rows. `scanned_at` refreshed on each request to look live. No signals table in Postgres.

### Risk Gate (/risk-gate)
**BROKEN — wrong table + type mismatches.**
1. API reads `validations` table (Kalshi-era). Alpaca v2 risk gate does not write there.
2. Frontend expects `veto_count`, `reasoning`, `scenarios[]`. API returns `confidence`, `risk_assessment`, `veto_reason`, `proposed_side`.
3. `DecisionTable` reads `decision.confluence_score`, API returns `decision.confluence`.

### Settings (/settings)
**Bugs:**
1. Frontend reads `settings.health.sqlite_db`, API returns `health.database` — always red.
2. `uptime_seconds`, `cycle_count`, `running` hardcoded (not from BotManager).
3. Missing Alpaca key silently shows as healthy.

### Bots (/bots)
Working. No Delete button in UI (API supports it).

### Login (/login)
Working correctly.

## Fix Priority

| Priority | Fix |
|---|---|
| HIGH | Signals: persist scanner output to `signals` DB table |
| HIGH | Risk Gate: write Alpaca decisions to DB; fix frontend type alignment |
| MEDIUM | Settings health: align `database` ↔ `sqlite_db` field name |
| MEDIUM | Benchmark cache: include `since` in cache key |
| LOW | Trades `pnl_percent`: calculate and return |
| LOW | Overview: remove dead benchmark `useAPI` calls from `page.tsx` |
