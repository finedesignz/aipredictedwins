# AI Predicted Wins — Trading Dashboard

**Date:** 2026-03-31
**Status:** Approved (user approved all sections, delegated full build)

## Overview

Replace the MiroFish frontend at `app.aipredictedwins.com` with a trading performance dashboard. Shows live equity, positions, trade history, technical signals, risk gate decisions, and system health. Built for a solo trader now, designed as a product for other traders later.

## Architecture

Single Docker container running both Next.js (frontend) and FastAPI (backend API + SSE). Deployed on Coolify at `app.aipredictedwins.com`.

```
app.aipredictedwins.com
        |
  [Nginx / Next.js]
   /          /api/*
   |            |
[Next.js]  [FastAPI :8000]
 (SSR)      |         |
        [SQLite]   [SSE stream]
            |
    alpaca-paper-data volume
    (shared with bot container)
```

- **FastAPI** reads `trades.db` read-only, serves REST endpoints + SSE
- **Next.js** App Router, TypeScript, Tailwind CSS, Recharts
- **Bot container** writes to `trades.db` — no changes to bot code
- **Shared volume**: `alpaca-paper-data:/app/data` mounted on both containers
- **Process manager**: `supervisord` runs both Next.js and FastAPI in one container

## Tech Stack

- **Framework**: Next.js 15 (App Router) + TypeScript
- **Styling**: Tailwind CSS 4 + CSS custom properties for design tokens
- **Charts**: Recharts (lightweight, React-native)
- **Data tables**: TanStack Table v8 (sortable, filterable)
- **Icons**: Lucide React
- **API**: FastAPI (Python) reading from SQLite
- **Real-time**: Server-Sent Events (SSE) from FastAPI
- **Deployment**: Single Dockerfile with supervisord, Coolify

## Design System

### Theme
Dark mode primary (trading dashboard standard). Colors from existing DESIGN.md:
- Background: `#0a0e17` (primary), `#111827` (secondary), `#1a2332` (card)
- Text: `#f1f5f9` (primary), `#94a3b8` (secondary), `#64748b` (muted)
- Profit: `#4ade80` (green), Loss: `#f87171` (red)
- Accent: `#60a5fa` (blue)
- Warning: `#fbbf24` (amber)

### Layout
Top navigation bar (not sidebar). Hero KPI number. Mobile-responsive.

### Typography
Inter for UI text, JetBrains Mono for financial numbers.

## Pages (6)

### 1. Overview (`/`)
- **Hero KPI**: portfolio value, big number centered, all-time change % and dollar amount below
- **4 metric cards**: Total P&L, Win Rate, Open Positions, Daily P&L
- **Equity curve**: full-width area chart, green when positive, red when negative
- **Two columns**: Open position cards (left), Live activity feed (right, SSE-powered)

### 2. Positions (`/positions`)
- **Toggle tabs**: Open / Closed
- **Open**: card per position — symbol, entry price, current price, unrealized P&L %, time held, trailing stop status
- **Closed**: table — symbol, entry/exit price, P&L, hold duration, close reason, timestamp
- **Summary row**: total realized P&L, average hold time, best/worst trade

### 3. Trade History (`/trades`)
- Full table of every trade
- **Filter bar**: date range, symbol dropdown, P&L positive/negative
- **Columns**: timestamp, symbol, confluence score, entry price, exit price, P&L, status, notes
- CSV export button
- Bottom summary: total trades, win rate, avg P&L per trade

### 4. Signals (`/signals`)
- Current technical scanner output
- **Table**: symbol, EMA, ADX, RSI, Volume Spike, VWAP, Confluence Score, Action
- Color-coded rows: green (3+/5), yellow (2/5), grey (1/5)
- Auto-refreshes via SSE on new scan cycle

### 5. Risk Gate Log (`/risk-gate`)
- Every PROCEED/VETO decision
- **Table**: timestamp, symbol, confluence, decision badge, veto count, reasoning
- Click to expand: full scenarios with likelihood/impact, individual analyst votes
- Filter: PROCEED / VETO / All

### 6. Settings (`/settings`)
- Bot status: running/stopped, last cycle, uptime, cycle number
- System health: Claude CLI, Alpaca API, SQLite DB size
- Config display (read-only): thresholds, limits, stops, Kelly
- Paper trading progress: X/50 trades, win rate vs 40%, equity vs $100k

## FastAPI Endpoints

```
GET  /api/portfolio          — KPI summary (equity, P&L, win rate, positions)
GET  /api/positions/open     — open positions with current prices
GET  /api/positions/closed   — closed positions with P&L
GET  /api/trades             — all trades (query: status, symbol, date_from, date_to, limit, offset)
GET  /api/signals            — latest technical signal scan results
GET  /api/risk-gate          — risk gate decisions (query: decision, limit, offset)
GET  /api/risk-gate/:id      — single decision with full scenarios
GET  /api/settings           — bot config + system health
GET  /api/activity/stream    — SSE endpoint for live activity feed
```

Response envelope:
```json
{"data": {...}, "meta": {"timestamp": "...", "count": N}}
```

## SSE Events

The FastAPI SSE endpoint watches for changes in the SQLite database (polling every 5s) and pushes events:

- `trade_placed` — new trade entered
- `trade_closed` — position closed with P&L
- `scan_complete` — technical scan finished with signal summary
- `risk_decision` — PROCEED/VETO with reasoning
- `cycle_complete` — full cycle summary

## File Structure

```
dashboard/
  api/
    main.py              — FastAPI app + SSE
    routes/
      portfolio.py
      positions.py
      trades.py
      signals.py
      risk_gate.py
      settings.py
      activity.py
    db.py                — SQLite connection helper
    models.py            — Pydantic response models
  web/
    package.json
    next.config.ts
    tailwind.config.ts
    tsconfig.json
    src/
      app/
        layout.tsx       — root layout with top nav
        page.tsx         — Overview
        positions/page.tsx
        trades/page.tsx
        signals/page.tsx
        risk-gate/page.tsx
        settings/page.tsx
      components/
        nav/TopNav.tsx
        kpi/HeroKPI.tsx
        kpi/MetricCard.tsx
        charts/EquityCurve.tsx
        positions/PositionCard.tsx
        positions/ClosedTable.tsx
        trades/TradeTable.tsx
        signals/SignalTable.tsx
        risk-gate/DecisionTable.tsx
        risk-gate/DecisionDetail.tsx
        activity/ActivityFeed.tsx
        settings/BotStatus.tsx
        settings/ConfigDisplay.tsx
        shared/Badge.tsx
        shared/ModeBadge.tsx
      hooks/
        useSSE.ts
        useAPI.ts
      lib/
        api.ts           — fetch wrapper
        format.ts        — number/currency formatters
      types/
        index.ts
  Dockerfile             — supervisord + Next.js + FastAPI
  supervisord.conf
```

## Deployment

- Single Dockerfile in `dashboard/`
- Supervisord runs: `uvicorn api.main:app --port 8000` + `node server.js`
- Coolify app: replace "AI-Predicted Wins" (MiroFish) with this dashboard
- FQDN: `app.aipredictedwins.com`
- Volume: `alpaca-paper-data:/app/data` (shared with bot)
- No env vars needed (reads SQLite directly)

## Success Criteria

- Dashboard loads in <2s
- SSE events arrive within 5s of bot activity
- All 6 pages functional with real data from trades.db
- Mobile-responsive (works on phone for quick health checks)
- Dark theme, professional product feel
