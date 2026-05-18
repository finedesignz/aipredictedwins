report = r"""# UI Data Audit - AI Predicted Wins Dashboard
Audited: 2026-04-10
Pages reviewed: 8

## Summary

| Page | Endpoints | Shape | Fields | Loading | Error | Empty | Mock | Params | Overall |
|------|-----------|-------|--------|---------|-------|-------|------|--------|---------|
| Overview | PASS | WARN | WARN | PASS | WARN | PASS | PASS | PASS | WARN |
| Signals | PASS | WARN | PASS | PASS | WARN | PASS | FAIL | PASS | FAIL |
| Positions | PASS | WARN | PASS | PASS | WARN | PASS | PASS | PASS | WARN |
| Trades | PASS | WARN | PASS | PASS | WARN | PASS | PASS | PASS | WARN |
| Risk Gate | PASS | FAIL | FAIL | PASS | WARN | PASS | PASS | PASS | FAIL |
| Bots | PASS | PASS | PASS | WARN | WARN | PASS | PASS | PASS | WARN |
| Settings | PASS | WARN | FAIL | PASS | WARN | PASS | WARN | PASS | FAIL |
| Login | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS |

---

## Critical Issues (FAIL)

### 1. Risk Gate page - complete field name mismatch

File: dashboard/web/types/index.ts:77-95
Frontend RiskDecision type expects: confluence_score, veto_count, reasoning, scenarios[]
Backend RiskGateRecord model returns: confluence, confidence, risk_assessment, veto_reason (no scenarios)
Result: every data column in the table renders undefined.
Crash: expanding a row calls decision.scenarios.length on undefined and throws TypeError.
Crash location: dashboard/web/components/risk-gate/DecisionDetail.tsx:28
Also: dashboard/web/components/risk-gate/DecisionTable.tsx:109,122,127

### 2. Signals page - entire endpoint is hardcoded mock data

File: dashboard/api/routes/signals.py:1-138
The route returns 8 statically defined assets with fixed indicator values.
Two TODO comments in the file confirm this is unresolved:
  "TODO: Wire this to real signal data once the technical scanner persists scan results to the database."
The Signals page ALWAYS shows the same fake data regardless of what the bot actually scanned.

### 3. Settings page - health field name mismatch

File: dashboard/web/types/index.ts:125, dashboard/web/components/settings/BotStatus.tsx:148
Frontend reads settings.health.sqlite_db; backend HealthStatus model returns health.database.
Result: DB health indicator always shows as unhealthy/red regardless of actual database status.

---

## Warnings (WARN)

### 4. ALL pages except login - no error state UI

Every page using useAPI ignores the error return value.
On API failure users see empty tables, "--" values, or infinite loading skeletons with no explanation.
Affects: dashboard/web/app/page.tsx, signals/page.tsx, positions/page.tsx,
         trades/page.tsx, risk-gate/page.tsx, bots/page.tsx, settings/page.tsx

### 5. Bots page - no loading indicator

File: dashboard/web/app/bots/page.tsx:18
loading is not destructured from useAPI.
While bots are loading, the page renders an empty grid with no spinner or skeleton.

### 6. Bots page - mutation errors silently fail

File: dashboard/web/app/bots/page.tsx:26,38
handleSave and handleToggle have no try/catch.
Failed creates, updates, and toggles produce unhandled promise rejections with no user feedback.

### 7. Settings - uptime and cycle count hardcoded zero

File: dashboard/api/routes/settings.py:96-97
uptime_seconds: 0 and cycle_count: 0 are hardcoded constants, not real bot process state.
These fields permanently display as "0 cycles" and "0s uptime" in the Settings UI.

### 8. Settings - fetch error shows permanent skeleton

When /api/settings fetch fails, settings stays null.
The condition (loading || !settings) renders loading skeletons indefinitely with no error message.

### 9. id type mismatch on ClosedPosition and Trade

File: dashboard/web/types/index.ts:31,46
Both ClosedPosition.id and Trade.id are typed as string.
Backend returns integers from alpaca_trades.id.
Low risk for React keys (implicit coercion works) but could break strict equality checks.

### 10. Dead Pydantic models

File: dashboard/api/models.py:65-83, 87-105, 110-117
ClosedPosition, TradeRecord, and SignalRecord Pydantic models define fields that do not
match what their corresponding routes actually return. The routes build raw dicts with
different field names. These models are never used and create false confidence in type safety.

### 11. Benchmark caching ignores the since param

Files: dashboard/api/routes/benchmark.py:48, benchmark_btc.py:61
Once the in-memory cache is warm, the since query param is ignored for 5 minutes.
If the user changes the equity chart time range, benchmark lines may not realign until cache expires.

---

## Per-Page Detail

### Overview Page - /

| Check | Status | Notes |
|-------|--------|-------|
| Endpoint exists | PASS | /api/portfolio, /api/positions/open, /api/equity, /api/benchmark/spy, /api/benchmark/btc all have matching backend routes |
| Response shape | WARN | MultiBotPortfolio backend model uses fixed keys A and B; frontend type is Record<string, Portfolio>. Non-A/B bot IDs silently missing. EquityData->series shape matches. |
| Rendered fields | WARN | All data fields (wins, losses, equity, etc.) present in PortfolioData. But portfolioLoading used to gate positions empty state instead of positions own loading var. |
| Loading state | PASS | Skeleton pulse animations present for Hero KPI and metric cards. |
| Error state | WARN | error from useAPI destructured but never displayed. Failures show "--" with no explanation. |
| Empty state | PASS | Empty positions show card with explanatory text. Equity chart handles empty series via equityData?.series ?? []. |
| No mock data | PASS | No hardcoded data or Math.random(). |
| Query params | PASS | bot=, days=, since= params all match backend handler signatures correctly. |

Issues:
- dashboard/web/app/page.tsx:31 - No error UI for portfolio fetch failure.
- dashboard/web/app/page.tsx:206 - Wrong loading var used for positions empty state check.

---

### Signals Page - /signals

| Check | Status | Notes |
|-------|--------|-------|
| Endpoint exists | PASS | /api/signals has a handler in signals.py |
| Response shape | WARN | SignalRecord Pydantic model has wrong field names (ema_bullish: bool) vs what route returns (ema_signal: string union). Model is unused dead code. |
| Rendered fields | PASS | All fields accessed in SignalTable present in the placeholder response dict. |
| Loading state | PASS | Loading message shown while loading is true. |
| Error state | WARN | error from useAPI not surfaced. Fetch failure shows empty table silently. |
| Empty state | PASS | SignalTable receives signals ?? [] and handles empty arrays. |
| No mock data | FAIL | Entire endpoint is static hardcoded placeholder data with two TODO comments. |
| Query params | PASS | No params sent or expected - consistent. |

---

### Positions Page - /positions

| Check | Status | Notes |
|-------|--------|-------|
| Endpoint exists | PASS | /api/positions/open and /api/positions/closed both exist |
| Response shape | WARN | ClosedPosition.id typed as string but backend returns integer. Dead ClosedPosition Pydantic model has wrong fields. |
| Rendered fields | PASS | All fields in ClosedTable and PositionCard are in backend response. Mappings qty->quantity, mirofish_prob->confluence_score, timestamp->opened_at all correct. |
| Loading state | PASS | Both tabs show loading messages while respective loading flags are true. |
| Error state | WARN | Neither tab surfaces error from useAPI. |
| Empty state | PASS | Open: "No open positions right now." Closed: "No closed positions yet." |
| No mock data | PASS | Live prices from Alpaca with graceful fallback to entry_price. |
| Query params | PASS | bot= param sent and handled on both endpoints. |

---

### Trades Page - /trades

| Check | Status | Notes |
|-------|--------|-------|
| Endpoint exists | PASS | /api/trades exists |
| Response shape | WARN | Trade.id typed as string, backend returns integer. pnl_percent always null from backend (never computed). |
| Rendered fields | PASS | All fields accessed by TradeTable and CSV export are present in backend response. |
| Loading state | PASS | Loading spinner shown while loading is true. |
| Error state | WARN | error from useAPI never displayed. |
| Empty state | PASS | TradeTable receives trades ?? []. Summary stats only render when summary is non-null. |
| No mock data | PASS | No hardcoded data. |
| Query params | PASS | bot, symbol, date_from, date_to correctly built via buildQueryString and handled backend. 30-day default matches on both ends. |

Issue: dashboard/api/routes/trades.py:79 - pnl_percent always hardcoded to None, never computed.

---

### Risk Gate Page - /risk-gate

| Check | Status | Notes |
|-------|--------|-------|
| Endpoint exists | PASS | /api/risk-gate exists and queries real validations table |
| Response shape | FAIL | Frontend RiskDecision type (confluence_score, veto_count, reasoning, scenarios[]) completely mismatches backend RiskGateRecord (confluence, confidence, risk_assessment, veto_reason). |
| Rendered fields | FAIL | confluence_score renders as undefined/5. veto_count renders as undefined/5. reasoning renders blank. Expanding a row crashes DecisionDetail with TypeError on decision.scenarios.length. |
| Loading state | PASS | Loading spinner shown. |
| Error state | WARN | error not surfaced. |
| Empty state | PASS | "No risk gate decisions recorded yet." shown when empty. |
| No mock data | PASS | Queries real validations table. |
| Query params | PASS | bot= param sent and handled. Filter chips work because decision.decision field name IS correct. |

---

### Bots Page - /bots

| Check | Status | Notes |
|-------|--------|-------|
| Endpoint exists | PASS | GET/POST /api/bots, PUT /api/bots/{id}, enable/disable endpoints all exist |
| Response shape | PASS | BotFull TS type matches BotFull Pydantic model field-for-field. Best shape alignment in codebase. |
| Rendered fields | PASS | All BotCard fields present in type and backend response. |
| Loading state | WARN | loading not destructured from useAPI. Empty grid shows with no indicator while fetching. |
| Error state | WARN | error not destructured. Mutation errors (handleSave, handleToggle) uncaught - fail silently. |
| Empty state | PASS | "No bots configured. Click '+ Add Bot' to get started." |
| No mock data | PASS | No hardcoded data. |
| Query params | PASS | No params needed. |

---

### Settings Page - /settings

| Check | Status | Notes |
|-------|--------|-------|
| Endpoint exists | PASS | /api/settings exists |
| Response shape | WARN | BotSettings.health.sqlite_db in TS type vs health.database in backend HealthStatus. |
| Rendered fields | FAIL | settings.health.sqlite_db is undefined at runtime; DB health indicator always shows red/unhealthy. |
| Loading state | PASS | Three skeleton pulse blocks shown while loading. |
| Error state | WARN | On fetch failure, loading or !settings keeps skeletons rendering indefinitely. |
| Empty state | PASS | loading or !settings guard handles no-data case with skeletons. |
| No mock data | WARN | uptime_seconds and cycle_count are hardcoded 0, not real bot process values. |
| Query params | PASS | Frontend omits ?bot= so backend defaults to both which is correct. |

---

### Login Page - /login

| Check | Status | Notes |
|-------|--------|-------|
| Endpoint exists | PASS | POST /api/auth/login and GET /api/auth/check both in main.py |
| Response shape | PASS | Checks res.ok for success. AuthGuard checks data.authenticated which matches. |
| Rendered fields | PASS | Only res.ok and error strings displayed - no complex field traversal. |
| Loading state | PASS | Button shows "Authenticating..." and is disabled while loading. |
| Error state | PASS | Both network errors and 401 explicitly handled and shown. |
| Empty state | PASS | Submit button disabled when token is empty. |
| No mock data | PASS | No hardcoded data. |
| Query params | PASS | POST body only, no query params. |

---

## All Clear

- Login page: all 8 checks pass. Full error handling, correct cookie security posture.
- Bots page (data shape): BotFull type alignment is the best in the codebase - field-for-field match.
- Positions page (rendered fields): field mappings (qty->quantity, mirofish_prob->confluence_score, timestamp->opened_at) correctly implemented.
- Trades page (query params): filter params correctly constructed via buildQueryString with matching 30-day default on both ends.
"""

outpath = "C:/Users/artic/GitHub/aipredictedwins/.claude/skills/ui-data-audit-workspace/iteration-1/eval-1-with-skill/outputs/report.md"
with open(outpath, "w", encoding="utf-8") as f:
    f.write(report)
print("Done, wrote", len(report), "bytes")
