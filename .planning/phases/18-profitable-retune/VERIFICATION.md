---
phase: 18-profitable-retune
verified: 2026-07-12
status: human_needed
score: 7/8 must-haves verified (1 PARTIAL)
verifier: independent (goal-backward, adversarial)
scope: plans 18-01..18-06 only (18-07 deliberately not executed — writes prod)
---

# Phase 18 — Profitable Retune (TUNE-01 + TUNE-03) — Independent Verification

**Verdict source:** the actual codebase + tests I ran myself + a fake-driven adversarial harness
I wrote against `_resolve_external_exit`. SUMMARY.md claims were not accepted as evidence.

---

## 1. LIVE-MONEY CHECK — `src/alpaca_orchestrator.py` position monitor — **PASS**

The only check that can lose real money. Traced the actual code (`src/alpaca_orchestrator.py:110-244`)
and then drove it with fakes.

| Question | Answer | Evidence |
|---|---|---|
| Is `if live_symbols is None: return {}` the FIRST statement of `_resolve_external_exit`, before any Alpaca call? | **YES** | `:133-134`. Nothing precedes it but the docstring. Fake with a client whose `get_order` would return `None` (→ would have written `_UNRESOLVABLE`) returns `{}` — proving the guard short-circuits before the call. |
| Is the monitor's `if live_symbols is not None:` guard retained? | **YES** | `:233`. The whole reconcile block, incl. the re-fetch, is inside it. `get_positions()` failure sets `live_symbols = None` (`:231`) and the block is skipped entirely. |
| Can a transient Alpaca error write ANYTHING? | **NO** | `get_positions()` raises → `{}` path. `get_order` raises → `{}` (`:141-144`). `get_closed_orders` raises → `{}` (`:163-165`). `if not kwargs: continue` at `:236`. Verified live with a raising fake for each. |
| Is `pnl=0.0` gone from the reconcile block? | **YES** | `git diff 19aed6f..9164358` removes the old `exit_price=trade["entry_price"], pnl=0.0` fabrication verbatim. The new terminal value is `_UNRESOLVABLE = {"status":"closed","exit_price":None,"pnl":None,"fees":None}` (`:118`). No `pnl=0.0` anywhere in the monitor. (`resolve_stale_row` still returns `pnl=0` for canceled/rejected 0-fill entries — correct: those never became positions.) |
| Slash vs slashless symbol shapes | **HANDLED** | `norm_live = {normalize(s) for s in live_symbols}` + `normalize(row["symbol"])` (`:151-155`). Fakes with `{"BTCUSD"}` and `{"BTC/USD"}` both return `{}` (still held) for a `BTC/USD` row. |
| Partial fill / ambiguous close | **SAFE** | `_match_close` qty-tolerance mismatch → `None` → `unresolvable` → `status=closed, pnl=NULL`. Honest NULL, not a fabricated P&L. Position is already gone from Alpaca in this path, so nothing is abandoned. |
| Position closed between `get_positions()` and `get_order()` | **SAFE** | Worst case is a genuine close that resolves via `get_closed_orders`, or `unresolvable` → NULL. No fake P&L. |

**My adversarial harness (9 cases) — actual output:**

```
positions-failed        -> {}                     (no Alpaca call made)
still-held slashless    -> {}
still-held slashed      -> {}
get_order raises        -> {}
get_closed raises       -> {}
gone, no close order    -> {status: closed, exit_price: None, pnl: None, fees: None}
partial close (qty mismatch) -> {... pnl: None ...}
real close              -> {status: closed, exit_price: 110.0, pnl: 9.475, fees: 0.525}
no order_id + STILL HELD -> {status: closed, ... pnl: None ...}   <-- see WARNING
```

### WARNING (not a blocker): the `order_id IS NULL` door

`_resolve_external_exit` checks `if not row.get("order_id"): return _UNRESOLVABLE` (`:136-137`)
**before** it ever consults `live_symbols` membership. So a DB-open row with a NULL `order_id`
whose symbol **is still held at Alpaca** is terminated `status='closed'` and drops out of
`get_open_alpaca_positions` → the monitor stops watching a live position (stops/targets gone).

- Reachable? Only if `order.get("order_id")` came back `None` at insert (`src/bot_thread.py:384`,
  `src/db.py:78` binds `trade_data.get("order_id")` with no NOT NULL guard). Rare, not impossible.
- Severity: **strictly no worse than pre-Phase-18** (the old code closed that row too, with a
  fabricated `pnl=0.0`). It is a residual of the same hazard class the phase set out to kill.
- Fix (one line, Phase 19): move the `normalize(row["symbol"]) in norm_live → return {}` check
  ABOVE the `order_id` branch.

**Live-money verdict: the change is a strict, large improvement and is safe to run. No path in
the reconcile block writes on a transient error, and no path fabricates P&L. PASS with one
narrow residual noted.**

---

## 2. Win-rate denominator — all three sites — **PASS**

| Site | Line | Evidence |
|---|---|---|
| `src/db.py` `get_alpaca_accuracy` | `:232` | `AND pnl IS NOT NULL` in the resolved-rows query; `win_rate = wins / resolved` (`:253`). |
| `dashboard/api/routes/portfolio.py` | `:70` | `AND pnl IS NOT NULL`; `win_rate_pct = wins / resolved * 100` (`:80`). |
| `dashboard/api/routes/settings.py` | `:43` | `AND pnl IS NOT NULL`; `win_rate_pct` (`:64`) feeds `win_rate=` / `win_rate_target=40.0` (`:137-138`). **The paper-gate readout still works** — the gate compares the (now honest) `win_rate` to the 40.0 target; only the denominator changed. |

`AIPW_DB_READONLY` guard exists (`src/db.py:22-23`) and is covered by `tests/test_db_readonly.py`.

---

## 3. The 4 `xfail(strict)` tests — legitimately deferred — **PASS**

`tests/test_rollout_config.py`, marker `_deferred_to_18_07`, `xfail(strict=True)`.
Run with `--runxfail` — they **genuinely fail today**:

```
FAILED test_kelly_above_ceiling_cannot_be_rolled_out
FAILED test_kelly_ceiling_on_bot_create
FAILED test_seed_cannot_restore_bot_b_at_half_kelly
FAILED test_kelly_clamped_on_read
4 failed, 2 passed, 1 skipped
```

They assert the quarter-Kelly ceiling (`BotConfig.from_row` currently returns `kelly_fraction=0.5`
unclamped) — exactly what 18-07 lands. `strict=True` means they cannot rot: the moment 18-07
clamps Kelly they flip to XPASS = suite failure until the marker is removed. This is a real
tripwire, not a dodge.

---

## 4. Sweep harness — fresh subprocess + reproducibility — **PASS**

`scripts/sweep_backtest.py`:
- `run_cell` builds `env = {**os.environ, "BAR_CACHE_DIR": CACHE_DIR, "AIPW_DB_READONLY": "1"}`
  and calls `subprocess.run([...python, -m, src.backtester ...])` — **each cell is a fresh
  process** (`:53-63`). The header explains why: `data_loader.py` reads `BAR_CACHE_DIR` at
  IMPORT and bakes it into default args, so an in-process loop would re-fetch from Alpaca
  mid-sweep. Correct diagnosis, correct fix.
- `passes_bar()` is real code (`:83-99`), a four-way conjunction, and **`trades >= 30` is checked
  FIRST** (`:87-88`) so an empty cell reads EMPTY, not "bad config".
- Holdout: `--holdout` without `--candidate` is a `parser.error` (`:147-151`); a second run is
  refused via `18-HOLDOUT.lock` (`:152-155`). The lock exists and is committed:
  `candidate=4,0.25,on / baseline=4,0.25,off / git_rev=656231d`. **Run exactly once.**
- `read_baseline_knobs()` forces `AIPW_DB_READONLY=1` before touching the prod DB.

---

## 5. Is the NEGATIVE sweep result trustworthy, or an artifact? — **PARTIAL (trustworthy, but a weak lower bound)**

I did not take the table on faith. I re-ran a cell myself:

```
BAR_CACHE_DIR=data/backtest_bars python -m src.backtester --phase 0 --train --min-confluence 3 --kelly-fraction 0.15
-> trade_count 31 | win_rate 0.0323 | max_drawdown 0.0938 | total_return_pct -8.8843
```

**Exactly reproduces 18-BACKTEST.md row 2.** Bars load (2946–2952 per symbol from the cache),
the entry predicate fires, positions open and close. **The harness is not broken.** Then I dumped
every trade:

- 31 trades: **29 `hard_stop`, 1 `hard_take_profit` (+30.19%), 1 `end_of_backtest`**.
- Every stop exits at **−15% to −21%**, and the single winner at **+30%**.

Why: the engine imports `HARD_STOP_PCT = -0.15` / `HARD_TAKE_PROFIT_PCT = +0.30`
(`src/exit_advisor.py:27-28`), and its exit ladder is those two thresholds and nothing else
(`src/backtester/engine.py:100-105`). So the 3–4% win rate is a **structural property of a
long-only −15%/+30% barrier over the Oct-2025→Jan-2026 crypto drawdown** — not a bug, and not a
signal about `min_confluence`/`kelly_fraction`.

Consequences the report should have drawn harder:
1. **Criterion 2 (`win_rate >= 40%`) never discriminated.** `kelly_fraction` scales position size
   only — it cannot move win rate. Across 12 live cells there are exactly **two** distinct win
   rates (3.23% at mc=3, 0.00% at mc=4). The bar was unreachable by construction of the engine's
   exit model, so "no cell clears the bar" is largely a statement about the engine, not the knobs.
2. **18-BACKTEST.md misstates its own thresholds.** Fidelity-gap item 4 says the engine has
   "HARD thresholds ONLY (−4% / +10%)". The real constants are **−15% / +30%**. The live SWING
   profile is `hard_stop_pct = -0.08` **plus an ATR trailing stop and an ATR fixed stop**
   (`src/strategy_profile.py:62`, `src/alpaca_orchestrator.py:307-332`) — none of which the
   engine models. The engine's stop is nearly 2× wider than live and lets every loser run.
   **Documentation defect, material to how a reader interprets a 4.17% win rate.**

**Is the negative real?** — **YES, it is trustworthy, with a bounded claim.** It is reproducible,
the bars load, the entries fire, the exits fire, and the holdout was spent once. But it only
supports:

> *No **entry-knob** configuration rescues a **long-only, wide-hard-stop** model over a crash window.*

It does **not** support "a retune cannot help the live bot", and it was never capable of doing so
— the win-rate criterion could not be met by any cell. **Crucially, the recommendation the report
draws from it is the conservative one** — change nothing, ship only the quarantine, which stands
on Phase-17's *real-trade* evidence (`17-04-EVIDENCE.md`), not on the sweep. That recommendation
is not endangered by the fidelity gap: a false negative here can only cause inaction, never a bad
prod write. The report also names the exit stack as the real culprit and defers it to Phase 19,
which is the right call and is consistent with Phase 17's finding that the losses are EXIT-side.

**So: TRUSTWORTHY as a lower bound and as a decision ("do not retune on this evidence"); NOT
trustworthy as proof that the knobs are optimal. The `−4%/+10%` line in 18-BACKTEST.md must be
corrected to `−15%/+30%`.**

---

## 6. Fences — **PASS**

| Fence | Result |
|---|---|
| `git diff src/technical_signals.py` (c142cbe~1..HEAD) | **EMPTY.** No new strategy. The `min_confluence=5` cells are honestly empty (score ceiling is 4) rather than "fixed". |
| `src/backfill.py` diff | **One line, a comment only** (a `# NOTE (Phase 18 W1)` on the slash-shape mismatch, deferred to Phase 20). No behavior change. |
| 395 sentinel rows | **Untouched.** No `INSERT`/`UPDATE`/`DELETE`/`commit()` in `scripts/sweep_backtest.py` or `scripts/fetch_backtest_bars.py`; no migration in the diff; `symbol_report.py` diff is a 4-line doc-string change. |
| Prod writes | **NONE.** Whole-phase diff touches only: `.planning/`, `.gitignore`, tests, the two read-only scripts, backtester package, the monitor, and the three win-rate readers. |

---

## 7. Test suite — run by me — **PASS**

```
python -m pytest tests/ dashboard/api/tests/ -q
423 passed, 28 skipped, 4 xfailed, 1 warning in 6.48s
```

Matches expectation exactly.

---

## Per-goal table

| # | Goal | Verdict |
|---|---|---|
| 1 | Monitor stops fabricating exits; never abandons a live book (18-03) | **PASS** (1 narrow residual — `order_id IS NULL` door) |
| 2 | Win-rate denominator fixed at all three sites; paper gate intact (18-04) | **PASS** |
| 3 | `AIPW_DB_READONLY` read-only guard (18-04) | **PASS** |
| 4 | RED tests first, 4 `xfail(strict)` legitimately deferred to 18-07 (18-01) | **PASS** |
| 5 | Read-only bar fetch + cache + coverage (18-02) | **PASS** |
| 6 | Backtester knobs + engine entry fidelity (`entry_allowed`, `rsi_ceiling`) (18-05) | **PASS** |
| 7 | Reproducible sweep: fresh subprocess, real `passes_bar`, trade-floor first, holdout once (18-06) | **PASS** |
| 8 | The sweep's negative verdict is honest and its "ship quarantine only" recommendation is supported | **PARTIAL** — reproducible and honest, but the win-rate criterion was structurally unreachable and 18-BACKTEST.md misstates the engine's own stop/TP as −4%/+10% (actually −15%/+30%) |
| — | No prod writes; `technical_signals.py` untouched; sentinels untouched | **PASS** |

**Score: 7 PASS / 1 PARTIAL / 0 MISSING.**

---

## SHIP VERDICT

**SHIP plans 18-01 through 18-06.** The live-money change is correct and is a strict improvement
over the code it replaces: no transient Alpaca error writes anything, `live_symbols is None`
short-circuits before any API call, the `is not None` monitor guard is retained, both symbol
shapes are normalized, and the `pnl=0.0` fabrication is genuinely gone. The win-rate denominator
is fixed at all three sites with the paper gate intact. The sweep is reproducible and its
negative result, while a weak lower bound rather than a proof, drives only a conservative
recommendation (change nothing, ship the quarantine on independent Phase-17 real-trade evidence)
— a wrong negative here can only cause inaction, never a bad prod write.

**Two follow-ups required before Phase 19 closes (neither blocks 18-01..06):**
1. **Correct 18-BACKTEST.md** fidelity-gap item 4: the engine's hard exits are **−15% / +30%**,
   not −4% / +10%, and the live ladder additionally has an ATR trailing stop and an ATR fixed
   stop at `hard_stop_pct=-0.08`. The stated numbers understate the gap that produced the 4.17%.
2. **Close the `order_id IS NULL` door** in `_resolve_external_exit`: hoist the
   `symbol in norm_live → return {}` check above the `order_id` branch.

**18-07 remains correctly HELD for explicit human authorization** — it is the only plan that
writes the prod `bots` row. Nothing in 18-01..18-06 wrote to any prod resource.

---

## Human decisions requested

1. Authorize (or not) the 18-07 rollout: quarantine ON for confluence bots A/B, Bot B
   `kelly_fraction 0.50 → 0.25` (hardcoded ceiling), Bot B `max_position_pct 0.10 → 0.05`.
2. Accept the two follow-ups above as Phase-19 items, or require the doc correction now.

_Verified: 2026-07-12 — Claude (independent verifier). Not committed._
