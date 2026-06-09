# Phase 8: Intraday Learning Dimensions + Shadow Mode - Research

**Researched:** 2026-06-08
**Domain:** Python 3 + Postgres (psycopg3) trading-bot learning loop; numbered SQL migrations
**Confidence:** HIGH (entire phase is in-repo wiring; all claims grep/read-verified in this session)

## Summary

Phase 8 is pure in-repo wiring on top of an already-closed learning loop (Phase 7). No new
external packages. Three additive nullable columns on `trade_context`
(`time_of_day_bucket TEXT`, `hold_minutes DOUBLE PRECISION`, `volatility_regime TEXT`),
populated at the existing `record_trade_context()` (entry: time bucket + vol regime) and
`learning_loop._sync_trade_outcomes()` (close: hold_minutes) seams; additive dimension grouping
in `generate_lessons()`/`update_strategy_scores()`; and a single `should_enforce_learning(memory, bot_id)`
helper that replaces the module-level static `LEARNING_ENFORCE` boolean at four veto/scale seams
across two runtimes.

The repo has **two** DDL sources and the planner MUST target the right one (see Pitfall 1):
`src/db_schema.sql` is the runtime bootstrap (`_bootstrap_schema()` on pool init) and contains a
STALE minimal `trade_context` (id, bot_id, timestamp, symbol, context). The CORRECT, live schema
for `trade_context` is `dashboard/api/migrations/006_learning_tables.sql` (the full column set the
Python code actually inserts). Schema changes are applied via **numbered idempotent SQL migrations**
run by `dashboard/api/migrations/run_migrations.py` (tracks applied files in `_migrations`).

**Primary recommendation:** Add migration `014_intraday_learning_dims.sql` with three
`ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS ...` (nullable, no NOT NULL/no default-backfill
needed) AND mirror the same three `ADD COLUMN IF NOT EXISTS` into `db_schema.sql`'s `trade_context`
block so the runtime bootstrap path stays consistent. Compute `volatility_regime` from
`Signal.atr_value / price_at_entry` at entry; `time_of_day_bucket` from the entry UTC timestamp;
`hold_minutes` from `alpaca_trades.timestamp`→`closed_at` at outcome sync. Replace `LEARNING_ENFORCE`
static checks with a count-based helper; explicit `LEARNING_ENFORCE=0` forces shadow.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| LEARN-04 | `trade_context` records `time_of_day_bucket`, `hold_minutes`, `volatility_regime` | Migration 014 + db_schema.sql mirror; entry compute in `record_trade_context`; close compute in `_sync_trade_outcomes` (§Architecture, §Code) |
| LEARN-05 | `generate_lessons()` / scoring condition on the new dimensions | Additive group passes in `generate_lessons`/`update_strategy_scores`, gated by existing `min_sample` (§Architecture Pattern 3) |
| LEARN-06 | Shadow mode log-only until `LEARNING_SHADOW_UNTIL_TRADES` (default 30) closed trades/bot, then auto-apply; `LEARNING_ENFORCE=0` manual override | `should_enforce_learning(memory, bot_id)` helper + closed-count query; replaces static flag at 4 seams (§Pattern 4) |
</phase_requirements>

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Locate where `trade_context` is defined; add the 3 columns nullable + backward-compatible migration. Existing rows get NULLs — handle gracefully in lessons.
- **D-02:** `time_of_day_bucket` + `volatility_regime` at entry (`record_trade_context`); `hold_minutes` at close (outcome sync has entry+exit timestamps). Compute `volatility_regime` from data available at entry (ATR/price or recent range) — `Signal.atr_value` is a candidate.
- **D-03:** Wire new fields through both runtimes' `record_trade_context` calls (long+short, bot_thread + orchestrator), reusing canonical `signal_type` from Phase 7.
- **D-04:** Extend `generate_lessons()`/`update_strategy_scores()` to group/condition on new dimensions where sample size supports it (respect existing `min_sample`). Keep additive — don't break existing per-signal/per-symbol lessons.
- **D-05:** Add helper returning whether learning should ENFORCE: count closed trades for the bot; `< LEARNING_SHADOW_UNTIL_TRADES` (default 30) → shadow (log-only); else enforce. Single source of truth at veto/scale seams. In shadow mode log `learn_shadow: WOULD veto/scale ×N` and DO NOT act.
- **D-06:** Manual override: explicit `LEARNING_ENFORCE=0` forces shadow regardless of count; default is count-based. Precedence: explicit 0 wins.

### Claude's Discretion
- Exact bucket boundaries / volatility thresholds and lesson grouping granularity — kept additive and tested.

### Deferred Ideas (OUT OF SCOPE)
- Bot D deployment — Phase 9. Backtest — Phase 10.
</user_constraints>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Schema columns + migration | Database / `src/db_schema.sql` + `dashboard/api/migrations/` | — | Two DDL sources; both must carry additive columns |
| Entry dimension compute (time bucket, vol regime) | `src/trade_memory.py:record_trade_context` | call sites in `bot_thread.py` / `alpaca_orchestrator.py` | data (`Signal.atr_value`, price, timestamp) available at entry |
| Close dimension compute (hold_minutes) | `src/learning_loop.py:_sync_trade_outcomes` | `trade_memory.update_trade_outcome` | only the outcome sync joins `alpaca_trades` (has `timestamp` + `closed_at`) |
| Dimension-conditioned lessons | `src/trade_memory.py:generate_lessons`/`update_strategy_scores` | — | additive grouping on closed rows |
| Shadow gate decision | new helper in `src/trade_memory.py` (or `src/learning_loop.py`) | seams in both runtimes | single source of truth feeding veto + scale |

## Standard Stack

No new packages. Existing in-repo stack only.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| psycopg | 3.x (`psycopg` + `psycopg_pool`) | Postgres access via `src.db.connection()` | already the sole DB driver |
| pytest | (installed; `tests/`) | test suite (~230 tests) | existing convention |

**Package Legitimacy Audit:** N/A — phase installs no external packages. (slopcheck not required.)

## Architecture Patterns

### System Architecture Diagram

```
ENTRY (trade placed)
  bot_thread.py / alpaca_orchestrator.py  (long + short candidate loops)
        │  builds trade_data dict { signal_type, price_at_entry, ... }
        │  NEW: + time_of_day_bucket(entry_ts) + volatility_regime(signal.atr_value, price)
        ▼
  TradeMemory.record_trade_context(trade_data)
        │  INSERT INTO trade_context (... + time_of_day_bucket, volatility_regime)  outcome='open'
        ▼
   Postgres trade_context  (hold_minutes = NULL while open)

CLOSE (position exits) — runs each LearningLoop.run_cycle()
  LearningLoop._sync_trade_outcomes()
        │  JOIN alpaca_trades at ON tc.trade_id = at.id  (at has timestamp + closed_at)
        │  NEW: compute hold_minutes = (closed_at - timestamp) in minutes
        ▼
  TradeMemory.update_trade_outcome(trade_id, outcome, pnl[, hold_minutes])
        │  UPDATE trade_context SET outcome, pnl, hold_minutes
        ▼
  generate_lessons() / update_strategy_scores()
        │  NEW: extra additive grouping passes conditioned on dimension cols (min_sample-gated)

SHADOW GATE (every entry seam, replaces static LEARNING_ENFORCE)
  should_enforce_learning(memory, bot_id):
     if env LEARNING_ENFORCE explicitly "0" -> False (shadow)         # D-06 precedence
     closed = count closed trades for bot_id
     return closed >= LEARNING_SHADOW_UNTIL_TRADES (default 30)
        │  True  -> apply veto/scale  |  False -> log "learn_shadow: WOULD ..." and fall through
```

### Recommended structure (files touched — no new files except the migration)
```
dashboard/api/migrations/014_intraday_learning_dims.sql   # NEW
src/db_schema.sql                                          # mirror 3 ADD COLUMN IF NOT EXISTS
src/trade_memory.py     # record_trade_context INSERT +2 cols; helpers; lesson grouping; gate helper
src/learning_loop.py    # _sync_trade_outcomes computes hold_minutes; passes to update_trade_outcome
src/bot_thread.py       # entry dicts +2 fields (long+short); swap LEARNING_ENFORCE -> gate (2 seams)
src/alpaca_orchestrator.py  # same (2 seams; note one record dict at ~968 lacks bull/bear args — fine)
tests/test_learning_wiring.py / new test file
```

### Pattern 1: Additive nullable migration (matches repo convention)
**What:** numbered `NNN_*.sql`, idempotent, `ADD COLUMN IF NOT EXISTS`, NO backfill of existing rows.
**Source:** `dashboard/api/migrations/006_learning_tables.sql` (verified in session).
```sql
-- 014_intraday_learning_dims.sql  (LEARN-04)
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS time_of_day_bucket TEXT;
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS hold_minutes       DOUBLE PRECISION;
ALTER TABLE trade_context ADD COLUMN IF NOT EXISTS volatility_regime  TEXT;
CREATE INDEX IF NOT EXISTS idx_trade_context_bot_volregime ON trade_context (bot_id, volatility_regime);
CREATE INDEX IF NOT EXISTS idx_trade_context_bot_tod      ON trade_context (bot_id, time_of_day_bucket);
```
Nullable (no `NOT NULL`, no `DEFAULT`) — existing rows simply read NULL, satisfying D-01. The runner
(`run_migrations.py`) skips already-applied files via `_migrations`; multi-statement SQL is sent via
`conn.pgconn.exec_()`, so semicolon-separated statements in one file are fine.

### Pattern 2: Entry-time dimension compute (pure helpers in trade_memory)
- `time_of_day_bucket(entry_iso: str) -> str` — parse the ISO timestamp already produced at
  `record_trade_context` (`datetime.now(timezone.utc).isoformat()`), bucket by UTC hour.
  **Recommendation (Claude's discretion):** UTC session labels aligned to US equity day —
  `asia` (00–07), `eu` (07–13), `us_am` (13–17), `us_pm` (17–21), `off` (21–24). Crypto trades 24/7
  so coarse 4-buckets is acceptable too; session labels give more lesson signal. Keep it a single
  pure function so it's trivially unit-testable.
- `volatility_regime(atr: float, price: float) -> str` — `Signal.atr_value` exists (default 0.0,
  populated Phase 3/4; `technical_signals.py:465`). Use ATR-as-%-of-price:
  `r = atr/price if price>0 else 0`. **Recommended thresholds:** `low` < 0.01, `med` 0.01–0.025,
  `high` ≥ 0.025 (1% / 2.5% hourly ATR). If `atr==0` (orchestrator path may not thread atr) →
  return `"unknown"` so NULL/unknown is explicit, not a fake `low`.

### Pattern 3: Additive dimension-conditioned lessons (LEARN-05)
**What:** Add NEW grouping passes; do NOT alter existing `(signal_type, symbol)` and signal-only loops.
- In `generate_lessons()`: after the existing two passes, add a pass grouping by
  `(signal_type, time_of_day_bucket)` and/or `(signal_type, volatility_regime)`, reusing
  `_analyze_pattern` and the SAME `min_sample` gate (`len(group) < min_sample: continue`). Skip rows
  where the dimension is NULL/`unknown` (existing rows) so legacy data never forms a bogus group.
- Extend the SELECT at `trade_memory.py:230-241` to also fetch the 3 new columns.
- `update_strategy_scores()`: optionally add a dimension `GROUP BY` pass with `HAVING COUNT(*) >= 2`
  (mirrors the existing per-symbol pass at line 670). `strategy_scores` already has a `symbol` column
  but NO dimension column — if dimension scores must persist, encode into `signal_type`
  (e.g. `technical_confluence_4@us_pm`) OR add a nullable column in 014; recommend encoding to avoid
  a second schema change. **Keep additive** — existing inserts unchanged.

### Pattern 4: Count-based shadow gate (LEARN-06) — single source of truth
**What:** one helper replaces the module-level `LEARNING_ENFORCE` boolean at all four seams.
```python
# src/trade_memory.py  (closed-count is per-bot, already the table's grain)
def count_closed_trades(self) -> int:
    with connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM trade_context "
            "WHERE bot_id = %s AND outcome IN ('win','loss')",
            (self.bot_id,),
        ).fetchone()
    return row["n"]

# module-level helper (trade_memory.py or learning_loop.py)
def should_enforce_learning(memory, bot_id: str,
                            shadow_until: int | None = None) -> bool:
    raw = os.environ.get("LEARNING_ENFORCE")
    if raw == "0":                      # D-06: explicit 0 forces shadow, wins over count
        return False
    until = shadow_until if shadow_until is not None \
        else int(os.environ.get("LEARNING_SHADOW_UNTIL_TRADES", "30"))
    return memory.count_closed_trades() >= until
```
**Seam replacement (verified locations):**
- `bot_thread.py:537,539,554` (long) and `:730,732,747` (short) — replace `LEARNING_ENFORCE` with a
  per-cycle local `enforce = should_enforce_learning(memory, bot_id)` (compute ONCE per cycle, not
  per candidate — avoids N count queries; per-bot count is stable within a cycle).
- `alpaca_orchestrator.py:886,888,901` (long) and `:1033,1035,1048` (short).
- Shadow-mode log line: keep the existing `learn_veto ... enforce=%s` info logs but when `not enforce`
  emit `learn_shadow: WOULD veto/scale ×%.2f` and DO NOT `continue`/apply (mirrors existing
  `elif LEARNING_ENFORCE:` fall-through, which already no-ops on adj when shadow).

### Anti-Patterns to Avoid
- **Editing only `db_schema.sql` OR only the migration.** Both DDL paths exist; touch both (Pitfall 1).
- **`NOT NULL`/backfill on new columns.** Breaks D-01 and existing-row tolerance.
- **Per-candidate count query.** Compute the gate once per cycle.
- **Including NULL/`unknown` dimension rows in new lesson groups.** Skews legacy data into fake patterns.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Migration tracking | custom applied-file ledger | `dashboard/api/migrations/run_migrations.py` + `_migrations` | already idempotent, ordered |
| ATR computation for regime | new volatility calc | `Signal.atr_value` (Phase 3/4) | already on the signal at entry |
| Closed-trade count | new SQL table/counter | `COUNT(*) ... outcome IN ('win','loss')` on `trade_context` | grain is already per-bot |
| Hold-time source | new timestamp column on trade_context at entry | `alpaca_trades.timestamp` + `closed_at` joined in `_sync_trade_outcomes` | both already exist; D-02 mandates compute-at-close |

## Runtime State Inventory

> Refactor-adjacent (additive schema + behavior swap). Checked all 5 categories.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `trade_context` rows in prod Postgres (Coolify, one DB) — existing rows will have NULL in 3 new cols | None (nullable); lessons skip NULL dimensions |
| Live service config | `LEARNING_ENFORCE` env in Coolify per-bot container; NEW `LEARNING_SHADOW_UNTIL_TRADES` (default 30, code default — no Coolify change needed unless overriding) | Optional: document new env; no migration of existing value |
| OS-registered state | None — verified (no scheduled tasks reference these names) | None |
| Secrets/env vars | `LEARNING_ENFORCE` (existing, semantics CHANGE from static→override). `LEARNING_SHADOW_UNTIL_TRADES` (new, has code default) | Update CLAUDE.md/docs; existing `LEARNING_ENFORCE=1` still means "count-based default" |
| Build artifacts | None — pure Python, no compiled artifacts | None |

## Common Pitfalls

### Pitfall 1: Two competing `trade_context` DDLs
**What goes wrong:** `src/db_schema.sql` (lines 161-167) defines a STALE minimal `trade_context`
(`id, bot_id, timestamp, symbol, context TEXT`) that does NOT match the columns the Python actually
inserts. The LIVE schema is `dashboard/api/migrations/006_learning_tables.sql`. Adding the new columns
to only one path means either the migration-applied prod DB or the bootstrap-created dev DB is missing
them.
**Why:** `_bootstrap_schema()` in `src/db.py` runs `db_schema.sql` on every pool init (CREATE IF NOT
EXISTS, so it never overwrites the migration-built table in prod), while `run_migrations.py` applies
the numbered files. They diverged historically.
**How to avoid:** Add the 3 `ADD COLUMN IF NOT EXISTS` to BOTH `014_*.sql` AND `db_schema.sql`'s
`trade_context` section. (Consider noting the drift for a later cleanup phase — out of scope here.)
**Warning sign:** a test that inserts via `record_trade_context` against a bootstrap-only DB fails on
unknown column.

### Pitfall 2: orchestrator record dict missing fields
**What goes wrong:** `alpaca_orchestrator.py:968` builds a thinner `record_trade_context` dict (no
`bull_arguments`/`bear_arguments`) than `bot_thread.py:613`. New dimension keys must be added to ALL
record sites (bot_thread long ~613, short ~799; orchestrator long ~968, short ~1110).
**How to avoid:** grep `record_trade_context({` → 4 call sites; add the 2 entry fields to each.

### Pitfall 3: `atr_value` may be 0.0 on a path
**What goes wrong:** orchestrator path may not thread `signal.atr_value`; `atr/price` → regime `low`
falsely. **Avoid:** return `"unknown"` when `atr <= 0`; lesson grouping skips `unknown`.

### Pitfall 4: timestamp arithmetic — TEXT vs TIMESTAMPTZ
**What goes wrong:** `alpaca_trades.timestamp` and `closed_at` are stored as TEXT ISO strings
(`db_schema.sql:24,37`), not timestamptz. Subtracting in SQL needs `::timestamptz` casts (see
`get_recent_loss_symbols` precedent at `db.py:136`), OR compute in Python in `_sync_trade_outcomes`
(parse both ISO strings → `(exit-entry).total_seconds()/60`). Recommend Python compute (the loop is
already row-by-row at `learning_loop.py:108`). `_sync_trade_outcomes` SELECT must add `at.timestamp`
and `at.closed_at` (currently selects `at.id, status, pnl, exit_price`).

### Pitfall 5: not breaking the ~230 tests
**What goes wrong:** changing `update_trade_outcome` signature (adding `hold_minutes`) breaks existing
callers/tests. **Avoid:** add `hold_minutes: float | None = None` as an optional kwarg (back-compat).
Tests use `FakeTradeMemory` (conftest.py:72) with NO DB and a duck-typed `record_trade_context` /
`get_advice` / `get_dynamic_thresholds` — if the gate helper calls `memory.count_closed_trades()`,
`FakeTradeMemory` needs that method added (and the wiring tests pass `enforce` explicitly via
`_advice_consume`, so the gate can be injected as a bool — keep the seam testable without DB).

## Code Examples

### hold_minutes at close (learning_loop._sync_trade_outcomes)
```python
# SELECT must add at.timestamp AS entry_ts, at.closed_at AS exit_ts
from datetime import datetime
def _hold_minutes(entry_ts: str | None, exit_ts: str | None) -> float | None:
    if not entry_ts or not exit_ts:
        return None
    try:
        e = datetime.fromisoformat(entry_ts); x = datetime.fromisoformat(exit_ts)
        return (x - e).total_seconds() / 60.0
    except ValueError:
        return None
# in loop: self.memory.update_trade_outcome(trade_id, outcome, pnl,
#                                            hold_minutes=_hold_minutes(row["entry_ts"], row["exit_ts"]))
```

### record_trade_context INSERT extension (trade_memory.py:66-94)
Add `time_of_day_bucket, volatility_regime` to the column list and 2 more `%s` placeholders, plus
two tuple values: `time_of_day_bucket(timestamp)` and `volatility_regime(trade_data.get("atr_value", 0.0), trade_data.get("price_at_entry", 0.0))`.
Call sites pass `"atr_value": signal.atr_value` in the dict.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Static `LEARNING_ENFORCE` module bool (Phase 7) | count-based `should_enforce_learning()` gate, env as override | Phase 8 | seam becomes dynamic per-bot |
| Lessons by signal_type/symbol only | + time_of_day / volatility_regime conditioning | Phase 8 | richer intraday lessons |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Session-label time buckets (asia/eu/us_am/us_pm/off) chosen over plain UTC 4h | Pattern 2 | low — discretion; planner may pick 4h buckets |
| A2 | Vol thresholds 1% / 2.5% ATR/price | Pattern 2 | low — tunable; crypto hourly ATR varies, validate against real rows |
| A3 | `strategy_scores` dimension persistence via signal_type encoding (no extra column) | Pattern 3 | medium — if persisted dimension scores must be queryable standalone, add a nullable col in 014 instead |
| A4 | orchestrator path may not have non-zero `atr_value` | Pitfall 3 | low — handled by `"unknown"` fallback |

## Open Questions

1. **Should dimension lesson groups also veto/scale, or only inform?** Phase 7 advice path keys on
   `(symbol, signal_type)` only. Conditioning `get_advice` on live dimensions would change runtime
   behavior. CONTEXT D-04 says "lessons can be conditioned" (analysis), not that advice must use them.
   Recommendation: Phase 8 generates dimension-conditioned LESSONS (text/scores) but leaves the
   runtime advice key unchanged unless the planner explicitly scopes advice changes.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Postgres (DATABASE_URL) | all DB tests/migration | prod: Coolify; local: needs DATABASE_URL | — | unit tests use FakeTradeMemory (no DB) |
| pytest | suite | ✓ | installed | — |

**Missing with no fallback:** none for unit-level work (FakeTradeMemory). Migration apply + DB
integration tests need a reachable Postgres (`run_migrations.py` requires `DATABASE_URL`).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | none detected — flat `tests/`, `tests/conftest.py` fixtures |
| Quick run command | `python -m pytest tests/test_learning_wiring.py -x -q` |
| Full suite command | `python -m pytest tests -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LEARN-04 | `time_of_day_bucket()` buckets entry ts correctly | unit (pure) | `pytest tests/test_learning_wiring.py -k time_of_day -x` | ❌ Wave 0 |
| LEARN-04 | `volatility_regime(atr,price)` thresholds + atr=0→unknown | unit (pure) | `pytest tests/test_learning_wiring.py -k volatility_regime -x` | ❌ Wave 0 |
| LEARN-04 | record dict carries new fields (long+short, both runtimes) | unit (FakeMemory.recorded) | `pytest tests/test_learning_wiring.py -k record_dimensions -x` | ❌ Wave 0 |
| LEARN-04 | `hold_minutes` computed at close from entry/exit ISO | unit (pure `_hold_minutes`) | `pytest tests/test_learning_wiring.py -k hold_minutes -x` | ❌ Wave 0 |
| LEARN-05 | lessons can condition on a dimension; min_sample respected; NULL rows skipped | unit/integration | `pytest tests/test_learning_wiring.py -k dimension_lesson -x` | ❌ Wave 0 |
| LEARN-06 | gate log-only below threshold, enforce at/above (mock count) | unit | `pytest tests/test_learning_wiring.py -k shadow_gate -x` | ❌ Wave 0 |
| LEARN-06 | explicit `LEARNING_ENFORCE=0` forces shadow regardless of count | unit (monkeypatch env) | `pytest tests/test_learning_wiring.py -k enforce_override -x` | ❌ Wave 0 |
| LEARN-04 | migration 014 applies cleanly + tolerates existing rows | integration (DB) | `python -m pytest tests/test_db.py -k migration -x` (needs DATABASE_URL) | ❌ Wave 0 |
| regression | full suite green (~230) | suite | `python -m pytest tests -q` | ✅ existing |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_learning_wiring.py -x -q`
- **Per wave merge:** `python -m pytest tests -q`
- **Phase gate:** full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] Pure-function dimension tests (time bucket, vol regime, hold_minutes) — covers LEARN-04
- [ ] `FakeTradeMemory.count_closed_trades()` method (conftest.py) so the gate is testable without DB
- [ ] Shadow-gate tests using injected count / monkeypatched `LEARNING_ENFORCE` — covers LEARN-06
- [ ] Dimension-lesson grouping test (min_sample + NULL-skip) — covers LEARN-05
- [ ] Optional DB integration test for migration 014 (skip if no DATABASE_URL)

## Security Domain

Not applicable beyond existing posture — no new external input, auth, network, or crypto surface.
Internal trading-bot DB writes via parameterized psycopg queries (already standard; new INSERT/UPDATE
columns use `%s` placeholders — keep that, no string interpolation). No ASVS category newly triggered.

## Sources

### Primary (HIGH confidence)
- `src/db.py`, `src/db_schema.sql`, `dashboard/api/migrations/006_learning_tables.sql`,
  `dashboard/api/migrations/run_migrations.py` — read in session
- `src/trade_memory.py`, `src/learning_loop.py` — read in full
- `src/bot_thread.py` (75-104, 500-819), `src/alpaca_orchestrator.py` (grep + 960-1019 read)
- `src/technical_signals.py` (Signal fields incl. `atr_value`)
- `tests/conftest.py`, `tests/test_learning_wiring.py` — test conventions

## Metadata

**Confidence breakdown:**
- Schema/migration mechanism: HIGH — both DDL paths + runner read directly
- Wiring seams: HIGH — all 4 record sites + 4 enforce seams located by grep/read
- Bucket/threshold values: MEDIUM — discretion, tunable, flagged in Assumptions
- Lessons grouping: HIGH (additive pattern), MEDIUM on persistence approach (A3)

**Research date:** 2026-06-08
**Valid until:** stable (in-repo) — re-verify if Phase 7 seams change
