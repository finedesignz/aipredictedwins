# Phase 13: Alpaca Reconciliation Check - Research

**Researched:** 2026-07-10
**Domain:** P&L reconciliation (trade-log realized vs Alpaca account realized), per bot
**Confidence:** HIGH (all findings verified against real repo code)

## Summary

Phase 13 adds a per-bot reconciliation routine that compares `sum(trade-log realized pnl)` against Alpaca's derived realized P&L `(equity − starting_equity) − sum(unrealized_pnl)` and flags deltas beyond a configurable dollar tolerance. The design is fully locked in CONTEXT: a pure `src/reconciliation.py::reconcile_bot(...)` math helper (cent-exact, unit-testable, no live API), a thin driver assembling inputs from `TradeLogger`/`AlpacaClient` per bot, an env tolerance (`RECONCILIATION_TOLERANCE_USD`, default 25.0), a new idempotent migration `017_reconciliation.sql` mirrored into `src/db_schema.sql`, a persist function in `src/db.py`, a WARNING log + existing-notifier reuse on breach, and a runnable entrypoint under `scripts/`.

All infrastructure the phase needs already exists and is consistent: `get_account`/`get_positions` return the exact float fields required, `starting_equity` lives on the `bots` row (read via a trivial `SELECT`), bots are enumerated from the `bots` table, migration numbering/mechanism is established (`run_migrations.py` + `_migrations` ledger, next free = 017), and the test suite has a well-established zero-network fake-double convention (`tests/test_close_pnl.py`, `tests/test_order_resolution.py`).

**Primary recommendation:** Add a pure helper + a `db.get_realized_pnl(bot_id)` summing the SAME terminal set the rest of the codebase already treats as position-closed — `('closed','stopped','target_hit')`, NOT `'closed'` alone (see Pitfall 1 — this is the single most important finding and contradicts the CONTEXT wording). Persist via a new `reconciliation` table + `db.record_reconciliation(...)`. Reuse `notifier.send_alert(subject, body)` on breach.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Delta math (pure) | `src/reconciliation.py` | — | Cent-exact, no I/O, unit-tested |
| Trade-log realized sum | `src/db.py` (Postgres) | TradeLogger shim | All per-bot SQL lives in db.py |
| Alpaca equity/unrealized | `src/alpaca_client.py` | — | Existing `get_account`/`get_positions` |
| starting_equity read | `src/db.py` (bots row) | — | Baseline lives on bots table |
| Persist flag | `src/db.py` + migration 017 | db_schema mirror | Matches all prior additive-table work |
| Breach alert | `src/notifier.py` | `src/alerter.py` | Reuse existing SES channel |
| Entrypoint | `scripts/reconcile.py` | — | Matches `scripts/check_alpaca.py` convention |

## Standard Stack

No new packages. Everything is stdlib + already-installed deps.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| psycopg 3 | installed | Postgres access (`src/db.py` pool, `dict_row`) | Repo standard |
| alpaca-py | 0.43.2 | account/positions read | Repo standard (CLAUDE.md) |
| pytest | installed | cent-exact unit tests (`pytest.approx`) | Repo standard |

**Package Legitimacy Audit:** N/A — phase installs no external packages.

## Detailed Findings (the 8 asked questions)

### 1. Summing per-bot closed-trade realized P&L

**No existing single-purpose "sum realized pnl" function exists** — but the pattern is established twice:
- `db.get_alpaca_accuracy` (src/db.py L168) sums `pnl` over `status IN ('closed','stopped','target_hit')`.
- `equity.py::_build_db_series` (L134-143) sums `pnl` over the SAME set (`'closed','stopped','target_hit'` + `closed_at IS NOT NULL`).

**CRITICAL discrepancy with CONTEXT:** CONTEXT (lines 24-26) says sum over `status='closed'` only. That is WRONG for reconciliation — the position-monitor close path writes terminal status `closed`, `stopped`, OR `target_hit` (all carry real `pnl`; see `update_alpaca_trade` L109-113 and `test_close_pnl.py`). Summing only `'closed'` silently drops every stop-loss and take-profit exit, guaranteeing a false-positive breach on every bot. **Recommendation: sum the three-state set**, matching the two existing accessors. `canceled/rejected/expired` rows never filled → `pnl IS NULL` → excluded by the status filter anyway (and `pnl or 0` guards NULL). The planner should treat the three-state set as the correct interpretation of "position-closed"; flag the CONTEXT wording as an imprecision, not a locked contradiction.

**Exact function to ADD** (src/db.py, mirror existing style):
```
def get_realized_pnl(bot_id: str) -> float:
    with connection() as conn:
        rows = conn.execute(
            "SELECT pnl FROM alpaca_trades WHERE bot_id = %s "
            "AND status IN ('closed','stopped','target_hit')",
            (bot_id,),
        ).fetchall()
    return sum((r["pnl"] or 0.0) for r in rows)
```
Alternatively reuse `db.get_alpaca_accuracy(bot_id)["total_pnl"]` (identical set) — but a dedicated helper is cleaner and cheaper. Optionally expose on TradeLogger as `get_realized_pnl(self)`.

### 2. Reading `starting_equity` + enumerating bots

- **starting_equity accessor:** none exists in `src/db.py`; the exact read pattern is in `equity.py` L129-132:
  `SELECT starting_equity FROM bots WHERE bot_id = %s`, fallback to a default if row missing. Column defined `src/db_schema.sql` L11 (`DOUBLE PRECISION NOT NULL DEFAULT 100000.0`). Add a small `db.get_starting_equity(bot_id) -> float` (or fold into a `get_bot_row`).
- **Bot enumeration:** the live source of truth is the `bots` table. `equity.py` L178 enumerates via `SELECT bot_id FROM bots WHERE enabled = TRUE ORDER BY bot_id`. `TradeLogger.KNOWN_BOT_IDS = ("A","B","C","D")` (src/trade_logger.py L14) is the env-var validation list, NOT the enumeration source. `seed_bots.build_bots()` builds A/B/C/D rows from `ALPACA_API_KEY_{X}` env vars. **Recommendation:** enumerate from `SELECT bot_id FROM bots WHERE enabled = TRUE` (matches dashboard), reconcile each.

### 3. Alpaca realized-P&L derivation + per-bot account wiring

- Formula (CONTEXT-locked): `alpaca_realized = (equity − starting_equity) − sum(unrealized_pnl)`.
- **Field names confirmed:** `get_account()` returns `equity` (float, alpaca_client L129). `get_positions()` returns per-position `unrealized_pnl` (float, from `pos.unrealized_pl`, L152). Both already `float()`-cast — no parsing needed.
- **Per-bot account selection (the wiring gotcha):** each orchestrator SERVICE reads BARE `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` (config.py L155-157; one account per service, no A/B/C/D suffix, fail-clear on empty). A **standalone reconcile script cannot rely on bare keys** — it runs outside any single orchestrator service. Two viable per-bot key sources:
  1. **DB (recommended):** the `bots` row stores `alpaca_api_key`/`alpaca_secret_key` (migration 002_multi_bot L10-11; seeded by `seed_bots.py`). Build one `AlpacaClient` per bot from its row's keys.
  2. **Env suffix:** `ALPACA_API_KEY_{bot_id}` / `ALPACA_SECRET_KEY_{bot_id}` — the pattern `equity.py` L185-186 uses on the dashboard service.
  The driver should take `(equity, starting_equity, unrealized_pnl)` as plain inputs (pure helper stays API-free); the driver constructs an `AlpacaClient(Config(alpaca_api_key=..., alpaca_secret_key=..., alpaca_env="paper"))` per bot from source (1) or (2). Read-only Alpaca calls; paper mode (`alpaca_env != "live"`).

### 4. Migration 017 DDL + schema mirror + persist signatures

**`dashboard/api/migrations/017_reconciliation.sql`** (additive, idempotent, matches 016 header style):
```
-- 017_reconciliation.sql  (PNL-03)
-- Latest per-bot reconciliation result: trade-log realized P&L vs Alpaca-derived
-- realized P&L, with breach flag. Additive, idempotent. NOT alembic.
CREATE TABLE IF NOT EXISTS reconciliation (
    bot_id             TEXT PRIMARY KEY,
    checked_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trade_log_pnl      DOUBLE PRECISION NOT NULL,
    alpaca_realized_pnl DOUBLE PRECISION NOT NULL,
    delta              DOUBLE PRECISION NOT NULL,
    within_tolerance   BOOLEAN NOT NULL,
    tolerance          DOUBLE PRECISION NOT NULL
);
```
- **PK = bot_id** gives "latest per bot" for free via UPSERT (`ON CONFLICT (bot_id) DO UPDATE`). CONTEXT defers time-series history to a later phase → single-row-per-bot is correct.
- **Mirror in `src/db_schema.sql`:** add the identical `CREATE TABLE IF NOT EXISTS reconciliation (...)` block after section 9 (signals, L192-205), before the INDEXES banner (L207). Keep the `IF NOT EXISTS` idempotency contract stated at file top (L3). Note: `bots.id`/`alpaca_trades.bot_id` use a `CHECK (id IN ('A','B'))` in the bootstrap schema but the live DB dropped it (migration 009_drop_bot_id_check) to allow C/D — do NOT add a bot_id CHECK constraint on the reconciliation table.
- **Persist function (src/db.py):**
```
def record_reconciliation(bot_id: str, result: dict) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO reconciliation (bot_id, checked_at, trade_log_pnl, "
            "alpaca_realized_pnl, delta, within_tolerance, tolerance) "
            "VALUES (%s, NOW(), %s, %s, %s, %s, %s) "
            "ON CONFLICT (bot_id) DO UPDATE SET "
            "checked_at=EXCLUDED.checked_at, trade_log_pnl=EXCLUDED.trade_log_pnl, "
            "alpaca_realized_pnl=EXCLUDED.alpaca_realized_pnl, delta=EXCLUDED.delta, "
            "within_tolerance=EXCLUDED.within_tolerance, tolerance=EXCLUDED.tolerance",
            (bot_id, result["trade_log_pnl"], result["alpaca_realized_pnl"],
             result["delta"], result["within_tolerance"], result["tolerance"]),
        )
```
Optional TradeLogger shim: `def record_reconciliation(self, result): _db.record_reconciliation(self.bot_id, result)`.
- **Migration mechanism:** `run_migrations.py` sorts `*.sql`, skips those already in the `_migrations` ledger, runs the rest in a transaction via raw libpq exec (supports multi-statement). Just drop the file in; no code change to the runner. The bootstrap `src/db._bootstrap_schema()` also applies `db_schema.sql` on first pool use — so mirroring keeps fresh installs consistent.

### 5. Notifier/alerter function to call on breach

Reuse — do NOT invent. Two channels exist:
- **`src/notifier.py::send_alert(subject: str, body: str) -> bool`** (L42) — plain-text SES, never raises. **Simplest reuse.** Call on breach:
  `notifier.send_alert(f"Reconciliation breach: Bot {bot_id}", body_text)`.
- **`src/alerter.py::Alerter.system_error(component: str, error: str)`** (L215) — HTML, rate-limited (critical, 10-min cooldown), needs a `config`. Use if the driver already has an `Alerter`/`Config`.

**Recommendation:** use `notifier.send_alert` (no config dependency, matches a standalone script). Always emit the WARNING log first (`log.warning(...)`) then the alert; within tolerance → `log.info(...)`, no email. There is no reconciliation-specific helper — add a thin `alert_reconciliation_breach(bot_id, delta, tolerance, trade_log_pnl, alpaca_realized_pnl)` wrapper in `notifier.py` following the existing `alert_*` helper pattern (L64-128) if the planner wants a named channel.

### 6. Entrypoint shape

`scripts/` scripts are flat, `if __name__` optional, docstring-first. Closest template: **`scripts/check_alpaca.py`** (per-bot loop, prints a header block + account/positions per bot). Also `scripts/daily_audit.py`, `scripts/check_trades.py`. Convention: module docstring, top-level constants, a `main()` or bare top-level loop, print human-readable per-bot lines. **Recommendation** — `scripts/reconcile.py`:
```
"""Reconcile trade-log realized P&L vs Alpaca realized P&L per bot (PNL-03)."""
# enumerate enabled bots -> for each: get_realized_pnl, get_starting_equity,
# AlpacaClient(per-bot keys).get_account()/get_positions() ->
# reconcile_bot(...) -> record_reconciliation(...) -> print "Bot A: delta $x PASS/FAIL"
```
Run as `python scripts/reconcile.py` (or `python -m scripts.reconcile`). Read-only vs Alpaca; only writes the reconciliation row. Exit non-zero if any bot breaches (useful for cron/CI signal) — optional.

### 7. Test approach

Follow the zero-network fake-double convention (`tests/test_close_pnl.py`, `tests/test_order_resolution.py`): in-memory `FakeLogger`/`FakeAlpacaClient`, `pytest.approx(..., abs=1e-9)` for cent-exactness. Put pure-helper tests in a new `tests/test_reconciliation.py`.

**Pure `reconcile_bot` unit tests (no I/O):**
- `test_reconcile_within_tolerance` — delta just under tolerance → `within_tolerance is True`.
- `test_reconcile_over_tolerance` — delta just over tolerance → `within_tolerance is False`.
- `test_reconcile_exact_boundary` — delta == tolerance → define/assert inclusive (`abs(delta) <= tolerance`).
- `test_reconcile_negative_delta` — trade_log > alpaca (delta negative) → `abs()` used, flagged correctly.
- `test_reconcile_long_unrealized` — open long, positive unrealized → subtracted correctly from `equity − starting_equity`.
- `test_reconcile_short_unrealized` — negative unrealized → sign handled.
- `test_reconcile_zero_positions` — `sum(unrealized)==0` → realized == equity − starting_equity.
- `test_reconcile_result_shape` — dict keys `{trade_log_pnl, alpaca_realized_pnl, delta, within_tolerance, tolerance}`.

**Driver/persist tests (fakes):**
- `test_driver_assembles_inputs` — FakeLogger.get_realized_pnl + FakeAlpacaClient.get_account/get_positions → correct call into helper.
- `test_driver_persists_result` — asserts `record_reconciliation` called with the helper's dict (FakeLogger captures rows, mirror `test_close_pnl.FakeLogger`).
- `test_driver_alerts_on_breach` (`caplog` + monkeypatched `notifier.send_alert`) — breach → WARNING logged + alert fired; within tolerance → INFO, no alert.
- `test_driver_multi_bot` — two bots, one clean one breaching → independent per-bot rows.

DB-touching `record_reconciliation`/`get_realized_pnl` tests: follow `tests/test_db.py`/`test_dashboard_db.py` (they gate on a real `DATABASE_URL`); keep them optional/skippable, keep the core math tests pure.

### 8. Gotchas

- **Terminal-status set (biggest):** sum `('closed','stopped','target_hit')`, not `'closed'` — see Finding 1.
- **One-account-per-bot:** never build a single AlpacaClient and reuse across bots — each bot's realized figure must come from ITS OWN account keys (CLAUDE.md hard rule). A standalone script must source per-bot keys from the `bots` row or `_{bot_id}` env suffix, not bare `ALPACA_API_KEY`.
- **None/zero guards:** `pnl or 0.0` on every row (NULL pnl exists for unfilled terminals); guard `starting_equity` fallback if a bots row is missing; `unrealized_pnl` already float-cast but guard empty positions list.
- **Sign conventions:** `unrealized_pnl` is signed (negative for losing positions); the formula subtracts the signed sum — a losing open position INCREASES derived realized. Keep signs literal; test both long/short.
- **Tolerance semantics:** compare `abs(delta) <= tolerance`; `RECONCILIATION_TOLERANCE_USD` parsed `float(os.environ.get("RECONCILIATION_TOLERANCE_USD", "25.0"))` (matches config.py `_env` style). Absolute USD only (CONTEXT allows optional pct floor — defer unless asked).
- **Paper vs live:** paper accounts, `alpaca_env` default `paper` → `paper=True`. Fine; just don't hardcode live.
- **Unrealized noise:** `equity − starting_equity` moves continuously with open-position mark-to-market; subtracting unrealized is what isolates realized. A bot mid-trade with large open exposure will show a large raw equity delta that MUST net out — a bug in unrealized subtraction masquerades as a reconciliation breach. Cover with the long/short unrealized tests.
- **Bots enumeration source:** don't hardcode A/B — enumerate `bots WHERE enabled = TRUE` so C/D are covered.
- **Schema drift:** the bootstrap `src/db_schema.sql` `bots` table and the migration-built `bots` table differ (bootstrap has `starting_equity`+CHECK; migrations add keys/config and drop the CHECK). Mirror the reconciliation table into BOTH the migration and `db_schema.sql`, and add NO bot_id CHECK.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Realized-pnl sum | New ad-hoc SQL with a novel status set | `('closed','stopped','target_hit')` set from `get_alpaca_accuracy`/`equity.py` | Consistency; avoids Pitfall 1 |
| starting_equity read | Hardcode 100000 | `SELECT starting_equity FROM bots` (equity.py L130) | CONTEXT forbids hardcode |
| Breach email | New SES client | `notifier.send_alert` | Existing, never-raises |
| Migration apply | Manual psql | drop file in `migrations/`, `run_migrations.py` | Ledger-tracked, idempotent |
| Per-bot Alpaca client | bare env keys | per-bot `bots` row keys or `_{id}` suffix | one-account-per-bot rule |

## Common Pitfalls

### Pitfall 1: Summing only `status='closed'`
**What goes wrong:** every stop-loss (`stopped`) and take-profit (`target_hit`) realized P&L is dropped → trade_log_pnl understated → false breach on every bot.
**Why:** CONTEXT wording says `status='closed'`; the close path actually writes three terminal statuses.
**Avoid:** sum `('closed','stopped','target_hit')` — the set already used by `get_alpaca_accuracy` and `equity.py`.
**Warning sign:** every bot breaches; delta ≈ magnitude of all stop/target exits.

### Pitfall 2: Reusing one Alpaca account across bots
**What goes wrong:** both bots reconcile against the same equity → wrong per-bot realized.
**Avoid:** one AlpacaClient per bot from that bot's own keys.

### Pitfall 3: Unrealized sign error
**What goes wrong:** adding instead of subtracting unrealized (or dropping the sign) makes open positions look like realized gains/losses.
**Avoid:** literal `(equity − starting_equity) − sum(unrealized_pnl)`; test long + short.

## Runtime State Inventory

Not a rename/refactor phase — greenfield additive. One live-state note: **migration 017 must be applied to the Coolify Postgres** (via `run_migrations.py`) before the persist function runs, and `src/db_schema.sql` mirror covers fresh bootstraps. No stored-key renames, no OS state, no secrets change (`RECONCILIATION_TOLERANCE_USD` is a NEW optional env, default-safe).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Postgres (DATABASE_URL) | persist + reads | ✓ (Coolify) | — | tests skip if unset |
| Alpaca paper API | driver equity/positions | ✓ | alpaca-py 0.43.2 | pure helper tests need no API |
| psycopg 3 | db | ✓ | installed | — |
| pytest | tests | ✓ | installed | — |

No blocking gaps. Pure helper + math tests run with zero external deps.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | pytest via `tests/conftest.py` |
| Quick run | `pytest tests/test_reconciliation.py -x` |
| Full suite | `pytest -q` |

### Phase Requirements → Test Map
| Req | Behavior | Type | Command | Exists? |
|-----|----------|------|---------|---------|
| PNL-03 | delta within/over tolerance | unit | `pytest tests/test_reconciliation.py -x` | ❌ Wave 0 |
| PNL-03 | breach logs WARNING + alerts | unit | `pytest tests/test_reconciliation.py -k breach` | ❌ Wave 0 |
| PNL-03 | result persisted per bot | unit(fake)/db | `pytest tests/test_reconciliation.py -k persist` | ❌ Wave 0 |

### Sampling Rate
- Per task commit: `pytest tests/test_reconciliation.py -x`
- Per wave merge: `pytest -q`
- Phase gate: full suite green + `python scripts/reconcile.py` prints per-bot pass/fail against the two paper accounts.

### Wave 0 Gaps
- [ ] `tests/test_reconciliation.py` — pure helper + driver/persist/alert cases (PNL-03)
- [ ] No framework install needed.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Correct terminal set is `('closed','stopped','target_hit')`, overriding CONTEXT's `'closed'` | Finding 1 | If truly `'closed'`-only, helper over-counts; but two existing accessors + close path confirm the three-state set. Planner should confirm the interpretation. |
| A2 | Standalone script sources per-bot keys from `bots` row or `_{id}` env suffix | Finding 3 | If neither populated in the run env, driver can't reach the right account — verify keys present before Alpaca calls. |
| A3 | Single-row-per-bot (`bot_id` PK) satisfies "latest per bot" | Finding 4 | CONTEXT defers history explicitly, so low risk. |

## Sources

### Primary (HIGH — repo code, this session)
- `src/alpaca_client.py` L122-157 — `get_account` (`equity`), `get_positions` (`unrealized_pnl`).
- `src/db.py` L101-198 — `update_alpaca_trade` terminal states, `get_alpaca_accuracy` status set.
- `dashboard/api/routes/equity.py` L127-189 — starting_equity read, realized-pnl status set, bot enumeration, per-bot key env pattern.
- `src/db_schema.sql` L8-15, L192-241 — bots table, mirror location, seed/CHECK notes.
- `dashboard/api/migrations/{002,016}*.sql`, `run_migrations.py` — numbering, additive style, apply mechanism.
- `src/notifier.py` L42-128, `src/alerter.py` L54-230 — reuse channels.
- `src/trade_logger.py` L14-53, `dashboard/api/seed_bots.py` — KNOWN_BOT_IDS, per-bot build.
- `scripts/check_alpaca.py`, `tests/test_close_pnl.py` — entrypoint + test conventions.
- `.planning/phases/13-alpaca-reconciliation-check/13-CONTEXT.md` — locked decisions.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps, all verified.
- Architecture/wiring: HIGH — every field/function read from source.
- Terminal-status finding: HIGH — corroborated by two accessors + close path + a passing test.
- Per-bot key sourcing for standalone script: MEDIUM — two valid paths exist; runtime env presence should be confirmed by planner.

**Research date:** 2026-07-10
**Valid until:** ~2026-08-10 (stable internal code)
