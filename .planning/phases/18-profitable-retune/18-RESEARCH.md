# Phase 18: Profitable Retune (Confluence + Kelly) — Research

**Researched:** 2026-07-12
**Domain:** Trading-strategy parameter retune (entry threshold + position sizing + per-symbol deny-list), backtest validation, P&L-truthfulness repair
**Confidence:** HIGH (every claim below re-read at file:line this session; three CONTEXT claims are CORRECTED)
**Requirements owned:** TUNE-01, TUNE-03

---

## ⚠ CORRECTIONS — three claims in `18-CONTEXT.md` are FALSE

The Phase-17 researcher shipped two confidently-stated falsehoods and the plan-checker caught them.
This section exists so Phase 18 does not repeat that. Each correction below was verified by reading
the code this session, and two of them **change the plan**.

### C1 — "the engine scores 0-5" / `min_confluence ∈ {3, 4, 5}` — **FALSE**

`18-CONTEXT.md` Decision 4 states: *"`min_confluence ∈ {3, 4, 5}` (5 = all five indicators; the
engine scores 0-5)."*

**The confluence score is 0–4. It is structurally impossible for it to reach 5.**

`src/technical_signals.py:361` — the comment on the block says it outright: `# --- Confluence Score
(max 4, regime-aware) ---`. The scoring is a two-branch if/else and **each branch contains exactly
four `score += 1` statements**:

- trending branch (`:371-386`): EMA (`:373`), ADX (`:376`), RSI band (`:380`), VWAP (`:383`) — 4.
- ranging/mixed branch (`:387-404`): EMA (`:391`), ADX (`:394`), RSI (`:399`), VWAP (`:403`) — 4.
- `src/technical_signals.py:405-406` explicitly documents the fifth indicator's removal:
  *"Volume spike intentionally excluded: QC: VolSpike=True trades went 0-for-17."*

Corroborating evidence, all independent:
- `src/technical_signals.py:40` — the dataclass field comment: `confluence_score: int  # 0-4`.
- `src/bot_thread.py:813` — the live entry log string is literally `confluence=%d/4`.
- Empirical: running `analyze()` across the 60-bar `tests/backtester/fixtures/BTC_USD.json`
  produces the histogram `{2: 7, 3: 3}` — max observed 3, and 4 is the ceiling by construction.

**Consequences (both must be carried into the plan):**

1. **The `min_confluence = 5` row of the sweep grid is provably vacuous — it yields ZERO entries,
   on every symbol, in every window, at every Kelly value.** The engine's entry gate
   (`src/backtester/engine.py:124`) is `signal.confluence_score < self.config.min_confluence →
   continue`; with a score ceiling of 4, `min_confluence=5` skips every bar. The 3×3×2 grid is
   therefore an effective **2×3×2 = 12 live cells + 6 provably-empty cells**.
   **Recommendation (does not relitigate the lock):** still *run* the six `min_confluence=5` cells,
   and record them in `18-BACKTEST.md` as `trades=0 → auto-fail on acceptance criterion 3
   (min 30 trades)`. That is honest, costs one loop iteration, and documents *why* the grid point is
   dead rather than silently dropping it. Do **not** "fix" the score to reach 5 — that would be a
   new strategy, which the phase fences forbid.
2. **`_KELLY_PROBS[5] = 0.65` (`src/backtester/engine.py:25`) and `win_prob_map[5] = 0.65`
   (`src/alpaca_orchestrator.py:434`) are dead entries** in both the backtester and the live sizer.
   The live comment at `:433` (`# 3/5 = 55%, 4/5 = 60%, 5/5 = 65%`) is stale. Leave them alone —
   they are harmless and touching them is out of scope — but do not reason from them.

### C2 — "`engine.py:124` … the SAME predicate the live bot uses" — **FALSE, and it is the most important finding in this document**

`18-CONTEXT.md` Grounding says: *"`src/backtester/engine.py:124` — entry is
`signal.confluence_score < config.min_confluence` → the SAME predicate the live bot uses."*

It is not. The live long-entry predicate is a **seven-way conjunction**; the backtester's is a
**one-way test plus a no-duplicate-position check**. Side by side:

| # | Live predicate (`src/bot_thread.py:139-149`, `select_long_candidates`) | Present in `BacktestEngine`? |
|---|---|---|
| 1 | `s.confluence_score >= cfg.min_confluence` (`:141`) | **YES** — `engine.py:124` |
| 2 | `s.symbol not in open_symbols` (`:142`) | **YES** — `engine.py:108` (`open_trade_ids`) |
| 3 | `s.symbol not in recent_loss_symbols` (`:143`) — the loss-cooldown (`db.get_recent_loss_symbols`) | **NO** |
| 4 | `s.symbol not in MEME_CRYPTO` (`:144`) | **NO** (moot — no memes in `cli.SYMBOLS`) |
| 5 | `s.symbol not in _ALPACA_UNTRADEABLE` (`:145`) | **NO** (moot — same) |
| 6 | `entry_allowed(s.symbol, cfg.symbols, cfg.quarantined)[0]` (`:146`) — **the Phase-15 allowlist + quarantine gate** | **NO** |
| 7 | `s.rsi_value < cfg.rsi_ceiling` (`:147`, default `65.0`) | **NO** |
| 8 | `getattr(s, "trend_4h", "unknown") != "bearish"` (`:148`) | **NO** — and see below |

Three further structural divergences:

- **The engine never computes `trend_4h`.** `engine.py:119` calls `analyze(sym, bars_window)` with
  `bars_4h` defaulting to `None` (`src/technical_signals.py:268`), so `trend_4h` is *always*
  `"unknown"` (`:425-426` requires ≥21 4H bars). The live scan passes `fetch_4h=True`
  (`src/bot_thread.py:623`). The backtester therefore takes trades the live bot rejects as
  4H-bearish.
- **The engine has no short side at all.** Live runs `select_short_candidates`
  (`src/bot_thread.py:152-167`) with `short_enabled` defaulting `True` and `min_short_confluence=3`
  (`src/bot_config.py:29`). Every short trade the live bot takes is invisible to the backtest.
- **The engine's exits are hard-thresholds only** (`engine.py:99-104`, `HARD_STOP_PCT` /
  `HARD_TAKE_PROFIT_PCT` from `src/exit_advisor.py`). Live additionally runs soft stops, the
  trailing stop (`src/alpaca_orchestrator.py:131`), and the MiroFish exit advisor.

**This matters because TUNE-03 says "validated against the existing backtest." A backtest that
validates a strategy the bot does not run validates nothing.** The Phase-17 evidence explicitly
found that the SOL/AVAX/ADA losses are *exit-side* (`avg_loss > avg_win`) — precisely the dimension
the engine models least faithfully.

**Recommendation — close the gap that the phase's own knobs live on, and declare the rest:**

- **MUST close (they are the knobs under test — leaving them out makes the sweep measure the wrong
  thing):**
  - **(6) `entry_allowed`** — CONTEXT Decision 6 already requires this ("reusing
    `src.universe.entry_allowed`, so the backtest gate is *literally the same predicate* as the live
    gate"). Correct and non-negotiable: **the quarantine arm of the sweep is meaningless without
    it.** Add `symbols: tuple[str, ...]` + `quarantined: tuple[str, ...]` to `PhaseConfig` and call
    `entry_allowed(sym, self.config.symbols, self.config.quarantined)[0]` in the engine's scan loop.
    Do NOT re-implement the gate — `src/universe.py:26` is pure, total, and already exhaustively
    tested (`tests/test_universe.py`).
  - **(7) `rsi_ceiling`** — this one is load-bearing and CONTEXT misses it. RSI interacts with
    confluence *directly*: `rsi_above_ceiling` already suppresses the RSI point inside the score
    (`src/technical_signals.py:380`, `:399`), and the live bot then *additionally* rejects the whole
    signal if `rsi_value >= cfg.rsi_ceiling`. Without it, the backtester enters overbought setups
    the live bot refuses — inflating trade count at exactly the confluence levels being swept. Add
    `rsi_ceiling: float = 65.0` to `PhaseConfig` and the guard to the engine.
- **MUST declare, do NOT close (out of scope; closing them is a new strategy model, not a retune):**
  the loss-cooldown (3), the 4H trend filter (8), the short side, and the soft/trailing/advisor exit
  stack. **`18-BACKTEST.md` must carry an explicit "Fidelity gap" section listing these four**, so
  the holdout number is read as *"the long-only, hard-exit lower bound"* and not as a promise about
  live P&L. This is the single most important honesty guardrail in the phase.

### C3 — "`get_alpaca_accuracy` … is the entire reason the dashboard shows Bot A at 12.4%" — **FALSE**

`18-CONTEXT.md` Decision 2 scopes the accuracy fix to **two** edits and asserts that fixing
`src/db.py:227-229` is what un-breaks the dashboard headline.

**The dashboard does not call `get_alpaca_accuracy`.** Verified by grep across the whole repo — the
only callers are `src/trade_logger.py:53` (a shim), `src/alpaca_orchestrator.py:577` and `:1254`
(bot-side logging), and `scripts/symbol_report.py:269` (the Phase-17 divergence table). The
dashboard API has its **own duplicated win-rate SQL, in two places**:

| Site | Query | Arithmetic |
|---|---|---|
| `dashboard/api/routes/portfolio.py:64-76` | `SELECT pnl … WHERE status IN ('closed','stopped','target_hit')` | `wins = sum(1 for r if (r["pnl"] or 0) > 0)`; `losses = len(closed) - wins`; `win_rate_pct = wins/resolved*100` |
| `dashboard/api/routes/settings.py:37-42, 58-61` | same status set, all bots | identical arithmetic (`:59-61`) |

Both reproduce the exact bug: `(r["pnl"] or 0) > 0` maps a `NULL` **and** a `0.0` to "not a win",
and `losses = resolved - wins` then books both as **losses**. **Fixing `src/db.py` alone leaves the
dashboard headline at 12.4%** — i.e. it fails Decision 2's own stated purpose ("the Phase-18
acceptance bar is unmeasurable while 60% of rows carry a fabricated zero").

**Recommendation:** the accuracy fix is **three** write-sites, not two — `src/db.py:211-229`,
`dashboard/api/routes/portfolio.py:64-76`, `dashboard/api/routes/settings.py:37-61`. All three take
the identical one-line change (`AND pnl IS NOT NULL` in the WHERE clause). This is a strict, minimal
extension of the locked decision's *intent*, not a relitigation of it: Decision 2 locks *"the
denominator excludes rows with `pnl IS NULL`"* — it simply mis-identified where the denominator
lives. Note the new NULL rows the Phase-18 sentinel fix starts writing will otherwise land straight
back in the dashboard's loss column, making the retune's own success criterion unreadable.

---

## Summary

Phase 18 is three separable pieces of work with one dependency edge between them.

**Piece 1 — make the win rate measurable (must land first).** The sentinel writer at
`src/alpaca_orchestrator.py:165-176` fabricates `status="closed", exit_price=entry_price, pnl=0.0`
for any DB-open trade that has vanished from Alpaca's live position set. 395 of 655 position-closed
rows (60%) are these. The repair does **not** need new logic: Phases 11–14 already built and tested
the exact resolver — `src/backfill.py:51 resolve_stale_row` (pure), `src/backfill.py:92 _match_close`
(pure), `src/pnl.py:10 realized_pnl` (pure), `src/order_resolution.py:14 classify_order` (pure), and
the two Alpaca wrappers they consume, `AlpacaClient.get_order` (`src/alpaca_client.py:401`) and
`AlpacaClient.get_closed_orders(symbol, after=…)` (`:419`). The monitor's trade row comes from
`SELECT *` (`src/db.py:125-130`), so it already carries `order_id`, `filled_qty`, `filled_avg_price`
— every input the resolver needs. The one genuinely new behavior is the *unresolvable* branch:
`backfill` leaves such a row `open` (`:74`), but the monitor must terminate it as
`status='closed', exit_price=NULL, pnl=NULL` so it stops re-alerting — and `update_alpaca_trade`
(`src/db.py:101-122`) already accepts `exit_price=None, pnl=None` and already stamps `closed_at` for
`'closed'`. Then the three duplicated win-rate denominators (C3) exclude `pnl IS NULL`.

**Piece 2 — the sweep.** The backtester (`src/backtester/`) is a real bar-replay engine, not a stub,
and its **sizing math is bit-for-bit identical to live** (verified below — this is the one CONTEXT
claim about the engine that holds). What it needs is CLI/config surface (`--min-confluence`,
`--kelly-fraction`, `--exclude-symbols`, `--symbols`) plus the two fidelity fixes from C2
(`entry_allowed`, `rsi_ceiling`). The grid is 2 live × 3 × 2 = 12 meaningful cells (+6 provably
empty, per C1) on TRAIN, one candidate, one HOLDOUT run.

**Piece 3 — the rollout.** Genuinely config-only, exactly as CONTEXT says. All three knobs are real
columns on `bots` (migrations `002_multi_bot.sql`, `018_universe_quarantine.sql`), all three are on
the `BotUpdate` model (`dashboard/api/models.py:258, 259, 276`), and `PUT /api/bots/{bot_id}`
(`dashboard/api/routes/bots.py:184-212`) builds its `SET` clause dynamically from whichever fields
are non-`None` and then calls `mgr.update(bot_id, updates)` to hot-swap the live `BotConfig`. **Zero
code change is required to apply or revert the retune.**

**Primary recommendation:** land Piece 1 (three-site accuracy fix + resolver-backed sentinel writer)
and the two engine-fidelity fixes **before** running a single grid cell — a sweep validated against
a drifted engine, scored by a win rate that counts fabricated zeros as losses, is a number that
means nothing.

---

## User Constraints (from 18-CONTEXT.md)

### Locked Decisions

1. **Quarantine from the live log; `min_confluence`/`kelly_fraction` from the BACKTEST.** The live
   log has no counterfactual for an unchosen threshold. The retune is NOT gated behind collecting a
   fresh sample; it IS gated behind the holdout acceptance bar.
2. **The sentinel writer is fixed IN this phase, before the retune lands.** Two edits (per CONTEXT;
   see C3 — it is three): `src/alpaca_orchestrator.py:167-176` must resolve the real exit from
   Alpaca or write `pnl=NULL` — **never a fabricated `0.0`, never `exit_price=entry_price`**; and
   the accuracy denominator excludes `pnl IS NULL`. **Historical sentinel rows are left in place —
   no backfill, no UPDATE, no DELETE on prod.**
3. **Granularity:** `min_confluence` per bot; `kelly_fraction` per bot; `quarantined_symbols` per
   bot. Per-symbol thresholds are **rejected** (32 free params on ~260 rows = curve-fitting).
4. **Quarter-Kelly is a CEILING.** Grid `kelly_fraction ∈ {0.15, 0.20, 0.25}` — **it may only go
   DOWN**. Bot B at 0.50 comes to ≤0.25. `min_confluence ∈ {3, 4, 5}`. `min_short_confluence`
   untouched.
5. **Quarantine rule (mechanical):** real-P&L cell with `trades >= 5` AND `win_rate < 25%` AND
   `expectancy < 0`. Per-(bot,symbol) first, then the ALL-bots roll-up. `insufficient` cells never
   trigger. → **QUARANTINE: BTC/USD, ETH/USD, TRUMP/USD, FIL/USD, ARB/USD.** KEEP: SOL, AVAX, ADA
   (exit-side losses), XRP, UNI, CRV, DOT, LINK.
6. **Backtest + acceptance bar.** CLI overrides only; no change to signal computation, exits,
   portfolio math, or metrics; engine behavior at current defaults must be **bit-identical** (pinned
   by a test). 3×3 grid × {quarantine ON, OFF} on TRAIN (2025-10-01 → 2026-01-31); ONE candidate;
   ONE HOLDOUT run (2026-02-01 → 2026-04-30). **Picking on the holdout is forbidden.** Bar (all on
   HOLDOUT): `win_rate >= 0.40`; `max_drawdown` improved vs baseline AND `< 0.20`; return/expectancy
   ≥ baseline AND **trade count ≥ 30**; results in `18-BACKTEST.md`.
   **If no grid point clears the bar: ship the quarantine ONLY**, leave the two knobs at current
   values, record the negative result honestly.
7. **Rollout is a DB row update, not a deploy** — via `PUT /api/bots/{bot_id}`. Previous values
   recorded in `18-BACKTEST.md` so revert is copy-paste. **Paper mode only.**
8. **`AIPW_DB_READONLY=1`** makes `get_pool()` skip `_bootstrap_schema()` and set
   `default_transaction_read_only = on`. Default (unset) = today's behavior exactly.

### Claude's Discretion

- The exact shape of the engine/CLI plumbing for the new knobs (dataclass fields vs. kwargs).
- How the sweep driver is structured (a script vs. a shell loop) — provided it is reproducible.
- The precise `PhaseConfig` field names.

### Deferred Ideas (OUT OF SCOPE)

- Auto-quarantine. Per-symbol confluence/Kelly. `get_recent_loss_symbols`' fourth status-set
  spelling (`src/db.py:198`). Gross-vs-net fee attribution. `symbol_report.py` W2 divergence
  windowing. **All → Phase 20.**
- Backfilling the 395 historical sentinel rows from Alpaca history.
- Re-running the retune on a fresh sentinel-free sample → v1.2.

---

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **TUNE-01** | Retune confluence + quarter-Kelly on the real dataset + backtest, targeting win rate ≥40% and halted drawdown | §2 (engine + CLI knobs), §3 (sweep grid — but see **C1**: the `mc=5` row is vacuous), §1 (the win rate is **unmeasurable** until the sentinel fix lands — see **C3**: three sites, not two) |
| **TUNE-03** | Validated against the existing backtest before going live on paper; reversible via config/env | §2 (the backtester exists and is real), **C2** (it has drifted from live — two gaps MUST be closed or the validation is void; four more MUST be declared), §4 (rollout + revert are pure `PUT /api/bots/{bot_id}`, zero code) |

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Entry gate (confluence / allowlist / quarantine) | Pure predicate (`src/universe.py`, `src/bot_thread.py` selectors) | — | Already pure + tested; the backtester must **import** it, never re-implement |
| Sizing (Kelly) | Pure function (`_kelly_technical`, `_position_dollar_amount`) | — | Both already pure; verified equivalent (§2.3) |
| Exit resolution from Alpaca | Pure resolver (`src/backfill.py`) + I/O wrapper (`src/alpaca_client.py`) | Monitor loop (`src/alpaca_orchestrator.py`) | The monitor should **orchestrate**, not compute — the compute already exists and is tested |
| Win-rate arithmetic | DB layer (`src/db.py`) + **dashboard routes** (duplicated!) | — | C3: three denominators, one bug, three identical fixes |
| Parameter storage / hot-swap | `bots` table + `PUT /api/bots/{bot_id}` → `BotManager.update` | — | Config-only rollout; **no deploy, no code** |
| Backtest replay | `src/backtester/engine.py` | `portfolio.py`, `metrics.py` | Owns the counterfactual the live log cannot provide |

---

## 1. The sentinel writer — DON'T HAND-ROLL IT, the resolver already exists

### 1.1 What is there now

`src/alpaca_orchestrator.py:148-180` (`PositionMonitor._check_all_positions`). It fetches DB-open
trades (`:150`), fetches live Alpaca positions (`:158`), builds `live_symbols` (`:159`), and then:

```python
# src/alpaca_orchestrator.py:165-176  — THE BUG
if live_symbols is not None:
    for trade in open_trades:
        sym = trade.get("symbol", "")
        alpaca_sym = sym.replace("/", "")
        if alpaca_sym and alpaca_sym not in live_symbols:
            log.info("[MONITOR] %s not in Alpaca positions — marking closed (externally exited)", sym)
            self.logger.update_alpaca_trade(
                trade_id=trade["id"],
                status="closed",
                exit_price=trade.get("entry_price", 0),   # ← a LIE: exit == entry
                pnl=0.0,                                   # ← a LIE: fabricated flat
            )
```

`exit_price=entry_price` and `pnl=0.0` are both **fabrications**. The position was closed at *some*
price; the monitor simply never asked.

**Verified: this is the ONLY sentinel writer in the codebase.** `src/bot_thread.py` has no
equivalent reconcile block (its four `update_alpaca_trade` calls at `:309, :317, :332, :338` are the
Phase-11 order-lifecycle resolver, which correctly writes `pnl=0` only for *terminal non-position*
orders — rejected/canceled/expired with zero fill, where `pnl=0` is **true**, not fabricated). So
the fix has exactly one site.

### 1.2 The resolver that already exists (all pure, all tested)

| Function | File:line | Contract |
|---|---|---|
| `classify_order(order)` | `src/order_resolution.py:14` | `→ (db_status, pnl)`. `filled`/`filled_qty>0` → `("open", None)`; terminal 0-fill → `(status, 0)`; in-flight → `(None, None)` |
| `_match_close(closes, entry_order, row)` | `src/backfill.py:92` | Picks the **single** closing order: opposite side, `filled_qty>0`, `filled_at` strictly after entry, **earliest**, qty within `_QTY_TOLERANCE`. Ambiguous/partial → `None` |
| `realized_pnl(side, entry_fill, exit_fill, qty, taker_fee)` | `src/pnl.py:10` | Side-aware, **net of taker fee on BOTH legs**. Single source of truth |
| `resolve_stale_row(row, entry_order, live_symbols, close_order)` | `src/backfill.py:51` | `→ (outcome, write_kwargs\|None)`, outcome ∈ `"resolved" \| "unchanged" \| "unresolvable"` |

`resolve_stale_row`'s branches (`src/backfill.py:62-89`) map **exactly** onto what the monitor needs:

- entry canceled/rejected/expired, 0 fill → `("resolved", {status, exit_price=None, pnl=0, fees=None})`
- filled **and** symbol in `live_symbols` → `("unchanged", None)` — genuinely still held
- filled, gone, `close_order` present, `filled_avg_price > 0` → `("resolved", {status:"closed",
  exit_price: exit_fill, pnl: realized, fees})` ← **the real exit**
- filled, gone, `close_order is None` (or exit fill ≤ 0) → **`("unresolvable", None)`**
- in-flight → `("unchanged", None)`

### 1.3 The Alpaca API surface — already wrapped, nothing new to add

- `AlpacaClient.get_order(order_id)` → `src/alpaca_client.py:401` (`get_order_by_id`).
- `AlpacaClient.get_closed_orders(symbol, after=None)` → `src/alpaca_client.py:419-442`. Built in
  **Phase 14 for exactly this purpose** (docstring `:420`: *"Phase-14 closing-order lookup"*).
  `GetOrdersRequest(status=QueryOrderStatus.CLOSED, symbols=[symbol], limit=500, direction="desc")`,
  slash **preserved**, `after` bounds the window to post-entry orders.
- `_parse_order` (`src/alpaca_client.py:447-464`) already normalizes `filled_qty`,
  `filled_avg_price`, `side`, `status`, `filled_at` — every field the resolver reads.

**There is no need for the Alpaca "closed positions" or "account activities" endpoint.** The
order-history path is already wrapped, already tested, and already the project's chosen mechanism.
Adding an activities wrapper would be a second source of truth for the same fact.

### 1.4 The row has the inputs

`get_open_alpaca_positions` (`src/db.py:125-130`) is `SELECT *`, and `alpaca_trades` carries the
Phase-11/12 columns (`src/db_schema.sql:44-49`): `order_id`, `order_type`, `filled_qty`,
`filled_avg_price`, `fees`. So `trade["order_id"]` is available inside the monitor loop **today**.

### 1.5 The one new behavior — the `unresolvable` branch

`backfill` (a batch repair script) leaves an unresolvable row **`open`** so a later run can retry.
The **monitor** cannot: leaving it open means it keeps re-alerting forever about a position that no
longer exists — which is the original reason the sentinel was written.

**Locked target (CONTEXT Decision 2):** `status='closed', exit_price=NULL, pnl=NULL`.

`update_alpaca_trade` (`src/db.py:101-122`) supports this with **no change**: `exit_price` and `pnl`
are `float | None = None` (`:105-106`), the UPDATE writes them straight through (`:118`), and
`closed_at` is stamped because `'closed'` is in the terminal set (`:111`). NULL is an *already
understood* signal — Phases 11–14 established `pnl IS NULL` as "unresolved", and Phase 17 confirmed
`null_pnl_total = 0` today, so the channel is clean.

### 1.6 Recommended shape

Put the orchestration in a **pure, testable function** (mirroring `backfill.backfill`'s split), so
the monitor stays a thin loop and the decision is unit-testable with fake doubles:

```python
# src/alpaca_orchestrator.py — replaces the :165-176 block
def _resolve_external_exit(alpaca, row, live_symbols) -> dict:
    """Resolve a vanished position to a REAL exit, or to NULL. Never fabricates."""
    from src.backfill import resolve_stale_row, _match_close
    entry_order = alpaca.get_order(row["order_id"]) if row.get("order_id") else None
    if entry_order is None:
        return {"status": "closed", "exit_price": None, "pnl": None, "fees": None}
    closes = alpaca.get_closed_orders(row["symbol"], after=entry_order.get("filled_at"))
    close_order = _match_close(closes, entry_order, row)
    outcome, kw = resolve_stale_row(row, entry_order, live_symbols, close_order)
    if outcome == "resolved":
        return kw
    if outcome == "unchanged":
        return {}                      # still held / in-flight — do NOT write
    return {"status": "closed", "exit_price": None, "pnl": None, "fees": None}  # unresolvable
```

Note `live_symbols` in the monitor is slash-**stripped** (`"BTCUSD"`, `:159`) while
`resolve_stale_row` compares `row["symbol"]` (`"BTC/USD"`) against it (`src/backfill.py:71`).
**This is a live mismatch and a real trap** — pass the resolver a slash-normalized set (or use
`src.universe.normalize` on both sides). Getting this wrong makes every held position look vanished.

**Every Alpaca call must be wrapped in try/except.** An API failure must yield `{}` (leave the row
open, retry next cycle) — *never* a NULL write, and *never* a fabricated close. Silently converting
a transient 500 into a terminal `closed/NULL` row would be a new, quieter version of the same bug.

---

## 2. The backtester — what exists, what must be added

### 2.1 Current surface (all re-read this session)

| File | Fact |
|---|---|
| `src/backtester/cli.py:22-25` | `TRAIN_START=2025-10-01`, `TRAIN_END=2026-01-31`, `HOLDOUT_START=2026-02-01`, `HOLDOUT_END=2026-04-30` — **exactly the CONTEXT windows.** `--train` / `--holdout` resolve them at `:50-53` |
| `src/backtester/cli.py:27-30` | `SYMBOLS` — hardcoded module constant, the 8-crypto universe. **Not overridable** |
| `src/backtester/cli.py:35-46` | args: `--phase`, `--train`, `--holdout`, `--start`, `--end`, `--disable`, `--fixture-dir`, `--output-dir`. **No `--min-confluence`, no `--kelly-fraction`, no symbol switches** |
| `src/backtester/cli.py:62-66` | `--disable` uses `dataclasses.replace(config, **{flag: False})` — the **exact idiom to reuse** for the new overrides |
| `src/backtester/config.py:33-36` | `min_confluence: int = 3`, `kelly_fraction: float = 0.25`, `max_position_pct: float = 0.05`, `starting_equity: float = 100_000.0`. **`PhaseConfig` is `frozen=True`** — mutate via `dataclasses.replace` only |
| `src/backtester/engine.py:124` | the entry gate: `if signal is None or signal.confluence_score < self.config.min_confluence: continue` |
| `src/backtester/engine.py:28-34` | `_position_dollar_amount(confluence, kelly_fraction, max_position_pct, equity)` |
| `src/backtester/engine.py:22-23` | `SIGNAL_WINDOW = 50`, `SCAN_INTERVAL_BARS = 30` (entry scan is throttled to 1-in-30 bars per symbol, `:112`) |
| `src/backtester/metrics.py` | `sharpe_ratio:6`, `max_drawdown:19`, `win_rate:34`, `monitor_pnl:40`, `compute_summary:44` — **all present, no change needed** |
| `src/backtester/data_loader.py:41` | `load_bars_fixture(symbol, fixture_dir)` — `"BTC/USD"` → `BTC_USD.json`; `:54 load_bars_cached`; `:75 save_bars_cache` |

### 2.2 Exactly what must be added

**`src/backtester/config.py`** — four new `PhaseConfig` fields (frozen dataclass, so defaults must
preserve today's behavior exactly):

```python
symbols: tuple[str, ...] = ()          # () = no allowlist restriction (matches entry_allowed's contract)
quarantined: tuple[str, ...] = ()      # () = nothing denied
rsi_ceiling: float = 65.0              # matches BotConfig default (src/bot_config.py:22)
```
(tuples, not lists — `frozen=True` dataclasses need hashable/immutable fields to stay safely shared.)

**`src/backtester/engine.py`** — two guards in the scan loop, immediately before the confluence test
at `:124`:

```python
from src.universe import entry_allowed           # import, do NOT re-implement
...
if not entry_allowed(sym, self.config.symbols, self.config.quarantined)[0]:
    continue
if signal is None or signal.confluence_score < self.config.min_confluence:
    continue
if signal.rsi_value >= self.config.rsi_ceiling:   # live: bot_thread.py:147 (strict <)
    continue
```
With the defaults above (`symbols=()`, `quarantined=()`, `rsi_ceiling=65.0`), `entry_allowed` returns
`(True, None)` for everything (`src/universe.py:47-49`: an empty allowlist means "no restriction")
— **but the `rsi_ceiling` guard is genuinely new behavior at the default.** That is unavoidable: it
is the C2 fidelity fix. CONTEXT Decision 6 demands *"the engine's behavior at the current defaults
must be bit-identical (pinned by a test)."* **These two requirements are in direct tension.**
**Resolution (recommend to the planner):** pin the bit-identical test against a config with the RSI
guard *disabled* (`rsi_ceiling=float("inf")`), which proves the refactor introduced no *incidental*
change; and separately assert that `rsi_ceiling=65.0` produces a **different, smaller** trade set —
proving the fidelity fix is non-vacuous. Then run the **baseline** row of `18-BACKTEST.md` with
`rsi_ceiling=65.0` too, so baseline and candidate are compared under the same engine. Never compare a
pre-fix baseline against a post-fix candidate — that difference would be the engine, not the retune.

**`src/backtester/cli.py`** — four new args, folded into the existing `dataclasses.replace` idiom:

```python
parser.add_argument("--min-confluence", type=int, default=None)
parser.add_argument("--kelly-fraction", type=float, default=None)
parser.add_argument("--symbols", default=None,          help="Comma-separated; overrides SYMBOLS")
parser.add_argument("--exclude-symbols", default=None,  help="Comma-separated deny-list -> PhaseConfig.quarantined")
```
then, after `config = PHASE_PRESETS[args.phase]`:
```python
overrides = {}
if args.min_confluence is not None: overrides["min_confluence"] = args.min_confluence
if args.kelly_fraction is not None:
    if args.kelly_fraction > 0.25:                       # HARD RULE — quarter-Kelly is a CEILING
        parser.error("--kelly-fraction may not exceed 0.25 (quarter-Kelly ceiling, CLAUDE.md)")
    overrides["kelly_fraction"] = args.kelly_fraction
syms = [s.strip() for s in args.symbols.split(",")] if args.symbols else list(SYMBOLS)
overrides["symbols"] = tuple(syms)
if args.exclude_symbols:
    overrides["quarantined"] = tuple(s.strip() for s in args.exclude_symbols.split(",") if s.strip())
config = dataclasses.replace(config, **overrides)
```
and the bar-load loop (`:74`) iterates `config.symbols` instead of the module `SYMBOLS`.

**The `--kelly-fraction > 0.25` hard error is not optional.** It is the only thing standing between a
good-looking backtest number and a violation of the hardcoded risk rules. It belongs in the CLI (a
`parser.error`, exit 1), not in a comment.

### 2.3 Sizing math — VERIFIED IDENTICAL to live (the one CONTEXT engine claim that holds)

| | Live (`src/alpaca_orchestrator.py:412-459`) | Backtester (`src/backtester/engine.py:28-34`) |
|---|---|---|
| win prob | `{3:0.55, 4:0.60, 5:0.65}.get(c, 0.55)` (`:434-435`) | `_KELLY_PROBS = {3:0.55,4:0.60,5:0.65}`, `.get(c, 0.55)` (`:25, :30`) |
| Kelly | `b = 0.08/0.08 = 1.0`; `kelly_pct = max(0, (b*p − q)/b)` = `2p − 1` (`:439, :443`) | `edge = p − (1 − p)` = `2p − 1` (`:31`) |
| × fraction | `adjusted_pct = kelly_pct * kelly_fraction` (`:444`) | `raw_kelly = edge * kelly_fraction` (`:32`) |
| cap | `if adjusted_pct > max_position_pct: adjusted_pct = max_position_pct` (`:454-456`) | `capped = min(raw_kelly, max_position_pct)` (`:33`) |
| $ | `bankroll * adjusted_pct` (`:458`) | `capped * equity` (`:34`) |

**Algebraically identical.** Two live-only extras are absent from the engine and should stay absent:
`confidence_adjustment` (LEARN-02, `:447`) and `min_position_pct` (LEARN-03, `:450-451`) — both are
shadow-gated by `LEARNING_SHADOW_UNTIL_TRADES` and modelling them would be a new strategy.

Materialized grid (computed, `equity=100k`, `max_position_pct=0.05`) — this is what the sweep is
actually varying:

| | `k=0.15` | `k=0.20` | `k=0.25` |
|---|---|---|---|
| `conf=3` (p=.55, edge=.10) | 1.50% | 2.00% | 2.50% |
| `conf=4` (p=.60, edge=.20) | 3.00% | 4.00% | **5.00%** (at the cap) |
| `conf=5` | *unreachable — see C1* | *unreachable* | *unreachable* |

The 5% max-position cap is never breached anywhere in the legal grid — the hard risk rule holds by
construction. **And the grid is non-vacuous**: every legal cell yields a distinct position size, so a
test asserting "a different knob yields a different result" has real content.

---

## 3. The sweep — reproducibility and the data problem

### 3.1 Bar data — **this is the Wave-0 blocker**

`tests/backtester/fixtures/` contains **exactly one file: `BTC_USD.json`, 60 bars.** Verified.

Three independent problems:
1. **60 bars.** `SIGNAL_WINDOW = 50` (`engine.py:22`) + `SCAN_INTERVAL_BARS = 30` (`:23`) means the
   fixture affords **at most one scan opportunity**. Unusable for a sweep.
2. **One symbol.** A 7-symbol universe cannot be swept from one symbol's bars.
3. **That symbol is BTC — the headline quarantine target.** With `--exclude-symbols BTC/USD`, a
   fixture-only sweep has **zero tradeable symbols** and every cell returns `trades=0`. The
   quarantine arm of the grid would be **vacuously "better"** (no trades, no losses, drawdown 0).
   A sweep run on fixtures would produce a confidently wrong answer.

**Therefore the sweep MUST run on real bars** via `load_bars_cached` (`src/backtester/data_loader.py:54`)
→ Alpaca market data (read-only, no `DATABASE_URL`, no prod DB). Fetch the 8 symbols across
2025-10-01 → 2026-04-30 **once**, `save_bars_cache` (`:75`), and run all 18 cells + baseline +
holdout against the **same cached bars**. Caching is what makes the sweep reproducible: an Alpaca
re-fetch is not guaranteed byte-identical.

**Reproducibility checklist for `18-BACKTEST.md`:** the cache path + bar count per symbol, the exact
CLI invocation per cell, engine `git rev-parse HEAD`, and the full 18-cell table (including the six
`mc=5` zeros). The engine has **no RNG** — given the same bars and config it is deterministic, so
bar provenance is the only reproducibility risk.

### 3.2 Sweep discipline

- **TRAIN only** for all 18 cells. Pick **one** candidate on TRAIN.
- **HOLDOUT is run ONCE**, on the single candidate, plus once on the baseline for comparison.
  Running the grid on holdout and picking the best is overfitting and is **forbidden** by Decision 6.
- **Baseline** = each bot's *current* live `bots` row values (read them out of the DB **with
  `AIPW_DB_READONLY=1`**, or via `GET /api/bots`, and record them in `18-BACKTEST.md` — they are the
  revert target).
- Acceptance criterion 3's **trade count ≥ 30** exists precisely to kill the degenerate
  "win rate 100% on 1 trade" cell. Enforce it in the sweep driver, not by eye.

---

## 4. Rollout — verified config-only, zero code

| Link in the chain | Evidence |
|---|---|
| Columns exist on `bots` | `dashboard/api/migrations/002_multi_bot.sql` (`min_confluence`, `kelly_fraction`), `018_universe_quarantine.sql` (`quarantined_symbols`). ⚠ `src/db_schema.sql:11-19` is only a **partial mirror** (it shows `quarantined_symbols` but not the other two) — the migrations are authoritative; do not read the mirror as the schema |
| `BotConfig` reads them | `src/bot_config.py:18` (`kelly_fraction=0.25`), `:19` (`min_confluence=4`), `:38` (`quarantined_symbols=""`); `from_row` at `:49, :50, :68`; `symbols` property `:72-76`; `quarantined` property `:78-80` |
| API accepts them | `dashboard/api/models.py:258` (`kelly_fraction`), `:259` (`min_confluence`), `:276` (`quarantined_symbols`, with the comment *"`""` clears the list; `None` means leave alone"*) |
| The route writes + hot-swaps | `dashboard/api/routes/bots.py:184-212` — `updates = {k: v for k, v in body.model_dump().items() if v is not None}` (`:187`), dynamic `SET` (`:191`), then `mgr.update(bot_id, updates)` (`:208`) |
| They bite live | `src/bot_thread.py:141` (`min_confluence`), `:146`/`:165`/`:355` (`entry_allowed(..., cfg.quarantined)`), `:798`/`:996` (`kelly_fraction=cfg.kelly_fraction`) |

**Quarantine format:** slash form, exact (`"BTC/USD,ETH/USD,TRUMP/USD,FIL/USD,ARB/USD"`).
`src/bot_config.py:36-37` warns *"a bare `BTC` will NOT match"* — though note `entry_allowed`
normalizes both sides through `src/universe.py:17 normalize` (which strips the slash), so `BTC`
*would* in fact match. **Follow the documented convention (slash form) regardless** — it is what
Phase 15 built, what `symbols` uses, and what any human reading the row will expect.

**Revert = the same `PUT` with the old values.** Record them in `18-BACKTEST.md`.

---

## 5. `AIPW_DB_READONLY=1`

### Current structure

```python
# src/db.py:18                _pool: ConnectionPool | None = None
# src/db.py:21-37             _create_pool(): reads os.environ["DATABASE_URL"], 3 retries,
#                             ConnectionPool(conninfo=url, min_size=2, max_size=10,
#                                            kwargs={"row_factory": dict_row}, open=True)
# src/db.py:40-45             get_pool(): if _pool is None: _pool = _create_pool(); _bootstrap_schema()
# src/db.py:48-53             _bootstrap_schema(): reads src/db_schema.sql, conn.execute(sql)  ← DDL
# src/db.py:56-60             connection(): contextmanager yielding get_pool().connection()
```

**W1 restated precisely:** `_bootstrap_schema` (`:48`) executes `src/db_schema.sql` — which is
`CREATE TABLE IF NOT EXISTS …` **plus** `INSERT INTO bots … ON CONFLICT DO NOTHING` — on **first
pool creation**. Any process that so much as imports `src.db` and touches a query will run DDL
against whatever `DATABASE_URL` points at.

### Recommended change (two small edits, default behavior byte-identical)

```python
# src/db.py — replace get_pool()
def _readonly() -> bool:
    return os.environ.get("AIPW_DB_READONLY", "") == "1"

def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = _create_pool()
        if not _readonly():
            _bootstrap_schema()
    return _pool
```
```python
# src/db.py — in _create_pool()'s ConnectionPool(...) call
kwargs={"row_factory": dict_row,
        **({"options": "-c default_transaction_read_only=on"} if _readonly() else {})},
```

`options="-c default_transaction_read_only=on"` is a **libpq connection parameter**
(`PGOPTIONS`-equivalent) that psycopg passes through, so the setting applies to **every** connection
the pool hands out — not just the first — and it is enforced **server-side**: any `INSERT`/`UPDATE`/
`DELETE`/`CREATE`/`DROP` raises `psycopg.errors.ReadOnlySqlTransaction` (SQLSTATE `25006`). That is
strictly stronger than a client-side convention, and it cannot be bypassed by a caller who forgets.

**Two traps for the planner:**
- **`_pool` is a module global.** A test that flips `AIPW_DB_READONLY` **must reset `src.db._pool =
  None`** before and after, or it inherits a pool created under the other flag value. Phase 17's
  `test_get_resolved_trades_sql` already established this pattern (`17-VALIDATION.md` case 18) —
  reuse it.
- **The flag is read at pool-creation time, not per-query.** Setting it after the first query is a
  no-op. Set it in the process environment before importing/using `src.db`.

**Consumers to set it on:** `scripts/symbol_report.py` (Phase-17, read-only by construction), any
Phase-18 sweep/baseline-read script, and any future analysis script. **Do not set it on the bots or
the dashboard** — they legitimately write.

---

## 6. `get_alpaca_accuracy` and its consumers (see **C3** — there are three denominators)

### The function today

```python
# src/db.py:211-229 (abridged)
base = """
    SELECT status, pnl, symbol, asset_class FROM alpaca_trades
    WHERE bot_id = %s AND status IN ('closed', 'stopped', 'target_hit')
    ORDER BY closed_at DESC
"""
resolved = len(rows)                                     # ← counts NULL-pnl and 0.0-pnl rows
wins     = sum(1 for r in rows if (r["pnl"] or 0) > 0)   # ← NULL → 0 → not a win
losses   = resolved - wins                               # ← every NULL and every 0.0 becomes a LOSS
win_rate = wins / resolved if resolved > 0 else 0.0
```

### The change

Add **one clause** to the WHERE: `AND pnl IS NOT NULL`. Then `resolved` means "rows with a real
P&L", and `losses = resolved - wins` means what it says. `total_pnl`, `avg_pnl`, `crypto_pnl`,
`stock_pnl` all become sums over real P&L only — which is what they were always meant to be.
Do **not** also filter `pnl != 0` — a genuine 0.00 close is a real (if unlikely) outcome, and
Decision 2 only licenses excluding NULL.

### Every consumer (grepped repo-wide this session)

| Consumer | Site | Effect of the change | Breaks? |
|---|---|---|---|
| `TradeLogger.get_alpaca_accuracy` | `src/trade_logger.py:52-53` | pass-through shim | No |
| Alpaca orchestrator summary | `src/alpaca_orchestrator.py:577` | logs `resolved`/`wins`/`win_rate` — now honest | No |
| Alpaca orchestrator summary | `src/alpaca_orchestrator.py:1254` | same | No |
| Phase-17 divergence table | `scripts/symbol_report.py:269` | the `R − T` column **shrinks** (that is the *point* — the divergence it measures is exactly the sentinel+NULL gap). Its prose at `:239` says *"Phase 17 does not change `get_alpaca_accuracy`"* — **Phase 18 does; update that line** or the report contradicts itself | **Prose only** |
| Unit test | `tests/test_db.py:34` | asserts on the returned dict — **must be re-read and updated** if its fixture contains NULL/0.0 rows | **Check** |
| Shim contract test | `tests/test_trade_logger_shim.py:18` | only asserts the method *name* exists | No |
| **Dashboard headline (`/api/portfolio`)** | `dashboard/api/routes/portfolio.py:64-76` | **does NOT call this function — duplicated SQL.** Needs the *same* `AND pnl IS NOT NULL` clause or the dashboard stays wrong | **YES — C3** |
| **Dashboard settings (`/api/settings`)** | `dashboard/api/routes/settings.py:37-42, 58-61` | **same duplicated SQL**, drives `win_rate` vs `win_rate_target=40.0` (`models.py:165-166`) — i.e. *the paper-gate readout itself* | **YES — C3** |

**Sibling functions to leave alone (deliberately):** `get_recent_loss_symbols` (`src/db.py:194-207`)
uses `status IN ('closed','stopped')` and `pnl < 0` — a NULL `pnl` fails `pnl < 0` in SQL, so a NULL
row simply never enters the cooldown set. **Correct by accident, correct nonetheless.** Its
status-set spelling defect is explicitly **Phase 20** (CONTEXT).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Resolve a vanished position's real exit | New Alpaca activity/closed-position polling + P&L math | `src/backfill.py:51 resolve_stale_row` + `:92 _match_close` + `src/pnl.py:10 realized_pnl` + `AlpacaClient.get_closed_orders` (`src/alpaca_client.py:419`) | All four are pure, Phase-11/14-built, and covered by `tests/test_backfill.py` (~20 cases). A second resolver = a second source of truth for the same fact |
| Fee-net P&L | `(exit − entry) * qty` inline | `src/pnl.py:10 realized_pnl` | Side-aware, fees on **both** legs. Phase-17 C2 found two writers that got this wrong |
| Order status → DB status | A status string `if/elif` chain | `src/order_resolution.py:14 classify_order` | Handles the `cancelled`/`canceled` spelling and partial fills |
| The backtester's universe/quarantine gate | A `symbol in exclude_list` check in the engine | `src/universe.py:26 entry_allowed` | It is *the live gate*. Re-implementing it is precisely how the backtest silently stops validating the live bot |
| Symbol comparison | `.replace("/", "")` ad hoc (as the monitor does at `alpaca_orchestrator.py:168`) | `src/universe.py:17 normalize` | Total, idempotent, tested. The ad-hoc version is the source of the §1.6 live-symbol mismatch trap |
| Read prod safely | "remember not to write" | `AIPW_DB_READONLY=1` → server-side `default_transaction_read_only` | A convention is not a fence |
| Win rate / drawdown / Sharpe | New metric code | `src/backtester/metrics.py:6, 19, 34, 44` | Already present; CONTEXT forbids touching them |

**Key insight:** Phase 18 needs almost **no new logic**. Phases 11–15 already built every pure piece
(order resolution, realized P&L, the universe gate, the config columns, the hot-swap route). The
phase is 90% *wiring existing pure functions into two call sites* and 10% CLI surface. Any plan that
introduces a new resolver, a new P&L formula, or a new symbol-gate has gone wrong.

---

## Common Pitfalls

### P1 — Sweeping a drifted engine (the fatal one)
**What goes wrong:** the grid is run against `engine.py` as it stands, whose entry predicate is 1 of
the live bot's 8 conjuncts (**C2**). A `min_confluence` is chosen that is optimal for a strategy
nobody runs.
**How to avoid:** land `entry_allowed` + `rsi_ceiling` in the engine **before** cell #1. Declare the
four residual gaps (loss-cooldown, 4H filter, shorts, soft/trailing/advisor exits) in
`18-BACKTEST.md`.
**Warning sign:** the backtest's trade count is far above the live bot's for the same window.

### P2 — Running the sweep on the fixture
**What goes wrong:** `tests/backtester/fixtures/` has one 60-bar BTC file. With BTC quarantined the
run has **zero symbols**; every cell returns `trades=0`, drawdown `0.0`, and the quarantine arm
"wins" vacuously.
**How to avoid:** real cached bars for all 8 symbols across both windows. Assert `trades >= 30` on
holdout (acceptance criterion 3) — it is the tripwire for exactly this.

### P3 — Comparing a pre-fix baseline against a post-fix candidate
**What goes wrong:** baseline is run before the `rsi_ceiling` guard lands, candidate after. The delta
is the engine change, not the retune.
**How to avoid:** run **both** on the final engine, in the same session, on the same cached bars.

### P4 — Fixing `src/db.py` and declaring the win rate measurable
**What goes wrong:** **C3** — the dashboard has its own two copies of the arithmetic. The headline
stays at 12.4%, and the new NULL rows the sentinel fix writes get booked as losses there.
**How to avoid:** three sites, one clause each. Verify against the live `/api/portfolio` response,
not against a unit test.

### P5 — The `live_symbols` slash mismatch
**What goes wrong:** the monitor builds `live_symbols` slash-**stripped** (`"BTCUSD"`,
`alpaca_orchestrator.py:159`) but `resolve_stale_row` tests `row["symbol"]` (`"BTC/USD"`) against it
(`backfill.py:71`). Every held position looks vanished → the fix mass-closes live positions.
**How to avoid:** normalize both sides through `src.universe.normalize`. **Test it explicitly** — a
held position must resolve `"unchanged"`.
**Warning sign:** the monitor closes everything on its first cycle.

### P6 — A transient Alpaca error becoming a NULL write
**What goes wrong:** `get_order`/`get_closed_orders` throws a 500; the code falls into the
`unresolvable` branch and terminates a **live, held** position as `closed/NULL`.
**How to avoid:** try/except around every Alpaca call → return `{}` (leave open, retry next cycle).
`unresolvable` must mean *"Alpaca answered, and the answer has no matching close order"* — **not**
*"Alpaca did not answer."*

### P7 — Raising Kelly because the backtest liked it
**What goes wrong:** a `kelly_fraction=0.5` cell shows the best return. Someone ships it.
**How to avoid:** the CLI `parser.error` at §2.2 makes the cell **unrunnable**. Quarter-Kelly is a
hardcoded ceiling; no number buys an exception.

### P8 — `_pool` global leaking across the read-only test
**What goes wrong:** a pool built without `AIPW_DB_READONLY` is reused by the test that asserts the
flag works; the assertion passes/fails for the wrong reason.
**How to avoid:** reset `src.db._pool = None` on entry **and** exit (Phase-17 case-18 pattern).

---

## Anti-Patterns to Avoid

- **Fabricating a number to fill a NOT NULL-shaped hole.** `pnl=0.0` for an unknown exit is the bug
  this phase exists to fix. `exit_price=entry_price` is the same lie wearing a different hat.
  **NULL is the honest value.** Never introduce a new fabricated default anywhere in this phase.
- **Backfilling / UPDATE-ing / DELETE-ing the 395 historical sentinels.** Explicitly forbidden by
  CONTEXT. They are historically opaque; their true exits are gone. Stop *creating* them and stop
  *counting* them — nothing else.
- **Re-implementing `entry_allowed` inside the backtester** "because importing `src.universe` into
  the engine feels like coupling." That coupling is the entire point of the validation.
- **Picking the candidate on the holdout.** Forbidden. One holdout run, on one candidate.
- **Forcing a number through a failed sweep.** Decision 6 has an explicit escape hatch: ship the
  quarantine only, record the negative result. **A failed sweep is a finding.**
- **Touching `min_short_confluence`, exits, the risk gate, the exit advisor, the learning gate, or
  Bot C/D/E strategy code.** All fenced.

---

## Code Examples

### Reading the current baseline knob values, safely
```bash
AIPW_DB_READONLY=1 python -c "
from src.db import connection
with connection() as c:
    for r in c.execute('SELECT bot_id, min_confluence, kelly_fraction, quarantined_symbols FROM bots ORDER BY bot_id'):
        print(r)"
```

### One grid cell (the shape the sweep driver repeats)
```bash
python -m src.backtester --phase 0 --train \
  --min-confluence 4 --kelly-fraction 0.20 \
  --symbols "BTC/USD,ETH/USD,SOL/USD,XRP/USD,ADA/USD,AVAX/USD,DOT/USD,LINK/USD" \
  --exclude-symbols "BTC/USD,ETH/USD,TRUMP/USD,FIL/USD,ARB/USD"
```

### The rollout (and its own revert)
```bash
curl -X PUT https://app.aipredictedwins.com/api/bots/A \
  -H 'Content-Type: application/json' \
  -d '{"min_confluence": 4, "kelly_fraction": 0.20,
       "quarantined_symbols": "BTC/USD,ETH/USD,TRUMP/USD,FIL/USD,ARB/USD"}'
# revert = the same call with the values recorded in 18-BACKTEST.md
```

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python + pytest | all tests | ✓ | 3.13 | — |
| `src/backtester` | the sweep | ✓ | in-repo | — |
| Alpaca market-data API | real bars for the sweep | ✓ (keys in `.env`) | `alpaca-py` 0.43.2 | **none — the fixture is unusable (P2)** |
| Postgres (`DATABASE_URL`) | baseline knob read; the `PUT` rollout | ✓ (prod) | — | `GET /api/bots` (read); **only ever read with `AIPW_DB_READONLY=1`** |
| `TEST_DATABASE_URL` | any DB-gated test | ⚠ set per Phase 17 (`17-RESEARCH.md` C3) | — | skip the DB-gated case |

**Missing dependencies with no fallback:** real cached Alpaca bars for 8 symbols × 2025-10-01 →
2026-04-30. **This is the Wave-0 blocker** — without it the sweep cannot run non-vacuously.

---

## Runtime State Inventory

Phase 18 changes runtime *parameters*, so this applies.

| Category | Items Found | Action Required |
|---|---|---|
| Stored data | `bots` rows (A/B/C/D): `min_confluence`, `kelly_fraction`, `quarantined_symbols`. **Bot B may still be at `kelly_fraction=0.50`** (the A/B experiment) — CONTEXT Decision 4 requires it come to ≤0.25 | **Data update** via `PUT /api/bots/{bot_id}` (Decision 7). Record the *previous* values in `18-BACKTEST.md` first — they are the revert |
| Stored data | 395 historical sentinel rows (`status='closed', pnl=0.0`) in `alpaca_trades` | **NONE — explicitly do not touch.** They stop being *counted* (the denominator fix); they are not *changed* |
| Live service config | BotManager holds an in-memory `BotConfig` per thread | **None** — `PUT /api/bots/{bot_id}` calls `mgr.update()` (`dashboard/api/routes/bots.py:208`), which hot-swaps atomically. No restart, no deploy |
| Secrets / env vars | **`AIPW_DB_READONLY`** — a *new* env var. Read-only default (unset) = today's behavior | Set it on analysis **scripts** only. **Do NOT set it on the bot or dashboard services** — they write |
| OS-registered state | None — verified: no scheduled tasks / pm2 entries / systemd units reference these knobs | None |
| Build artifacts | None — no compiled artifact embeds the knobs | None |

---

## Validation Architecture

### Test Framework
| Property | Value |
|---|---|
| Framework | pytest |
| Config | repo root; `tests/` (`vendor/TradingAgents/tests` collects with errors and is **not** in the baseline) |
| Quick run | `python -m pytest tests/test_backfill.py tests/test_universe.py tests/backtester/ -q` |
| Full suite | `python -m pytest tests/ -q` |
| **Baseline** | **395 passed / 24 skipped** — must not regress |

### Sampling Rate
- **Per task commit:** the quick run above.
- **Per wave merge:** full suite.
- **Phase gate:** full suite green (≥395 passed) before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] **Cached Alpaca bars, 8 symbols × 2025-10-01 → 2026-04-30** — the sweep is vacuous without them
      (P2). Highest-priority Wave-0 item.
- [ ] `tests/test_external_exit_resolution.py` — the sentinel writer's fake-double tests.
- [ ] `tests/test_db_readonly.py` — the `AIPW_DB_READONLY` bootstrap-skip test.
- [ ] `tests/backtester/test_cli_overrides.py` — the new CLI knobs.
- [ ] Extend `tests/backtester/test_engine.py` — `entry_allowed` + `rsi_ceiling` guards, and the
      bit-identical-defaults pin.
- [ ] Existing-consumer check: re-read `tests/test_db.py:34` before changing `get_alpaca_accuracy`.

---

## Security Domain

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | no | no new auth surface |
| V4 Access Control | yes | `PUT /api/bots/{bot_id}` is an existing authenticated route — Phase 18 adds no new endpoint |
| V5 Input Validation | yes | the new CLI knobs are **local-operator** input, but the **`--kelly-fraction ≤ 0.25` guard is a safety control, not a validation nicety** — it enforces a hardcoded risk rule |
| V6 Cryptography | no | none |

| Pattern | STRIDE | Mitigation |
|---|---|---|
| Accidental DDL/DML against prod from an analysis script | Tampering | **`AIPW_DB_READONLY=1`** → server-side `default_transaction_read_only` (§5) |
| A backtest result licensing a risk-rule breach | Elevation of Privilege | `parser.error` on `--kelly-fraction > 0.25`; the 5% cap is enforced in `_position_dollar_amount` (`engine.py:33`) and `_kelly_technical` (`:454-456`) |
| Fabricated P&L corrupting the paper-gate readout | Repudiation | NULL-not-zero (§1); the three-site denominator fix (**C3**) |

---

## State of the Art

| Old | Current | Impact |
|---|---|---|
| Vanished position → `pnl=0.0` sentinel (`alpaca_orchestrator.py:175`) | Resolve from order history, else `pnl=NULL` | The win rate becomes measurable — which is the precondition for TUNE-01's own acceptance bar |
| `losses = resolved − wins` over all terminal rows | denominator excludes `pnl IS NULL` — **at three sites** | Bot A's displayed 12.4% → the real ~33.0% |
| `get_pool()` always bootstraps DDL | `AIPW_DB_READONLY=1` skips it + read-only transactions | "Read prod safely" becomes a supported operation, not a discipline |
| Backtester entry = confluence only | + `entry_allowed` + `rsi_ceiling` | The backtest starts validating the strategy the bot actually runs (partially — see the declared gaps) |

---

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|---|---|---|
| A1 | The live `bots` row for Bot B still has `kelly_fraction = 0.50` | Runtime State Inventory | Low — **read it with `AIPW_DB_READONLY=1` before writing.** If already ≤0.25, no change needed |
| A2 | Alpaca's order history still retains closing orders for currently-open positions | §1.3 | Medium — if an entry is older than Alpaca's retention, `_match_close` returns `None` → `unresolvable` → NULL. **That is the correct, honest outcome**, so the design degrades safely |
| A3 | `psycopg` passes `options="-c default_transaction_read_only=on"` through to libpq | §5 | Low — standard libpq behavior; **the validation suite asserts DDL actually fails**, so a wrong assumption is caught by test, not in prod |
| A4 | Alpaca has bar data for all 8 symbols across the full 2025-10-01 → 2026-04-30 range | §3.1 | **Medium-high** — if a symbol is short of bars, its cells are thin. Wave 0 must **report per-symbol bar counts** before the sweep runs |
| A5 | The dashboard's `/api/portfolio` win rate is what the user reads as "the headline" | C3 | Low — even if not, `settings.py:135`'s `win_rate` vs `win_rate_target=40.0` **is** the paper-gate readout, and it has the same bug |

---

## Open Questions

1. **Which grid point does the sweep pick if two cells tie on the acceptance bar?**
   - Known: the bar is a conjunction of four criteria, not a ranking.
   - Unclear: the tiebreak.
   - **Recommendation:** prefer the **lower** `kelly_fraction`, then the **higher** `min_confluence`
     — i.e. break ties toward *less risk and fewer trades*. State the rule in `18-BACKTEST.md`
     **before** looking at the grid.

2. **Is the quarantine applied to Bot C (TradingAgents) and Bot D (daytrade)?**
   - Known: Decision 5 says *"quarantined for **every confluence bot**"*. Bot C is
     `tradingagents_enabled`; Bot D is `BOT_PROFILE=daytrade`. `entry_allowed` is called in
     `bot_thread` for all of them (`:146, :165, :355`).
   - **Recommendation:** apply the quarantine to every bot whose `strategy == "confluence"` (the
     `BotConfig` default, `src/bot_config.py:34`). Read each bot's `strategy` before writing, and
     record which bots were touched in `18-BACKTEST.md`.

3. **`src/db_schema.sql:11-19`'s `bots` mirror is missing `min_confluence` / `kelly_fraction`, and
   its `CHECK (id IN ('A','B'))` predates bots C and D.**
   - Known: the migrations are authoritative and prod is fine; the mirror is only executed by
     `_bootstrap_schema` under `CREATE TABLE IF NOT EXISTS` (so it is a no-op against prod).
   - **Recommendation:** **out of scope — do not touch it in Phase 18.** Log it for Phase 20. Note
     it means a *fresh* DB bootstrapped from the mirror alone would be missing the knobs — worth
     knowing, not worth fixing under this phase's fences.

---

## Sources (all re-read at file:line this session)

### Primary (HIGH — direct code reads)
- `src/technical_signals.py:40, 268, 287, 361-406, 425-436, 461-478` — the 0–4 confluence ceiling (**C1**)
- `src/bot_thread.py:130-167, 623, 798, 813, 996` — the live 7-conjunct entry predicate (**C2**)
- `src/backtester/{cli,config,engine,metrics,portfolio,data_loader}.py` — full surface
- `src/alpaca_orchestrator.py:148-180, 412-467, 577, 1254` — the sentinel writer + `_kelly_technical`
- `src/backfill.py:51-128`, `src/pnl.py:10-38`, `src/order_resolution.py:14-28` — the existing resolver
- `src/alpaca_client.py:401-464` — `get_order` / `get_closed_orders` / `_parse_order`
- `src/db.py:18-60, 101-130, 194-244` — pool/bootstrap, `update_alpaca_trade`, `get_alpaca_accuracy`
- `src/db_schema.sql:11-51` — `bots` + `alpaca_trades` columns
- `src/bot_config.py:7-80`, `src/universe.py:1-51` — the knobs and the gate
- `dashboard/api/models.py:254-276`, `dashboard/api/routes/bots.py:184-212` — the rollout path
- **`dashboard/api/routes/portfolio.py:62-76`, `dashboard/api/routes/settings.py:37-61`** — the two
  duplicated win-rate denominators (**C3**)
- `tests/backtester/test_engine.py`, `tests/test_backfill.py`, `tests/test_db.py:34` — conventions

### Empirical (HIGH — executed this session)
- `analyze()` over the BTC fixture → confluence histogram `{2: 7, 3: 3}`, ceiling 4 (**C1**)
- `_position_dollar_amount` across the legal grid → the §2.3 sizing table (grid is non-vacuous; 5%
  cap never breached)
- `ls tests/backtester/fixtures/` → **one file, `BTC_USD.json`, 60 bars** (**P2**, Wave-0 blocker)
- repo-wide grep for `get_alpaca_accuracy` callers → **the dashboard is not among them** (**C3**)

### Referenced
- `.planning/phases/18-profitable-retune/18-CONTEXT.md` — locked decisions (three corrected above)
- `.planning/phases/17-per-symbol-performance/{EVIDENCE,VERIFICATION}.md` — quarantine input, W1/W2
- `CLAUDE.md` — the hardcoded risk rules

---

## Metadata

**Confidence breakdown:**
- Sentinel fix (§1): **HIGH** — every component read; the resolver exists and is tested
- Backtester surface (§2): **HIGH** — full file reads; sizing equivalence verified algebraically and numerically
- **C1 (0–4 ceiling): HIGH** — three independent code confirmations + empirical histogram
- **C2 (predicate drift): HIGH** — side-by-side line-level comparison
- **C3 (three denominators): HIGH** — repo-wide grep; the dashboard's own SQL read at file:line
- Rollout (§4): **HIGH** — every link in the chain read
- `AIPW_DB_READONLY` (§5): **MEDIUM-HIGH** — the code structure is HIGH; the libpq `options`
  passthrough is standard but **is asserted by test rather than assumed** (A3)
- Sweep data (§3): **MEDIUM** — the fixture gap is certain; Alpaca's bar coverage over the windows is
  unverified (A4) and is a Wave-0 task

**Research date:** 2026-07-12
**Valid until:** 2026-08-11 (30 days — in-repo code, no fast-moving external deps)
