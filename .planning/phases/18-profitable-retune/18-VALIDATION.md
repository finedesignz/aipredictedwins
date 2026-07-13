<!--
Phase 18 — Profitable Retune (Confluence + Kelly)
Validation strategy. Consumed by the planner (test tasks) and the verifier (ship gate).
Every case below is traceable to a file:line in 18-RESEARCH.md.
-->

# Phase 18 — Validation Strategy

**Requirements:** TUNE-01, TUNE-03
**Baseline (must not regress):** **395 passed / 24 skipped** (`python -m pytest tests/ -q`)
**Framework:** pytest, `tests/` (fake doubles + pure functions; `vendor/TradingAgents/tests` is NOT in the baseline)

---

## The three blockers this validation exists to catch

Each is a *specific, verified* failure mode from `18-RESEARCH.md`. A test suite that passes without
exercising these three is a suite that would have shipped the bug.

| # | Blocker | Where proved | Cases |
|---|---|---|---|
| **B1** | The sentinel writer fabricates `pnl=0.0` / `exit_price=entry_price` for a vanished position. A naive "fix" that resolves the *happy* path but silently falls back to `0.0` — or that turns a transient Alpaca 500 into a terminal NULL row, or that mass-closes **held** positions on a slash mismatch — is the same class of bug. | `src/alpaca_orchestrator.py:165-176` | 1–8 |
| **B2** | The win-rate denominator is duplicated at **THREE** sites, not one. `18-CONTEXT.md` names only `src/db.py`. Fixing it alone leaves the dashboard headline at 12.4% *and* books the new NULL rows as fresh losses — i.e. it fails its own stated purpose. | `src/db.py:227-229`, `dashboard/api/routes/portfolio.py:64-76`, `dashboard/api/routes/settings.py:37-61` | 9–13 |
| **B3** | The backtester's entry predicate has **drifted** from the live bot's (1 conjunct vs 8), and `min_confluence=5` is **structurally unreachable** (score ceiling is 4, not 5). A sweep on the drifted engine validates a strategy nobody runs; the `mc=5` grid row is provably empty. | `src/backtester/engine.py:124` vs `src/bot_thread.py:139-149`; `src/technical_signals.py:361-406` | 14–22 |

---

## Test Infrastructure

| Property | Value |
|---|---|
| Quick run (per task commit) | `python -m pytest tests/test_external_exit_resolution.py tests/test_db_readonly.py tests/backtester/ -q` |
| Full suite (per wave merge) | `python -m pytest tests/ -q` — **≥ 395 passed** |
| Phase gate | full suite green **+ `18-BACKTEST.md` committed** before `/gsd-verify-work` |
| Fake doubles | reuse `tests/test_backfill.py:96-120` (`FakeAlpaca` — `get_order` / `get_positions` / `get_closed_orders`, **no network**) |
| DB-gated cases | **`TEST_DATABASE_URL` only — NEVER `DATABASE_URL`** (Phase-17 C3). Reset `src.db._pool = None` on entry AND exit |
| Prod fence | **No test may write to prod.** No test may call the live Alpaca API |

---

## The test cases

### B1 — the sentinel writer never fabricates again (`tests/test_external_exit_resolution.py`)

All use `FakeAlpaca`; none touch the network or the DB. The unit under test is the pure
`_resolve_external_exit(alpaca, row, live_symbols) -> dict` extracted from
`src/alpaca_orchestrator.py:165-176`.

| # | Case | Test | Proves |
|---|---|---|---|
| **1** | **The fabrication is gone (static)** | Read the source of `src/alpaca_orchestrator.py`'s monitor reconcile block; assert it contains **no** `pnl=0.0` and **no** `exit_price=trade.get("entry_price"` literal. Positive control first: the slice is non-empty and contains `not in live_symbols`. | The literal bug at `:175` is **removed**, not merely bypassed. Without the positive control the regex could pass vacuously on an empty slice |
| **2** | **Unresolvable → NULL, never 0.0** | Filled entry; symbol absent from `live_symbols`; `get_closed_orders` returns `[]`. Assert the write kwargs are exactly `{"status": "closed", "exit_price": None, "pnl": None, "fees": None}`. **Assert `pnl is None`, NOT `pnl == 0`** (`0 == False == None` traps: use `is None`) | **The headline requirement.** A position that vanishes and cannot be resolved gets **NULL**, not a fabricated flat |
| **3** | **Resolvable → the REAL pnl** | Filled entry (`filled_avg_price=100.0`, `filled_qty=2`, side `buy`); symbol gone; `get_closed_orders` returns one opposite-side filled order at `110.0`, qty `2`, `filled_at` after entry. Assert `status == "closed"`, `exit_price == 110.0`, and `pnl == pytest.approx(realized_pnl("buy", 100.0, 110.0, 2, TAKER_FEE))` — **i.e. ≈ 20.0 minus fees on BOTH legs, and strictly `!= 0.0` and `!= 20.0`** | The real exit is recovered from order history, and it is **fee-net** (`src/pnl.py:10`) — not gross, not fabricated. Asserting `!= 20.0` proves fees are actually subtracted |
| **4** | **A HELD position is left alone (the slash trap)** | Filled entry for `"BTC/USD"`; `live_symbols = {"BTCUSD"}` (**slash-stripped, exactly as `alpaca_orchestrator.py:159` builds it**). Assert the result is `{}` — **no write at all** | **P5.** The monitor's `live_symbols` is slash-stripped while `resolve_stale_row` compares `row["symbol"]` (`"BTC/USD"`) — `src/backfill.py:71`. If normalization is wrong, the fix **mass-closes every live position on its first cycle.** This is the most dangerous regression in the phase |
| **5** | **A transient Alpaca error → no write** | `get_closed_orders` raises `RuntimeError`. Assert the result is `{}` (row stays `open`, retried next cycle) — assert it is **not** a NULL-terminal write | **P6.** `unresolvable` must mean *"Alpaca answered and there is no matching close"*, **never** *"Alpaca did not answer."* Otherwise a 500 silently terminates a live position |
| **6** | **A terminal non-position entry → `pnl=0` is TRUE, not fabricated** | Entry order `status="canceled"`, `filled_qty=0`. Assert `status == "canceled"`, `exit_price is None`, `pnl == 0` | The `0` here is **honest** (`src/order_resolution.py:14`: no position ever existed). Distinguishes the legitimate zero from the fabricated one — and stops an over-eager fix from NULL-ing it |
| **7** | **An ambiguous / partial close → unresolvable** | `get_closed_orders` returns an opposite-side order whose `filled_qty` is **half** the entry's. Assert `pnl is None` (`_match_close`'s `_QTY_TOLERANCE` rejects it → `src/backfill.py:124-127`) | The resolver refuses to guess. Half a close is not an exit |
| **8** | **A row with no `order_id` → NULL** | `row["order_id"] = None`; symbol gone. Assert `pnl is None`, `status == "closed"` | Pre-Phase-11 rows have no `order_id` (`src/db_schema.sql:44`, nullable). They resolve to NULL, not 0.0 |

### B2 — `get_alpaca_accuracy` excludes NULL, and all three consumers still work

| # | Case | Test | Proves |
|---|---|---|---|
| **9** | **NULL excluded from the denominator** | Rows: 2 wins (`pnl>0`), 3 real losses (`pnl<0`), 1 `pnl=0.0`, **4 `pnl=NULL`**. Assert `resolved == 6` (**not 10**), `wins == 2`, `losses == 4` (`3 losses + the 1 real zero`), `win_rate == pytest.approx(2/6)` | **The core fix.** Under today's code this fixture yields `resolved=10`, `losses=8`, `win_rate=0.20` — the 12.4%-vs-33% bug. `pnl=0.0` is **still counted** (Decision 2 licenses excluding NULL only, not zero) |
| **10** | **Non-vacuous: the old arithmetic gives a DIFFERENT answer** | On the same fixture, compute the pre-fix expression inline (`resolved_old = len(all_terminal)`, `wins_old = sum(1 for r if (r["pnl"] or 0) > 0)`, `losses_old = resolved_old - wins_old`). Assert `win_rate_new != win_rate_old` **and** `losses_new < losses_old` | The change is real and measurable, not a no-op that happens to pass |
| **11** | **Sums are unaffected** | Assert `total_pnl == pytest.approx(sum of the 6 real pnls))` and that adding more NULL rows does **not** change `total_pnl` | NULL never contributed to the sum anyway (`r["pnl"] or 0.0`). **The bug was always in the DENOMINATOR** — this pins that the fix did not accidentally move the numerator |
| **12** | **Existing consumers still work** | Re-run `tests/test_db.py:34` and `tests/test_trade_logger_shim.py:18` unmodified. Assert the returned dict still has **every** key (`total_trades`, `resolved`, `wins`, `losses`, `win_rate`, `total_pnl`, `avg_pnl`, `crypto_pnl`, `stock_pnl`) — the **shape is unchanged**; only the row filter moved | **No silent display break.** `src/alpaca_orchestrator.py:577` and `:1254` read this dict positionally-by-key; a dropped key is a crash in the live bot |
| **13** | **B2 — the DASHBOARD's two duplicated denominators are ALSO fixed** | Static: read `dashboard/api/routes/portfolio.py` and `dashboard/api/routes/settings.py`; assert **each** closed-trades query contains `pnl IS NOT NULL`. Positive control first (each file's slice contains `status IN ('closed', 'stopped', 'target_hit')`). Behavioral: against `TEST_DATABASE_URL`, seed the case-9 fixture, `GET /api/portfolio`, assert `win_rate == 33.3` (**not `20.0`**) | **THE BLOCKER `18-CONTEXT.md` MISSES.** The dashboard does **not** call `get_alpaca_accuracy` — grep-verified. It has its own SQL at `portfolio.py:64-76` and `settings.py:37-61`. Fixing `src/db.py` alone leaves the headline wrong **and books every new NULL row from the case-2 fix as a fresh loss.** `settings.py:135`'s `win_rate` vs `win_rate_target=40.0` **is the paper-gate readout** |

### B3 — the backtester knobs are real, and the engine matches the live bot

| # | Case | Test | Proves |
|---|---|---|---|
| **14** | **`--min-confluence` actually changes the trade count (NON-VACUOUS)** | Run the engine over the **same** bars at `min_confluence=3` and `min_confluence=4`. Assert `len(trades_at_3) > len(trades_at_4)` — **a strict inequality, and both > 0**. A test asserting only "it runs" would pass on a knob that is wired to nothing | **The knob is load-bearing.** The whole sweep is meaningless if `--min-confluence` does not move the entry gate at `engine.py:124` |
| **15** | **`--kelly-fraction` actually changes position size (NON-VACUOUS)** | Same bars, `kelly_fraction=0.15` vs `0.25`. Assert the first trade's notional at `0.25` is **strictly greater** than at `0.15`, and `pytest.approx`-equal to the computed grid (`conf=4 → 5.00%` vs `3.00%` of equity, per `18-RESEARCH.md` §2.3) | The sizing knob is wired to `_position_dollar_amount` (`engine.py:132-137`), and the numbers match the live formula |
| **16** | **The quarter-Kelly CEILING is enforced at the CLI** | `main(["--phase","0","--train","--kelly-fraction","0.50"])` → **`SystemExit` (exit 2, `parser.error`)**. Also assert `0.25` is accepted | **HARD RULE.** `kelly_fraction` may only go DOWN. This makes a risk-rule violation *unrunnable*, not merely discouraged. Bot B's historical `0.50` must not be reachable from any backtest result |
| **17** | **The 5% max-position cap is never breached** | Across the whole legal grid (`conf∈{3,4}` × `k∈{0.15,0.20,0.25}`), assert every `_position_dollar_amount(...) / equity <= 0.05 + 1e-9` | The hardcoded max-5%-bankroll rule holds by construction (`engine.py:33`) |
| **18** | **`min_confluence=5` yields ZERO trades — the grid row is provably vacuous** | (a) Static: assert **each** branch of `src/technical_signals.py`'s scoring block contains exactly **four** `score += 1` (`:371-386` and `:387-404`). (b) Behavioral: run the engine at `min_confluence=5` over the fixture bars; assert `len(trades) == 0`. (c) Assert `max(s.confluence_score for s in all_signals) <= 4` | **B3 / C1.** `18-CONTEXT.md` Decision 4 asserts *"5 = all five indicators; the engine scores 0-5"* — **FALSE.** The ceiling is **4** (`src/technical_signals.py:40`, `:361`; volume-spike deliberately excluded at `:405-406`; live logs `confluence=%d/4` at `bot_thread.py:813`). The six `mc=5` cells are empty and **must be recorded as such in `18-BACKTEST.md`**, not silently dropped |
| **19** | **The quarantine is applied by the LIVE gate, not a re-implementation** | Run the engine with `quarantined=("BTC/USD",)` over BTC+ETH bars. Assert **zero** BTC trades and **non-zero** ETH trades. Then assert `src/backtester/engine.py` **imports** `entry_allowed` from `src.universe` (static grep) and contains **no** `in exclude` / `.replace("/","")` ad-hoc gate | **TUNE-03's core claim.** The backtest gate must be *literally the same predicate* as the live gate (`src/universe.py:26`, used at `bot_thread.py:146,165,355`). A re-implemented gate is how a backtest silently stops validating the live bot |
| **20** | **`rsi_ceiling` is enforced, and it is NON-VACUOUS** | Assert the engine skips a signal with `rsi_value >= config.rsi_ceiling`. Then assert `run(rsi_ceiling=65.0)` yields **strictly fewer** trades than `run(rsi_ceiling=inf)` on the same bars | **B3 / C2.** The live bot rejects overbought longs (`bot_thread.py:147`, `cfg.rsi_ceiling=65.0`); the engine did **not**. Without this, the backtest enters setups the live bot refuses — inflating trade counts **at exactly the confluence levels being swept** |
| **21** | **The refactor introduced no INCIDENTAL behavior change** | Pin: with `symbols=()`, `quarantined=()`, **`rsi_ceiling=float("inf")`**, the engine's trade history over the fixture is **byte-identical** to the pre-Phase-18 engine's (golden list committed in the test) | CONTEXT Decision 6: *"the engine's behavior at the current defaults must be bit-identical."* The RSI guard is a **deliberate** fidelity fix (case 20), so the pin disables it — proving the *plumbing* changed nothing while the *fidelity fix* changed exactly one thing. **Baseline and candidate in `18-BACKTEST.md` must BOTH be run on the final engine** (P3) |
| **22** | **The sweep is reproducible** | Run the same cell (same cached bars, same config) **twice**; assert identical `trade_history` and identical `compute_summary` output. Assert the engine contains **no RNG** (static: no `random`/`np.random` import) | Determinism is the only thing making the 18-cell grid in `18-BACKTEST.md` auditable. Bar provenance is the sole reproducibility risk → the cache is committed/recorded, not re-fetched per cell |

### Prod safety — `AIPW_DB_READONLY`

| # | Case | Test | Proves |
|---|---|---|---|
| **23** | **`AIPW_DB_READONLY=1` genuinely prevents DDL — no bootstrap runs** | Monkeypatch `src.db._bootstrap_schema` with a spy that sets a flag. Reset `src.db._pool = None`. With `AIPW_DB_READONLY=1`, call `get_pool()`; assert **the spy was NEVER called**. Reset `_pool = None`, unset the flag, call `get_pool()`; assert **the spy WAS called**. Reset `_pool = None` in teardown | **W1 closed.** `get_pool()` (`src/db.py:40-45`) calls `_bootstrap_schema()` (`:48`), which executes `src/db_schema.sql` — **DDL + `INSERT INTO bots`** — against whatever `DATABASE_URL` names. The both-directions assertion is what makes this non-vacuous: asserting only the skip would pass even if bootstrap were deleted entirely |
| **24** | **Read-only is enforced SERVER-side, not by convention** | `TEST_DATABASE_URL`-gated. With `AIPW_DB_READONLY=1`, open a pooled connection and attempt `CREATE TABLE _aipw_probe (x int)`; assert it raises `psycopg.errors.ReadOnlySqlTransaction` (SQLSTATE **`25006`**). Assert a `SELECT 1` still succeeds. **Assert the connection's dbname/host match the parsed `TEST_DATABASE_URL` BEFORE the probe** | A client-side convention is not a fence. `default_transaction_read_only=on` is enforced by Postgres and cannot be forgotten by a caller. The dbname pre-check is the Phase-17-C3 prod guard — **a test that accidentally points at prod must fail loudly, not write** |
| **25** | **Default (unset) behavior is byte-identical** | With `AIPW_DB_READONLY` unset, assert the pool's connection has `default_transaction_read_only` **off** and that `_bootstrap_schema` ran | "No service changes" (Decision 8). The bots and the dashboard **must** still write |

### Rollout — config-only, no code

| # | Case | Test | Proves |
|---|---|---|---|
| **26** | **The quarantine list is applied CONFIG-ONLY — zero code change** | `BotConfig.from_row({... "quarantined_symbols": "BTC/USD,ETH/USD,TRUMP/USD,FIL/USD,ARB/USD"})`; assert `cfg.quarantined == ["BTC/USD","ETH/USD","TRUMP/USD","FIL/USD","ARB/USD"]` (`src/bot_config.py:78-80`) and that `select_long_candidates` (`bot_thread.py:130`) **drops** a `confluence=4` BTC signal while **keeping** an identical SOL one. **No `src/` diff is required for this behavior** | **TUNE-03's "reversible via config."** The deny-list is a DB string → `BotConfig` property → `entry_allowed`. Proves the quarantine ships as data, and reverts as data |
| **27** | **`PUT /api/bots/{bot_id}` accepts all three knobs and hot-swaps** | Against `TEST_DATABASE_URL`: `PUT` `{"min_confluence": 4, "kelly_fraction": 0.20, "quarantined_symbols": "BTC/USD,ETH/USD"}`; assert 200, assert the `bots` row is updated, and assert `BotManager.update` was called with those keys (`dashboard/api/routes/bots.py:208`) | The rollout path (Decision 7) is a **row update, not a deploy**. All three fields are on `BotUpdate` (`dashboard/api/models.py:258,259,276`) and the route builds its `SET` dynamically from non-`None` fields (`:187`) |
| **28** | **`kelly_fraction > 0.25` cannot be rolled out** | `PUT {"kelly_fraction": 0.50}` — assert it is **rejected** (the API-side mirror of case 16) | The CLI guard is worthless if the *rollout* path can still raise Kelly. Bot B's historical `0.50` must be unreachable from **every** direction |
| **29** | **No prod write, anywhere in the suite** | Static fence over `tests/` and any Phase-18 sweep script: no `DATABASE_URL` reference (only `TEST_DATABASE_URL`); no `--apply`/`--write`/`--fix` argparse surface on the sweep driver. **Self-test:** the same fence applied to `src/db.py:101-122` (`update_alpaca_trade`) **MUST match** — proving the detector actually fires | Phase-17 case 20/21 pattern. Without the self-test an empty slice passes vacuously |

---

## Coverage → requirement map

| Requirement | Cases |
|---|---|
| **TUNE-01** — retune confluence + quarter-Kelly on the real dataset + backtest; win rate ≥40%; halted drawdown | 9–13 (the win rate becomes **measurable**), 14–18 (the knobs are real and the grid is honest), 16/17/28 (the risk rules hold), 22 (reproducible) |
| **TUNE-03** — validated against the existing backtest; reversible via config/env | 19–21 (the backtest validates **the strategy the bot runs**), 22 (auditable), 26–28 (**reversible via config, zero code**) |
| **Decision 2** — sentinel fix, NULL not zero | 1–8 |
| **Decision 8** — W1 closed | 23–25 |
| **Fences** — never write prod | 24, 29 |

---

## Wave-0 gap

**These do not exist yet and block everything downstream. They are Wave 0.**

- [ ] **⛔ BLOCKER — cached Alpaca bars, 8 symbols × 2025-10-01 → 2026-04-30.**
      `tests/backtester/fixtures/` contains **exactly one file: `BTC_USD.json`, 60 bars.**
      `SIGNAL_WINDOW=50` + `SCAN_INTERVAL_BARS=30` means that affords **at most one scan**.
      Worse: **the one fixture symbol is BTC — the headline quarantine target.** A fixture-only sweep
      with `--exclude-symbols BTC/USD` has **zero tradeable symbols**, so every cell returns
      `trades=0`, drawdown `0.0`, and **the quarantine arm "wins" vacuously.** The sweep would
      produce a confidently wrong answer.
      → Fetch via `load_bars_cached` (`src/backtester/data_loader.py:54`) **once**, `save_bars_cache`
      (`:75`), run all cells against the same cache. **Report per-symbol bar counts before cell #1**
      (assumption A4 — a symbol short of bars yields thin cells).
- [ ] `tests/test_external_exit_resolution.py` — cases 1–8 (`FakeAlpaca` from `tests/test_backfill.py:96`)
- [ ] `tests/test_db_readonly.py` — cases 23–25
- [ ] `tests/backtester/test_cli_overrides.py` — cases 14–17, 22
- [ ] Extend `tests/backtester/test_engine.py` — cases 18–21
- [ ] Extend `tests/test_db.py` — cases 9–12 (**re-read `tests/test_db.py:34` first** — it asserts on
      the accuracy dict and may need updating)
- [ ] Dashboard route tests — case 13 (`dashboard/api/tests/`)
- [ ] `TEST_DATABASE_URL` must be set for cases 13, 24, 27, 28 — else they **skip** (and the skip must
      be visible in the run, never silent)

---

## Non-negotiables (the verifier checks these directly)

1. **`pnl is None`, never `pnl == 0`, for an unresolvable exit.** Case 2. `0 == False` and
   `0 == None` are both traps in Python truthiness — assert identity.
2. **A transient Alpaca failure never writes anything.** Case 5. This is how a "fix" becomes a
   position-destroying outage.
3. **All THREE win-rate denominators.** Cases 9 + 13. Two of them are in the dashboard and
   `18-CONTEXT.md` does not mention them.
4. **`kelly_fraction` may only go DOWN.** Cases 16 + 28. Enforced at the CLI **and** the API.
5. **The `min_confluence=5` grid row is empty and is recorded as empty.** Case 18. Do not "fix" the
   score to reach 5 — that is a new strategy, which the phase fences forbid.
6. **The backtest gate is `src.universe.entry_allowed`, imported — not re-implemented.** Case 19.
7. **Never write to prod.** Cases 24 + 29. The only prod write in Phase 18 is the deliberate `bots`
   row update via `PUT /api/bots/{bot_id}` (Decision 7).
8. **Full suite ≥ 395 passed.**

## Revision 3 additions (plan-check round 2)

| # | Case | Test | Proves |
|---|------|------|--------|
| 4b | `_resolve_external_exit(alpaca, row, live_symbols=None)` returns `{}` — NO write, NO Alpaca call (FakeAlpaca records zero calls) | test_none_live_symbols_is_no_op | THE THIRD DOOR. `None` means get_positions() FAILED (alpaca_orchestrator.py:160-163); it does NOT mean "nothing is held". Coercing it to an empty set terminates EVERY open position as closed/NULL and the monitor abandons live positions with their stops unwatched. |
| 5b | `get_order` raising and `get_closed_orders` raising, INDEPENDENTLY, each yield `{}` | test_each_alpaca_call_fails_closed | a transient failure must never fall through into the unresolvable branch (`grep -c "try:"` was a weak proxy) |
| 28d | `BotConfig.from_row({"kelly_fraction": 0.50, ...}).kelly_fraction == 0.25` | test_kelly_clamped_on_read | THE READ-SIDE CLAMP. Every WRITE path is now bounded, but a row written BEFORE those bounds existed (Bot B's live row) is still 0.50 and nothing clamps it on read. `from_row` (src/bot_config.py:49) is the single choke point every bot reads through — clamping there makes the hardcoded quarter-Kelly ceiling TOTAL, not perimeter-only. |

**Baseline reminder:** full suite 395 passed / 24 skipped.
