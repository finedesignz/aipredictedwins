# Phase 20 — Verification & E2E Reconciliation — CONTEXT

*Milestone v1.1 (FINAL phase) · captured 2026-07-13 · mode: --auto (YOLO, decisions auto-selected and LOCKED)*

## Domain

Phases 11–19 built the machinery: order-state resolution (11), realized P&L from fills (12), the
reconciliation check (13), the backfill tool (14), the universe hard-gate (15/16), the per-symbol
evidence (17), the retune + sentinel-writer fix (18), and the watchdog + honest headline (19).
Phase 20 is the phase that asks, adversarially, **does any of it actually reconcile against real
money?**

**Requirements owned:** VERIFY-01 (unit/integration tests cover order-state resolution, realized-P&L
math *with fees*, universe rejection, and the reconciliation check) and VERIFY-02 (an end-to-end check
on live/paper data shows resolution rate and P&L reconciliation *within tolerance* after the fix).

**Not owned here:** the entry-knob retune (TUNE-01 is deliberately PARTIAL — the backtester models
exits as a flat −15%/+30% barrier while the live bot runs −8% + ATR trailing + ATR fixed stop, so the
12-cell sweep was unfalsifiable; that is **Phase 21** and Phase 20 does not touch it).

### The live fact this phase exists for

Verified against prod this session, after the Phase-19 deploy:

| Signal | Value | Reading |
|---|---|---|
| Bots A / B / C | **running, cycling** | RUN-01's watchdog holds. |
| Bot E | disabled | correct, not a fault. |
| Alert path | **delivering** (SES accepted 4 alerts within 60s of boot) | the notifier is real. |
| `reconciliation.within_tolerance` | **false on every bot** | Bot A delta **$8,720.31** · Bot B **$1,610.22** · Bot C **$2,039.64** |
| `win_rate` | **34.6%** (gate is 40%) | honest, and it now reads worse. Intended (Phase 19 Decision 3). |
| `unresolved` | **395** | the historical `pnl = 0.0` sentinels. |
| `pnl_source` | `reconciled` | the headline IS reading the reconciliation table. |
| `paper_trades_completed` | **655** | **wrong — see below.** |

The milestone's stated goal is *"the dashboard reconciles to real Alpaca equity."* Right now it does
not, by thousands of dollars, on all three live bots. **That breach is VERIFY-02's entire agenda.**

## Grounding (from code scout)

### The $8,720 delta is STRUCTURAL, not a new bug — and the arithmetic proves it

`src/reconciliation.py:16-42` (pure, cent-exact):

```
alpaca_realized_pnl = (equity - starting_equity) - unrealized_pnl
delta               = trade_log_pnl - alpaca_realized_pnl
within_tolerance    = abs(delta) <= tolerance        # default $25, RECONCILIATION_TOLERANCE_USD
```

Both sides are **all-time cumulative**. `trade_log_pnl` (`src/db.py` `get_realized_pnl`) sums the trade
log since inception; `equity - starting_equity` is Alpaca's since-inception move.

The 395 sentinel rows carry `pnl = 0.0` (`.planning/phases/17-per-symbol-performance/EVIDENCE.md`:
395/655 = **60%** of all closed rows). They contribute **exactly zero** to `trade_log_pnl`. Their *true*
P&L — whatever those positions actually made or lost on the way out — was **never recorded anywhere**,
and Alpaca's equity move already contains it. So:

> **delta ≈ the sum of the 395 unrecorded outcomes.** A positive delta of **+$8,720** on Bot A means
> the trade log claims **$8,720 more profit** than Alpaca's equity supports — i.e. those 395 exits were,
> net, ~$8,720 of **losses that were booked as zero**. It lines up exactly with the audit baseline
> (logged +$1,296 for Bot A vs a real Alpaca account down −14.34%).

**Two consequences, and they are the whole phase:**

1. The breach is **expected**, not a regression. Phase 18 fixed the *writer* (`pnl = NULL`, never
   `0.0`); Phase 19 fixed the *readers* (`RESOLVED := pnl IS NOT NULL AND pnl <> 0`,
   `src/db.py:95`). Neither could retroactively invent the P&L of an exit that was never observed.
2. It is **permanent and un-shrinkable** under the current formula. It is a fixed *level offset*
   baked into a cumulative comparison. Every future perfectly-reconciling trade adds the same amount
   to both sides and leaves the offset intact. **`abs(delta) <= $25` on the all-time window can never
   be satisfied for A/B/C — not next week, not ever — unless the 395 rows are repaired.**

**Therefore: VERIFY-02, as literally worded ("within tolerance"), is UNACHIEVABLE on the all-time
window without writing to the 395 historical rows.** Saying otherwise would be the kind of number
this milestone exists to eliminate. The honest close is stated in Decision 2.

### `paper_trades_completed` is counting things that were never trades

`dashboard/api/routes/settings.py:36` →
`SELECT COUNT(*) AS n FROM alpaca_trades WHERE bot_id IN (...)` → surfaced at `:192` as
`paper_trades_completed=total_trades`, against `models.py:183` and the 50-trade paper gate.

That `COUNT(*)` has **no status filter and no P&L filter**. It counts `submitted` rows, `rejected`
rows, canceled 0-fill entries — non-trades — alongside real closed positions. Live it reads **655**,
which is *the total row count of the table*, while the resolved population that the win-rate is
computed from (`settings.py:47`, the Phase-19 RESOLVED predicate) is ~260 and `unresolved` is 395.

**This is a gate-honesty bug and it is squarely inside VERIFY's remit.** The gate that guards live
trading ("50+ paper trades completed") is being satisfied by rows that never became positions, in
exactly the same class of error as the `100_000.0 * len(bot_ids)` hardcode Phase 19 deleted two lines
above it. Phase 20 fixes it (Decision 4).

### `src/backfill.py` — the tool that would repair the 395 rows is itself broken

`src/backfill.py:147`:

```python
live_symbols = {p["symbol"] for p in (client.get_positions() or [])}   # Alpaca → "BTCUSD"
```

and then `:71` / `:154` compare against `row["symbol"]` from `alpaca_trades` — which is **slashed**
(`"BTC/USD"`, per CLAUDE.md's SDK note). `"BTC/USD" in {"BTCUSD"}` is **False for every held
position.** The known-bug NOTE at `:70` (planted by Phase 18 as a Phase-20 item) understates it:

> **Every genuinely-held open position looks VANISHED to the backfill.** `resolve_stale_row` falls
> straight through the `unchanged` arm into the close-order hunt, and resolves a live, open, held
> position as `closed` (or `unresolvable` → `pnl = NULL`) against whatever close order it can find —
> or none. Run with `--apply`, this **corrupts open trades**.

The live monitor gets this right (`src/alpaca_orchestrator.py:151-155` normalizes *both* sides). The
backfill does not. **If a backfill is ever authorized, this bug must be fixed and tested FIRST.**
Phase 20 fixes the code and pins it with tests; Phase 20 **does not run the backfill**.

### The test suite as it stands: 488 passed / 29 skipped

`tests/` (39 files) + `dashboard/api/tests/` (6 files). Phases 11–19 already cover, genuinely:

| VERIFY-01 clause | Already covered by | Verdict |
|---|---|---|
| order-state resolution | `tests/test_order_resolution.py`, `tests/test_external_exit_resolution.py` | **covered** |
| realized-P&L math with fees | `tests/test_pnl.py`, `tests/test_close_pnl.py`, `tests/test_fee_gate.py` | **covered** |
| universe rejection | `tests/test_universe.py`, `tests/test_universe_resolution.py`, `tests/test_effective_universe.py` | **covered** |
| the reconciliation check | `tests/test_reconciliation.py` (pure `reconcile_bot`), `dashboard/api/tests/test_portfolio_win_rate.py` | **covered (unit)** |
| fences (no prod write, no risk-rule drift) | `tests/test_phase19_fences.py`, `tests/test_db_readonly.py` | **covered** |

**VERIFY-01 is therefore ~80% already satisfied.** Piling on more tests of the same units is
box-ticking. The genuine gaps — the things nothing in 11–19 asserts — are exactly four, and they are
all *seams between* modules rather than modules:

- **G1 — no end-to-end integration test.** Nothing drives submit → fill → external exit → resolved row
  → `get_realized_pnl` → `reconcile_bot` as one chain against fakes. Every link is tested; the chain is
  not. A sign error or a unit mismatch at any join survives the current suite.
- **G2 — the `paper_trades_completed` gate has no test at all.** No test asserts that a `submitted` or
  `rejected` row is excluded from it. That is why the bug shipped.
- **G3 — `src/backfill.py`'s symbol normalization is untested.** `tests/test_backfill.py` exists but
  never feeds it a slashless Alpaca `get_positions()` payload against a slashed row — the exact shape
  that makes it destroy held positions.
- **G4 — nothing tests the reconciliation *window*.** `reconcile_bot` is tested as pure arithmetic; the
  question "does this bot reconcile over the period in which the fixed code was actually running" is
  not expressible in the current codebase.

## Decisions (locked — auto-selected recommended defaults)

### 1. The E2E check is a **read-only script + a committed report**, not a test and not a route.

`scripts/e2e_verify.py` — a **SELECT-only, no-`--apply`, no-write-flag** CLI in the shape of
`scripts/symbol_report.py` (which Phase 17 already proved can be run against a prod mirror with
`SET default_transaction_read_only = on`). It prints, per bot, a machine-readable JSON block + a human
table, and exits non-zero on FAIL.

- **Not a pytest test:** it needs a live Alpaca account and a live trade log; a CI test that requires
  prod credentials is a test that gets skipped forever (the suite already carries 29 skips).
- **Not a dashboard route:** the dashboard already surfaces `reconciled` / `pnl_source` / `stale`
  (Phase 19). A second live surface is duplication.
- Its output is committed to **`.planning/phases/20-verification-e2e/20-EVIDENCE.md`**, with the same
  provenance header Phase 17's `EVIDENCE.md` carries (source, read-only proof, reproduce command).
  That file **is** VERIFY-02's deliverable.
- **`src/db.py:44` `get_pool()` calls `_bootstrap_schema()` — which runs DDL.** Phase 17 flagged this:
  *any* script importing `src.db` writes DDL to whatever `DATABASE_URL` names. `e2e_verify.py` must
  therefore run against a **prod mirror** (plain `SELECT` out, load into scratch Postgres) exactly as
  Phase 17 did — or against a connection opened read-only *without* `get_pool()`. Locked: **mirror,
  same recipe as Phase 17.** Non-negotiable; it is the difference between "read-only" and "read-only
  except for the DDL".

### 2. "Within tolerance" — LOCKED definition, and the honest verdict on VERIFY-02.

**The all-time reconciliation stays exactly as Phase 13 built it, keeps breaching, and is RELABELLED —
not silenced.**

- `RECONCILIATION_TOLERANCE_USD` stays at **$25** for the all-time row. It will read
  `within_tolerance: false` on A/B/C **forever**, and that is the correct, honest output of a system
  that lost the P&L of 395 exits. **Do not widen the tolerance to make it green.** Widening a tolerance
  until the breach disappears is the single most tempting and most dishonest move available in this
  phase, and it is banned.
- **New: an ANCHORED reconciliation window.** Additive table `reconciliation_anchor`
  (`bot_id PK, anchored_at TIMESTAMPTZ, equity NUMERIC, unrealized_pnl NUMERIC, trade_log_pnl NUMERIC`),
  written **once per bot, on first run, from a live Alpaca + trade-log read**. `T0` = Phase-20 deploy,
  which is strictly **after** the Phase-18 sentinel-writer fix — so the window contains **zero
  fabricated rows by construction.** Then:

  ```
  alpaca_realized_window = (equity_now - equity_T0) - (unrealized_now - unrealized_T0)
  trade_log_window       = trade_log_pnl_now - trade_log_pnl_T0
  delta_window           = trade_log_window - alpaca_realized_window
  tolerance_window       = max(25.0, 0.005 * abs(alpaca_realized_window))   # $25 floor, 0.5% band
  ```

  The 0.5% relative band exists because crypto fee/slippage residue scales with turnover and a flat $25
  on a growing sum is a tolerance that tightens as the sample grows — the wrong direction.
  `RECONCILIATION_TOLERANCE_PCT` (default `0.005`) makes it reversible via env, per TUNE-03's standard.
- **The legacy offset is SURFACED, never hidden.** The E2E report and the reconciliation payload carry
  an explicit `legacy_offset_usd` = the all-time delta at `T0` (Bot A ≈ $8,720 · B ≈ $1,610 · C ≈
  $2,040), labelled *"unrecoverable P&L of 395 pre-fix exits — requires an authorized backfill to
  clear."* A number that is excluded from a check must be visible next to the check, or the exclusion
  is a lie of omission.

**VERIFY-02's acceptance bar (locked):**

| Criterion | Bar |
|---|---|
| Resolution rate, post-`T0` | `resolved / (resolved + unresolved)` over rows with `timestamp >= T0` and terminal status **≥ 95%** |
| Windowed reconciliation | `abs(delta_window) <= tolerance_window` for **every enabled bot** |
| Sample sufficiency | **≥ 20 post-`T0` resolved trades per bot.** Below that the check reports **`INSUFFICIENT_SAMPLE`**, which is **not a PASS.** |
| Legacy offset | reported, per bot, with its authorization note |
| All-time reconciliation | reported as `legacy: true` — expected-breach, not a fresh failure |

**Plain answer, on the record: VERIFY-02 as originally worded — the all-time trade log reconciling to
Alpaca within tolerance — is NOT achievable without touching the 395 historical rows. It is achievable,
and honestly so, on the post-`T0` window.** The requirement will be closed as **VERIFY-02 (scoped)**
with that boundary written into `.planning/REQUIREMENTS.md` in the same "PARTIAL, and here is exactly
why" register TUNE-01 already uses — not silently ticked.

### 3. The 395 rows: NOT TOUCHED. The backfill is FIXED, TESTED, and LEFT UNARMED.

- **NO `UPDATE`. NO `DELETE`. NO `--apply`. NO backfill run.** Repairing the 395 rows is a **write to
  historical production trade data** and requires **EXPLICIT HUMAN AUTHORIZATION.** It is a
  **blocking checkpoint**, in the shape of Phase 18's held `18-07` — Phase 20 will produce a plan for
  it, and will **not execute it**, including "while we're in there."
- Phase 20 **does** fix `src/backfill.py`'s slash-mismatch (`:147` builds `live_symbols`
  slash-STRIPPED; `:71`/`:154` compare a slashed `row["symbol"]`). Normalize **both** sides with the
  same helper the monitor uses (`src/alpaca_orchestrator.py:151-155`), and pin it with G3's tests. This
  is a **prerequisite of any future authorized backfill**, not permission to run one: today, an
  `--apply` run would resolve every genuinely-held position as vanished and corrupt open trades.
- Even fixed, the backfill **cannot recover most of the 395**: Alpaca's order history has a retention
  horizon and the earliest sentinels predate it. The authorized-backfill plan must state a *recovery
  ceiling* (dry-run count of how many of the 395 Alpaca can still answer for) **before** any human is
  asked to authorize a write. The dry-run (`apply=False`, which writes nothing — `src/backfill.py:78`)
  produces exactly that count, and running it is in scope.

### 4. The `paper_trades_completed` gate bug IS fixed here.

`settings.py:36`'s `COUNT(*)` becomes the **RESOLVED** count — the same canonical predicate
`src/db.py:95` `is_resolved` already defines and that `settings.py:47` and `portfolio.py:87`/`:127`
already use:

```sql
status IN ('closed','stopped','target_hit') AND pnl IS NOT NULL AND pnl <> 0
```

- The number will drop from **655 → ~260** and the paper gate will read **worse**. **That is correct
  and it is not to be tuned back.** A gate satisfied by `submitted` and `rejected` rows is not a gate.
- The un-counted rows do not vanish: `total_rows` and `unresolved` are already on the payload
  (`settings.py:51`), so the drop is explainable on the surface that shows it.
- **Live trading stays PAPER-GATED. Making the gate honest is not the same as opening it.** Nothing in
  this phase changes the 40% win-rate target, the 50-trade minimum, the equity target, or any hardcoded
  risk rule.

### 5. VERIFY-01's coverage bar = the four seams (G1–G4), not more unit tests.

The suite is already large and the four clauses of VERIFY-01 are already covered at unit level (see
Grounding). Phase 20 adds **only** what nothing asserts today:

- **G1 — `tests/test_e2e_reconciliation.py`**: one fake-driven integration chain — submit → partial
  fill → external exit → `resolve_stale_row` → resolved row → `get_realized_pnl` → `reconcile_bot` →
  `within_tolerance` — asserting the *joins*: fee sign, long **and** short, slashed/slashless symbol
  shapes, and that a `pnl = NULL` (unresolvable) row is excluded from **both** the numerator and the
  denominator rather than booked as a loss.
- **G2 — `dashboard/api/tests/test_paper_gate.py`**: `submitted` / `rejected` / `pnl = 0.0` rows are
  **excluded** from `paper_trades_completed`; a fence asserting the bare `COUNT(*)` never returns
  (same shape as `test_routes.py:224`'s `100_000.0` absence fence).
- **G3 — `tests/test_backfill.py` extension**: slashless `get_positions()` vs slashed `row["symbol"]`
  → **`unchanged`** (held), never `closed`/`unresolvable`. Plus a fence: `backfill(apply=False)` issues
  **zero** mutating SQL.
- **G4 — `tests/test_reconciliation.py` extension**: the anchored-window arithmetic — window delta,
  the `max($25, 0.5%)` tolerance, the `INSUFFICIENT_SAMPLE` verdict, and `legacy_offset_usd`
  passthrough.
- **Plus a traceability matrix** in `20-EVIDENCE.md` mapping each VERIFY-01 clause → the test file(s)
  and case names that prove it. That matrix, not a coverage percentage, is the deliverable.

**Target: the full suite green (currently 488 passed / 29 skipped) with the new cases added, zero new
skips.** A new test that skips is a new test that does not exist.

### 6. What Phase 20 is allowed to write

| Target | Allowed? |
|---|---|
| `reconciliation_anchor` table (new, additive migration; one UPSERT per bot, once) | **Yes** |
| `reconciliation` table (existing Phase-13 UPSERT, unchanged) | **Yes** |
| `src/backfill.py` (fix the slash bug; leave it unarmed) | **Yes — code only. Do NOT run `--apply`.** |
| `dashboard/api/routes/settings.py` (`paper_trades_completed` predicate) | **Yes** |
| Tests, `scripts/e2e_verify.py`, `.planning/` | **Yes** |
| `alpaca_trades` — any `UPDATE` / `DELETE` / backfill / sentinel repair | **NO. EXPLICIT HUMAN AUTHORIZATION REQUIRED. Plan it; do not do it.** |
| `bots` config knobs (`min_confluence`, `kelly_fraction`, `quarantined_symbols`) | **NO — that is Phase 21.** |
| `RECONCILIATION_TOLERANCE_USD` widened to clear the breach | **NO. Banned outright.** |
| Coolify env / deploy config | **NO — verify and report; changing it is a separate authorized step.** |

## Scope discipline (fences)

- **NEVER write to prod trade data.** The 395 sentinels are read-around and reported, never repaired.
  Any backfill is a separate, human-authorized task with its own dry-run recovery-ceiling report.
- **The hardcoded risk rules are NEVER overridden.** Max 5% bankroll/position, quarter-Kelly ceiling,
  20% drawdown stop, limit orders only, 50 paper trades before live, max 3 correlated positions, max 10
  sims/cycle. Phase 20 touches none of them.
- **Live trading stays PAPER-GATED, and the gate may read WORSE after this phase** (655 → ~260 trades;
  34.6% win rate). **That is the intended outcome. Do not "fix" it back.**
- **Do not widen a tolerance to turn a breach green.** The breach is the finding.
- **One Alpaca account per bot** — `src/reconciliation.py:62-93` `_client_for_bot` enforces it and
  raises on a keyless bot. The anchor writer and `e2e_verify.py` use it; never a bare/shared key.
- **Do not re-open the retune.** No `min_confluence` / `kelly_fraction` / `quarantined_symbols` change
  — Phase 21, on the exit-model-faithful backtester.
- **No new strategies, assets, indicators, or bots.** No changes to entries, exits, risk gate, exit
  advisor, or the learning/shadow gate.
- **Do not roll a new notifier.** `src/notifier.py` (SES behind `alerts@emails4agents.com`) is the path,
  and it is demonstrably delivering.
- **No new test that skips.** No CI test that requires prod credentials.

## Canonical refs (MANDATORY reading for research/plan)

- `.planning/REQUIREMENTS.md` — VERIFY-01, VERIFY-02; and the **TUNE-01 PARTIAL** entry (`:40-54`) —
  the register in which VERIFY-02's scoping must be written, and the reason the retune is Phase 21.
- `.planning/phases/17-per-symbol-performance/EVIDENCE.md` — the **395/655 (60%)** sentinel figure, the
  `zero_pnl` bucket, the read-only-mirror recipe `scripts/e2e_verify.py` must copy, and the
  `_bootstrap_schema()`-writes-DDL-on-import warning (explicitly logged there as a Phase-20 item).
- `.planning/phases/18-profitable-retune/18-BACKTEST.md` + `VERIFICATION.md` — the writer fix
  (NULL-not-zero), the exit-model fidelity gap, the `order_id IS NULL` door, and **W1: the
  `src/backfill.py` slash mismatch, explicitly deferred to Phase 20**.
- `.planning/phases/19-reliable-runtime/19-CONTEXT.md` + `VERIFICATION.md` — the RESOLVED predicate,
  the five reader sites, `pnl_source` / `stale` / `unresolved`, and the two `human_needed` items
  (live UI render, real SES delivery) — **both now discharged by the live deploy** and to be recorded
  as such in `20-EVIDENCE.md`.
- `src/reconciliation.py:16-42` (pure `reconcile_bot`, the cumulative formula that produces the
  permanent offset), `:44-46` (`_tolerance`), `:62-93` (`_client_for_bot`, one account per bot),
  `:96-153` (driver + per-bot try).
- `src/backfill.py:55-80` (`resolve_stale_row`, **the `:70` NOTE and the `:71` compare**), `:100-140`
  (`_match_close`), `:147` (**`live_symbols` built slash-STRIPPED**), `:154` (the second slashed
  compare), `:78` (dry-run writes nothing).
- `src/alpaca_orchestrator.py:118` (`_UNRESOLVABLE`), `:133-134` (the `live_symbols is None` guard),
  `:151-155` (**the symbol normalization the backfill is missing**), `:233` (monitor guard).
- `dashboard/api/routes/settings.py:36` (**the bare `COUNT(*)`**), `:40-56` (the RESOLVED predicate +
  `unresolved`), `:192-195` (`paper_trades_completed`, `win_rate_target=40.0`).
- `dashboard/api/routes/portfolio.py:87`, `:127` (the other RESOLVED reader sites),
  `_reconciliation_for_bot` (`pnl_source` / `stale`).
- `src/db.py:44` (`get_pool` → `_bootstrap_schema`, **the DDL-on-import trap**), `:95` (`is_resolved`,
  canonical predicate), `get_realized_pnl`, `get_starting_equity`, `record_reconciliation`,
  `get_stale_alpaca_candidates`.
- `src/symbol_stats.py` — the `zero_pnl` bucketing everything else is aligned to.
- `dashboard/api/migrations/017_reconciliation.sql`, `019_runtime_heartbeat.sql` — the additive-migration
  shape the anchor table follows.
- `tests/test_phase19_fences.py`, `tests/test_db_readonly.py` — the fence idiom the new fences copy.
- `scripts/symbol_report.py` — the read-only CLI shape `scripts/e2e_verify.py` copies.
- CLAUDE.md — hardcoded risk rules, one-account-per-bot, paper gate, never write prod without
  permission.

## Blocking human checkpoint (surface it; do NOT act on it)

> **Backfilling / repairing the 395 historical `pnl = 0.0` rows against Alpaca activity history is a
> WRITE to production trade data and requires EXPLICIT HUMAN AUTHORIZATION.**
>
> Phase 20 will deliver, and stop at: (1) the **fixed** `src/backfill.py` (slash bug closed, tested —
> today an `--apply` run would corrupt every held position); (2) a **dry-run recovery-ceiling report**
> — how many of the 395 Alpaca can still answer for, per bot; (3) the exact `--apply` command and its
> rollback. **It will not run it.** Until it is authorized, the legacy offset stands, is reported per
> bot, and VERIFY-02 is closed on the post-`T0` window only.

## Deferred ideas (not this phase)

- **The authorized backfill itself** — see the checkpoint above. Its own task, its own authorization.
- **Fee backfill.** 643/655 rows carry `fees IS NULL` and 248 counted rows have **GROSS** P&L
  (`src/bot_c/strategy.py:393-395`, `src/trend_strategy.py:172-173`). Even a perfect sentinel repair
  leaves a fee-shaped residue in the trade log — which is part of why the windowed tolerance carries a
  relative band. Fixing the *writers* to always record fees is a follow-on.
- **Backdating `T0`.** The anchor is taken at Phase-20 deploy because that is provably post-fix.
  Backdating it to the actual Phase-18 deploy would widen the honest window, but requires an equity
  snapshot at that timestamp that may not exist. Not worth a fabricated anchor.
- **A `/api/reconciliation` route or an SSE push of reconciliation state.** The dashboard already
  carries `reconciled` / `pnl_source` / `stale` (Phase 19). Streaming is a follow-on.
- **Alerting on a *windowed* breach** (as opposed to the all-time one, which now breaches permanently
  and would alert-storm at every cooldown). The all-time breach alert should be **downgraded to a
  once-daily INFO** and the windowed breach promoted to the real alert — worth doing, needs the window
  to have a sample first.
- **Entry-knob retune (TUNE-01 completion)** — **Phase 21**, on the sentinel-free, honestly-measured
  sample this phase finally certifies.
