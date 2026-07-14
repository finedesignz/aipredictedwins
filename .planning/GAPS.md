# Gap List — aipredictedwins

Generated 2026-07-12 from three independent audits: code/architecture, planning/operations, and a capability benchmark against `virattt/ai-hedge-fund`.

Severity: **P0** = exploitable now or corrupts money/decisions. **P1** = will bite before live. **P2** = debt.

---

## P0 — Security

### S1. Gateway has no authentication
`gateway/main.py:52-95` — `/v1/chat/completions` accepts unauthenticated requests and spawns `claude -p` subprocesses on the Max plan. Anyone who finds the URL can burn the plan.

**Fix:** require `X-API-Key`/bearer on all `/v1/*` routes; reject unknown keys.

### S2. Path traversal into the Claude CLI's working directory
`gateway/main.py:110` — `_resolve_project(x_project)` resolves an attacker-controlled `X-Project` header to a directory under `PROJECTS_DIR`. A `../../` value points the Claude CLI — which has file tools — at an arbitrary cwd. Compounds S1.

**Fix:** whitelist the name (`re.fullmatch(r"[a-z0-9_-]+")`) and assert `Path.resolve().is_relative_to(PROJECTS_DIR)`.

### S3. Dashboard auth fails open
`dashboard/api/main.py:103-125` — `if not DASHBOARD_TOKEN: return` skips the auth check entirely when the env var is unset or empty, and `/api/auth/login` returns success for any token in that state. A Coolify env typo silently exposes bot create/delete and position data.

**Fix:** fail closed — raise at startup if `DASHBOARD_TOKEN` is empty; delete the dev-mode branch.

### S4. Token compared with `==`, and the token is the session cookie
`dashboard/api/main.py:114,122` — timing-comparable, no rotation, 30-day `max_age`, and the secret is echoed back as the cookie.

**Fix:** `hmac.compare_digest`; move to a signed session cookie.

### S5. Alpaca API keys stored in plaintext in Postgres
`dashboard/api/routes/bots.py:146-163`, `dashboard/api/alpaca_health.py:30` — key + secret live in the `bots` table and are selected back on every enable/create. A DB dump or one SQL injection yields live broker credentials.

**Fix:** encrypt at rest (app-level Fernet, key from env), or keep keys in Coolify env referenced by `bot_id`.

---

## P0 — Money / correctness

### M1. The drawdown stop does not stop
`src/alpaca_orchestrator.py:687-698` — on breach the loop sleeps 3600s and continues. It does not flatten positions, does not persist a halt flag, and `daily_pnl` resets at UTC midnight. A container restart clears the state entirely and the bot resumes trading.

**Fix:** persist `halted_at` / `halt_reason` per bot; `BotThread` refuses entries while set; manual unhalt via API.

### M2. Three conflicting values for that same kill switch
`src/alpaca_orchestrator.py:69` defaults `DRAWDOWN_STOP_PCT=0.10`; `src/config.py:41` says `0.20`; `src/orchestrator.py:40` hardcodes `0.20`; CLAUDE.md claims 20% "HARDCODED — never override" while it is in fact env-overridable. Two live code paths halt at different thresholds.

**Fix:** one constant, one module, no env override.

### M3. Fabricated exit fills poison P&L, the learning loop, and the live gate
`src/alpaca_orchestrator.py:302-310` — when `filled_avg_price` is 0, the code substitutes the last quote as the exit fill. The sentinel writer also fabricates `pnl = 0.0` on external exits. Booked P&L is fiction, and it feeds `learning_loop.py` **and** the paper-to-live gate.

**Fix:** land Phase 18-03 (resolve the real exit or write NULL) and 18-04 (fix the win-rate denominator at all three sites). Never book a synthetic fill — mark `status='unresolved'` and reconcile from the Alpaca order later.

### M4. Order-submit retry can double-fill
`src/alpaca_client.py:45-63` — `_retry` retries every `Exception`, and it wraps `submit_order` (lines 326, 374). A timeout on an order that actually landed produces a duplicate order.

**Fix:** pass a `client_order_id` for idempotency, or retry reads only.

### M5. The live gate can be passed by a bug
CLAUDE.md gates live trading on "win rate > 40%" — computed from the fabricated zeros in M3.

**Fix:** gate on reconciled Alpaca P&L (Phase 13 output), not the trade log. Add an explicit go-live checklist.

---

## P1 — Reliability

- **PositionMonitor can die silently.** `src/alpaca_orchestrator.py:135-145` catches `Exception` around `_check_all_positions()` and loops forever. On a persistent failure (bad creds, schema drift) stops never fire but the thread still looks alive. → Count consecutive failures; after N, halt entries.
- **Order-placement failure is swallowed.** `src/bot_thread.py:372-373` — no retry, no dead-letter, no alert. A broker outage is indistinguishable from "no signals". → Alert + counter; retry network errors, not rejections.
- **`cancel_order_by_id` swallows its exception.** `src/alpaca_client.py:394-397` — stale limit orders linger past `LIMIT_ORDER_TIMEOUT_S` and can double-fill next cycle.
- **24 blanket `except Exception` sites in `src/bot_thread.py`** (114, 243, 275, 294, 314, 329, 402, 428, 450, 496, 512, 529, 555, 564, 577, 593, 599, 624, 631, 723, 780, 872, 926, 978, 1066) — the bot keeps trading in a partially broken state. → Narrow to the calls that legitimately fail.
- **No crash-recovery reconciliation on boot.** Positions/orders opened before a crash are only re-found by the monitor's live scan. `src/reconciliation.py` and `src/backfill.py` run from cron, not at `BotThread` startup.
- **Orphan-order cleanup is a one-off script for Bot C** (`scripts/close_bot_c_orphans.py`). → Generalize into a periodic per-bot sweep.
- **Two `NotImplementedError` stubs in the query layer** (`dashboard/api/db.py:82-92`) — un-migrated routes 500 at call time rather than failing at import.

## P1 — Tests / CI

- **441 tests, none run in CI.** The only workflow is `docs-drift.yml`. A broken risk gate merges green. → Add a required `pytest` job.
- **`pytest` at repo root is red out of the box** — 14 collection errors from `vendor/TradingAgents/tests/` (`ModuleNotFoundError: cli.utils`). → `--ignore=vendor` in `pytest.ini`.
- **The entire live trading path has zero direct tests:** `alpaca_orchestrator.py` (1364 LoC), `bot_thread.py` (1075), `alpaca_client.py`, `risk_gate.py`, `bot_manager.py`, `gateway/main.py`. Coverage today is the pure functions (indicators, PnL, universe). → Fake `AlpacaClient`; test the drawdown halt, monitor hard-stop, order-fail path, dedup.

## P1 — Strategy validation (Phase 18 is planned but unexecuted: 7 plans, 0 done)

- **The backtester does not run the live strategy.** No `entry_allowed`, wrong `rsi_ceiling`, hardcoded 8-symbol list, no confluence/Kelly knobs (`src/backtester/cli.py:27-30`). Any sweep run today measures a different bot than the one trading. → Land 18-05 before 18-06.
- **No cached historical bars** — the 18-cell sweep has nothing to run on. Marked Wave 0 BLOCKER. → Execute 18-02.
- **Overfit risk is designed-for but not enforced.** The retune fits knobs to ~260 honest rows. The plan's mitigations are sound (TRAIN/HOLDOUT, holdout viewed once, ≥30 holdout trades, negative result shippable) — the risk is plan drift. → The verifier must check literally: one holdout run, grid committed to `18-BACKTEST.md`, no re-pick.
- **No walk-forward, no regime labeling.** 2025-10 → 2026-04 is one crypto regime; a single holdout pass is not robustness. → Rolling-window WF + an ADX/vol regime tag before any live cutover.
- **Slippage is a static constant.** `SLIPPAGE_BUFFER` in `src/fee_gate.py` was never calibrated, though real fills are now recorded. → Compute realized fill-vs-limit deltas from `alpaca_trades`; feed the empirical value into both the gate and the backtester.
- **`AIPW_DB_READONLY` is designed but not implemented** — the backtester and `scripts/symbol_report.py` currently share a DB path with the live bots.

## P1 — Observability / data

- **No Postgres backup.** The trade history is the only record of whether this strategy has an edge, and there is no backup or retention policy. → Enable Coolify scheduled backups; verify a restore.
- **No bot-internals metrics.** No cycle latency, signal counts, gate-veto reasons, or LLM failure counters. Alerting is email-only, rate-limited, fire-and-forget. Dashboard headline P&L still reads the raw trade-log sum with no reconciliation-breach indicator. (This is Phase 19 — unplanned.)

---

## P1 — Worth stealing from `virattt/ai-hedge-fund`

Their valuable parts are the plumbing, not the headline LLM persona ensemble. Ranked:

1. **On-disk bar cache + committed fixtures** (their `src/data/cache.py` + `tests/fixtures/api/*`) — *S*. Unblocks 18-02 today, makes backtests reproducible, kills Alpaca rate-limit flake in tests.
2. **Sharpe / Sortino / max-DD as the retune objective** (their `src/backtesting/`) — *S*. Phase 18 optimizes win rate, which permits a strategy that wins often and loses big.
3. **A deterministic `risk_manager` that returns a per-symbol dollar cap** instead of a boolean veto — *M*. This is where correlation clusters belong: our 8 crypto assets are one beta, so five "independent" positions in BTC/ETH/SOL is one leveraged BTC bet. Currently unmodeled.
4. **A basket-level `portfolio_manager` as the sole order emitter** — *M*. Today `bot_thread.py` decides per-symbol inside a scan loop, so scan order decides who gets capital. Also gives one choke point for the Phase 15 universe gate.
5. **Confidence-weighted signal aggregation** — *M*. Every source emits `(signal, confidence, reasoning)`; one aggregator weights them. Beats the binary 3-of-5 confluence count, and directly serves Phase 18.
6. **Pydantic structured output + retry on LLM gate calls** — *S*. Gates parse free text; a malformed reply currently degrades silently.
7. **A persisted per-cycle decision trace** (their `--show-reasoning`) surfaced on the dashboard — *S*. Answers "why didn't the bot trade today?" without log-diving. `scripts/diag_no_trades.py` exists precisely because this is missing.

**Skip:** persona analyst agents (fundamentals-driven, no crypto signal, and no performance-attribution loop — our `learning_loop.py` + `symbol_stats.py` already puts us ahead there), LangGraph (overhead on a linear pipeline), the multi-provider LLM registry (violates Claude-CLI-only), the React-Flow canvas.

---

## P2 — Debt and drift

**Planning bookkeeping is inconsistent.** Milestone v1.1 is 4/10 phases done, but `STATE.md` says `status: completed`, the ROADMAP Progress table says every phase is "Not started", and the checkboxes mark 12/16/17 done while 11/13/14/15 have shipped `VERIFICATION.md` files. Three artifacts disagree. Phases 19 and 20 have no directories and no plans — orphaned. Root ROADMAP still headlines v1.0.

**Config sprawl.** ~120 env vars, ~60 of them `BOT_{A..D}_*` clones — but per-bot config already lives in the `bots` table. Adding Bot E means hand-editing `bot_config.py`, `seed_bots.py`, and Coolify.

**Dead code.** ~1800 LoC of PAUSED Kalshi path (`orchestrator.py`, `kalshi_client.py`, `gap_detector.py`, `market_evaluator.py`, `quick_simulator.py`) still imports, still tests, still pulls `private_key.pem` into the runtime image. `src/config.py` is a Kalshi-era dataclass while the Alpaca path reads `os.environ` directly — two config systems, neither authoritative.

**Three Alpaca clients** (`src/alpaca_client.py`, `dashboard/api/alpaca_client.py`, `dashboard/api/alpaca_health.py`); retry/rate-limit logic exists in only one.

**Nothing pinned.** All three `requirements.txt` use `>=` or bare names. A minor `alpaca-py`/`pydantic` release can change order semantics in production. `kalshi-python>=2.1.0` is still listed though the SDK in use is `kalshi-python-sync` 3.9.0.

**Latent bug:** `src/trade_logger.py` validates `BOT_ID in ("A","B")` — crashes Bots C/D through that path.

**CLAUDE.md is materially wrong** in four places:
- Says "Trade logger — SQLite at `data/trades.db`". It is Postgres (`src/db.py`, `psycopg`, `DATABASE_URL`, 18 migrations). The only remaining SQLite is the LLM response cache in `src/claude_llm.py` — which is fine, but means rule 26 is actually *satisfied* and only the docs lie.
- Says the MiroFish exit advisor runs in the position monitor. `src/alpaca_orchestrator.py:115-117` says exits are fully deterministic — ATR trailing stop plus hard/soft thresholds, no LLM calls.
- Says the universe is a fixed top-8 crypto list. It is dynamic (`DYNAMIC_UNIVERSE_SIZE`, `get_dynamic_crypto_universe`, `src/effective_universe.py`) and now includes stocks (`008_asset_class.sql`).
- Documents Bots A–D as a fixed set. Bot E (copytrade) exists (`012_copytrade_bot_e.sql`, `src/copytrade_thread.py`, `scripts/seed_bot_e.py`) and bots are DB rows created via `POST /api/bots`. Shorts also exist (`SHORT_ENABLED`) and are undocumented.

README disagrees with CLAUDE.md separately — it lists 3 bots and says MiroFish risk gate is on for Bot A, which v1.0 removed from the trading path.

---

## Suggested order

1. **S1–S5** — the gateway is exploitable today and the dashboard is one env typo from public.
2. **M1–M2** — the kill switch doesn't kill.
3. **CI green + tests running** (P1 tests) — so everything below can be fixed with a safety net.
4. **M3–M5** — stop fabricating P&L before anything reads it, including Phase 18.
5. **Phase 18 Wave 0** (18-02 bars, 18-03/04 data integrity, 18-05 backtest parity) — plus steal items 1 and 2, which land inside this phase.
6. Steal items 3–4 (risk manager, portfolio manager), then Phase 19 observability.
