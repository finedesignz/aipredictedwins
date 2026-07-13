# Phase 18 — Profitable Retune (Confluence + Kelly) — CONTEXT

*Milestone v1.1 · captured 2026-07-12 · mode: --auto (YOLO, decisions auto-selected and LOCKED)*

## Domain

Phase 17 produced the per-symbol / per-bot evidence (TUNE-02). Phase 18 must turn it into an actual
parameter change: entry threshold (`min_confluence`), position sizing (`kelly_fraction`), and the
per-bot deny-list (`quarantined_symbols`) — retuned, backtest-validated, reversible via config.

**Requirements owned:** TUNE-01 (retune confluence + quarter-Kelly on the real dataset + backtest,
targeting win rate ≥40% and halted drawdown), TUNE-03 (validated against the existing backtest
before going live on paper; reversible via config/env).

**The uncomfortable fact this phase is built around.** 395 of the 655 position-closed rows (**60%**)
are external-exit **sentinels**: `status='closed', pnl=0.0`, fabricated at
`src/alpaca_orchestrator.py:167-176` when a position vanished from Alpaca's live set. They are not
flat trades — they are trades whose real exit was **never recorded**. `get_alpaca_accuracy`
(`src/db.py:227-229`, `losses = resolved - wins`) books every one of them as a LOSS, which is the
entire reason the dashboard shows Bot A at 12.4% while the real resolved rate is 33.0%.
The honest live sample is the **~260 rows with real P&L**, not 655.

## Grounding (from code scout)

- **The knobs are already DB-column-driven — no code change is needed to retune.**
  `src/bot_config.py:18-19,39` — `kelly_fraction` (default 0.25), `min_confluence` (default 4),
  `quarantined_symbols` (default `""`, Phase-15 UNIV-02 column, `BTC/USD` slash format).
  `from_row` (`:42-69`) rebuilds `BotConfig` from the `bots` row; BotManager swaps it atomically on
  `PUT /api/bots/{bot_id}`. So the retune is **one row update per bot**, and reverting it is the
  same update with the old values — TUNE-03's "reversible via config" is satisfied structurally.
- **Where they bite:** `src/bot_thread.py:141` (`s.confluence_score >= cfg.min_confluence`), `:157`
  (`min_short_confluence`, default 3), `:146`/`:165`/`:355` (`entry_allowed(symbol, cfg.symbols,
  cfg.quarantined)` — the Phase-15 hard gate), `:802`/`:1000` (`kelly_fraction=cfg.kelly_fraction`).
- **The backtest harness EXISTS** — `src/backtester/` (`engine.py`, `config.py`, `metrics.py`,
  `portfolio.py`, `report.py`, `cli.py`), run as `python -m src.backtester --phase 0 --train` /
  `--holdout`, with a fixture path (`--fixture-dir tests/backtester/fixtures`) and tests under
  `tests/backtester/`. It is a real bar-replay engine, not a stub:
  - `src/backtester/engine.py:124` — entry is `signal.confluence_score < config.min_confluence` →
    the SAME predicate the live bot uses.
  - `src/backtester/engine.py:28-33` — `_position_dollar_amount(confluence, kelly_fraction,
    max_position_pct)`; `capped = min(raw_kelly, max_position_pct)`.
  - `src/backtester/config.py:33-34` — `PhaseConfig.min_confluence = 3`, `kelly_fraction = 0.25`.
  - `src/backtester/metrics.py` — `win_rate`, `max_drawdown`, `sharpe_ratio`, `compute_summary`.
  **Gap:** the CLI exposes `--phase` / `--disable <flag>` only. There is **no** `--min-confluence`,
  `--kelly-fraction`, or symbol-exclusion switch, and `SYMBOLS` is hardcoded at `cli.py:27-30`.
  This is the only code the retune itself requires.
- **Phase-17 warning W1 is live:** `src/db.py:44` `get_pool()` calls `_bootstrap_schema()`, which
  executes `src/db_schema.sql` (DDL + `INSERT INTO bots ... ON CONFLICT DO NOTHING`) on FIRST pool
  creation. Any script importing `src.db` writes DDL to whatever `DATABASE_URL` names.

## Decisions (locked — auto-selected recommended defaults)

### 1. Is ~260 honest rows enough to retune on? Split verdict — and it changes the plan.

**Enough to QUARANTINE on. Not enough to set `min_confluence` or `kelly_fraction` on.** Locked:

- **Quarantine (per-symbol, from the live log).** Phase 17's `MIN_SAMPLE=5` cells with **real P&L**
  are a legitimate basis for a deny-list: a symbol that is 0-for-9 or 2-for-23 on real fills is not
  noise, and the decision it drives (stop trading it) is monotone and reversible. Sentinel rows are
  **excluded** from every cell — `symbol_stats` already excludes them (they are the `zero_pnl`
  bucket, never counted as trades).
- **min_confluence / kelly_fraction (from the BACKTEST, not the live log).** The live log **cannot**
  identify a better threshold: every row was produced at the bot's *then-current* threshold, so
  there is no counterfactual — no observations of the trades a threshold of 5 would have skipped or a
  threshold of 3 would have added. Sweeping a threshold requires replaying bars. That is exactly
  what `src/backtester/engine.py` does. **The threshold/Kelly retune is therefore derived from a
  backtester parameter sweep, cross-checked against the live per-symbol ranking — not fitted to 260
  rows.** This also makes TUNE-01's "using the real resolved-trade dataset + backtest harness" and
  TUNE-03's "validated against the existing backtest" the same artifact.
- **Consequence:** the retune is **NOT** gated behind collecting a fresh honest sample (that would
  cost months). It IS gated behind the backtest holdout passing the acceptance bar (Decision 6).

### 2. The sentinel writer is fixed IN this phase, before the retune lands.

Not deferred. The Phase-18 acceptance bar is "win rate ≥40%" — and **that number is unmeasurable
while 60% of rows carry a fabricated zero.** Shipping a retune whose success criterion cannot be
evaluated is not shipping. Scope, deliberately narrow, two edits:

- **`src/alpaca_orchestrator.py:167-176`** — an externally-exited position must be resolved from
  Alpaca (closed-position activity / last fill) into a real `exit_price` + `pnl`. If Alpaca cannot
  supply it, the row is written `status='closed', exit_price=NULL, pnl=NULL` — **never a fabricated
  `pnl=0.0`, never `exit_price=entry_price`.** NULL is honest; zero is a lie that the accuracy math
  then counts as a loss. Phases 11-14 already established `pnl IS NULL` as the "unresolved" signal
  and Phase 17 confirmed `null_pnl_total = 0` today, so NULL re-enters a channel that is already
  understood by every downstream reader.
- **`src/db.py:227-229` `get_alpaca_accuracy`** — the denominator excludes rows with `pnl IS NULL`
  (`resolved` = rows with a real P&L; `losses = resolved - wins` then means what it says). Existing
  sentinel rows are **left in place** — no backfill, no UPDATE, no DELETE on prod (they are
  historically opaque; their true exits are gone). They simply stop being counted as losses.
- Anything beyond these two edits (the `get_recent_loss_symbols` fourth status-set spelling at
  `src/db.py:201`, gross-vs-net fee attribution, the `_divergence` windowing bug W2) is **Phase 20**.

### 3. What gets retuned, and at what granularity.

| Knob | Granularity | Source of the new value |
|---|---|---|
| `min_confluence` | **per bot** (not per symbol) | backtester sweep, holdout-validated |
| `kelly_fraction` | **per bot** | backtester sweep, holdout-validated, hard-capped ≤ 0.25 |
| `quarantined_symbols` | **per bot** (per-symbol deny-list) | Phase-17 EVIDENCE.md, rule in Decision 5 |

Per-**symbol** confluence thresholds are **rejected**: 8 symbols × 4 bots × a threshold each is 32
free parameters fitted to ~260 rows — that is curve-fitting, and `BotConfig` has no per-symbol
threshold field, so it would also require new schema. The per-symbol dimension is expressed
**entirely through the quarantine list**, which is what TUNE-02 ("per-symbol informed, not uniform")
actually asks for and what Phase 15 built the column for.

### 4. Quarter-Kelly is a CEILING, and Bot B is currently in violation.

CLAUDE.md hardcodes quarter-Kelly (`kelly_fraction = 0.25`) and max 5% bankroll per position. The
sweep grid is therefore **`kelly_fraction ∈ {0.15, 0.20, 0.25}`** — it may only go DOWN. Bot B has
historically run `kelly_fraction = 0.50` (the A/B experiment); if the live `bots` row still says
0.50, Phase 18 brings it to ≤0.25. **Raising Kelly above 0.25 is out of bounds for any backtest
result, however good.** `min_confluence ∈ {3, 4, 5}` (5 = all five indicators; the engine scores
0-5). Short entries keep `min_short_confluence` untouched this phase.

### 5. Quarantine rule — mechanical, applied to Phase-17 EVIDENCE.md numbers.

**Rule (locked):** quarantine a symbol for a bot when a cell with **real P&L** meets *all* of —
`trades >= 5` (Phase-17 MIN_SAMPLE) **AND** `win_rate < 25%` **AND** `expectancy < 0`. Evaluated on
the per-(bot,symbol) table first, then on the ALL-bots roll-up (a symbol that fails the roll-up is
quarantined for **every** confluence bot, even where its per-bot cell is `insufficient`). Cells
marked `insufficient` never *trigger* a quarantine on their own. Any cell with `gross_pnl_rows > 0`
and a non-zero `sign_suspect_rows` count would be excluded — Phase 17 reports `sign_suspect_rows: 0`,
so nothing is excluded on that basis today.

Applying it to EVIDENCE.md (full-history run):

| Symbol | Evidence (ALL roll-up) | Verdict |
|---|---|---|
| **BTC/USD** | 23 trades, **8.7%** win, −1,206.90, exp −52.47 | **QUARANTINE** (in-universe; the headline change) |
| **TRUMP/USD** | 9 trades, **0.0%** win, −1,776.90 | **QUARANTINE** |
| **FIL/USD** | 13 trades, **15.4%** win, −837.74 | **QUARANTINE** |
| **ARB/USD** | 6 trades, **0.0%** win, −127.11 | **QUARANTINE** |
| **ETH/USD** | 5 trades, **0.0%** win, −59.67, exp −11.93 | **QUARANTINE** (in-universe; small money, but the rule is the rule) |
| SKY/USD | 11 trades, 36.4% win, −1,939.76 | keep-blocked by the Phase-15 allowlist (off-universe); win rate fails the <25% test → **not** quarantined on merit |
| SOL, AVAX, ADA | 30-50% win, negative expectancy | **KEEP** — the losses are exit-side (avg_loss > avg_win), not entry-side. Confluence/Kelly is the lever here, not a deny-list. |
| XRP, UNI, CRV, DOT, LINK | positive or ~flat expectancy | **KEEP** |

TRUMP / FIL / ARB / SKY are already **off-universe** and blocked by the Phase-15 hard gate; listing
them in `quarantined_symbols` is belt-and-braces, costs nothing, and is what makes the deny-list
self-documenting. The two decisions with real teeth are **BTC/USD and ETH/USD out of the
in-universe crypto set** — a bot that is 2-for-23 on BTC should not be entering BTC.

### 6. The backtest that validates it (TUNE-03), and the acceptance bar.

- **Harness:** the existing `src/backtester`. Phase 18 adds **CLI overrides only** —
  `--min-confluence N`, `--kelly-fraction F`, `--exclude-symbols "BTC/USD,ETH/USD"` (piped into a
  `PhaseConfig` field + an engine entry filter reusing `src.universe.entry_allowed`, so the backtest
  gate is *literally the same predicate* as the live gate) and `--symbols` to override the hardcoded
  `cli.py:27-30` list. **No change to signal computation, exits, portfolio math, or metrics** — the
  engine's behavior at the current defaults must be bit-identical (pinned by a test).
- **Sweep:** 3 × 3 grid (`min_confluence` × `kelly_fraction`) × {quarantine ON, OFF} on the **TRAIN**
  window (2025-10-01 → 2026-01-31), pick one candidate, then run it **ONCE** on the **HOLDOUT**
  window (2026-02-01 → 2026-04-30). Holdout is looked at once; picking on the holdout is
  overfitting and is forbidden.
- **Acceptance bar (all must hold on the HOLDOUT run):**
  1. `win_rate >= 0.40` (TUNE-01 / REQUIREMENTS).
  2. `max_drawdown` **improved vs the current-config baseline** and `< 0.20` (the hardcoded 20%
     drawdown stop — "halted drawdown").
  3. Total return / expectancy ≥ baseline (the retune may not buy the win rate by taking no trades:
     a minimum trade count ≥ 30 on the holdout is required, else the result is "no signal", not
     "pass").
  4. Results committed as `18-BACKTEST.md` (baseline vs candidate, full grid, holdout run).
- **If no grid point clears the bar:** ship the **quarantine only** (it is independently justified by
  the live evidence and does not depend on the sweep), leave `min_confluence`/`kelly_fraction` at
  their current values, and record the negative result honestly in `18-BACKTEST.md`. A failed sweep
  is a finding, not a reason to force a number through.

### 7. Rollout is a DB row update, not a deploy.

The new values land as an `UPDATE bots SET min_confluence=…, kelly_fraction=…, quarantined_symbols=…`
per bot (through the existing `PUT /api/bots/{bot_id}` path, which is what BotManager watches). The
**previous values are recorded in `18-BACKTEST.md`** so the revert is a copy-paste. Paper mode only —
the paper-only gate (50 trades / 40% win rate / equity target) is untouched and Phase 18 does **not**
unlock live trading.

### 8. Phase-17 W1 (`get_pool()` writes DDL) is closed here.

`src/db.py:38-53` — an `AIPW_DB_READONLY=1` env var makes `get_pool()` **skip `_bootstrap_schema()`**
and set `default_transaction_read_only = on` on the connection. Analysis/reporting scripts
(`scripts/symbol_report.py`, and the Phase-18 sweep if it reads prod) set it. Default (unset) keeps
today's behavior exactly, so no service changes. This is the cheapest possible fence and it makes
"read prod safely" a supported operation instead of a manual discipline. **W2** (`_divergence`
windowing + hardcoded `db_label` in `scripts/symbol_report.py`) is a reporting-cosmetics defect →
**Phase 20**, not here.

## Scope discipline (fences)

- **The hardcoded risk rules are NEVER overridden.** Max 5% bankroll per position; `kelly_fraction`
  may only move DOWN from 0.25; 20% drawdown stop; limit orders only; 50 paper trades before live.
  No backtest number can buy an exception.
- **Live trading stays paper-gated.** Phase 18 does not touch the live gate.
- **NEVER write to the prod DB from a script, and never point `src.db` at prod.** The sweep runs on
  Alpaca bars / fixtures. The only prod write in this phase is the deliberate `bots` row update via
  the dashboard API (Decision 7).
- **One Alpaca account per bot** — unchanged.
- **No new strategies, no new assets, no new indicators.** The universe only *shrinks*.
- Does NOT change exits, the risk gate, the exit advisor, learning/shadow gate, or Bot C/D/E
  strategy code.
- Does NOT backfill or delete the 395 historical sentinel rows — it stops *creating* them and stops
  *counting* them.
- Does NOT change `get_recent_loss_symbols`, fee attribution, or `symbol_report.py`'s divergence
  table — Phase 20.

## Canonical refs (MANDATORY reading for research/plan)

- `.planning/REQUIREMENTS.md` — TUNE-01, TUNE-03.
- `.planning/phases/17-per-symbol-performance/EVIDENCE.md` — **the input**. Every quarantine verdict
  must be traceable to a row in it.
- `.planning/phases/17-per-symbol-performance/VERIFICATION.md` — W1 (closed here), W2 (deferred).
- `src/bot_config.py:18-19,39,42-69,71-80` — the three knobs and `from_row` / `symbols` /
  `quarantined`.
- `src/bot_thread.py:141,157,146,165,355,802,1000` — where confluence, quarantine and Kelly bite.
- `src/universe.py` — `normalize` / `entry_allowed` (reuse in the backtester; do not re-implement).
- `src/backtester/{cli,config,engine,metrics}.py` — `cli.py:27-30` (`SYMBOLS`), `config.py:33-34`
  (`min_confluence`/`kelly_fraction`), `engine.py:28-33` (sizing), `engine.py:124` (entry gate),
  `metrics.py` (`win_rate`, `max_drawdown`).
- `src/alpaca_orchestrator.py:155-176` — the sentinel writer to fix.
- `src/db.py:38-53` (bootstrap/pool), `:227-229` (`get_alpaca_accuracy` denominator).
- `tests/backtester/*`, `tests/test_bot_config.py`, `tests/test_universe.py`,
  `tests/test_symbol_stats.py` — the fake-double / pure-function test conventions to reuse.
- CLAUDE.md — hardcoded risk rules, one-account-per-bot, never write prod without permission.

## Deferred ideas (not this phase)

- **Auto-quarantine** (a symbol crossing N-for-M gets deny-listed automatically, without a human).
  The rule in Decision 5 is deliberately applied by hand, once, with the evidence in front of it.
  Automating it before the P&L log is honest would automate the sentinel bug. Revisit post-Phase-20.
- **Per-symbol confluence thresholds / per-symbol Kelly** — needs schema, and needs far more than
  260 honest rows.
- Fixing `get_recent_loss_symbols`' status-set spelling (`src/db.py:201`), gross-vs-net fee
  attribution, `symbol_report.py` W2 — **Phase 20**.
- Backfilling the 395 historical sentinel rows from Alpaca activity history — the data may not
  survive at Alpaca; out of scope, and not needed for any Phase-18 decision.
- Re-running the retune on a fresh, sentinel-free sample once ~100 honest trades accumulate post-fix
  — that is a v1.2 milestone, and it is the run that will actually confirm or refute this one.
