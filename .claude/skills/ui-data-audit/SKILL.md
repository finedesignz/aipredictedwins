---
name: ui-data-audit
description: >
  Systematically review every page and UI component to verify data is correctly
  wired end-to-end. Use this skill whenever the user asks to "audit the UI",
  "check that data is wired up", "review all pages", "verify the dashboard",
  "make sure everything is connected", or any time you need to confirm that
  frontend components correctly reflect backend data. Also use it proactively
  after major refactors, before shipping a new dashboard, or any time a new
  page or API route is added and you want to verify the plumbing is correct.
  Spawns one focused subagent per page for parallelism and produces a unified
  pass/fail checklist across all pages.
---

# UI Data Audit

A systematic, agent-driven review of every page in a web UI to verify that all
data is correctly wired from the backend through to what the user sees.

---

## What "correctly wired" means

Before starting, you must establish the standards you'll check against. The
defaults are listed below. If the project deviates from any of them — or if
you're unsure — **stop and confirm with the user** rather than guessing.

### The 8 standard checks (per page/component)

| # | Check | What it means |
|---|-------|---------------|
| 1 | **Endpoint exists** | Every API URL the frontend calls has a matching route in the backend |
| 2 | **Response shape matches** | The TypeScript type / schema used in the frontend matches what the API actually returns (field names, types, nesting) |
| 3 | **All rendered fields present** | Every field read in JSX/template code (`data.field`, `item.value`, etc.) exists in the type AND in the actual API response |
| 4 | **Loading state** | While data is fetching, the UI shows a skeleton, spinner, or loading message — not blank space or stale data |
| 5 | **Error state** | If the API call fails, the UI shows a meaningful error message or retry option instead of crashing silently |
| 6 | **Empty state** | When the API returns zero items / null, the UI shows a meaningful "no data" message instead of being blank |
| 7 | **No mock/hardcoded data** | No static arrays, hardcoded values, TODO comments, or `Math.random()` calls standing in for real API data |
| 8 | **Query params correct** | Any filters, pagination, or date range params passed to the API are documented, used consistently, and match what the backend expects |

### Additional checks for common patterns

- **SSE / WebSocket feeds**: Connection established, events parsed correctly, reconnect logic present
- **Polling intervals**: Refresh rate appropriate for the data type (live prices vs. historical stats)
- **Auth guards**: Protected pages redirect unauthenticated users; API calls include the correct auth headers
- **Type file completeness**: The type barrel/index doesn't export types that are never imported or import types that don't exist

---

## Step 0: Orient (do this first, every time)

Read enough of the codebase to answer these questions before creating any tasks:

1. **Pages** — Where are the page files? (e.g., `app/**/page.tsx`, `pages/**/*.tsx`, `src/views/`, `src/routes/`)
2. **Data fetching** — How does the frontend call APIs? (e.g., `useAPI` hook, SWR, React Query, `fetch` directly, axios)
3. **Types** — Where are the TypeScript types / interfaces / Zod schemas? (e.g., `@/types`, `src/types/index.ts`)
4. **Backend routes** — Where are the API handlers? (e.g., FastAPI `routes/`, Express `routes/`, tRPC routers)
5. **Real-time feeds** — Is there SSE, WebSocket, or long-polling? Where is it set up?

If any of these are ambiguous (multiple patterns, mixed conventions), **ask the user** before proceeding.

---

## Step 1: Discover all pages

List every page / route that a user can navigate to. For each one, capture:

- **Route path** (e.g., `/`, `/signals`, `/settings`)
- **File path** of the page component
- **API endpoints called** (every URL passed to the data fetching hook/function)
- **Real-time feeds** (SSE/WS URLs, if any)
- **Key components** rendered on the page that fetch their own data

Present this as a table to the user and ask: "Does this list look complete? Any pages or sections I'm missing?" Wait for confirmation before proceeding.

---

## Step 2: Create tasks

Create one task per page using TaskCreate. Name each task clearly:

```
Audit: <PageName> page — <route path>
```

Also create:
- `Audit: Type definitions — verify type barrel completeness`
- `Audit: Cross-page consistency — shared components and hooks`

Mark all tasks as `todo` to start.

---

## Step 3: Run per-page agents in parallel

Spawn one subagent per page (all in the same turn for parallelism). Give each
agent this exact brief — fill in the placeholders for the specific page:

```
You are auditing the <PageName> page of a web app to verify data is wired up correctly.

## What to audit

Page file: <file path>
Route: <route path>
API calls: <list of endpoints>
Real-time feeds: <SSE/WS URLs or "none">
Key sub-components: <list or "none">

## The 8 checks to perform

For each check, read the relevant files (page component, backend route handler,
type definitions) and produce a verdict: PASS, FAIL, or WARNING.

1. **Endpoint exists** — Does each API URL the page calls have a matching handler in the backend? Read both the frontend call and the backend route file.
2. **Response shape matches** — Does the TypeScript type match the backend response? Compare field names, types, optional vs required. Look at the actual backend code (not just docs).
3. **All rendered fields present** — Scan the JSX for every `data.X`, `item.X`, `obj?.X` access. Does each field exist in the type AND in the backend response?
4. **Loading state** — Is there a loading spinner, skeleton, or message shown while data is in flight? Or does the component just render nothing?
5. **Error state** — If the fetch throws or returns a non-2xx status, does the UI handle it gracefully?
6. **Empty state** — When the API returns `[]` or `null`, is there a meaningful "no data" message?
7. **No mock/hardcoded data** — Grep the page and its direct child components for static arrays, hardcoded strings that look like real data, `Math.random()`, or TODO/FIXME comments near data rendering.
8. **Query params correct** — List every query param passed in the URL. Verify each one is read and handled in the backend handler.

## Output format

Return a markdown report in this exact structure:

### <PageName> Page — /route

| Check | Status | Notes |
|-------|--------|-------|
| Endpoint exists | PASS/FAIL/WARN | ... |
| Response shape | PASS/FAIL/WARN | ... |
| Rendered fields | PASS/FAIL/WARN | ... |
| Loading state | PASS/FAIL/WARN | ... |
| Error state | PASS/FAIL/WARN | ... |
| Empty state | PASS/FAIL/WARN | ... |
| No mock data | PASS/FAIL/WARN | ... |
| Query params | PASS/FAIL/WARN | ... |

**Issues found:**
- <list each FAIL/WARN with the specific file:line and what's wrong>

**Looks good:**
- <list each PASS with one-line confirmation of what you verified>
```

Mark the page's task as `in_progress` when you spawn its agent, `completed` when the result comes back.

---

## Step 3.5: Interactive design validation (per page, sequential)

After the technical audits return, do a second pass — this time interactively with the user, one page at a time. The goal is to surface design intent questions that the code can't answer: what data the user *wants* to see, what defaults make sense, and whether the layout matches their mental model.

### How it works

For each page, read the audit report + the page component, then ask **no more than 3 questions**. Pick the most valuable questions — ones where different answers would actually change something. Skip questions whose answers are obvious or already known.

**Good questions** are concrete and specific:
- "The equity chart defaults to 30 days. Should that be a different default, or should it remember the user's last selection?"
- "The positions page shows open positions at the top and closed at the bottom. Should it be the other way around, or would a tab switch (Open / Closed) work better?"
- "The bot filter shows all bots selected by default. Should it start with a specific bot instead?"

**Bad questions** are vague or obvious:
- "Does this page look good?" (too vague)
- "Should the trades page show trades?" (obvious)
- "Do you want a button here?" (not informed by the code)

### Format for asking questions

Present questions clearly, grouped by page:

```
**[PageName] — /route**
Based on the audit, I have a few questions about this page:

1. [question about data/content]
2. [question about defaults/filters]
3. [question about layout/priority]

(Skip any question that isn't relevant — just let me know.)
```

### Tracking global answers

Some answers apply to the whole app, not just one page. When a user answers something that could be a global preference, mark it explicitly:

> ✓ Recorded as **global preference**: "Bot filter should default to showing all bots."

Then, on subsequent pages, **show the relevant global preferences that already apply** and skip asking the same question again:

```
**[NextPage] — /route**
Global preferences already recorded:
- Bot filter defaults to all bots ✓

Questions for this page:
1. [only questions not already answered globally]
```

### When to ask fewer than 3

Ask fewer than 3 questions if:
- The page is simple (one data source, minimal UI choices)
- Global preferences already answer most questions
- The code makes the intent completely clear

Aim for questions that would actually change what you build — not questions you're asking just to hit the number.

---

## Step 4: Aggregate the results

Once all agents have returned and the design validation is complete, compile a unified report:

```markdown
# UI Data Audit — <Project Name>
Audited: <date>
Pages reviewed: N

## Summary

| Page | Endpoints | Shape | Fields | Loading | Error | Empty | Mock | Params | Overall |
|------|-----------|-------|--------|---------|-------|-------|------|--------|---------|
| Overview | ✅ | ✅ | ⚠️ | ✅ | ❌ | ✅ | ✅ | ✅ | ⚠️ |
| ...      | ...  | ...  | ...  | ...  | ...  | ...  | ...  | ...  | ...  |

Legend: ✅ PASS  ⚠️ WARN  ❌ FAIL

## Issues requiring action

### Critical (FAIL)
- **Page / component**: description, file:line

### Warnings (WARN)
- **Page / component**: description, file:line

## All clear
- List pages with all 8 checks passing

## Design preferences captured

### Global preferences (apply to all pages)
- [preference]: [what user said]

### Page-specific preferences
- **[PageName]**: [what user said]
```

Print the full report in the conversation so the user can see it without opening a file.

---

## Step 5: Fix or delegate

For each FAIL or WARN, offer the user two options:

1. **Fix now** — You make the fix inline (for simple issues: missing empty state, wrong field name, missing error handler)
2. **Track for later** — You leave a clear `// TODO(audit):` comment at the exact file:line so it's easy to find

Ask: "Which issues should I fix now and which should be tracked?" Then act on their answer.

---

## Confirming standards

At any point where the project doesn't match one of the 8 standard checks — for
example, it intentionally has no error state because errors are handled at the
app level, or it uses optimistic rendering so there's no loading state — confirm
this with the user before marking it as a FAIL. The goal is to surface real
problems, not flag intentional design choices.

If you can't determine the project's conventions from the code alone (e.g.,
no clear pattern for empty states, mixed fetching approaches), ask before
proceeding. A well-targeted question beats an inaccurate audit.

---

## Shortcuts for small projects

If the project has 3 or fewer pages, skip the parallel agent spawning and do
the audit inline in a single pass. The 8-check table and report format remain
the same.

If the user only wants to audit one specific page, apply the same 8 checks but
skip the discovery step and go straight to the per-page audit.
