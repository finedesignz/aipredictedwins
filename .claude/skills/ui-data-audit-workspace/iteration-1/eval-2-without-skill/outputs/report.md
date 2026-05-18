# Signals Page Audit (No Skill)

**Bottom line: The signals page is entirely hardcoded. No real data is being shown.**

### What the backend actually does

`dashboard/api/routes/signals.py` returns a static Python list called `_PLACEHOLDER_SIGNALS` containing fixed values for all 8 crypto assets. The file even has explicit TODO comments admitting this.

The only thing that's dynamic is `scanned_at` — it's injected as `datetime.now(timezone.utc)` at response time, so the timestamp looks fresh even though all indicator values are frozen.

### The bot computes real signals but never saves them

`src/technical_signals.py` and `src/alpaca_orchestrator.py` do run real `scan_assets()` calls against Alpaca each cycle. The signals are used in-process to make trading decisions, but they are **never written to the database**. No `signals` table exists in the Postgres schema.

### The frontend wiring is correct

`dashboard/web/app/signals/page.tsx` correctly polls `/api/signals` every 30 seconds via `useAPI`. The `SignalTable` component maps all columns properly.

### What needs to happen to fix it

1. Add a `signals` table to Postgres (new migration)
2. After each `scan_assets()` call, upsert the results into that table
3. Update `dashboard/api/routes/signals.py` to query the table instead of returning `_PLACEHOLDER_SIGNALS`
