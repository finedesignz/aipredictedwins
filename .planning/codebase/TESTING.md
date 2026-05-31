# Testing Patterns

**Analysis Date:** 2026-05-31

## Test Framework

**pytest, real and substantial suite (~14 core test files, hundreds of test functions).**
- Runner: **pytest 8.4.1** (confirmed by `__pycache__` artifacts `*.cpython-313-pytest-8.4.1.pyc`).
- Python: 3.13 (cpython-313 bytecode; a 3.11 set also present under `src/__pycache__`).
- Assertions: plain `assert` (pytest rewrite). `pytest.raises(...)` for error paths.
- **No config file** (`pytest.ini` / `pyproject.toml` / `setup.cfg` / `tox.ini` absent) → pytest runs with defaults (auto-discovers `test_*.py`; no custom markers, addopts, or coverage gate).
- **No suite-root `conftest.py`** (only `vendor/TradingAgents/tests/conftest.py`, a vendored dep). Per-file fixtures used instead.
- pytest is **not declared in `requirements.txt`** — dev-only, installed in `.venv`. Gap: pin it in a dev-requirements file.

## Run Commands

```bash
# repo root, .venv active
pytest                          # discover + run everything (includes vendor/, slow)
pytest tests/                   # core suite (recommended)
pytest tests/test_technical_signals.py
pytest -k kelly                 # by keyword
DATABASE_URL=postgres://... pytest tests/test_db.py   # enable skipped Postgres smoke tests
python -m src.backtester        # backtester offline validation (separate path)
```

## Test File Organization

**Location:** top-level `tests/` dir (NOT co-located with `src/`), mirroring module names. Subpackage tests under `tests/backtester/` with JSON `fixtures/`.

**Core suite (`tests/`):**
| File | Covers | Notes |
|------|--------|-------|
| `test_technical_signals.py` | EMA/RSI/ADX(+DI/-DI)/volume-spike/VWAP, `analyze`, RSI ceiling, **plus orchestrator helpers** `_kelly_technical`, `_select_cycle_candidates`, `_check_market_regime`, `_apply_volume_context_filter`, and `RiskGate`/`ExitAdvisor` `_parse_response` | Largest file (~644 lines); synthetic OHLCV via `_make_*_bars` helpers |
| `test_exit_advisor.py` | `check_position_thresholds`, `TrailingStop` thresholds | |
| `test_position_sizer.py` | `kelly_size` (Kalshi-style: side/cap/quarter-kelly/contracts/price_cents) | |
| `test_pipeline_state.py` | `PipelineState` immutability / `with_updates` | |
| `test_bot_config.py` | `BotConfig.from_row` defaults/custom, zero-not-replaced | |
| `test_claude_llm_cache.py` | `LLMCache` (uses `tempfile` + `sqlite3`) | |
| `test_gap_detector.py`, `test_event_formatter.py` | Kalshi (paused) helpers — still unit-tested | |
| `test_db.py` | Postgres DAL (`src.db`) | **skipped** unless `DATABASE_URL` set (`pytest.mark.skipif`) |
| `test_trade_logger_shim.py` | `TradeLogger` BOT_ID validation + db delegation | mocks `src.db` |
| `tests/backtester/` | `test_engine.py`, `test_portfolio.py`, `test_metrics.py`, `test_data_loader.py` | fixture-driven |

**Dashboard suite (`dashboard/api/`):** `test_api.py`, `tests/test_db.py`, `tests/test_routes.py` (FastAPI; run from dashboard dir).
**Connectivity smoke:** `scripts/test_connectivity.py` (live reachability, not a unit test).

**Structure conventions:** grouped into `class TestXxx` with banner-comment section headers; `import pytest` at top; module-under-test imported either at top (`test_technical_signals`, `test_position_sizer`) or lazily inside each test (common — keeps import cost off collection and isolates env-dependent modules). Several files prepend repo root to `sys.path` (`sys.path.insert(0, ...)`) to import `src.*` without install.

## Mocking / Fixtures

- **No external mock library** — uses stdlib + pytest builtins.
- `monkeypatch` for env vars (`test_trade_logger_shim.py`: `setenv`/`delenv` `BOT_ID`).
- **`sys.modules` injection** (`test_trade_logger_shim.py`): an `autouse` fixture installs a fake `src.db` module (all no-op functions) and force-reimports `src.trade_logger`, so DAL tests need no Postgres / `psycopg_pool` / `DATABASE_URL`.
- **`__new__`-bypass pattern** (`test_technical_signals.py`): `RiskGate.__new__(RiskGate)` / `ExitAdvisor.__new__(...)` to test `_parse_response` and `evaluate` without running `__init__` (no real LLM); fake LLM injected via a tiny `FakeLLM` class whose `call()` returns `None`.
- **Synthetic data generators** instead of fixtures for indicators (`_make_uptrend_bars` etc., with sine overlays tuned to hit specific RSI bands).
- **JSON fixtures** for backtester (`tests/backtester/fixtures/BTC_USD.json`, loaded via `load_bars_fixture`).
- DB-touching real tests gated by `skipif(DATABASE_URL unset)`.

## Coverage

- **No coverage tooling configured** (no `pytest-cov`); effective coverage unmeasured but qualitatively high for pure logic.

### Well covered
Indicator math + confluence, Kelly sizing (both `kelly_size` and `_kelly_technical`), exit thresholds + trailing stop, market-regime / volume-context / per-cycle-entry-cap orchestrator helpers, gate/exit JSON parsing, **the security-critical invariant that `RiskGate` VETOes when the LLM is unavailable (no high-confluence bypass)**, BOT_ID validation, pipeline state, bot config, LLM cache, backtester engine/metrics/portfolio/data-loader, Kalshi gap/event helpers.

### High-risk coverage gaps (money-touching, largely untested)
| Area | Files | Risk |
|------|-------|------|
| Orchestrator end-to-end loop | `src/alpaca_orchestrator.py` (`main`, `evaluate`) | Scan→gate→size→order wiring, daily reset, exposure/regime/bear gating not integration-tested |
| Order placement / dedup / reconciliation | `src/alpaca_client.py`, `PositionMonitor._check_all_positions` | Duplicate/rejected limit orders, external-close reconciliation, sub-penny entry fallback |
| Active gate (`RulesGate`) | `src/rules_gate.py` | Gap-chase + flat-market (ADX) veto logic has no direct test (LLM `RiskGate` is the one tested) |
| Live safety gate | `_check_paper_requirements`, `_confirm_live_mode` | 50-trade / 40%-WR / equity-threshold truth table not asserted |
| Retry / rate limiter | `_retry`, `_RateLimiter` (`src/alpaca_client.py`) | Backoff + thread-safety under failure |
| Notifier (SES) | `src/notifier.py` | Alert paths exercised only in incidents |
| Multi-bot / copytrade threads | `bot_manager.py`, `bot_thread.py`, `copytrade_thread.py`, `bot_c/` | Threading/attribution untested |
| Postgres DAL by default | `src/db.py` (`test_db.py`) | Skipped unless `DATABASE_URL` provided — no DB in default CI = these never run |

## De-Facto / Manual Verification (complements unit tests)

1. **Evaluate mode** — `python -m src.alpaca_orchestrator --mode evaluate`: full technical scan + `rich` candidate table, no trades. Primary live-data sanity check.
2. **Backtester** — `python -m src.backtester`: offline strategy validation on historical bars (own unit tests + JSON fixtures).
3. **Bounded paper run** — `--mode paper --max-trades N`: real pipeline against paper account, prints final win-rate/P&L report (STRONG/MARGINAL/NO EDGE verdict at ≥10 resolved).
4. **Paper-trading gate** — real acceptance test before live: 50+ paper trades, win rate > 40%, equity ≥ live threshold ($100k) (`_check_paper_requirements`).
5. **A/B bots** — A vs B (and stock Bot C) on separate Alpaca accounts; equity curves compared on the dashboard (https://app.aipredictedwins.com).
6. **Health/log inspection** — `/health` probe + INFO startup logging surface bot-thread activity; trades from Postgres, live output from `data/bot_output.log`.

## Recommended Improvements

- Pin pytest + add `pytest-cov` in `requirements-dev.txt`; add `pyproject.toml [tool.pytest.ini_options]` with `testpaths = ["tests"]` to exclude `vendor/` and `dashboard/web/node_modules`.
- Add direct `RulesGate.evaluate` tests (gap + flat-market veto), and the full `_check_paper_requirements` truth table.
- Mock `alpaca.*` to cover order-placement + reconciliation paths without the broker.
- CI: run `pytest tests/` with an ephemeral Postgres so `test_db.py` actually executes.

---

*Testing analysis: 2026-05-31*
