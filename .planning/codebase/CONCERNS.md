# Codebase Concerns

**Analysis Date:** 2026-05-31

> Severity-ranked technical debt, risks, and watch-items for the AI Predicted Wins
> automated trading system. Each item lists files, impact, and a fix approach so it
> can be turned into a remediation phase. Findings verified against `src/`,
> `dashboard/`, `gateway/`, and project memory.

---

## High Severity

### 1. Secrets handling — `.env` and `private_key.pem` on disk
- **Issue:** All API keys (Alpaca A/B/C, MiroFish, gateway, email, `DATABASE_URL`)
  live in a gitignored `.env`; the Kalshi RSA signing key sits in
  `private_key.pem` at repo root.
- **Files:** `.env`, `private_key.pem`, `src/kalshi_client.py` / `src/orchestrator.py`
  (load the key), `src/config.py`, Coolify env config.
- **Impact:**
  - A private signing key on the container FS is high-value; shell access or a
    path-traversal bug in the dashboard exfiltrates it.
  - `.env` holds multiple distinct Alpaca accounts (A, B, C) — a shared-ref bug
    points two bots at one account, explicitly forbidden by the "ONE ACCOUNT PER
    BOT" hard rule (corrupts P&L, dedups out one bot's trades).
  - Accidental-commit risk if `.gitignore` is edited.
- **Fix approach:** Keep secrets in Coolify env only; load the Kalshi key from an
  env var / secret mount, never materialize `private_key.pem`. Add a startup
  assertion that each bot's `ALPACA_API_KEY_*` is distinct. CI check that
  `.env` and `*.pem` stay gitignored.

### 2. Gateway auth fragility — Claude CLI OAuth login expiry
- **Issue:** MiroFish LLM panel, exit advisor, copytrade, and the gateway depend on
  a Claude Max plan via `claude login` OAuth inside the Coolify container. Token
  expires; must be re-established manually in the Coolify terminal. Memory states
  **no Anthropic API-key fallback is permitted** (OAuth + `CLAUDE_CREDENTIALS` only).
- **Files:** `gateway/main.py`, `gateway/entrypoint.sh`, `src/mirofish_client.py`,
  `src/risk_gate.py`, `src/exit_advisor.py`, `src/claude_llm.py`,
  `src/claude_copytrade.py`, `/root/.claude` volume.
- **Impact:** Expired token → gateway 500s → every LLM path degrades. If the
  exit-advisor call errors, soft-threshold exits may not fire, leaving positions
  on stale logic until hard thresholds hit. No automatic recovery.
- **Fix approach:** Verify `/root/.claude` is on a persistent volume. Add a CLI
  health check that alerts (emails4agents) on auth failure *before* it blocks
  trading. Make LLM call sites fail safe — gateway down ⇒ fall back to the
  deterministic hard stop/take-profit thresholds, never skip exits.

### 3. Single-container coupling: dashboard + API + BotManager
- **Issue:** Next.js dashboard, FastAPI, and the BotManager (live trading threads
  for Bot A/B/C) run in one Coolify container at `app.aipredictedwins.com`,
  orchestrated by `dashboard/supervisord.conf` + `dashboard/entrypoint.sh`.
- **Files:** `dashboard/supervisord.conf`, `dashboard/entrypoint.sh`,
  `src/bot_manager.py`, `src/bot_thread.py`, `src/copytrade_thread.py`,
  `src/alpaca_orchestrator.py` (60s position-monitor thread).
- **Impact:**
  - A dashboard deploy/rebuild restarts the trading bots; the 60s monitor thread
    dies mid-cycle on every redeploy — open positions can miss a soft-exit window.
    (The 50-trade paper-gate count itself is in Postgres and survives rebuilds; the
    in-memory monitor thread state does not.)
  - A crash/leak in the web layer kills the trading engine (and vice versa). No
    process isolation between "show a chart" and "manage real money."
  - `/health` can return 200 while a BotManager thread has silently died
    (thread-level failure not surfaced at HTTP).
- **Fix approach:** Split the trading engine into its own long-lived Coolify
  service decoupled from web deploys. Add a BotManager liveness heartbeat
  (row/endpoint) so a dead trading thread fails the health check.

---

## Medium Severity

### 4. MiroFish risk gate evaluated as counterproductive
- **Issue:** Per `project_mirofish_evaluation.md` (2026-04-09) the MiroFish
  5-analyst risk gate is **counterproductive** (~$2K monitor-P&L gap); exit-advisor
  value "unclear." Bot B already runs with the gate **off** as the A/B control.
- **Files:** `src/risk_gate.py`, `src/exit_advisor.py`, `src/mirofish_client.py`,
  `src/alpaca_orchestrator.py` (pipeline step 4), `dashboard/api/routes/risk_gate.py`.
- **Impact:** Vetoes valid technical signals and adds an LLM round-trip (latency +
  gateway-auth fragility, #2) on the entry hot path. If net-negative, it loses money
  while adding a failure mode; combined with low-confluence idle periods it may be
  starving the bot of trades.
- **Fix approach:** Conclude the A/B test, then make the gate config-gated
  (default off) rather than a hard stage. Demote MiroFish to advisory logging until
  it shows positive EV. Document the decision so it isn't silently re-enabled.

### 5. PAUSED Kalshi orchestrator — dormant / dead code path
- **Issue:** The entire Kalshi prediction-market pipeline is paused but still
  present and importable. CLAUDE.md: "do not run the Kalshi orchestrator."
- **Files:** `src/orchestrator.py`, `src/kalshi_client.py`, `src/gap_detector.py`,
  `src/market_evaluator.py`, `src/event_formatter.py`, `src/quick_simulator.py`,
  `private_key.pem` (only used here), `kalshi-python-sync` dep.
- **Impact:** Dead code rots and still imports the high-value RSA key + unused SDK;
  risk of accidental execution placing real prediction-market trades; maintenance
  tax on shared modules (`mirofish_client`, `trade_logger`) for untested code.
- **Fix approach:** Archive behind a feature flag / branch and remove the key + SDK
  from the active runtime, OR add a hard guard at `orchestrator.py` entry that
  refuses to run without explicit `KALSHI_ENABLED=1`. Mark quarantined in docs.

### 6. Probability-extraction systematic bias (latent correctness bug)
- **Issue:** Per CLAUDE.md "Common Issues" and memory, the `extract_probability`
  prompt must ask for *agent consensus*, not the LLM's own estimate, or it defaults
  to 1–5% skepticism on everything ("all NO-side trades").
- **Files:** `src/mirofish_client.py` (extract_probability prompt).
- **Impact:** A prompt regression silently biases every probability downward →
  systematically wrong decisions with no exception raised. Mostly Kalshi-relevant
  (paused) but the client is shared.
- **Fix approach:** Add a sanity assertion flagging suspiciously uniform low
  probabilities; pin/version the prompt; comment why it anchors on consensus.

### 7. Error-handling gaps on the trading hot path
- **Issue:** Many network-dependent steps (Alpaca bars, gateway LLM calls,
  ai4trade client, order placement) plus the 60s monitor thread. Recent commits
  show recurring failures (gateway 500s, empty-feed skips, ai4trade client timeout
  bumped to 90s, leader-discovery fallback).
- **Files:** `src/alpaca_orchestrator.py`, `src/technical_signals.py`,
  `src/risk_gate.py`, `src/exit_advisor.py`, `src/mirofish_client.py`,
  `src/ai4trade_client.py`, `src/bot_thread.py`, `src/copytrade_thread.py`.
- **Impact:** An unhandled exception in the monitor thread can die silently
  (single-container, no thread liveness — #3), leaving positions unmanaged.
  LLM-call timeouts on entry can block/skip trades. No evident circuit breaker /
  retry-with-backoff.
- **Fix approach:** Supervise the monitor loop with restart + alerting. Bound every
  LLM/exchange call timeout with deterministic-rule fallback. Log a line on each
  caught exception so silent failures surface (INFO logging was only just enabled —
  observability is thin).

### 8. Untested vendored TradingAgents + Bot C / copytrade surface
- **Issue:** Large vendored dependency `vendor/TradingAgents/` and newer Bot C
  (`src/bot_c/`, `src/claude_copytrade.py`, `src/copytrade_thread.py`,
  `src/ai4trade_client.py`) expand the live-money surface area. Bot C uses an
  `llm_shim` and a leader-discovery copytrade flow with recent fix churn.
- **Files:** `src/bot_c/strategy.py`, `src/bot_c/llm_shim.py`,
  `src/claude_copytrade.py`, `src/copytrade_thread.py`, `src/ai4trade_client.py`,
  `vendor/TradingAgents/`.
- **Impact:** Copytrade depends on an external ai4trade server (30–45s responses,
  90s client timeout) — a slow/down leader feed stalls the bot. Vendored code is a
  supply-chain + maintenance liability.
- **Fix approach:** Add timeouts/circuit breaker around ai4trade; pin/document the
  vendored TradingAgents version; add smoke tests for Bot C strategy + copytrade
  fallback.

### 9. Stale BOT_ID validation hardcodes ("A","B") — rejects Bot C
- **Issue:** `src/trade_logger.py` is now a thin Postgres shim (good — see "Resolved"
  below), but its `BOT_ID` env-var path still validates against `("A","B")` and
  raises if the value is `"C"` or a UUID. The DAL's canonical set is
  `KNOWN_BOTS = ("A","B","C")` (`src/db.py` / `dashboard/api/db.py`).
- **Files:** `src/trade_logger.py` (lines ~26–30), `src/db.py`,
  `dashboard/api/db.py`.
- **Impact:** A Bot C process instantiating `TradeLogger()` via the env path crashes
  on startup; only the explicit-`bot_id`-kwarg path works. Inconsistent multi-bot
  support; latent footgun as bots are added.
- **Fix approach:** Validate against `KNOWN_BOTS` (or accept any non-empty id) in the
  env path; centralize the bot allowlist in one module.

---

## Low Severity

### 10. Bot idle / unmet weekly return target
- **Issue:** Per memory the bot sits idle on low confluence; 7–10%/week target
  unmet (equity ~$98,380 vs $100,000 breakeven gate).
- **Files:** `src/technical_signals.py` (confluence threshold), `src/bot_config.py`.
- **Impact:** Conservative confluence filter (3+ bullish indicators) plus
  risk-gate vetoes may over-throttle entries, stalling the paper-trade gate.
- **Fix approach:** Tune confluence per-bot (partly done in A/B); track trade
  frequency as a first-class metric.

### 11. Unimplemented Options v3 spec drift
- **Issue:** Options (calls/puts/spreads/multi-leg) spec exists
  (`project_options_v3_plan.md`, 2026-04-01) but is not implemented.
- **Impact:** Spec/code drift; risk of half-built options code added ad hoc.
- **Fix approach:** Keep clearly marked "not implemented"; gate options work behind
  its own phase.

### 12. Hardcoded risk constants risk drifting out of sync
- **Issue:** Critical invariants (max 5%/position, quarter-Kelly 0.25, 20% drawdown
  stop, soft/hard thresholds -2%/+5% and -4%/+10%) are "HARDCODED — never override."
- **Files:** `src/alpaca_orchestrator.py`, `src/risk_gate.py`,
  `src/position_sizer.py`, `src/bot_config.py`.
- **Impact:** If duplicated across modules, a future edit could change one and not
  another, silently violating the hard rules. Low likelihood, high blast radius.
- **Fix approach:** Centralize all risk constants in one config module with a lock
  test asserting the values; reference from a single source of truth.

---

## Resolved / Stale-Docs Watch-Items

### SQLite trade DB → Postgres (RESOLVED; docs stale)
- **Status:** RESOLVED. `src/trade_logger.py` is now a thin shim over `src/db.py`
  (Postgres via `psycopg` + `DATABASE_URL`). The `db_path="data/trades.db"` kwarg is
  ignored, kept only for call-site backward compat. The dashboard API
  (`dashboard/api/db.py`) reads the same Postgres tables, `bot_id`-filtered. No live
  code path writes SQLite.
- **Residual:** CLAUDE.md and `data/trades.db` references still describe SQLite as
  the trade DB — **stale docs**. Update CLAUDE.md "Architecture" / "Key Files" to say
  Postgres. (The leftover `BOT_ID` validation bug is tracked separately as #9.)

### `_PLACEHOLDER_SIGNALS` mock data in signals route (RESOLVED)
- **Status:** RESOLVED. `dashboard/api/routes/signals.py` previously returned a
  hardcoded `_PLACEHOLDER_SIGNALS` array with two `TODO` comments; it now reads real
  technical-scan rows from Postgres (empty list pre-first-scan). The TODO strings
  survive only in `.claude/skills/ui-data-audit-workspace/` audit artifacts.

---

## Test Coverage Gaps

- **Bot-side trading logic largely untested.** Highest-stakes code — Kelly sizing
  (`src/position_sizer.py`), hard-threshold exits (`src/alpaca_orchestrator.py`,
  `src/exit_advisor.py`), and P&L attribution (`src/trade_logger.py` / `src/db.py`)
  — has no visible unit suite. **Priority: High.** A refactor could break stop-loss
  firing or double-trade a symbol with no failing test.
- **Dashboard API has some tests** (`dashboard/api/test_api.py`,
  `dashboard/api/tests/test_db.py`, `test_routes.py`) — good, but coverage of the
  trading engine itself is the gap.
- **No regression test** guarding the probability-extraction prompt bias (#6).
- **No integration test** simulating gateway-down → fallback-to-hard-thresholds (#2).
- **No smoke test** for Bot C copytrade / ai4trade-down fallback (#8).

---

## TODO / FIXME Markers

- **`src/`, `gateway/`, and `dashboard/api/` are clean** — no `TODO`/`FIXME`/`HACK`
  markers in production source as of this scan.
- The only `TODO` hits are in `dashboard/web/node_modules/` (third-party,
  not actionable) and in historical audit artifacts under
  `.claude/skills/ui-data-audit-workspace/` (evidence of the now-fixed
  `_PLACEHOLDER_SIGNALS` issue).

---

*Concerns audit: 2026-05-31*
