# AI Predicted Wins -- Dashboard Design Plan

**Version**: 1.0
**Date**: 2026-03-20
**Status**: Design specification, ready for implementation

---

## Technology Decision

**Recommendation: Replace Streamlit with a Next.js + React dashboard.**

Streamlit is adequate for prototyping but fundamentally limited for a production trading dashboard:

| Concern | Streamlit | Next.js + React |
|---|---|---|
| Real-time updates | Full page re-run on every interaction | WebSocket/SSE for granular updates |
| Layout control | Single-column with basic `st.columns` | Full CSS Grid/Flexbox, pixel-perfect |
| Component richness | Limited built-in widgets | Unlimited (Recharts, AG Grid, Radix UI) |
| Mobile responsiveness | Poor -- designed for desktop | First-class responsive design |
| Performance | Re-executes entire script on interaction | Virtual DOM, surgical re-renders |
| Dark mode / theming | Hacky CSS overrides | Native CSS custom properties |
| Deployment | Requires Python runtime | Static export or serverless |

**Stack**:
- **Framework**: Next.js 15 (App Router) with TypeScript
- **Styling**: Tailwind CSS 4 + CSS custom properties for design tokens
- **Charts**: Recharts (lightweight, composable, React-native)
- **Data tables**: TanStack Table v8 (headless, sortable, filterable, virtualized)
- **UI primitives**: Radix UI (accessible, unstyled, composable)
- **Icons**: Lucide React (consistent, MIT-licensed)
- **Data layer**: REST API served by a lightweight Python FastAPI backend reading from SQLite
- **Real-time**: Server-Sent Events (SSE) from FastAPI for live activity feed

**Alternative (lower effort)**: If the team wants to stay in Python, upgrade to **Dash by Plotly** which offers real callbacks, proper layout, and WebSocket support while keeping the Python ecosystem.

---

## Design Foundations

### Color System

The palette is built around a dark theme as the primary mode. Trading dashboards are used for extended periods; dark backgrounds reduce eye strain and make colored data (green/red P&L) pop.

```
Token Name              Light Mode        Dark Mode (Primary)
------------------------------------------------------------
--bg-primary            #ffffff           #0a0e17
--bg-secondary          #f8fafc           #111827
--bg-card               #ffffff           #1a2332
--bg-card-hover         #f1f5f9           #1e293b
--bg-input              #ffffff           #0f172a

--border-primary        #e2e8f0           #1e293b
--border-subtle         #f1f5f9           #151d2b

--text-primary          #0f172a           #f1f5f9
--text-secondary        #475569           #94a3b8
--text-muted            #94a3b8           #64748b

--accent-blue           #3b82f6           #60a5fa
--accent-blue-dim       #1e40af           #1e3a5f

--profit-green           #16a34a           #4ade80
--profit-green-bg        #dcfce7           #052e16
--loss-red               #dc2626           #f87171
--loss-red-bg            #fee2e2           #450a0a

--warning-amber          #d97706           #fbbf24
--warning-amber-bg       #fef3c7           #451a03

--tier-1                 #8b5cf6           #a78bfa     (purple -- political/sentiment)
--tier-2                 #06b6d4           #22d3ee     (cyan -- tech/economic)
--tier-3                 #f97316           #fb923c     (orange -- weather/sports)

--sim-running            #3b82f6           #60a5fa
--sim-completed          #16a34a           #4ade80
--sim-failed             #dc2626           #f87171
```

All color combinations meet WCAG AA (4.5:1 contrast ratio minimum for normal text, 3:1 for large text and UI components).

### Typography

```
Token                    Value
---------------------------------------------------------
--font-primary           'Inter', system-ui, -apple-system, sans-serif
--font-mono              'JetBrains Mono', 'Fira Code', monospace

--text-xs                0.75rem / 1rem      (12px -- labels, timestamps)
--text-sm                0.875rem / 1.25rem  (14px -- table cells, secondary)
--text-base              1rem / 1.5rem       (16px -- body text)
--text-lg                1.125rem / 1.75rem  (18px -- section headers)
--text-xl                1.25rem / 1.75rem   (20px -- card titles)
--text-2xl               1.5rem / 2rem       (24px -- page sections)
--text-3xl               1.875rem / 2.25rem  (30px -- KPI values)
--text-4xl               2.25rem / 2.5rem    (36px -- hero bankroll number)

--font-weight-normal     400
--font-weight-medium     500
--font-weight-semibold   600
--font-weight-bold       700
```

Monospace font is used for all numerical financial data (prices, P&L, probabilities, percentages) to ensure column alignment and easy scanning.

### Spacing

8px base unit with a consistent scale:

```
--space-0    0
--space-1    0.25rem    (4px)
--space-2    0.5rem     (8px)
--space-3    0.75rem    (12px)
--space-4    1rem       (16px)
--space-5    1.25rem    (20px)
--space-6    1.5rem     (24px)
--space-8    2rem       (32px)
--space-10   2.5rem     (40px)
--space-12   3rem       (48px)
--space-16   4rem       (64px)
```

### Shadows and Elevation

```
--shadow-sm       0 1px 2px 0 rgb(0 0 0 / 0.05)
--shadow-card     0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1)
--shadow-dropdown 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)
--shadow-modal    0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1)
```

In dark mode, elevation is communicated through background lightness shifts rather than shadows:
- Level 0: `--bg-primary` (deepest)
- Level 1: `--bg-secondary`
- Level 2: `--bg-card`
- Level 3: `--bg-card-hover`

### Border Radius

```
--radius-sm     0.25rem   (4px -- badges, small chips)
--radius-md     0.375rem  (6px -- inputs, buttons)
--radius-lg     0.5rem    (8px -- cards)
--radius-xl     0.75rem   (12px -- modals, large panels)
--radius-full   9999px    (pills, avatars)
```

---

## Layout Architecture

### Overall Grid

The dashboard uses a sidebar + main content area layout:

```
+--------+----------------------------------------------+
| SIDEBAR|  HEADER BAR                                   |
| (240px)|                                               |
|        +----------------------------------------------+
|  Nav   |                                               |
|  items |  MAIN CONTENT AREA                            |
|        |  (scrollable, padded 24px)                    |
|        |                                               |
|        |  Organized in a 12-column CSS Grid            |
|        |  with 16px gutters                            |
|        |                                               |
|        |                                               |
+--------+----------------------------------------------+
```

**Sidebar** (240px, collapsible to 64px icon-only on mobile):
- App logo and name at top
- Navigation links with icons:
  - Overview (default view -- KPIs + charts + activity)
  - Markets (evaluation table)
  - Positions (active + history)
  - Simulations (monitor)
  - Risk (drawdown, limits)
  - Settings (thresholds, API status)
- Mode indicator at bottom (PAPER / LIVE badge)
- Collapse toggle

**Header Bar** (56px fixed):
- Breadcrumb or page title (left)
- Live clock with last-refresh timestamp (center)
- Status indicators (right): MiroFish health, Kalshi connection, bot running/paused
- Balance quick-view pill
- Theme toggle (dark/light)

### Responsive Breakpoints

```
Mobile:       < 640px    -- sidebar hidden, hamburger menu, single column
Tablet:       640-1023px -- sidebar collapsed (icon-only), 2-column grid
Desktop:      1024-1439px -- full sidebar, 2-3 column grid
Large:        >= 1440px  -- full sidebar, 3-4 column grid, expanded charts
```

---

## Section Specifications

### 1. Header Bar

**Purpose**: Persistent top bar providing global context at a glance.

**Layout**: Fixed position, full width, height 56px, `--bg-card` background, bottom border.

**Components**:
```
[Logo Icon] AI Predicted Wins    |    Last updated: 12s ago    |    [MiroFish: OK] [Kalshi: OK] [Bot: Running]    $1,247.32    [Theme]
```

- **App identity**: 20px Lucide `brain-circuit` icon + "AI Predicted Wins" in `--text-lg --font-weight-semibold`
- **Freshness indicator**: "Last updated: Xs ago" in `--text-xs --text-muted`, updates every second, turns amber if >30s stale
- **Connection indicators**: Three small dots (8px circles) with labels:
  - Green dot = connected/healthy
  - Amber dot = degraded/slow
  - Red dot = disconnected/error
  - Tooltip on hover shows detail (e.g., "MiroFish backend at app.aipredictedwins.com -- 142ms latency")
- **Mode badge**: "PAPER" in amber pill or "LIVE" in red pill with subtle pulse animation
- **Balance**: Monospace, `--text-lg`, colored green if positive, red if negative

### 2. Portfolio KPIs

**Purpose**: Top-level financial health at a glance. This is the first thing you see on the Overview page.

**Layout**: Full-width row of 5 cards, equal width, `--space-4` gap. On mobile: 2x2 grid + 1 full-width.

**Cards**:

Each KPI card is 120px tall with:
- Label: `--text-xs --text-muted --font-weight-medium` uppercase tracking-wide
- Value: `--text-3xl --font-mono --font-weight-bold`
- Delta: `--text-sm` with arrow icon, green for positive, red for negative
- Sparkline: 40px tall mini line chart (last 30 days) at bottom of card, no axes

| Card | Label | Value Format | Delta | Sparkline |
|---|---|---|---|---|
| Bankroll | BANKROLL | $1,247.32 | +$247.32 (24.7%) from start | Daily bankroll |
| Total P&L | TOTAL P&L | +$247.32 | +$18.50 today | Daily P&L |
| Win Rate | WIN RATE | 67.3% | 14W / 7L (21 resolved) | Rolling 20-trade win rate |
| Open Positions | OPEN POSITIONS | 4 | $52.00 at risk | Count over time |
| Sharpe Ratio | SHARPE RATIO | 1.84 | -- | Rolling Sharpe |

**Interaction**: Click any card to scroll to its detailed section below.

### 3. Live Activity Feed

**Purpose**: Real-time log of bot actions. Gives confidence the system is alive and working.

**Layout**: Right sidebar panel on desktop (320px wide, docked to right edge of main content), or below KPIs on mobile. Max height 480px, scrollable, newest at top.

**Data source**: SSE endpoint streaming bot log events. Falls back to polling `/api/activity` every 5s.

**Event types and visual treatment**:

| Event | Icon | Color | Example |
|---|---|---|---|
| SCAN | `search` | `--text-muted` | Scanning 604 markets... |
| EVALUATE | `filter` | `--accent-blue` | Evaluating KXBTC-25MAR -- Tier 1, score 0.82 |
| SIMULATE | `cpu` | `--tier-1` | Running simulation: 1000 agents, 30 rounds |
| SIM_COMPLETE | `check-circle` | `--profit-green` | Simulation complete: 72% probability |
| TRADE | `arrow-up-right` | `--profit-green` | BUY 3x YES @ 55c -- gap 17pp |
| SKIP | `minus-circle` | `--text-muted` | Skipped: gap 8pp below threshold |
| RESOLVE | `award` | `--profit-green` or `--loss-red` | WON: KXBTC-25MAR +$1.35 |
| ERROR | `alert-triangle` | `--loss-red` | MiroFish timeout after 600s |
| RISK | `shield-alert` | `--warning-amber` | Drawdown 15% -- approaching 20% stop |

**Each entry**:
```
[HH:MM:SS]  [Icon]  Event message text
                     Optional detail line in muted text
```

Timestamp in `--font-mono --text-xs`. Message in `--text-sm`. Fades in with a subtle slide-down animation.

**Controls**: Filter by event type (toggle chips at top). Clear button. Pause auto-scroll toggle.

### 4. Market Evaluation Table

**Purpose**: Show all markets the bot has scanned and scored, so you can see the pipeline.

**Layout**: Full page (accessed from sidebar nav). Full-width table with toolbar above.

**Toolbar**:
- Search input (filters by ticker or event title)
- Tier filter: pill toggles for Tier 1 / Tier 2 / Tier 3 / All
- Sort dropdown: Score, Gap, Volume, Close Time
- Refresh button

**Table columns**:

| Column | Width | Format | Notes |
|---|---|---|---|
| Tier | 60px | Colored badge (T1 purple, T2 cyan, T3 orange) | Sortable |
| Ticker | 120px | Monospace, uppercase | Sortable, links to Kalshi |
| Event | flex | Truncated with tooltip | Searchable |
| MiroFish Score | 100px | 0.00-1.00, monospace | Sortable, color gradient |
| Kalshi Price | 90px | 55c format, monospace | Sortable |
| Gap | 80px | +17pp format, bold if >= 15 | Sortable, highlighted row if tradeable |
| Volume | 90px | $12.3K abbreviated | Sortable |
| Status | 100px | Badge: Simulated / Traded / Skipped / Pending | Filterable |
| Close | 100px | Relative time ("in 3d 4h") | Sortable |

**Row interaction**:
- Hover: `--bg-card-hover` background
- Click: Expands inline detail panel showing simulation results, report summary, and trade action taken
- Rows where gap >= 15pp have a subtle left border in `--profit-green`

**Pagination**: Virtual scrolling (TanStack Virtual) for 604+ rows. No traditional pagination.

### 5. Active Positions

**Purpose**: Monitor open trades with live unrealized P&L.

**Layout**: Card-based grid on Overview page (2 columns desktop, 1 column mobile). Full table on Positions page.

**Card layout for each position**:
```
+----------------------------------------------------------+
|  [YES badge]  KXBTC-25MAR21-T1050                        |
|  Will Bitcoin exceed $105,000 on March 25?               |
|                                                          |
|  Entry: 55c    Current: 62c    Contracts: 3              |
|                                                          |
|  [=========>          ]  MiroFish: 72%                   |
|                                                          |
|  Unrealized P&L: +$0.21      Gap at entry: 17pp         |
|  Kelly size: 2.1%            Opened: 2h 14m ago         |
+----------------------------------------------------------+
```

- **Side badge**: "YES" in green pill or "NO" in red pill
- **Progress bar**: Shows MiroFish probability as a horizontal bar, colored by tier
- **P&L**: Green or red, monospace, with background tint
- **Current price**: Polls every 30s from Kalshi API (via backend proxy)

**Table view** (Positions page): Same data in sortable table with columns: Ticker, Event, Side, Contracts, Entry, Current, Unrealized P&L, MiroFish Prob, Gap, Kelly %, Age, Actions (close button if live mode).

### 6. Trade History

**Purpose**: Complete record of all trades with filtering and analysis.

**Layout**: Full page, full-width table with filter bar.

**Filter bar**:
- Date range picker (preset: Today, 7d, 30d, All)
- Status filter: Won / Lost / Open / All
- Side filter: Yes / No / All
- Min gap slider
- Export CSV button

**Table columns**:

| Column | Format | Notes |
|---|---|---|
| Date | YYYY-MM-DD HH:MM | Sortable |
| Ticker | Monospace link | Opens Kalshi page |
| Event | Truncated, tooltip | -- |
| Side | YES/NO badge | -- |
| Contracts | Integer, monospace | -- |
| Entry Price | Cents format (55c) | -- |
| MiroFish | Percentage (72%) | -- |
| Kalshi Price | Cents at entry | -- |
| Gap | pp format | -- |
| Kelly % | Percentage | -- |
| Amount | Dollar format | -- |
| P&L | Dollar, green/red | -- |
| Status | Badge: Won/Lost/Open | Color-coded |
| Sim ID | Truncated, link to sim detail | -- |

**Row coloring**: Subtle `--profit-green-bg` for wins, `--loss-red-bg` for losses, neutral for open.

**Summary row at bottom**: Total trades, total P&L, win rate, average gap, average Kelly.

### 7. Performance Charts

**Purpose**: Visual performance tracking over time.

**Layout**: On Overview page, 2-column chart grid below KPIs. Full-width charts on dedicated view.

**Chart 1: Cumulative P&L** (primary chart, most prominent)
- Area chart with gradient fill
- X-axis: dates, Y-axis: dollar amount
- Green fill when positive, red fill when negative
- Hover tooltip: date, daily P&L, cumulative P&L, trade count
- Benchmark line at $0 (break-even)
- Optional: overlay bankroll line on secondary axis

**Chart 2: Rolling Win Rate**
- Line chart, 20-trade rolling window
- Y-axis: 0-100%
- Reference line at 50% (break-even for binary markets)
- Shaded confidence band (optional)
- Color: `--accent-blue`

**Chart 3: Gap Distribution**
- Histogram, separate series for Won (green) and Lost (red)
- X-axis: gap in percentage points (15-50)
- Y-axis: count of trades
- Vertical reference line at 15pp (minimum threshold)
- Key insight: do larger gaps produce more wins?

**Chart 4: Daily P&L Bar Chart**
- Vertical bars, green for positive days, red for negative
- X-axis: dates, Y-axis: dollar P&L
- Hover: date, daily P&L, trades that day

**Chart 5: Tier Performance Breakdown**
- Grouped bar chart or stacked bar
- Compare win rate and average P&L across Tier 1 / Tier 2 / Tier 3
- Helps calibrate which market categories the bot handles best

**All charts**:
- Built with Recharts
- Responsive (resize with container)
- Consistent color usage from design tokens
- Accessible: patterns/shapes supplement color for colorblind users
- Time range selector: 7d / 30d / 90d / All

### 8. Simulation Monitor

**Purpose**: Track running and recent simulations.

**Layout**: Dedicated page from sidebar. Split into two sections: Running (top) and Recent (bottom).

**Running Simulations** (top section):

Card per active simulation:
```
+----------------------------------------------------------+
|  [RUNNING spinner]  sim_1711000000                       |
|  Will the Fed cut rates in March 2026?                   |
|  Tier 1 -- Political/Sentiment                           |
|                                                          |
|  Agents: 1,000    Rounds: 30    Est. cost: $3.00        |
|  Phase: Executing round 18/30                            |
|  [==============>               ] 60%                    |
|                                                          |
|  Started: 4m 22s ago    ETA: ~3m remaining              |
|  [Stop] button                                           |
+----------------------------------------------------------+
```

- Phase indicator: Creating -> Preparing -> Running -> Generating Report -> Complete
- Progress bar: animated stripes while running
- Auto-updates every 5s via SSE or polling

**Recent Simulations** (bottom section):

Table of last 50 simulations:

| Column | Format |
|---|---|
| Status | Badge: Completed (green), Failed (red), Timeout (amber) |
| Sim ID | Monospace link to detail |
| Event | Truncated |
| Tier | Colored badge |
| Agents | Integer |
| Rounds | Integer |
| MiroFish Prob | Percentage |
| Kalshi Price | Cents |
| Gap | pp format |
| Cost | Dollar |
| Traded? | Yes/No badge |
| Duration | "2m 14s" |
| Timestamp | Relative ("14m ago") |

**Simulation detail modal** (click sim ID):
- Full event title and seed text summary
- Simulation parameters
- Report excerpt (first 500 chars)
- Probability extraction details
- Trade decision reasoning (gap calculation, Kelly sizing)
- Link to trade if one was placed

### 9. Risk Dashboard

**Purpose**: Monitor risk exposure and enforce safety limits.

**Layout**: Dedicated page. Grid of risk metric cards + charts.

**Risk Metric Cards** (top row, 4 cards):

| Metric | Current | Limit | Visual |
|---|---|---|---|
| Max Drawdown | -$42 (4.2%) | 20% stop | Gauge chart, green/amber/red zones |
| Position Concentration | 3 correlated | Max 3 | Filled dots indicator |
| Daily Trade Count | 7 today | No hard limit | Bar showing today vs average |
| Capital at Risk | $52 (4.2%) | 5% per position | Progress bar |

**Drawdown Chart**:
- Area chart showing drawdown from peak over time
- Red zone shading at 20% threshold
- Amber zone at 15%
- Current drawdown prominently displayed

**Position Heatmap**:
- Grid showing positions grouped by market category/tier
- Size = dollar exposure, color = unrealized P&L
- Reveals concentration risk visually

**Daily Limits Panel**:
- Shows current values vs configured limits from `config.py`:
  - `min_gap_threshold`: 15pp
  - `max_position_pct`: 5%
  - `kelly_fraction`: 25%
  - `max_correlated_positions`: 3
  - `drawdown_stop_pct`: 20%
- Each with a progress indicator showing how close to the limit

**Risk Events Timeline**:
- Chronological list of risk-related events
- When drawdown exceeded thresholds
- When position limits were hit
- When the bot paused trading due to risk rules

---

## Data Architecture

### Backend API (FastAPI)

A thin Python API layer between the React frontend and the SQLite database. Deployed alongside the bot process.

**Endpoints**:

```
GET  /api/portfolio          -- KPI summary (bankroll, P&L, win rate, open count, Sharpe)
GET  /api/trades             -- All trades (query params: status, date_from, date_to, limit, offset)
GET  /api/trades/active      -- Open positions with current market prices
GET  /api/simulations        -- Simulation history (query params: status, limit, offset)
GET  /api/simulations/active -- Currently running simulations
GET  /api/markets            -- Evaluated markets with tier, score, gap
GET  /api/daily-stats        -- Daily stats for charting
GET  /api/risk               -- Current risk metrics
GET  /api/status             -- System health (MiroFish, Kalshi, bot state)
GET  /api/activity/stream    -- SSE endpoint for live activity feed
GET  /api/config             -- Current trading parameters (read-only)
```

**Response format**: All endpoints return JSON with consistent envelope:
```json
{
  "data": { ... },
  "meta": {
    "timestamp": "2026-03-20T14:32:00Z",
    "count": 42
  }
}
```

### Data Refresh Strategy

| Data | Method | Interval | Notes |
|---|---|---|---|
| Activity feed | SSE (streaming) | Real-time | Falls back to 5s polling |
| Portfolio KPIs | Polling | 10s | Lightweight query |
| Active positions | Polling | 30s | Includes Kalshi price fetch |
| Running simulations | Polling | 5s | Only when sims are active |
| Trade history | On-demand | -- | Fetched on page load + manual refresh |
| Market evaluation | On-demand | -- | Fetched on page load, refresh button |
| Performance charts | On-demand | -- | Fetched on page load, cached 60s |
| Risk metrics | Polling | 15s | |
| System status | Polling | 10s | Health checks |

**Stale data indicator**: Every component shows a "last updated" timestamp. If data is older than 2x the expected interval, the component shows an amber warning border.

---

## Interaction Patterns

### Loading States

Every data-dependent component has three states:

1. **Loading**: Skeleton screens matching the exact layout of the loaded state. Animated pulse effect. Never show spinners for initial page load.
2. **Loaded**: Full data display.
3. **Error**: Inline error message with retry button. Never show a full-page error for a single failed component.

### Transitions

- Page navigation: instant (no route transition animation -- speed over flair)
- Data updates: numbers animate using `framer-motion` counter transitions (smooth tick-up/tick-down)
- New activity feed items: slide down from top, 200ms ease-out
- Chart data changes: 300ms ease transition
- Card hover: 150ms `translateY(-1px)` + shadow lift

### Keyboard Navigation

- `Tab` moves through all interactive elements in logical order
- `Escape` closes modals and expanded rows
- Arrow keys navigate table rows when a table is focused
- `?` opens keyboard shortcut reference
- `/` focuses the search input

### Empty States

Each section has a purposeful empty state:
- **No trades**: Illustration + "No trades yet. The bot will place trades when it finds markets with a gap exceeding 15 percentage points."
- **No simulations**: "No simulations have been run. The bot scans markets and triggers simulations automatically."
- **No activity**: "Waiting for bot activity. Make sure the trading bot process is running."

---

## Mobile Responsiveness

### Breakpoint Behavior

**Mobile (< 640px)**:
- Sidebar becomes a bottom tab bar (5 icons: Overview, Markets, Positions, Simulations, Risk)
- Header bar: hide app name, show only mode badge + balance + status dots
- KPI cards: 2-column grid, Sharpe ratio card hidden (least critical)
- Activity feed: full-width below KPIs, collapsed to 3 items with "Show more"
- Tables: horizontal scroll with sticky first column (ticker)
- Charts: full-width, stacked vertically, reduced height (200px)
- Active positions: single-column card stack

**Tablet (640-1023px)**:
- Sidebar: collapsed to 64px icon-only rail
- KPI cards: 3+2 layout
- Tables: full-width with horizontal scroll if needed
- Charts: 2-column grid

**Desktop (1024-1439px)**:
- Full sidebar (240px)
- KPI cards: 5-across
- Main content: 2-3 column grid for mixed card/chart layouts
- Activity feed: right-docked panel

**Large (>= 1440px)**:
- Same as desktop but charts get more horizontal space
- Tables show all columns without scroll
- Activity feed remains docked right

### Touch Targets

All interactive elements have a minimum 44x44px touch target. Table rows have 48px row height on mobile (vs 40px desktop).

---

## Accessibility

### WCAG AA Compliance

- All text meets 4.5:1 contrast ratio against its background
- Large text (18px+ or 14px+ bold) meets 3:1
- Interactive elements have visible focus rings (2px solid `--accent-blue`, 2px offset)
- No information conveyed by color alone (icons/shapes supplement color for status)
- All images and icons have appropriate alt text or aria-labels
- Form inputs have associated labels
- Tables use proper `<thead>`, `<th>`, and `scope` attributes

### Screen Reader Support

- Semantic HTML5 landmarks (`<nav>`, `<main>`, `<header>`, `<aside>`)
- ARIA live regions for:
  - Activity feed (polite)
  - KPI value changes (polite)
  - Error messages (assertive)
- Descriptive page titles that update per route
- Skip-to-main-content link

### Reduced Motion

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

Chart animations and number transitions are disabled when the user prefers reduced motion.

---

## Component Inventory

Summary of unique components to build:

| Component | Instances | Priority |
|---|---|---|
| KPICard | 5 | P0 |
| StatusDot | 3 | P0 |
| ModeBadge | 1 | P0 |
| ActivityFeed | 1 | P0 |
| ActivityEntry | N | P0 |
| DataTable (generic) | 4 (trades, markets, sims, positions) | P0 |
| TierBadge | N | P0 |
| StatusBadge | N | P0 |
| SideBadge (YES/NO) | N | P0 |
| CumulativePnLChart | 1 | P0 |
| RollingWinRateChart | 1 | P1 |
| GapDistributionChart | 1 | P1 |
| DailyPnLChart | 1 | P1 |
| TierPerformanceChart | 1 | P2 |
| PositionCard | N | P0 |
| SimulationCard | N | P1 |
| DrawdownGauge | 1 | P1 |
| PositionHeatmap | 1 | P2 |
| RiskLimitBar | 5 | P1 |
| SearchInput | 1 | P1 |
| FilterChips | 3 | P1 |
| DateRangePicker | 1 | P1 |
| Skeleton variants | 8+ | P0 |
| EmptyState | 5 | P1 |
| Sidebar | 1 | P0 |
| HeaderBar | 1 | P0 |

**Priority key**: P0 = MVP (week 1-2), P1 = complete (week 3-4), P2 = polish (week 5+)

---

## File Structure

```
dashboard/
  app.py                    # Legacy Streamlit (keep for now)
  DESIGN.md                 # This file
  api/
    main.py                 # FastAPI app entry
    routes/
      portfolio.py
      trades.py
      simulations.py
      markets.py
      risk.py
      activity.py
      status.py
    db.py                   # SQLite connection helper
    models.py               # Pydantic response models
  web/
    package.json
    next.config.ts
    tailwind.config.ts
    tsconfig.json
    public/
      favicon.ico
    src/
      app/
        layout.tsx          # Root layout with sidebar + header
        page.tsx            # Overview (default route)
        markets/
          page.tsx
        positions/
          page.tsx
        simulations/
          page.tsx
        risk/
          page.tsx
        settings/
          page.tsx
      components/
        layout/
          Sidebar.tsx
          HeaderBar.tsx
          MobileTabBar.tsx
        kpi/
          KPICard.tsx
          KPIRow.tsx
        activity/
          ActivityFeed.tsx
          ActivityEntry.tsx
        tables/
          DataTable.tsx      # Generic table wrapper
          TradeHistoryTable.tsx
          MarketEvalTable.tsx
          SimulationTable.tsx
          PositionTable.tsx
        charts/
          CumulativePnL.tsx
          RollingWinRate.tsx
          GapDistribution.tsx
          DailyPnL.tsx
          TierPerformance.tsx
        positions/
          PositionCard.tsx
          PositionGrid.tsx
        simulations/
          SimulationCard.tsx
          SimulationDetail.tsx
        risk/
          DrawdownGauge.tsx
          RiskLimitBar.tsx
          PositionHeatmap.tsx
        shared/
          Badge.tsx          # StatusBadge, TierBadge, SideBadge
          Skeleton.tsx
          EmptyState.tsx
          StatusDot.tsx
          ModeBadge.tsx
      hooks/
        usePolling.ts       # Generic polling hook with stale detection
        useSSE.ts           # Server-Sent Events hook
        usePortfolio.ts
        useTrades.ts
        useSimulations.ts
        useMarkets.ts
        useRisk.ts
      lib/
        api.ts              # Fetch wrapper with base URL config
        format.ts           # Number/date/currency formatters
        tokens.css          # CSS custom properties (design tokens)
      types/
        index.ts            # TypeScript interfaces matching API models
```

---

## Implementation Phases

### Phase 1 -- MVP (Weeks 1-2)

Build the FastAPI backend and core Overview page:

1. FastAPI backend with SQLite reads (`/api/portfolio`, `/api/trades`, `/api/daily-stats`, `/api/status`)
2. Next.js project scaffolding with Tailwind, design tokens, dark theme
3. Sidebar + HeaderBar layout
4. KPI cards with polling
5. Cumulative P&L chart
6. Basic trade history table (no filters yet)
7. Activity feed with polling (SSE later)

**Deliverable**: A functional dashboard that replaces the Streamlit app with real data.

### Phase 2 -- Complete (Weeks 3-4)

Fill out all pages and add interactivity:

1. Market evaluation page with tier filters and search
2. Active positions with live price updates
3. Simulation monitor with running/recent views
4. All performance charts
5. Trade history filters and CSV export
6. SSE for activity feed
7. Mobile responsive layout

**Deliverable**: Full-featured dashboard across all sections.

### Phase 3 -- Polish (Week 5+)

1. Risk dashboard with drawdown gauge and heatmap
2. Skeleton loading states for all components
3. Keyboard shortcuts
4. Empty states with illustrations
5. Settings page (read-only config display, API health)
6. Performance optimization (virtualized tables, chart lazy loading)
7. PWA manifest for mobile home screen install

**Deliverable**: Production-quality dashboard ready for daily use.

---

## Design QA Checklist

Before each phase ships, verify:

- [ ] All text passes WCAG AA contrast check (use axe DevTools)
- [ ] Tab order is logical on every page
- [ ] Screen reader announces dynamic content changes
- [ ] No layout shift when data loads (skeletons match loaded dimensions)
- [ ] Charts are readable at 320px width
- [ ] Tables scroll horizontally on mobile without breaking layout
- [ ] Monospace alignment is correct on all financial numbers
- [ ] Dark mode has no invisible text or lost borders
- [ ] Stale data indicators appear when backend is slow/down
- [ ] Error states show actionable messages with retry
- [ ] All interactive elements have 44px+ touch targets on mobile
