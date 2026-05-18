# UI Data Audit — AI Predicted Wins Dashboard
Audited: 2026-04-10 | Pages reviewed: 8

## Summary

| Page | Endpoints | Shape | Fields | Loading | Error | Empty | Mock | Params | Overall |
|------|-----------|-------|--------|---------|-------|-------|------|--------|---------|
| Overview `/` | ✅ | ⚠️ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ⚠️ |
| Signals `/signals` | ✅ | ⚠️ | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ | ❌ |
| Positions `/positions` | ✅ | ⚠️ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ⚠️ |
| Trades `/trades` | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ⚠️ |
| Risk Gate `/risk-gate` | ✅ | ❌ | ❌ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ |
| Bots `/bots` | ✅ | ✅ | ✅ | ❌ | ⚠️ | ✅ | ✅ | ✅ | ❌ |
| Settings `/settings` | ✅ | ❌ | ❌ | ✅ | ❌ | ✅ | ✅ | ✅ | ❌ |
| Login `/login` | ✅ | ✅ | ✅ | ✅ | ✅ | N/A | ✅ | ✅ | ✅ |

Legend: ✅ PASS  ⚠️ WARN  ❌ FAIL

## Issues Requiring Action

### Critical (FAIL)

- **Risk Gate — shape mismatch + crash on row expand**: Backend sends `confluence`/`veto_reason`/`risk_assessment` with no `veto_count` or `scenarios`. Frontend reads `confluence_score`/`veto_count`/`reasoning`/`scenarios`. Expanding any row throws `TypeError` (`decision.scenarios.length` on undefined). Files: `dashboard/api/models.py:122–133`, `dashboard/web/components/risk-gate/DecisionTable.tsx:109,123,127`, `dashboard/web/components/risk-gate/DecisionDetail.tsx:27`

- **Settings — health field mismatch**: Backend sends `health.database`, frontend reads `health.sqlite_db`. DB health permanently red. Files: `dashboard/api/models.py:152`, `dashboard/web/types/index.ts:127`, `dashboard/web/components/settings/BotStatus.tsx:142`

- **Signals — hardcoded placeholder data**: `dashboard/api/routes/signals.py:19–138`

- **Bots — no loading state**: Empty state flashes on every page load. `dashboard/web/app/bots/page.tsx:18`

### Warnings (WARN)

- **Error states missing on all data pages**: 6 pages discard `error` from `useAPI`. A shared `<ErrorBanner error={error} />` component would fix all 6:
  - `dashboard/web/app/page.tsx:31–52`
  - `dashboard/web/app/signals/page.tsx:9`
  - `dashboard/web/app/positions/page.tsx:16–21`
  - `dashboard/web/app/trades/page.tsx:25`
  - `dashboard/web/app/risk-gate/page.tsx:14`
  - `dashboard/web/app/settings/page.tsx:8`

- **Bots — toggle errors silently swallowed**: `handleToggle` has no catch block. `dashboard/web/app/bots/page.tsx:38–41`

- **MultiBotPortfolio type divergence**: Backend Pydantic has explicit `A`/`B` fields; frontend is `Record<string, Portfolio>`. `dashboard/api/models.py:258–260`

## All Clear

Login passes all 8 checks. No other pages are fully clean.

## Quick Fix Priority

1. Rename `health.database` → `health.sqlite_db` in `dashboard/api/models.py:152`
2. Add `<ErrorBanner>` to all 6 data pages
3. Risk Gate field mapping: `confluence`→`confluence_score`, derive `veto_count`, guard `scenarios?.length ?? 0`
4. Wire signals to real DB data
5. Extract `loading` from `useAPI` in bots page
