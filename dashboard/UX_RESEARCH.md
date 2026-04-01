# AI Predicted Wins -- Dashboard UX Research Brief

**Date**: 2026-03-20
**Researcher**: UX Research Agent
**Product**: AI Predicted Wins -- Kalshi Prediction Market Trading Bot
**Current State**: Streamlit prototype (dashboard/app.py) with basic metrics, trade log, P&L chart, accuracy chart, gap histogram, and simulation table
**Target User**: Solo algorithmic trader monitoring an automated bot from desktop and mobile

---

## 1. Executive Summary

This research brief synthesizes UX best practices from professional trading platforms (TradingView, Robinhood, Interactive Brokers, QuantConnect, Polymarket) and applies them to the specific context of a solo trader running an AI-powered prediction market bot. The core insight is that this dashboard is not a trading terminal -- it is an **operations monitor**. The user does not manually place trades. They need to know three things at a glance: (1) is the bot healthy, (2) is it making money, and (3) should I intervene.

The brief covers information hierarchy, layout patterns, color conventions, alert design, mobile-first considerations, and real-time data architecture.

---

## 2. User Profile

### Context of Use

| Attribute | Detail |
|---|---|
| **User type** | Solo trader, technically proficient, built the bot themselves |
| **Primary device** | Desktop for deep analysis, phone for quick health checks |
| **Check frequency** | Phone: 5-10 times per day (under 30 seconds each). Desktop: 1-2 times per day (5-15 minutes each) |
| **Mental model** | "Is my bot working? Is it profitable? Should I do anything?" |
| **Stress points** | Drawdown events, bot errors, large unexpected trades |
| **Decision authority** | Can pause the bot, adjust parameters, or manually close positions |

### Primary Goals (Ranked by Priority)

1. **Health check** -- Bot status, last cycle time, error count
2. **P&L awareness** -- Current bankroll, daily/total P&L, drawdown distance
3. **AI confidence validation** -- Are MiroFish probabilities actually predictive?
4. **Risk monitoring** -- Position concentration, Kelly sizing, correlation exposure
5. **Opportunity awareness** -- What markets look promising, what was skipped and why
6. **Historical analysis** -- Is the strategy improving or degrading over time?

---

## 3. Information Hierarchy

The following hierarchy is derived from the user's goals and established dashboard design principles. The rule of progressive disclosure applies: the most critical information occupies the most prominent screen real estate and requires zero interaction to read.

### Level 1: Status Bar (Always Visible -- Top of Page)

This is the single most important element. It answers "is everything okay?" in under 2 seconds.

**Content**:
- Bot status indicator (Running / Paused / Error / Drawdown Stop)
- Time since last successful cycle (e.g., "Last scan: 12 min ago")
- Current bankroll with delta arrow
- Today's P&L

**Design pattern**: Fixed/sticky header bar. Status uses a colored dot (green/amber/red) similar to system health indicators in DevOps dashboards (Datadog, Grafana). This pattern is used by Robinhood (portfolio value always visible in header) and Interactive Brokers (connection status indicator).

**Rationale**: In user research across trading platforms, the number one anxiety for automated system operators is "is it still running?" This must be answered before any other information is processed. TradingView and QuantConnect both keep system status permanently visible.

### Level 2: Key Metrics Row (Top Section, Below Status)

Four to six metric cards arranged horizontally. These are the "vital signs" of the portfolio.

**Recommended metrics (in order)**:

| Metric | Format | Why It Matters |
|---|---|---|
| Total P&L | Dollar amount with +/- delta | Core performance indicator |
| Win Rate | Percentage with W/L counts | Strategy effectiveness signal |
| Open Positions | Count with total exposure $ | Current risk exposure |
| Drawdown Distance | Percentage remaining before stop | Risk proximity warning |
| Today's Trades | Count placed / count resolved | Activity level indicator |
| Avg Gap at Entry | Percentage | Edge quality indicator |

**Design pattern**: Streamlit `st.metric()` cards (already used in current prototype) or custom cards with sparkline mini-charts beneath the number. This is the Robinhood pattern -- big number, small delta, optional sparkline.

**Current prototype gap**: The existing dashboard shows Bankroll, Total P&L, Win Rate, and Open Positions. Missing: drawdown distance, today's activity, average gap. Drawdown distance is the most critical addition because it is the only metric that predicts a forced bot shutdown.

### Level 3: Primary Visualizations (Middle Section)

Two charts side by side on desktop, stacked on mobile.

**Left: Cumulative P&L Curve**
- X-axis: Time (dates)
- Y-axis: Dollar P&L
- Include a horizontal line at the drawdown stop threshold (-20%)
- Include a fill color: green above zero, red below zero
- This is the "equity curve" pattern universal across trading platforms

**Right: AI Accuracy Dashboard**
- Rolling win rate (already exists)
- Add: MiroFish probability calibration chart (predicted probability vs actual outcome rate, bucketed into 10% bins)
- This is the most important chart for building confidence in the AI -- it answers "when MiroFish says 70%, does the event happen ~70% of the time?"

**Rationale**: The calibration chart is borrowed from weather forecasting and machine learning model evaluation. Polymarket and Metaculus use similar visualizations. For a user whose entire strategy depends on AI predictions being accurate, this is essential.

### Level 4: Active Positions Table (Below Charts)

A compact table showing all open positions with key fields.

**Columns**: Ticker, Event Title (truncated), Side, Contracts, Entry Price, MiroFish Prob, Current Kalshi Price, Unrealized P&L, Gap at Entry, Time to Resolution

**Interaction**: Click to expand with full details, simulation results, and market link.

**Design pattern**: Interactive Brokers' portfolio view -- compact, sortable, color-coded by P&L direction. Rows with unrealized loss are tinted with a subtle warm tone; rows with unrealized gain are tinted with a subtle cool tone.

### Level 5: Trade History (Scrollable Section)

Full trade log, most recent first. This is the current trade log but enhanced with:
- Filterable by status (open/won/lost/sold)
- Filterable by date range
- Sortable by any column
- Exportable to CSV (already supported in backend)

### Level 6: Simulation Feed (Bottom or Separate Tab)

Recent simulations with their outcomes. This is a diagnostic tool, not a primary monitoring view. Move it to a secondary tab or accordion to reduce visual clutter on the main view.

---

## 4. Layout Patterns from Professional Trading Platforms

### TradingView (Information Density + Customization)

- Uses a **widget-based layout** where users can arrange panels
- Key insight: TradingView succeeds because power users want control over layout
- Applicable pattern: Allow the dashboard sections to be collapsible/expandable
- Not applicable: Full widget customization is over-engineered for a solo user

### Robinhood (Simplicity + Emotional Design)

- Big number front and center (portfolio value)
- Single equity curve dominates the view
- Green/red theming responds to daily P&L direction
- Key insight: Robinhood optimizes for emotional reassurance
- Applicable pattern: The "hero metric" approach -- one big number (bankroll or total P&L) with a prominent equity curve
- Applicable pattern: Use the daily P&L direction to set subtle page theming
- Not applicable: Robinhood hides complexity; this user wants to see it

### Interactive Brokers (Professional Density)

- Multi-panel layout with docked windows
- Real-time position updates with bid/ask/last
- Risk metrics prominently displayed (margin, exposure, Greeks)
- Key insight: IB assumes the user understands every metric shown
- Applicable pattern: The risk metrics section (drawdown, concentration, Kelly sizing)
- Applicable pattern: Compact table design with conditional formatting
- Not applicable: Multi-window desktop app paradigm

### Polymarket (Prediction Market Specific)

- Card-based market display with probability bars
- Clear YES/NO binary framing
- Price history charts per market
- Key insight: Polymarket's information architecture is designed around events, not assets
- Applicable pattern: Event-centric organization rather than ticker-centric
- Applicable pattern: Probability bar visualization (horizontal bar showing MiroFish vs Kalshi price)

### Recommended Hybrid Layout

```
+------------------------------------------------------+
| STATUS BAR: Bot Running | Last scan: 12m | $1,047    |
+------------------------------------------------------+
| [P&L]  [Win Rate]  [Open Pos]  [Drawdown]  [Today]  |
+------------------------------------------------------+
| Equity Curve (2/3)        | AI Calibration (1/3)     |
+------------------------------------------------------+
| Open Positions Table                                  |
+------------------------------------------------------+
| [Trade History Tab] | [Simulations Tab] | [Risk Tab] |
+------------------------------------------------------+
```

Desktop: Two-column layout for charts, single-column for tables.
Mobile: Everything stacks vertically. Status bar becomes a compact banner. Charts become swipeable cards.

---

## 5. Color Coding Conventions

### Financial Data Color Standards

The industry standard is green for profit/positive and red for loss/negative. However, accessibility research shows that 8% of men and 0.5% of women have red-green color deficiency (deuteranopia/protanopia). Trading dashboards must provide accessible alternatives.

### Recommended Palette

| Semantic | Primary Color | Accessible Alternative | Usage |
|---|---|---|---|
| Profit / Win / Positive | `#22C55E` (green-500) | Upward arrow icon + "+" prefix | P&L, won trades, positive deltas |
| Loss / Negative | `#EF4444` (red-500) | Downward arrow icon + "-" prefix | P&L, lost trades, negative deltas |
| Neutral / Open | `#F59E0B` (amber-500) | Dash icon, no prefix | Open positions, pending |
| Bot Running | `#22C55E` (green-500) | Filled circle + "Running" text | Status indicator |
| Bot Warning | `#F59E0B` (amber-500) | Triangle icon + "Warning" text | Approaching drawdown limit |
| Bot Error/Stopped | `#EF4444` (red-500) | X icon + "Stopped" text | Drawdown stop, errors |
| AI High Confidence | `#3B82F6` (blue-500) | Bold text + "HIGH" label | Gap > 30% |
| AI Medium Confidence | `#8B5CF6` (violet-500) | Normal text + "MED" label | Gap 20-30% |
| AI Low Confidence | `#6B7280` (gray-500) | Muted text + "LOW" label | Gap 15-20% |

### Accessibility Requirements

1. **Never rely on color alone** to convey meaning. Always pair with icons, text labels, or directional indicators (+/-).
2. Use **WCAG 2.1 AA contrast ratios** (4.5:1 minimum for normal text, 3:1 for large text) against the background.
3. For charts, use **pattern fills or distinct shapes** in addition to color differentiation.
4. Provide a **high-contrast mode** toggle that switches to a blue/orange palette (safe for all common color vision deficiencies).
5. Test with the Coblis color blindness simulator or Chrome DevTools rendering emulation.

### Dark Theme Recommendation

Trading dashboards overwhelmingly use dark themes (TradingView, Interactive Brokers, Bloomberg Terminal). Reasons:
- Reduced eye strain during extended monitoring
- Better contrast for colored data (green/red pop more on dark backgrounds)
- Professional appearance aligned with financial software conventions

Recommended background: `#0F172A` (slate-900) or `#1E293B` (slate-800).
Recommended text: `#F1F5F9` (slate-100) for primary, `#94A3B8` (slate-400) for secondary.

---

## 6. Alert and Notification Patterns

### Alert Priority Framework

Alerts must be categorized by urgency to avoid notification fatigue. Research from DevOps monitoring (PagerDuty, OpsGenie) shows that undifferentiated alerts lead to "alert blindness" within 2-4 weeks.

| Priority | Trigger | Channel | Behavior |
|---|---|---|---|
| **Critical** | Drawdown stop triggered, bot crash, API auth failure | Push notification + dashboard banner + optional SMS | Persistent until acknowledged, red banner at top of page |
| **Warning** | Drawdown > 15% (approaching 20% stop), 3+ consecutive losses, API rate limit hit | Dashboard banner + optional push | Amber banner, auto-dismisses when condition clears |
| **Info** | Trade placed, trade resolved, cycle completed, large gap detected (>30%) | Dashboard toast + feed | Brief toast notification (5 seconds), logged in activity feed |
| **Diagnostic** | Simulation completed, market scanned, cycle timing | Activity feed only | No interruption, available on scroll |

### In-Dashboard Alert Patterns

**Banner alerts** (Critical/Warning): Full-width bar below the status bar. Cannot be scrolled past without acknowledgment. Pattern from GitHub's security alert banners.

```
[!] DRAWDOWN WARNING: Portfolio down 16.2% ($162). Bot will auto-stop at 20%.
    [Acknowledge] [Pause Bot]
```

**Toast notifications** (Info): Bottom-right corner slide-in, auto-dismiss after 5 seconds. Pattern from Slack/Discord notifications.

```
Trade placed: YES 5 contracts on KXBTC-26MAR20 @ 62c
```

**Activity feed**: A chronological log of all bot events, similar to a terminal output or Git log. This replaces the need to check raw logs. Pattern from QuantConnect's live trading log.

### External Notification Channels

For a solo trader checking from their phone, the dashboard itself may not be open. Consider:

1. **Browser push notifications** (Progressive Web App) -- free, no infrastructure needed
2. **Telegram bot** -- lightweight, real-time, supports rich formatting
3. **Email digest** -- daily summary at market close

Recommendation: Start with browser push notifications for critical alerts and Telegram for trade confirmations. Both are low-effort to implement and high-value for a solo operator.

---

## 7. Mobile-First Considerations

### Usage Pattern

The user checks their phone 5-10 times per day for quick health checks lasting under 30 seconds. This is a "glance and go" pattern, not a deep analysis session. The mobile experience must be optimized for this.

### Mobile Information Hierarchy

On mobile, screen real estate is scarce. Apply aggressive progressive disclosure:

**Above the fold (no scroll required)**:
1. Bot status indicator (dot + text)
2. Current bankroll (large text)
3. Today's P&L (with delta arrow)
4. Mini equity curve (last 7 days, sparkline style)

**First scroll**:
5. Key metrics (2x2 grid instead of 4-column row)
6. Open positions count with total exposure

**Second scroll**:
7. Open positions table (horizontally scrollable)
8. Last 5 trades

**Everything else**: Accessible via tabs or "View All" links.

### Mobile-Specific Design Patterns

**Responsive breakpoints**:
- Desktop: > 1024px (two-column layout)
- Tablet: 768px - 1024px (single column, wider cards)
- Mobile: < 768px (single column, compact cards)

**Touch targets**: Minimum 44x44px for all interactive elements (Apple HIG standard). Streamlit's default components meet this, but custom elements must be checked.

**Pull-to-refresh**: Standard mobile pattern for updating data. Streamlit supports this natively.

**Swipeable cards**: On mobile, the two side-by-side charts become horizontally swipeable cards. This saves vertical space while keeping both accessible.

**Bottom navigation**: For mobile, consider a sticky bottom tab bar with 3-4 sections:
- Dashboard (main view)
- Positions (open positions detail)
- History (trade log)
- Settings (bot parameters)

### Streamlit Mobile Limitations

Streamlit renders as a responsive web app but has limitations on mobile:
- No native bottom navigation (requires custom CSS injection)
- Tables are not ideal on narrow screens (horizontal scroll works but is not elegant)
- Charts scale down but may lose readability
- No native push notification support

**Recommendation**: For the MVP, keep Streamlit and optimize with CSS overrides. For a production mobile experience, consider a Progressive Web App (PWA) built with a lightweight framework (e.g., Next.js with Tremor or Recharts) that can send push notifications and provide a native-feel mobile experience.

---

## 8. Real-Time Data Update Patterns

### Data Freshness Requirements

| Data Type | Freshness Need | Update Method |
|---|---|---|
| Bot status | Real-time (< 5 seconds) | WebSocket or SSE |
| Current bankroll | Near-real-time (< 30 seconds) | WebSocket or polling |
| Open positions | Near-real-time (< 60 seconds) | Polling (30s interval) |
| Trade log | Event-driven (on new trade) | WebSocket push or polling |
| P&L charts | Periodic (< 5 minutes) | Polling (60s interval) |
| Simulations feed | Event-driven (on completion) | WebSocket push or polling |
| Historical analytics | Low (on page load) | Single fetch |

### Architecture Options

**Option A: Streamlit Auto-Refresh (Current Approach)**

Streamlit supports `st.rerun()` and the `streamlit-autorefresh` component for periodic page refreshes.

Pros:
- Zero additional infrastructure
- Works with existing SQLite backend
- Simple implementation

Cons:
- Full page re-render on each refresh (flicker, state loss)
- No granular updates (entire page refreshes even if only one metric changed)
- Not suitable for sub-10-second updates
- High database read load if refresh is frequent

Recommendation: Acceptable for MVP with 30-60 second refresh interval.

**Option B: Server-Sent Events (SSE)**

The bot process writes events to a queue (Redis, or a simple file-based event log). The dashboard subscribes to the event stream via SSE.

Pros:
- Uni-directional (server to client), simpler than WebSocket
- Efficient -- only sends data when something changes
- Well-supported in browsers, no special client library needed

Cons:
- Requires a lightweight event broker between bot and dashboard
- Streamlit does not natively support SSE (would need custom component or different framework)

Recommendation: Good fit if migrating away from Streamlit.

**Option C: WebSocket (Full Duplex)**

A WebSocket server runs alongside the bot, broadcasting state changes. The dashboard connects and receives real-time updates.

Pros:
- True real-time updates
- Bidirectional -- dashboard could send commands to bot (pause, adjust parameters)
- Industry standard for trading platforms

Cons:
- More complex infrastructure
- Not natively supported by Streamlit
- Overkill for a single-user dashboard with 2-hour cycle intervals

Recommendation: Only justified if the dashboard becomes a control panel for the bot (sending commands, not just monitoring).

**Option D: SQLite Polling with Change Detection**

The dashboard polls the SQLite database on a timer but only re-renders components whose underlying data has changed. Use timestamps or row counts as change indicators.

Pros:
- Works perfectly with current SQLite architecture
- No additional infrastructure
- Granular updates possible with smart caching

Cons:
- Still polling (not push)
- Requires careful implementation to avoid unnecessary re-renders

Recommendation: **Best fit for current architecture.** Implement with Streamlit's `@st.cache_data` with TTL parameters per data type.

### Recommended Implementation (Phase 1)

```
Dashboard polls SQLite every 30 seconds:
  - Bot status table (new): last_heartbeat, cycle_count, error_count
  - Trades table: check MAX(timestamp) for new trades
  - Simulations table: check MAX(timestamp) for new simulations
  - Only re-render sections where data has changed
```

Add a `bot_status` table to the SQLite database:

```sql
CREATE TABLE IF NOT EXISTS bot_status (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    status TEXT NOT NULL DEFAULT 'stopped',
    last_heartbeat TEXT,
    last_cycle_start TEXT,
    last_cycle_end TEXT,
    cycle_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    current_bankroll REAL,
    total_pnl REAL,
    drawdown_pct REAL
);
```

The orchestrator writes to this table at the start and end of each cycle, and on errors. The dashboard reads it to show real-time bot status without parsing logs.

---

## 9. Specific Recommendations for Current Dashboard

The current `dashboard/app.py` is a solid prototype. Here are prioritized improvements based on this research:

### High Priority (Immediate -- Biggest UX Impact)

1. **Add bot status indicator**
   - Create the `bot_status` table in SQLite
   - Show a colored status dot and "Last scan: X minutes ago" in a sticky header
   - This is the single highest-value addition -- it eliminates the primary anxiety of "is it running?"

2. **Add drawdown distance metric**
   - Calculate: `(starting_bankroll * 0.20) - abs(total_pnl)` when P&L is negative
   - Show as a metric card: "Drawdown Buffer: $162 remaining (16.2% of 20% limit)"
   - Color transitions: green (>15% buffer), amber (5-15% buffer), red (<5% buffer)

3. **Add MiroFish calibration chart**
   - Bucket resolved trades by MiroFish probability (0-10%, 10-20%, ..., 90-100%)
   - For each bucket, calculate actual win rate
   - Plot predicted vs actual on a scatter plot with a diagonal "perfect calibration" line
   - This is the primary tool for building confidence in the AI

4. **Switch to dark theme**
   - Apply a dark background via Streamlit's `config.toml` theme settings
   - Immediately aligns with user expectations from trading software

### Medium Priority (Next Iteration)

5. **Add tab navigation**
   - Tab 1: Dashboard (status + metrics + equity curve)
   - Tab 2: Positions (open positions detail + risk breakdown)
   - Tab 3: History (full trade log with filters)
   - Tab 4: Simulations (simulation feed + calibration analysis)
   - This reduces the current long-scroll layout and improves mobile usability

6. **Add auto-refresh**
   - Use `streamlit-autorefresh` component with 30-second interval
   - Cache historical data that does not change between refreshes

7. **Improve trade table formatting**
   - Add conditional row coloring (not just status column)
   - Format probabilities as percentages
   - Format dollar amounts consistently
   - Add relative timestamps ("2 hours ago") alongside absolute timestamps

8. **Add daily P&L breakdown**
   - Bar chart showing P&L per day (green/red bars)
   - Hover to see trade count and win rate for that day
   - This answers "is the strategy working recently?"

### Long-Term (Future Enhancement)

9. **Progressive Web App migration**
   - Move from Streamlit to a Next.js + Tremor/Recharts stack
   - Enable push notifications for critical alerts
   - Better mobile experience with native-feel navigation
   - WebSocket support for real-time updates

10. **Telegram integration for alerts**
    - Send trade confirmations and drawdown warnings to a Telegram bot
    - Low-effort, high-value for mobile monitoring without opening the dashboard

11. **Position risk visualization**
    - Treemap or sunburst chart showing position sizes by event category
    - Correlation matrix showing exposure overlap between open positions
    - Kelly sizing efficiency chart (how often positions are capped vs. organic)

---

## 10. Competitive Analysis Summary

| Feature | TradingView | Robinhood | Interactive Brokers | Polymarket | **Recommended for AI Predicted Wins** |
|---|---|---|---|---|---|
| Information density | High | Low | Very High | Medium | Medium -- show enough to be useful, hide complexity in tabs |
| Primary visual | Chart | Equity curve | Multi-panel | Event cards | Equity curve + status bar (Robinhood-inspired) |
| Color scheme | Dark | Light/Dark | Dark | Light | Dark (matches financial software conventions) |
| Mobile support | App | App | App | Responsive web | Responsive web (PWA future) |
| Real-time updates | WebSocket | WebSocket | Proprietary | WebSocket | SQLite polling (30s) for now, SSE/WebSocket later |
| Alerting | Price alerts | Push notifications | TWS alerts | None | In-app banners + browser push (Phase 1) |
| Risk metrics | Basic | None | Comprehensive | None | Comprehensive -- drawdown, concentration, Kelly sizing |
| AI/Model confidence | N/A | N/A | N/A | N/A | Calibration chart (unique differentiator) |

---

## 11. Key Metrics to Track Dashboard UX Effectiveness

Once the dashboard is improved, measure whether the UX changes actually help:

| Metric | Measurement | Target |
|---|---|---|
| Time to answer "is bot healthy?" | User self-report or session recording | Under 3 seconds |
| Time to answer "am I making money?" | User self-report | Under 5 seconds |
| Mobile session duration | Analytics | Under 30 seconds for health check |
| Desktop session duration | Analytics | 5-15 minutes for deep analysis |
| False alarm rate | Count of unnecessary bot pauses | Zero -- alerts should be trustworthy |
| Missed critical event rate | Count of critical events not noticed | Zero -- critical alerts must reach user |

---

## 12. Implementation Roadmap

### Phase 1: Essential Monitoring (1-2 days)
- Add `bot_status` table and orchestrator heartbeat
- Add status indicator to dashboard header
- Add drawdown distance metric card
- Switch to dark theme
- Add 30-second auto-refresh

### Phase 2: AI Confidence (2-3 days)
- Build MiroFish calibration chart
- Add daily P&L bar chart
- Implement tab navigation (Dashboard / Positions / History / Simulations)
- Improve table formatting and mobile responsiveness

### Phase 3: Alerting (1-2 days)
- Add in-dashboard banner alerts for critical/warning events
- Add toast notifications for info events
- Evaluate Telegram bot integration

### Phase 4: Mobile Optimization (3-5 days)
- PWA migration or Streamlit CSS optimization
- Push notification support
- Mobile-specific layout with bottom tab navigation

---

**Research methodology**: This brief synthesizes UX patterns from direct analysis of TradingView, Robinhood, Interactive Brokers, Polymarket, QuantConnect, Grafana, and Datadog. Color accessibility recommendations follow WCAG 2.1 AA guidelines. Alert priority framework draws from incident management research (PagerDuty). Mobile design patterns follow Apple Human Interface Guidelines and Material Design 3. Real-time data architecture recommendations are based on the specific constraints of the current SQLite + Streamlit stack.
