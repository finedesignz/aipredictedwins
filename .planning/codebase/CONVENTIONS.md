# Coding Conventions

**Analysis Date:** 2026-05-31

## Naming Patterns

**Files:**
- `snake_case.py` modules under `src/`, named by responsibility. Active trading path: `alpaca_orchestrator.py`, `technical_signals.py`, `rules_gate.py`, `risk_gate.py`, `exit_advisor.py`, `alpaca_client.py`, `trade_logger.py`, `db.py`, `config.py`, `notifier.py`, `pipeline_state.py`, `claude_llm.py`.
- Multi-bot / copytrade: `bot_manager.py`, `bot_thread.py`, `bot_config.py`, `copytrade_thread.py`, `claude_copytrade.py`, `ai4trade_client.py`, plus `bot_c/` subpackage (`strategy.py`, `llm_shim.py`).
- Learning/memory: `trade_memory.py`, `learning_loop.py`, `signal_validator.py`, `trend_strategy.py`, `position_sizer.py`.
- Kalshi (PAUSED): `orchestrator.py`, `kalshi_client.py`, `gap_detector.py`, `market_evaluator.py`, `event_formatter.py`, `quick_simulator.py`, `mirofish_client.py`, `tradingagents_gate.py`.
- Backtester is its own subpackage: `src/backtester/` with `cli.py`, `engine.py`, `portfolio.py`, `metrics.py`, `data_loader.py`, `report.py`, `config.py`, `__main__.py`.

**Functions:**
- `snake_case` (`scan_assets`, `analyze`, `load_config`, `_kelly_technical`, `_check_market_regime`).
- Module-private helpers prefixed with underscore (`_ema`, `_rsi`, `_sma`, `_retry`, `_setup_logging`, `_print_banner`, `_select_cycle_candidates`).

**Variables:**
- `snake_case` locals. Module-level singletons also underscore-prefixed (`_rate_limiter`, `_HAS_LEARNING`).

**Constants:**
- `UPPER_SNAKE_CASE`, defined at module top under a `# Constants — hardcoded risk management rules` banner. Most are env-overridable (see Configuration).

**Types:**
- `PascalCase` classes (`AlpacaClient`, `TradeLogger`, `RulesGate`, `RiskGate`, `ExitAdvisor`, `PositionMonitor`, `Config`, `MiroFishClient`).
- `@dataclass` for value objects: `Signal` (`src/technical_signals.py`), `PipelineState` (`src/pipeline_state.py`), gate verdict dataclasses in `rules_gate.py`/`risk_gate.py`.

## Code Style

**Formatting:**
- No formatter/linter config in repo (no black/ruff/flake8 in `requirements.txt`, no `pyproject.toml`/`setup.cfg` detected). 4-space indent, double-quoted strings, ~100-col lines.
- Every module opens with a `"""triple-quoted docstring"""` describing purpose; sections separated by `# ---- banner ----` comment rules.
- Heavy use of `rich` (`Console`, `Panel`, `Table`) for operator-facing terminal output, distinct from `logging` for machine logs.

**Type Hints:**
- Used on most public functions/params/returns via builtin generics (`list[float]`, `dict`, `tuple[str, float, float]`) and `| None`. Not enforced (no mypy).

## Import Organization

Observed order (`src/alpaca_orchestrator.py`):
1. stdlib (`argparse`, `logging`, `sys`, `threading`, `time`, `datetime`)
2. third-party (`rich.*`, `pandas`, `alpaca.*`, `requests`, `openai`)
3. local `from src.<module> import ...` (absolute, package-qualified; modules run via `python -m src.<module>`)

Patterns:
- Optional features guarded by `try/except ImportError` setting a `_HAS_*` flag (learning system in orchestrator; `alpaca-py` in `AlpacaClient._init_clients`).
- Some imports are deliberately lazy / function-local to avoid heavy startup cost or circulars (`from src.technical_signals import _rsi` inside `_get_btc_regime`; `from src.db import connection` inside `TradeLogger.get_open_positions`).
- No path aliases, no barrel re-exports.

## Configuration / Env Loading

- `python-dotenv` `load_dotenv()` at startup; all config via `os.environ.get(name, default)`.
- **Risk constants are env-overridable with hardcoded defaults** (`src/alpaca_orchestrator.py:52-81`), e.g. `MAX_POSITION_PCT` (0.05), `MAX_TOTAL_EXPOSURE_PCT` (0.80), `DRAWDOWN_STOP_PCT` (0.10), `MIN_PAPER_TRADES` (50), `MIN_WIN_RATE` (0.40), `MIN_CONFLUENCE` (4), `MIN_SHORT_CONFLUENCE` (3), `CYCLE_SLEEP_SECONDS` (1800), `POSITION_CHECK_INTERVAL` (60), `LIVE_TRADING_THRESHOLD` (100000), `SKIP_RISK_GATE`, `SHORT_ENABLED`, `BOT_LABEL`.
- Boolean envs parsed as `os.environ.get(x, "").lower() in ("1","true","yes")`.
- Untradeable-symbol blocklist is a comma-split env → `frozenset` (`_ALPACA_UNTRADEABLE`), default includes ghost/0-win symbols (LDO, POL, ONDO, RENDER, DOT, ARB, SUSHI, HYPE, LINK, ETH).
- Central `Config` object via `load_config()` (`src/config.py`) holds Alpaca keys, kelly_fraction, starting_bankroll, MiroFish/LLM URLs — injected into clients (`AlpacaClient(config)`).
- **Per-bot account selection (HARD RULE):** each bot uses its own Alpaca account via `ALPACA_API_KEY_{bot}` / `ALPACA_SECRET_KEY_{bot}`. Never share an account across bots.
- **`BOT_ID` required for persistence:** `TradeLogger` requires `bot_id` kwarg (any non-empty string for multi-bot UUIDs) or `BOT_ID` env in `("A","B")`, else raises `ValueError` (`src/trade_logger.py:14-30`).
- Paper vs live: `os.getenv("ALPACA_PAPER", "true")`.
- Secrets read from `~/.claude/secrets/services.json` for local dev, env vars in container (`src/notifier.py` AWS SES; note: SENDER is `alerts@emails4agents.com`). `.env` and `private_key.pem` gitignored.

## Persistence

- **Postgres, not SQLite.** `TradeLogger` is a thin shim over `src/db.py` using `psycopg` (`psycopg[binary]>=3.2`, `psycopg-pool`). `connection()` context manager; queries use `%s` params and `bot_id` for per-bot scoping. `data/trades.db` path is legacy/ignored (kept for call-site back-compat); schema in `src/db_schema.sql`.

## CLI Arg Patterns

- `argparse` in `if __name__ == "__main__"` blocks. `src/alpaca_orchestrator.py` exposes `--mode {paper,live,evaluate}` (default `paper`) and `--max-trades` (int, default 0 = run forever).
- `evaluate` mode dispatches to `evaluate()` (scan + `rich` table, no trades); other modes call `main()`.
- Backtester run as `python -m src.backtester` (`__main__.py` → `cli.py`).
- Run commands documented in `CLAUDE.md` / `README.md`: `python -m src.alpaca_orchestrator --mode paper --max-trades 50`.

## Error Handling

- **Fail-open on advisory LLM components:** risk gate / exit advisor exceptions are caught, logged as warnings, and default to non-blocking (trade proceeds / position held) so a broken LLM never halts trading.
- **Fail-fast on misconfiguration:** missing Alpaca keys and invalid `BOT_ID` raise `ValueError` at construction; missing `alpaca-py` raises `ImportError` with install hint.
- **Per-symbol isolation in loops:** each candidate/position is wrapped in try/except with `continue`, so one bad symbol never aborts the cycle (`PositionMonitor._check_all_positions`, main trade loop).
- **Top-level crash guard:** `main()` wrapped to catch `KeyboardInterrupt` (clean stop) and `Exception` → `log.exception` + `alert_bot_crash(exc)` + `sys.exit(1)`.
- **API resilience:** `_retry` decorator-style helper does exponential backoff (`MAX_RETRIES=3`, `RETRY_BACKOFF=1.0` doubling) behind a thread-safe `_RateLimiter` (~5 rps) in `src/alpaca_client.py`.

## Logging

- Stdlib `logging`; per-module `log = logging.getLogger(__name__)`.
- Configured once at orchestrator entry: `logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s -- %(message)s", stream=sys.stdout)` (`_setup_logging`). App startup forces INFO to surface bot thread activity (recent commit).
- Prefers `%`-style lazy args in hot paths (`log.info("...%ds", x)`) and f-strings in operator `console.print` output.
- Email alerts (AWS SES via `src/notifier.py`): `alert_bot_crash`, `alert_drawdown_stop`, `alert_monitor_error`, `alert_position_closed`, `send_alert` to `articulatedesigns@gmail.com`.

## Module Design

- One class per concern; orchestrator composes by constructor injection (`AlpacaClient(config)`, `TradeLogger()`, `RulesGate()`, `ExitAdvisor()`, `PositionMonitor(alpaca, logger, exit_advisor)`).
- Background work via `threading.Thread` subclass with `_stop_event` + `_lock` (`PositionMonitor`); daemon threads.
- **Active risk gate is `RulesGate` (deterministic)**, not the LLM `RiskGate` — `RiskGate` import is kept "for backward compat / type hints". Gate `.evaluate(...)` returns a verdict with `.decision` (`PROCEED`/`VETO`), `.reasoning`, `.votes`.

## Risk Rules (defaults — overridable via env, treat as HARD RULES in code)

| Constant | Default | Meaning |
|----------|---------|---------|
| `MAX_POSITION_PCT` | 0.05 | Max 5% bankroll per position |
| `MAX_TOTAL_EXPOSURE_PCT` | 0.80 | 80% total-exposure cap; scan skipped above it |
| `DRAWDOWN_STOP_PCT` | 0.10 | Daily drawdown stop → sleep 1h |
| `MIN_CONFLUENCE` / `MIN_SHORT_CONFLUENCE` | 4 / 3 | Indicators required to long / short |
| kelly_fraction (Config) | 0.25 | Quarter-Kelly (`_kelly_technical`); win-prob map 3→.55, 4→.60, 5→.65; b=0.08/0.05 |
| `HARD_STOP_PCT` / `SOFT_STOP_PCT` / `SOFT_TAKE_PROFIT_PCT` | (in `exit_advisor.py`) | Hard exits immediate; soft thresholds consult exit advisor |
| `POSITION_CHECK_INTERVAL` | 60 | Monitor cadence (s) |
| `MAX_ENTRIES_PER_CYCLE` | 3 | Per-cycle entry cap (anti-correlation) |
| Market regime | — | BTC RSI 1h>70 & 4h>65 ⇒ OVERHEATED, skip entries; ≥60% EMA-bear ⇒ broad-bear long pause |

## Documented HARD RULES (from CLAUDE.md)

- **One Alpaca account per bot.** Never point two bots at one account (breaks equity curves, dedup, P&L attribution). Enforced via `_{bot}` env-var pattern.
- **Paper-only gate.** Live blocked until 50+ paper trades, win rate > 40%, and equity ≥ `LIVE_TRADING_THRESHOLD` ($100k default). Checked by `_check_paper_requirements`; live also requires interactive `CONFIRM` (`_confirm_live_mode`).
- **Limit orders only**, 20% drawdown stop, max 3 correlated positions per event, max 10 simulations per cycle, min 15% gap to trade (Kalshi).
- **Kalshi orchestrator is PAUSED** — do not run `src/orchestrator.py`.

---

*Convention analysis: 2026-05-31*
