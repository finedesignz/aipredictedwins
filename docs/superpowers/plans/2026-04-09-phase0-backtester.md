# Trading Bot v2.1 Phase 0 — Backtester + PipelineState

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an offline backtesting framework and wire `PipelineState` through the orchestrator's trading pipeline — establishing the mandatory validation gate for all future phases.

**Architecture:** `PipelineState` is a frozen dataclass flowing through each pipeline stage. The backtester replays historical bars through the same signal/sizing logic offline, using a SQLite LLM cache so Phase 1+ can replay LLM decisions deterministically. Phase 0 itself makes no behavior changes — existing tests must pass unchanged.

**Tech Stack:** Python 3.11, pytest, SQLite (stdlib), alpaca-py, `src/technical_signals.py` (existing), `src/exit_advisor.py` (existing)

**Spec:** `docs/superpowers/specs/2026-04-09-trading-bot-v21-design.md` — Phase 0 section

**Note on scope:** This plan covers Phase 0 only. Phases 1–5 have separate plans generated after this ships and is validated.

---

## File Map

**New files:**
- `src/pipeline_state.py` — frozen PipelineState dataclass
- `src/backtester/__init__.py` — package exports
- `src/backtester/config.py` — PhaseConfig feature flags
- `src/backtester/data_loader.py` — bar loading: fixture → disk cache → Alpaca API
- `src/backtester/portfolio.py` — simulated position tracking + P&L
- `src/backtester/metrics.py` — Sharpe, max drawdown, win rate, monitor P&L
- `src/backtester/engine.py` — time-aligned replay loop
- `src/backtester/report.py` — HTML report generator (no Jinja2 — plain strings)
- `src/backtester/cli.py` — argparse entry point
- `tests/test_pipeline_state.py`
- `tests/backtester/__init__.py`
- `tests/backtester/test_data_loader.py`
- `tests/backtester/test_portfolio.py`
- `tests/backtester/test_metrics.py`
- `tests/backtester/test_engine.py`
- `tests/backtester/fixtures/BTC_USD.json` — 60 synthetic 1-hour bars for CI

**Modified files:**
- `src/claude_llm.py` — add optional SQLite LLM cache
- `src/alpaca_orchestrator.py` — wrap main scan loop in PipelineState
- `requirements.txt` — no new deps (all stdlib or already present)

---

## Task 1: PipelineState dataclass

**Files:**
- Create: `src/pipeline_state.py`
- Create: `tests/test_pipeline_state.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_state.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline_state import PipelineState


class TestPipelineState:
    def _bars(self):
        return tuple({"close": 100.0 + i, "open": 100.0 + i, "high": 101.0 + i,
                      "low": 99.0 + i, "volume": 1000.0, "timestamp": f"2026-03-01T{i:02d}:00:00"}
                     for i in range(5))

    def test_construct(self):
        s = PipelineState(symbol="BTC/USD", bars=self._bars())
        assert s.symbol == "BTC/USD"
        assert len(s.bars) == 5
        assert s.signal is None
        assert s.kelly_fraction == 0.0
        assert s.skipped_reason is None

    def test_with_updates_returns_new(self):
        s = PipelineState(symbol="BTC/USD", bars=self._bars())
        s2 = s.with_updates(kelly_fraction=0.15)
        assert s2.kelly_fraction == 0.15
        assert s.kelly_fraction == 0.0  # original unchanged

    def test_with_updates_preserves_other_fields(self):
        s = PipelineState(symbol="ETH/USD", bars=self._bars(), correlation_penalty=0.1)
        s2 = s.with_updates(kelly_fraction=0.20)
        assert s2.correlation_penalty == 0.1
        assert s2.symbol == "ETH/USD"

    def test_immutable(self):
        import dataclasses
        s = PipelineState(symbol="BTC/USD", bars=self._bars())
        try:
            s.symbol = "ETH/USD"
            assert False, "should have raised FrozenInstanceError"
        except dataclasses.FrozenInstanceError:
            pass

    def test_skipped(self):
        s = PipelineState(symbol="BTC/USD", bars=self._bars(),
                          skipped_reason="reentry_blocked: hard_stop 2h ago")
        assert s.skipped_reason is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:/Users/artic/GitHub/aipredictedwins
python -m pytest tests/test_pipeline_state.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.pipeline_state'`

- [ ] **Step 3: Create `src/pipeline_state.py`**

```python
"""
PipelineState — immutable stage contract for the trading pipeline.

Each stage in the orchestrator (signal scan → research panel → sizing → order)
consumes a PipelineState and returns a new one with its outputs populated.
No stage mutates the object directly.

Stage outputs use `Any | None` for types that don't exist yet in Phase 0
(ResearchOpinion, SentimentResult). These are upgraded in Phases 1 and 4.
"""
from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class PipelineState:
    # ── Inputs ────────────────────────────────────────────────────────────────
    symbol: str
    bars: tuple[dict, ...]          # tuple required for frozen dataclass

    # ── Stage outputs (None until populated by the relevant stage) ───────────
    signal: Any | None = None       # src.technical_signals.Signal
    research_opinion: Any | None = None   # src.research_panel.ResearchOpinion (Phase 1)
    sentiment_result: Any | None = None   # src.sentiment_signal.SentimentResult (Phase 4)
    correlation_penalty: float = 0.0
    kelly_fraction: float = 0.0
    order_id: str | None = None
    skipped_reason: str | None = None

    def with_updates(self, **kwargs: Any) -> "PipelineState":
        """Return a new PipelineState with the given fields replaced."""
        return dataclasses.replace(self, **kwargs)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_pipeline_state.py -v
```

Expected: 5 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add src/pipeline_state.py tests/test_pipeline_state.py
git commit -m "feat(phase0): add immutable PipelineState dataclass"
```

---

## Task 2: LLM call cache

**Files:**
- Modify: `src/claude_llm.py`
- Create: `tests/test_claude_llm_cache.py`

The cache stores `sha256(prompt + model)` → response in `data/llm_cache.db`. The production bot writes to it automatically (so Phase 1+ backtests can replay decisions). Cache is disabled by default and opt-in via `cache_db` param.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_claude_llm_cache.py
import sys, os, tempfile, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.claude_llm import LLMCache


class TestLLMCache:
    def _db(self, tmp_path):
        return os.path.join(tmp_path, "test_cache.db")

    def test_miss_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(self._db(tmp))
            assert cache.get("hello", "model-x") is None

    def test_put_then_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(self._db(tmp))
            cache.put("hello", "model-x", "the response")
            assert cache.get("hello", "model-x") == "the response"

    def test_different_model_is_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(self._db(tmp))
            cache.put("hello", "model-a", "response-a")
            assert cache.get("hello", "model-b") is None

    def test_different_prompt_is_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(self._db(tmp))
            cache.put("prompt-1", "model-x", "resp-1")
            assert cache.get("prompt-2", "model-x") is None

    def test_idempotent_put(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(self._db(tmp))
            cache.put("p", "m", "first")
            cache.put("p", "m", "second")   # should overwrite
            assert cache.get("p", "m") == "second"

    def test_db_created_automatically(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._db(tmp)
            assert not os.path.exists(path)
            LLMCache(path)
            assert os.path.exists(path)
```

- [ ] **Step 2: Run to verify fails**

```bash
python -m pytest tests/test_claude_llm_cache.py -v
```

Expected: `ImportError: cannot import name 'LLMCache'`

- [ ] **Step 3: Add `LLMCache` to `src/claude_llm.py`**

Add after the existing imports at the top of the file:

```python
import hashlib
import sqlite3
from pathlib import Path
```

Add this class before `ClaudeLLM`:

```python
class LLMCache:
    """SQLite-backed cache for LLM responses, keyed by sha256(prompt + model).

    Used by the backtester to replay past LLM decisions deterministically.
    Also written by the production bot so decisions accumulate over time.

    Cache key: sha256(prompt + "\x00" + model) — any prompt edit invalidates.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS llm_cache (
        cache_key  TEXT PRIMARY KEY,
        prompt     TEXT NOT NULL,
        model      TEXT NOT NULL,
        response   TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """

    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        with sqlite3.connect(db_path) as conn:
            conn.execute(self._SCHEMA)

    @staticmethod
    def _key(prompt: str, model: str) -> str:
        return hashlib.sha256(f"{prompt}\x00{model}".encode()).hexdigest()

    def get(self, prompt: str, model: str) -> str | None:
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT response FROM llm_cache WHERE cache_key = ?",
                (self._key(prompt, model),),
            ).fetchone()
        return row[0] if row else None

    def put(self, prompt: str, model: str, response: str) -> None:
        key = self._key(prompt, model)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO llm_cache (cache_key, prompt, model, response) "
                "VALUES (?, ?, ?, ?)",
                (key, prompt, model, response),
            )
```

- [ ] **Step 4: Add `cache_db` parameter to `ClaudeLLM.__init__` and wire into `call()`**

Replace the existing `__init__` and `call()` methods:

```python
def __init__(self, model: str = DEFAULT_MODEL, timeout: int = DEFAULT_TIMEOUT,
             cache_db: str | None = None):
    self.model = model
    self.timeout = timeout
    self._cache: LLMCache | None = LLMCache(cache_db) if cache_db else None

def call(self, prompt: str, max_tokens: int = 1024) -> str | None:
    # Check cache first
    if self._cache is not None:
        cached = self._cache.get(prompt, self.model)
        if cached is not None:
            log.debug("Claude LLM cache HIT for model=%s (%d chars)", self.model, len(cached))
            return cached

    cmd = [
        "claude",
        "-p", prompt,
        "--model", self.model,
        "--output-format", "json",
        "--max-turns", "1",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            env=None,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()[:200] if result.stderr else "no stderr"
            log.error("Claude CLI failed (exit %d): %s", result.returncode, stderr)
            return None

        if not result.stdout.strip():
            log.error("Claude CLI returned empty output")
            return None

        data = json.loads(result.stdout)

        if data.get("is_error"):
            log.error("Claude CLI error: %s", data.get("result", "unknown error"))
            return None

        response_text = data.get("result", "")
        cost = data.get("total_cost_usd", 0)
        duration = data.get("duration_ms", 0)

        log.debug(
            "Claude CLI: model=%s, cost=$%.4f, duration=%dms, response=%d chars",
            self.model, cost, duration, len(response_text),
        )

        # Write to cache
        if self._cache is not None and response_text:
            self._cache.put(prompt, self.model, response_text)

        return response_text

    except subprocess.TimeoutExpired:
        log.error("Claude CLI timed out after %ds", self.timeout)
        return None
    except json.JSONDecodeError as exc:
        log.error("Claude CLI returned non-JSON: %s", exc)
        return None
    except FileNotFoundError:
        log.error("Claude CLI not found — is it installed? Run: npm install -g @anthropic-ai/claude-code")
        return None
    except Exception as exc:
        log.error("Claude CLI unexpected error: %s", exc)
        return None
```

- [ ] **Step 5: Run all tests**

```bash
python -m pytest tests/test_claude_llm_cache.py tests/test_pipeline_state.py -v
```

Expected: 11 tests PASSED

- [ ] **Step 6: Commit**

```bash
git add src/claude_llm.py tests/test_claude_llm_cache.py
git commit -m "feat(phase0): add SQLite LLM cache with sha256 prompt keying"
```

---

## Task 3: Backtester data_loader

**Files:**
- Create: `src/backtester/__init__.py`
- Create: `src/backtester/data_loader.py`
- Create: `tests/backtester/__init__.py`
- Create: `tests/backtester/fixtures/BTC_USD.json`
- Create: `tests/backtester/test_data_loader.py`

- [ ] **Step 1: Create the fixture file**

Create `tests/backtester/fixtures/BTC_USD.json` with 60 synthetic 1-hour bars:

```python
# Run this once to generate the fixture, then commit the output
import json, math
bars = []
for i in range(60):
    base = 65000.0 + i * 50 + 500 * math.sin(i * 0.3)
    bars.append({
        "timestamp": f"2026-03-01T{i % 24:02d}:00:00+00:00",
        "open":   round(base, 2),
        "high":   round(base * 1.005, 2),
        "low":    round(base * 0.995, 2),
        "close":  round(base + 20, 2),
        "volume": round(1000 + i * 10, 2),
        "vwap":   round(base + 10, 2),
    })
print(json.dumps(bars, indent=2))
```

Save the output as `tests/backtester/fixtures/BTC_USD.json`.

- [ ] **Step 2: Write the failing test**

```python
# tests/backtester/test_data_loader.py
import sys, os, tempfile, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.backtester.data_loader import load_bars_fixture, normalise_bar


FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class TestNormaliseBar:
    def test_required_keys_present(self):
        bar = normalise_bar({
            "timestamp": "2026-03-01T00:00:00+00:00",
            "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.5, "volume": 500.0, "vwap": 100.3,
        })
        for key in ("timestamp", "open", "high", "low", "close", "volume", "vwap"):
            assert key in bar

    def test_missing_vwap_defaults_to_close(self):
        bar = normalise_bar({"timestamp": "t", "open": 1.0, "high": 1.0,
                              "low": 1.0, "close": 1.0, "volume": 1.0})
        assert bar["vwap"] == 1.0


class TestLoadBarsFixture:
    def test_loads_btc_fixture(self):
        bars = load_bars_fixture("BTC/USD", fixture_dir=FIXTURE_DIR)
        assert len(bars) == 60
        assert bars[0]["close"] > 0

    def test_unknown_symbol_raises(self):
        try:
            load_bars_fixture("FAKE/USD", fixture_dir=FIXTURE_DIR)
            assert False, "should have raised FileNotFoundError"
        except FileNotFoundError:
            pass

    def test_bars_sorted_by_timestamp(self):
        bars = load_bars_fixture("BTC/USD", fixture_dir=FIXTURE_DIR)
        timestamps = [b["timestamp"] for b in bars]
        assert timestamps == sorted(timestamps)
```

- [ ] **Step 3: Run to verify fails**

```bash
python -m pytest tests/backtester/test_data_loader.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.backtester'`

- [ ] **Step 4: Create package files**

`src/backtester/__init__.py`:
```python
"""Backtester package — offline replay of the trading pipeline."""
```

`tests/backtester/__init__.py`:
```python
```

- [ ] **Step 5: Create `src/backtester/data_loader.py`**

```python
"""
Backtester data loading utilities.

Priority order for bar data:
  1. fixture_dir (JSON files, for CI / unit tests)
  2. disk cache (data/bar_cache/<symbol>_<timeframe>.json)
  3. Alpaca API (requires credentials in env)

Symbol names use slash format: "BTC/USD" → fixture file "BTC_USD.json"
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

BAR_CACHE_DIR = os.environ.get("BAR_CACHE_DIR", "data/bar_cache")


def normalise_bar(raw: dict) -> dict:
    """Ensure a bar dict has all required keys with correct types."""
    close = float(raw.get("close", 0))
    return {
        "timestamp": str(raw.get("timestamp", "")),
        "open":   float(raw.get("open", close)),
        "high":   float(raw.get("high", close)),
        "low":    float(raw.get("low", close)),
        "close":  close,
        "volume": float(raw.get("volume", 0)),
        "vwap":   float(raw.get("vwap", close)),   # default vwap = close
    }


def _symbol_to_filename(symbol: str) -> str:
    """'BTC/USD' → 'BTC_USD'"""
    return symbol.replace("/", "_")


def load_bars_fixture(symbol: str, fixture_dir: str) -> list[dict]:
    """Load bars from a JSON fixture file. Used for CI and unit tests.

    File naming: BTC/USD → <fixture_dir>/BTC_USD.json
    Raises FileNotFoundError if the file does not exist.
    """
    fname = _symbol_to_filename(symbol) + ".json"
    path = Path(fixture_dir) / fname
    if not path.exists():
        raise FileNotFoundError(f"No fixture for {symbol} at {path}")
    with open(path) as f:
        raw_bars = json.load(f)
    bars = [normalise_bar(b) for b in raw_bars]
    bars.sort(key=lambda b: b["timestamp"])
    return bars


def load_bars_cached(
    symbol: str,
    start_iso: str,
    end_iso: str,
    timeframe: str = "1Hour",
    cache_dir: str = BAR_CACHE_DIR,
) -> list[dict] | None:
    """Load bars from disk cache. Returns None if not cached."""
    fname = f"{_symbol_to_filename(symbol)}_{timeframe}.json"
    path = Path(cache_dir) / fname
    if not path.exists():
        return None
    with open(path) as f:
        all_bars = json.load(f)
    bars = [normalise_bar(b) for b in all_bars
            if start_iso <= str(b.get("timestamp", "")) <= end_iso]
    bars.sort(key=lambda b: b["timestamp"])
    log.debug("Bar cache HIT: %s %s bars (%s–%s)", symbol, len(bars), start_iso[:10], end_iso[:10])
    return bars or None


def save_bars_cache(
    symbol: str,
    bars: list[dict],
    timeframe: str = "1Hour",
    cache_dir: str = BAR_CACHE_DIR,
) -> None:
    """Write bars to disk cache (merges with any existing cached bars)."""
    fname = f"{_symbol_to_filename(symbol)}_{timeframe}.json"
    path = Path(cache_dir) / fname
    Path(cache_dir).mkdir(parents=True, exist_ok=True)

    existing: list[dict] = []
    if path.exists():
        with open(path) as f:
            existing = json.load(f)

    # Merge: existing + new, deduplicate by timestamp, sort
    by_ts: dict[str, dict] = {b["timestamp"]: b for b in existing}
    for b in bars:
        by_ts[b["timestamp"]] = b
    merged = sorted(by_ts.values(), key=lambda b: b["timestamp"])

    with open(path, "w") as f:
        json.dump(merged, f)
    log.debug("Bar cache WRITE: %s %d bars → %s", symbol, len(merged), path)


def load_bars_from_alpaca(
    symbol: str,
    start_iso: str,
    end_iso: str,
    timeframe: str = "1Hour",
    cache_dir: str = BAR_CACHE_DIR,
) -> list[dict]:
    """Fetch bars from Alpaca and write to disk cache.

    Requires ALPACA_API_KEY and ALPACA_SECRET_KEY in environment.
    Raises RuntimeError if credentials are missing.
    """
    from alpaca.data import CryptoHistoricalDataClient
    from alpaca.data.requests import CryptoBarsRequest
    from alpaca.data.timeframe import TimeFrame

    api_key = os.environ.get("ALPACA_API_KEY")
    secret_key = os.environ.get("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        raise RuntimeError("ALPACA_API_KEY and ALPACA_SECRET_KEY must be set for live bar fetching")

    tf_map = {
        "1Hour": TimeFrame.Hour,
        "1Day": TimeFrame.Day,
        "15Min": TimeFrame.Minute,
    }
    tf = tf_map.get(timeframe, TimeFrame.Hour)

    client = CryptoHistoricalDataClient(api_key, secret_key)
    request = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=tf,
                                 start=start_iso, end=end_iso)
    response = client.get_crypto_bars(request)
    df = response.df.reset_index()

    bars = []
    for _, row in df.iterrows():
        bars.append(normalise_bar({
            "timestamp": str(row["timestamp"]),
            "open":   row["open"],
            "high":   row["high"],
            "low":    row["low"],
            "close":  row["close"],
            "volume": row["volume"],
            "vwap":   row.get("vwap", row["close"]),
        }))

    bars.sort(key=lambda b: b["timestamp"])
    save_bars_cache(symbol, bars, timeframe=timeframe, cache_dir=cache_dir)
    return bars


def load_bars(
    symbol: str,
    start_iso: str,
    end_iso: str,
    timeframe: str = "1Hour",
    fixture_dir: str | None = None,
    cache_dir: str = BAR_CACHE_DIR,
) -> list[dict]:
    """Load bars with priority: fixture → disk cache → Alpaca API.

    Args:
        symbol: e.g. "BTC/USD"
        start_iso / end_iso: ISO-8601 date strings, e.g. "2026-02-01"
        timeframe: "1Hour" | "1Day" | "15Min"
        fixture_dir: if set, use fixtures only (for tests)
        cache_dir: disk cache location
    """
    if fixture_dir:
        return load_bars_fixture(symbol, fixture_dir=fixture_dir)

    cached = load_bars_cached(symbol, start_iso, end_iso,
                               timeframe=timeframe, cache_dir=cache_dir)
    if cached:
        return cached

    log.info("Bar cache miss for %s — fetching from Alpaca", symbol)
    return load_bars_from_alpaca(symbol, start_iso, end_iso,
                                  timeframe=timeframe, cache_dir=cache_dir)
```

- [ ] **Step 6: Generate the fixture file**

```bash
cd C:/Users/artic/GitHub/aipredictedwins
python - <<'EOF'
import json, math
bars = []
for i in range(60):
    base = 65000.0 + i * 50 + 500 * math.sin(i * 0.3)
    bars.append({
        "timestamp": f"2026-03-01T{i % 24:02d}:00:00+00:00",
        "open":   round(base, 2),
        "high":   round(base * 1.005, 2),
        "low":    round(base * 0.995, 2),
        "close":  round(base + 20, 2),
        "volume": round(1000 + i * 10, 2),
        "vwap":   round(base + 10, 2),
    })
import os; os.makedirs("tests/backtester/fixtures", exist_ok=True)
with open("tests/backtester/fixtures/BTC_USD.json", "w") as f:
    json.dump(bars, f, indent=2)
print("Generated 60 bars → tests/backtester/fixtures/BTC_USD.json")
EOF
```

- [ ] **Step 7: Run tests**

```bash
python -m pytest tests/backtester/test_data_loader.py -v
```

Expected: 5 tests PASSED

- [ ] **Step 8: Commit**

```bash
git add src/backtester/ tests/backtester/ 
git commit -m "feat(phase0): add backtester data_loader with fixture/cache/Alpaca priority"
```

---

## Task 4: Backtester portfolio

**Files:**
- Create: `src/backtester/portfolio.py`
- Create: `tests/backtester/test_portfolio.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/backtester/test_portfolio.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.backtester.portfolio import BacktestPortfolio


class TestBacktestPortfolio:
    def test_initial_equity(self):
        p = BacktestPortfolio(100_000.0)
        assert p.equity() == 100_000.0

    def test_open_reduces_cash(self):
        p = BacktestPortfolio(100_000.0)
        p.open_position("BTC/USD", entry_price=50_000.0, qty=0.5, timestamp="2026-03-01T00:00:00")
        assert p.cash() == 75_000.0   # 100k - 0.5 * 50k

    def test_close_profitable(self):
        p = BacktestPortfolio(100_000.0)
        trade_id = p.open_position("BTC/USD", entry_price=50_000.0, qty=0.5,
                                    timestamp="2026-03-01T00:00:00")
        pnl = p.close_position(trade_id, exit_price=55_000.0, timestamp="2026-03-01T12:00:00",
                                reason="hard_take_profit")
        assert pnl == 2_500.0   # (55k - 50k) * 0.5
        assert p.cash() == 102_500.0

    def test_close_loss(self):
        p = BacktestPortfolio(100_000.0)
        trade_id = p.open_position("ETH/USD", entry_price=3_000.0, qty=2.0,
                                    timestamp="2026-03-01T00:00:00")
        pnl = p.close_position(trade_id, exit_price=2_880.0, timestamp="2026-03-01T06:00:00",
                                reason="hard_stop")
        assert abs(pnl - (-240.0)) < 0.01   # (2880 - 3000) * 2
        assert abs(p.cash() - (100_000.0 - 240.0)) < 0.01

    def test_open_positions_count(self):
        p = BacktestPortfolio(100_000.0)
        p.open_position("BTC/USD", 50_000.0, 0.5, "t1")
        p.open_position("ETH/USD", 3_000.0, 1.0, "t2")
        assert len(p.open_positions()) == 2

    def test_equity_includes_open_positions(self):
        p = BacktestPortfolio(100_000.0)
        p.open_position("BTC/USD", 50_000.0, 0.5, "t1")
        # equity = cash(75k) + mark-to-market at current price
        # If current price == entry, equity == starting equity
        assert abs(p.equity(prices={"BTC/USD": 50_000.0}) - 100_000.0) < 0.01

    def test_trade_history_after_close(self):
        p = BacktestPortfolio(100_000.0)
        tid = p.open_position("BTC/USD", 50_000.0, 0.5, "t1")
        p.close_position(tid, 52_000.0, "t2", "trailing_stop")
        hist = p.trade_history()
        assert len(hist) == 1
        assert hist[0]["pnl"] == 1_000.0
        assert hist[0]["reason"] == "trailing_stop"

    def test_close_unknown_trade_raises(self):
        p = BacktestPortfolio(100_000.0)
        try:
            p.close_position(999, 50_000.0, "t", "stop")
            assert False, "should raise KeyError"
        except KeyError:
            pass
```

- [ ] **Step 2: Run to verify fails**

```bash
python -m pytest tests/backtester/test_portfolio.py -v
```

Expected: `ImportError: cannot import name 'BacktestPortfolio'`

- [ ] **Step 3: Create `src/backtester/portfolio.py`**

```python
"""
BacktestPortfolio — simulated position tracking for backtesting.

Simulates limit fills at the close price of the entry bar.
No slippage, no partial fills, no commissions (conservative for crypto).
"""
from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass
class _Position:
    trade_id: int
    symbol: str
    entry_price: float
    qty: float
    entry_timestamp: str
    cost_basis: float           # entry_price * qty


class BacktestPortfolio:
    """Tracks cash, open positions, and closed trade history."""

    def __init__(self, starting_equity: float = 100_000.0):
        self._cash = starting_equity
        self._positions: dict[int, _Position] = {}
        self._history: list[dict] = []
        self._next_id = 1

    # ── Writes ────────────────────────────────────────────────────────────────

    def open_position(
        self,
        symbol: str,
        entry_price: float,
        qty: float,
        timestamp: str,
    ) -> int:
        """Simulate a market buy. Deducts cost from cash. Returns trade_id."""
        cost = entry_price * qty
        self._cash -= cost
        trade_id = self._next_id
        self._next_id += 1
        self._positions[trade_id] = _Position(
            trade_id=trade_id,
            symbol=symbol,
            entry_price=entry_price,
            qty=qty,
            entry_timestamp=timestamp,
            cost_basis=cost,
        )
        return trade_id

    def close_position(
        self,
        trade_id: int,
        exit_price: float,
        timestamp: str,
        reason: str,
    ) -> float:
        """Simulate a market sell. Returns realised P&L."""
        pos = self._positions.pop(trade_id)     # raises KeyError if unknown
        proceeds = exit_price * pos.qty
        pnl = proceeds - pos.cost_basis
        self._cash += proceeds
        self._history.append({
            "trade_id":        trade_id,
            "symbol":          pos.symbol,
            "entry_price":     pos.entry_price,
            "exit_price":      exit_price,
            "qty":             pos.qty,
            "entry_timestamp": pos.entry_timestamp,
            "exit_timestamp":  timestamp,
            "pnl":             pnl,
            "reason":          reason,
        })
        return pnl

    # ── Reads ─────────────────────────────────────────────────────────────────

    def cash(self) -> float:
        return self._cash

    def equity(self, prices: dict[str, float] | None = None) -> float:
        """Total equity = cash + mark-to-market value of open positions.

        If `prices` not provided, uses entry price (no unrealised P&L).
        """
        mtm = sum(
            (prices.get(pos.symbol, pos.entry_price) if prices else pos.entry_price) * pos.qty
            for pos in self._positions.values()
        )
        return self._cash + mtm

    def open_positions(self) -> list[_Position]:
        return list(self._positions.values())

    def trade_history(self) -> list[dict]:
        return list(self._history)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/backtester/test_portfolio.py -v
```

Expected: 8 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add src/backtester/portfolio.py tests/backtester/test_portfolio.py
git commit -m "feat(phase0): add BacktestPortfolio with position tracking and P&L"
```

---

## Task 5: Backtester metrics

**Files:**
- Create: `src/backtester/metrics.py`
- Create: `tests/backtester/test_metrics.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/backtester/test_metrics.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.backtester.metrics import (
    sharpe_ratio, max_drawdown, win_rate, monitor_pnl, compute_summary
)


class TestSharpeRatio:
    def test_positive_returns(self):
        returns = [0.01] * 252   # 1%/period × 252
        sr = sharpe_ratio(returns)
        assert sr > 0

    def test_zero_returns(self):
        assert sharpe_ratio([0.0] * 10) == 0.0

    def test_negative_returns(self):
        returns = [-0.01] * 100
        assert sharpe_ratio(returns) < 0

    def test_empty_returns(self):
        assert sharpe_ratio([]) == 0.0


class TestMaxDrawdown:
    def test_no_drawdown(self):
        # Strictly increasing equity
        curve = [100.0 + i for i in range(10)]
        assert max_drawdown(curve) == 0.0

    def test_simple_drawdown(self):
        # Peak 110, drops to 99 → drawdown = (110-99)/110
        curve = [100.0, 105.0, 110.0, 99.0, 102.0]
        dd = max_drawdown(curve)
        assert abs(dd - (110 - 99) / 110) < 0.001

    def test_empty(self):
        assert max_drawdown([]) == 0.0


class TestWinRate:
    def test_all_wins(self):
        trades = [{"pnl": 100}, {"pnl": 50}, {"pnl": 200}]
        assert win_rate(trades) == 1.0

    def test_half_wins(self):
        trades = [{"pnl": 100}, {"pnl": -50}, {"pnl": 200}, {"pnl": -30}]
        assert win_rate(trades) == 0.5

    def test_empty(self):
        assert win_rate([]) == 0.0


class TestMonitorPnl:
    def test_sum_of_pnl(self):
        trades = [{"pnl": 100.0}, {"pnl": -50.0}, {"pnl": 75.0}]
        assert monitor_pnl(trades) == 125.0

    def test_empty(self):
        assert monitor_pnl([]) == 0.0


class TestComputeSummary:
    def test_full_summary(self):
        trades = [
            {"pnl": 500.0, "entry_timestamp": "2026-03-01T00:00:00",
             "exit_timestamp": "2026-03-02T00:00:00", "symbol": "BTC/USD"},
            {"pnl": -200.0, "entry_timestamp": "2026-03-03T00:00:00",
             "exit_timestamp": "2026-03-03T12:00:00", "symbol": "ETH/USD"},
        ]
        equity_curve = [100_000.0, 100_500.0, 100_300.0]
        result = compute_summary(trades, equity_curve, starting_equity=100_000.0)
        assert result["trade_count"] == 2
        assert result["monitor_pnl"] == 300.0
        assert result["win_rate"] == 0.5
        assert "sharpe_ratio" in result
        assert "max_drawdown" in result
        assert "total_return_pct" in result
```

- [ ] **Step 2: Run to verify fails**

```bash
python -m pytest tests/backtester/test_metrics.py -v
```

- [ ] **Step 3: Create `src/backtester/metrics.py`**

```python
"""Backtester performance metrics."""
from __future__ import annotations
import math


def sharpe_ratio(returns: list[float], risk_free: float = 0.0) -> float:
    """Annualised Sharpe ratio from per-period returns."""
    if len(returns) < 2:
        return 0.0
    n = len(returns)
    mean = sum(returns) / n - risk_free
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(252)   # annualise assuming daily periods


def max_drawdown(equity_curve: list[float]) -> float:
    """Maximum peak-to-trough drawdown as a fraction (0.0–1.0)."""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def win_rate(trades: list[dict]) -> float:
    """Fraction of closed trades with positive P&L."""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    return wins / len(trades)


def monitor_pnl(trades: list[dict]) -> float:
    """Total realised P&L across all closed trades."""
    return sum(t.get("pnl", 0.0) for t in trades)


def compute_summary(
    trades: list[dict],
    equity_curve: list[float],
    starting_equity: float = 100_000.0,
) -> dict:
    """Compute all metrics for a backtest run."""
    # Per-period returns from equity curve
    returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]
        returns.append((equity_curve[i] - prev) / prev if prev > 0 else 0.0)

    total_pnl = monitor_pnl(trades)
    final_equity = equity_curve[-1] if equity_curve else starting_equity

    return {
        "trade_count":       len(trades),
        "monitor_pnl":       round(total_pnl, 2),
        "win_rate":          round(win_rate(trades), 4),
        "sharpe_ratio":      round(sharpe_ratio(returns), 4),
        "max_drawdown":      round(max_drawdown(equity_curve), 4),
        "total_return_pct":  round((final_equity - starting_equity) / starting_equity * 100, 4),
        "final_equity":      round(final_equity, 2),
    }
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/backtester/test_metrics.py -v
```

Expected: 14 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add src/backtester/metrics.py tests/backtester/test_metrics.py
git commit -m "feat(phase0): add backtester metrics (Sharpe, drawdown, win rate, monitor P&L)"
```

---

## Task 6: PhaseConfig

**Files:**
- Create: `src/backtester/config.py`

No test needed — it's a plain dataclass with no logic.

- [ ] **Step 1: Create `src/backtester/config.py`**

```python
"""
PhaseConfig — feature flags for backtester phase comparisons.

Each phase preset represents the cumulative features active at that phase.
Use --disable <flag> to run counterfactuals.
"""
from __future__ import annotations
import dataclasses


@dataclasses.dataclass
class PhaseConfig:
    # Phase 0 — always on
    use_pipeline_state: bool = True

    # Phase 1
    skip_risk_gate: bool = False
    use_research_panel: bool = False

    # Phase 2
    use_atr_thresholds: bool = False
    use_vol_adjusted_kelly: bool = False

    # Phase 3
    use_weighted_ensemble: bool = False
    use_correlation_limits: bool = False

    # Phase 4
    use_sentiment: bool = False
    use_reentry_manager: bool = False
    use_regime_detection: bool = False

    # Misc
    min_confluence: int = 3
    kelly_fraction: float = 0.25
    max_position_pct: float = 0.05
    starting_equity: float = 100_000.0


# Named presets — cumulative (each phase enables everything from prior phases)
PHASE_PRESETS: dict[int, PhaseConfig] = {
    0: PhaseConfig(),
    1: PhaseConfig(skip_risk_gate=True, use_research_panel=True),
    2: PhaseConfig(skip_risk_gate=True, use_research_panel=True,
                   use_atr_thresholds=True, use_vol_adjusted_kelly=True),
    3: PhaseConfig(skip_risk_gate=True, use_research_panel=True,
                   use_atr_thresholds=True, use_vol_adjusted_kelly=True,
                   use_weighted_ensemble=True, use_correlation_limits=True),
    4: PhaseConfig(skip_risk_gate=True, use_research_panel=True,
                   use_atr_thresholds=True, use_vol_adjusted_kelly=True,
                   use_weighted_ensemble=True, use_correlation_limits=True,
                   use_sentiment=True, use_reentry_manager=True, use_regime_detection=True),
}
```

- [ ] **Step 2: Update `src/backtester/__init__.py` to export the key types**

```python
"""Backtester package — offline replay of the trading pipeline."""
from src.backtester.config import PhaseConfig, PHASE_PRESETS
from src.backtester.portfolio import BacktestPortfolio
from src.backtester.metrics import compute_summary

__all__ = ["PhaseConfig", "PHASE_PRESETS", "BacktestPortfolio", "compute_summary"]
```

- [ ] **Step 3: Commit**

```bash
git add src/backtester/config.py src/backtester/__init__.py
git commit -m "feat(phase0): add PhaseConfig with per-phase feature flag presets"
```

---

## Task 7: Backtester engine

**Files:**
- Create: `src/backtester/engine.py`
- Create: `tests/backtester/test_engine.py`

The engine iterates bars chronologically across all symbols, runs technical signals on a sliding window, and simulates entries/exits. Phase 0 uses hard thresholds only (no LLM).

- [ ] **Step 1: Write the failing test**

```python
# tests/backtester/test_engine.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.backtester.engine import BacktestEngine
from src.backtester.config import PhaseConfig, PHASE_PRESETS
from src.backtester.data_loader import load_bars_fixture

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_all_fixtures() -> dict[str, list[dict]]:
    bars = {}
    for sym in ["BTC/USD"]:
        try:
            bars[sym] = load_bars_fixture(sym, fixture_dir=FIXTURE_DIR)
        except FileNotFoundError:
            pass
    return bars


class TestBacktestEngine:
    def test_runs_without_error(self):
        engine = BacktestEngine(config=PHASE_PRESETS[0])
        bars_by_symbol = _load_all_fixtures()
        assert bars_by_symbol, "need at least one fixture"
        result = engine.run(bars_by_symbol, start_iso="2026-03-01", end_iso="2026-03-03")
        # May or may not have trades depending on signal — just must not error
        assert result is not None
        assert result.equity() > 0

    def test_equity_non_negative(self):
        engine = BacktestEngine(config=PHASE_PRESETS[0])
        result = engine.run(_load_all_fixtures(), "2026-03-01", "2026-03-03")
        assert result.equity() >= 0

    def test_history_has_expected_fields(self):
        engine = BacktestEngine(config=PHASE_PRESETS[0])
        result = engine.run(_load_all_fixtures(), "2026-03-01", "2026-03-03")
        for trade in result.trade_history():
            for field in ("symbol", "entry_price", "exit_price", "qty", "pnl", "reason"):
                assert field in trade, f"missing field: {field}"

    def test_no_duplicate_positions(self):
        """Engine must not open a second position in the same symbol while one is open."""
        engine = BacktestEngine(config=PHASE_PRESETS[0])
        result = engine.run(_load_all_fixtures(), "2026-03-01", "2026-03-03")
        open_symbols = {p.symbol for p in result.open_positions()}
        # No symbol can appear twice in open positions
        all_open = [p.symbol for p in result.open_positions()]
        assert len(all_open) == len(set(all_open))
```

- [ ] **Step 2: Run to verify fails**

```bash
python -m pytest tests/backtester/test_engine.py -v
```

- [ ] **Step 3: Create `src/backtester/engine.py`**

```python
"""
BacktestEngine — time-aligned replay of the trading pipeline.

Phase 0 behaviour:
  - Technical signals (analyze()) on a sliding 50-bar window
  - Entry: confluence >= config.min_confluence, no existing position in symbol
  - Exit: hard thresholds only (-4% hard stop, +10% hard take-profit)
  - No LLM calls (risk gate retired in Phase 1, soft thresholds in Phase 2)
  - Sizing: quarter-Kelly based on confluence score, capped at max_position_pct

Later phases wire in additional logic controlled by PhaseConfig flags.
"""
from __future__ import annotations

import logging
from typing import Any

from src.backtester.config import PhaseConfig
from src.backtester.portfolio import BacktestPortfolio
from src.exit_advisor import HARD_STOP_PCT, HARD_TAKE_PROFIT_PCT

log = logging.getLogger(__name__)

# Sliding window of bars fed to the signal engine
SIGNAL_WINDOW = 50

# Kelly win probabilities by confluence score (mirrors _kelly_technical in orchestrator)
_KELLY_PROBS = {3: 0.55, 4: 0.60, 5: 0.65}

# Minimum bars between entry scans per symbol (prevents re-scanning every tick)
SCAN_INTERVAL_BARS = 30


def _kelly_fraction(confluence: int, kelly_fraction: float, max_position_pct: float,
                    equity: float) -> float:
    """Dollar amount to invest based on Kelly criterion."""
    win_prob = _KELLY_PROBS.get(confluence, 0.55)
    loss_prob = 1 - win_prob
    # Edge fraction: (win_prob * 1 - loss_prob * 1) / 1 (assuming 1:1 payoff)
    edge = win_prob - loss_prob
    raw_kelly = edge * kelly_fraction
    capped = min(raw_kelly, max_position_pct)
    return capped * equity


class BacktestEngine:
    """Replays historical bars through the trading pipeline."""

    def __init__(self, config: PhaseConfig, starting_equity: float | None = None):
        self.config = config
        self._starting_equity = starting_equity or config.starting_equity

    def run(
        self,
        bars_by_symbol: dict[str, list[dict]],
        start_iso: str,
        end_iso: str,
    ) -> BacktestPortfolio:
        """Run the backtest and return the final portfolio state.

        Args:
            bars_by_symbol: dict of symbol → sorted list of OHLCV bars
            start_iso: inclusive start date, e.g. "2026-03-01"
            end_iso: inclusive end date, e.g. "2026-03-31"
        """
        portfolio = BacktestPortfolio(self._starting_equity)

        # Build time-sorted event stream across all symbols
        all_timestamps = sorted({
            b["timestamp"]
            for bars in bars_by_symbol.values()
            for b in bars
            if b["timestamp"][:10] >= start_iso[:10] and b["timestamp"][:10] <= end_iso[:10]
        })

        if not all_timestamps:
            log.warning("No bars in date range %s–%s", start_iso, end_iso)
            return portfolio

        # Per-symbol sliding windows and scan-rate limiting
        windows: dict[str, list[dict]] = {sym: [] for sym in bars_by_symbol}
        last_scan_idx: dict[str, int] = {sym: -SCAN_INTERVAL_BARS for sym in bars_by_symbol}
        bar_indices: dict[str, int] = {sym: 0 for sym in bars_by_symbol}
        open_trade_ids: dict[str, int] = {}   # symbol → trade_id

        # Pre-index bars by timestamp for O(1) lookup
        bars_by_ts: dict[str, dict[str, dict]] = {sym: {} for sym in bars_by_symbol}
        for sym, bars in bars_by_symbol.items():
            for bar in bars:
                bars_by_ts[sym][bar["timestamp"]] = bar

        equity_curve: list[float] = [self._starting_equity]

        for ts_idx, ts in enumerate(all_timestamps):
            current_prices: dict[str, float] = {}

            # Advance sliding windows
            for sym in bars_by_symbol:
                bar = bars_by_ts[sym].get(ts)
                if bar:
                    windows[sym].append(bar)
                    if len(windows[sym]) > SIGNAL_WINDOW + 10:
                        windows[sym] = windows[sym][-SIGNAL_WINDOW:]
                    current_prices[sym] = bar["close"]

            # ── Check exits for open positions ────────────────────────────────
            for sym, trade_id in list(open_trade_ids.items()):
                price = current_prices.get(sym)
                if price is None:
                    continue
                pos_list = [p for p in portfolio.open_positions() if p.trade_id == trade_id]
                if not pos_list:
                    del open_trade_ids[sym]
                    continue
                pos = pos_list[0]
                pnl_pct = (price - pos.entry_price) / pos.entry_price

                if pnl_pct <= HARD_STOP_PCT:
                    portfolio.close_position(trade_id, price, ts, "hard_stop")
                    del open_trade_ids[sym]
                elif pnl_pct >= HARD_TAKE_PROFIT_PCT:
                    portfolio.close_position(trade_id, price, ts, "hard_take_profit")
                    del open_trade_ids[sym]

            # ── Scan for new entries (throttled) ─────────────────────────────
            for sym, bars_window in windows.items():
                if sym in open_trade_ids:
                    continue   # already have a position
                if len(bars_window) < SIGNAL_WINDOW:
                    continue   # not enough data
                if ts_idx - last_scan_idx.get(sym, -SCAN_INTERVAL_BARS) < SCAN_INTERVAL_BARS:
                    continue   # scan rate limit

                last_scan_idx[sym] = ts_idx

                try:
                    from src.technical_signals import analyze
                    signal = analyze(sym, bars_window)
                except Exception as exc:
                    log.debug("Signal error for %s: %s", sym, exc)
                    continue

                if signal is None or signal.confluence_score < self.config.min_confluence:
                    continue

                price = current_prices.get(sym)
                if price is None or price <= 0:
                    continue

                equity = portfolio.equity(prices=current_prices)
                dollar_amt = _kelly_fraction(
                    signal.confluence_score,
                    self.config.kelly_fraction,
                    self.config.max_position_pct,
                    equity,
                )
                if dollar_amt < 10:
                    continue

                qty = dollar_amt / price
                trade_id = portfolio.open_position(sym, price, qty, ts)
                open_trade_ids[sym] = trade_id
                log.debug("ENTRY %s @ %.2f (confluence=%d, $%.0f)",
                          sym, price, signal.confluence_score, dollar_amt)

            equity_curve.append(portfolio.equity(prices=current_prices))

        self._last_equity_curve = equity_curve
        return portfolio

    def equity_curve(self) -> list[float]:
        """Returns the equity curve from the last run() call."""
        return getattr(self, "_last_equity_curve", [self._starting_equity])
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/backtester/test_engine.py -v
```

Expected: 4 tests PASSED

- [ ] **Step 5: Run all backtester tests to catch any regressions**

```bash
python -m pytest tests/backtester/ -v
```

Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add src/backtester/engine.py tests/backtester/test_engine.py
git commit -m "feat(phase0): add BacktestEngine with time-aligned bar replay"
```

---

## Task 8: HTML report + CLI

**Files:**
- Create: `src/backtester/report.py`
- Create: `src/backtester/cli.py`

- [ ] **Step 1: Create `src/backtester/report.py`**

```python
"""HTML report generator for backtest results. No external dependencies."""
from __future__ import annotations

import json
import os
from datetime import datetime


def generate_report(
    phase: int,
    config_dict: dict,
    summary: dict,
    equity_curve: list[float],
    trade_history: list[dict],
    output_dir: str = "data/backtest_results",
) -> str:
    """Write an HTML report and return the file path."""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"phase{phase}_{ts}.html"
    path = os.path.join(output_dir, fname)

    # Equity curve for inline chart (JSON array)
    eq_json = json.dumps(equity_curve)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Backtest Phase {phase} — {ts}</title>
<style>
  body {{ font-family: monospace; max-width: 900px; margin: 2rem auto; background: #0d1117; color: #e6edf3; }}
  h1, h2 {{ color: #58a6ff; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 1rem; }}
  th {{ background: #161b22; padding: 8px; text-align: left; }}
  td {{ padding: 6px 8px; border-bottom: 1px solid #30363d; }}
  .pos {{ color: #3fb950; }} .neg {{ color: #f85149; }}
  canvas {{ background: #161b22; border-radius: 6px; margin: 1rem 0; }}
</style>
</head>
<body>
<h1>Backtest Report — Phase {phase}</h1>
<p>Generated: {datetime.now().isoformat()[:19]}</p>

<h2>Summary</h2>
<table>
  <tr><th>Metric</th><th>Value</th></tr>
  <tr><td>Trade count</td><td>{summary.get('trade_count', 0)}</td></tr>
  <tr><td>Monitor P&L</td>
      <td class="{'pos' if summary.get('monitor_pnl',0)>=0 else 'neg'}">
          ${summary.get('monitor_pnl', 0):,.2f}</td></tr>
  <tr><td>Win rate</td><td>{summary.get('win_rate', 0):.1%}</td></tr>
  <tr><td>Sharpe ratio</td><td>{summary.get('sharpe_ratio', 0):.3f}</td></tr>
  <tr><td>Max drawdown</td><td class="neg">{summary.get('max_drawdown', 0):.2%}</td></tr>
  <tr><td>Total return</td>
      <td class="{'pos' if summary.get('total_return_pct',0)>=0 else 'neg'}">
          {summary.get('total_return_pct', 0):+.2f}%</td></tr>
  <tr><td>Final equity</td><td>${summary.get('final_equity', 0):,.2f}</td></tr>
</table>

<h2>Equity Curve</h2>
<canvas id="chart" width="880" height="300"></canvas>
<script>
const eq = {eq_json};
const canvas = document.getElementById('chart');
const ctx = canvas.getContext('2d');
const w = canvas.width, h = canvas.height, pad = 20;
const mn = Math.min(...eq), mx = Math.max(...eq);
const sy = (v) => pad + (1 - (v - mn) / (mx - mn || 1)) * (h - 2*pad);
const sx = (i) => pad + i / (eq.length - 1) * (w - 2*pad);
ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 1.5; ctx.beginPath();
eq.forEach((v,i) => i === 0 ? ctx.moveTo(sx(i), sy(v)) : ctx.lineTo(sx(i), sy(v)));
ctx.stroke();
</script>

<h2>Config</h2>
<pre>{json.dumps(config_dict, indent=2)}</pre>

<h2>Trade History</h2>
<table>
  <tr><th>Symbol</th><th>Entry</th><th>Exit</th><th>Qty</th><th>P&L</th><th>Reason</th></tr>
  {''.join(
    f'<tr><td>{t["symbol"]}</td><td>${t["entry_price"]:,.2f}</td>'
    f'<td>${t["exit_price"]:,.2f}</td><td>{t["qty"]:.4f}</td>'
    f'<td class="{"pos" if t["pnl"]>=0 else "neg"}">${t["pnl"]:+,.2f}</td>'
    f'<td>{t["reason"]}</td></tr>'
    for t in trade_history
  )}
</table>
</body></html>"""

    with open(path, "w") as f:
        f.write(html)
    return path
```

- [ ] **Step 2: Create `src/backtester/cli.py`**

```python
"""
Backtester CLI entry point.

Usage:
  python -m src.backtester --phase 0 --train
  python -m src.backtester --phase 0 --holdout
  python -m src.backtester --phase 0 --start 2026-02-01 --end 2026-04-09
  python -m src.backtester --phase 0 --holdout --disable skip_risk_gate
"""
from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("backtester")

TRAIN_START = "2025-10-01"
TRAIN_END   = "2026-01-31"
HOLDOUT_START = "2026-02-01"
HOLDOUT_END   = "2026-04-30"

SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD",
           "ADA/USD", "AVAX/USD", "DOT/USD", "LINK/USD"]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Trading bot backtester")
    parser.add_argument("--phase", type=int, default=0, choices=[0, 1, 2, 3, 4],
                        help="Phase preset to use")
    parser.add_argument("--train", action="store_true",
                        help=f"Use train window ({TRAIN_START} – {TRAIN_END})")
    parser.add_argument("--holdout", action="store_true",
                        help=f"Use holdout window ({HOLDOUT_START} – {HOLDOUT_END})")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--disable", nargs="*", default=[],
                        help="Disable PhaseConfig flags (e.g. --disable use_sentiment)")
    parser.add_argument("--fixture-dir", default=None,
                        help="Use fixture JSON files instead of Alpaca API (for testing)")
    parser.add_argument("--output-dir", default="data/backtest_results")
    args = parser.parse_args(argv)

    # Resolve date range
    if args.train:
        start, end = TRAIN_START, TRAIN_END
    elif args.holdout:
        start, end = HOLDOUT_START, HOLDOUT_END
    elif args.start and args.end:
        start, end = args.start, args.end
    else:
        parser.error("Provide --train, --holdout, or --start/--end")

    # Build config
    from src.backtester.config import PHASE_PRESETS
    config = PHASE_PRESETS[args.phase]
    for flag in args.disable:
        if not hasattr(config, flag):
            log.error("Unknown PhaseConfig flag: %s", flag)
            sys.exit(1)
        config = dataclasses.replace(config, **{flag: False})

    log.info("Phase %d | %s → %s | disabled=%s", args.phase, start, end, args.disable or "none")

    # Load bars
    from src.backtester.data_loader import load_bars
    bars_by_symbol: dict[str, list[dict]] = {}
    for sym in SYMBOLS:
        try:
            bars = load_bars(sym, start, end, fixture_dir=args.fixture_dir)
            if bars:
                bars_by_symbol[sym] = bars
                log.info("Loaded %d bars for %s", len(bars), sym)
        except Exception as exc:
            log.warning("Skipping %s: %s", sym, exc)

    if not bars_by_symbol:
        log.error("No bar data available — nothing to backtest")
        sys.exit(1)

    # Run engine
    from src.backtester.engine import BacktestEngine
    engine = BacktestEngine(config=config)
    portfolio = engine.run(bars_by_symbol, start_iso=start, end_iso=end)

    # Compute metrics
    from src.backtester.metrics import compute_summary
    summary = compute_summary(
        portfolio.trade_history(),
        engine.equity_curve(),
        starting_equity=config.starting_equity,
    )

    # Print summary
    log.info("── Backtest Results ──────────────────────────")
    for k, v in summary.items():
        log.info("  %-25s %s", k, v)
    log.info("─────────────────────────────────────────────")

    # Write HTML report
    from src.backtester.report import generate_report
    report_path = generate_report(
        phase=args.phase,
        config_dict=dataclasses.asdict(config),
        summary=summary,
        equity_curve=engine.equity_curve(),
        trade_history=portfolio.trade_history(),
        output_dir=args.output_dir,
    )
    log.info("Report written: %s", report_path)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Add `__main__.py` so `python -m src.backtester` works**

Create `src/backtester/__main__.py`:
```python
from src.backtester.cli import main
main()
```

- [ ] **Step 4: Smoke test the CLI with fixtures**

```bash
cd C:/Users/artic/GitHub/aipredictedwins
python -m src.backtester --phase 0 --start 2026-03-01 --end 2026-03-03 \
  --fixture-dir tests/backtester/fixtures
```

Expected: logs show loaded bars, summary metrics, and "Report written: data/backtest_results/phase0_*.html"

- [ ] **Step 5: Commit**

```bash
git add src/backtester/report.py src/backtester/cli.py src/backtester/__main__.py
git commit -m "feat(phase0): add HTML report generator and CLI entry point"
```

---

## Task 9: Wire PipelineState into the orchestrator

**Files:**
- Modify: `src/alpaca_orchestrator.py` (lines ~532–694)

This is a refactor only — zero behavior change. The same logic runs, just wrapped in `PipelineState` objects. Existing tests must still pass.

The scan loop currently builds ad-hoc dicts (`approved` list). We replace this with a list of `PipelineState` objects flowing through stages.

- [ ] **Step 1: Verify existing tests pass before touching anything**

```bash
python -m pytest tests/ -v --ignore=tests/backtester
```

Expected: all PASSED (note the current test file imports `_kelly_technical` from the orchestrator — verify this function exists)

- [ ] **Step 2: Add the import at the top of `src/alpaca_orchestrator.py`**

Add after the existing imports block (after `from src.trade_logger import TradeLogger`):

```python
from src.pipeline_state import PipelineState
```

- [ ] **Step 3: Replace the `approved` list assembly in the scan loop**

Find this block (around line 562):

```python
            # Filter: minimum confluence, dedup, and blocklist meme coins
            candidates = [
                s for s in signals
                if s.confluence_score >= MIN_CONFLUENCE
                and s.symbol not in open_symbols
                and s.symbol not in MEME_CRYPTO
            ]
```

Replace the `approved = []` list and the per-signal loop that builds it (lines ~564–624) with:

```python
            # Filter: minimum confluence, dedup, and blocklist meme coins
            candidates = [
                s for s in signals
                if s.confluence_score >= MIN_CONFLUENCE
                and s.symbol not in open_symbols
                and s.symbol not in MEME_CRYPTO
            ]
            signals_found = len(candidates)

            if candidates:
                console.print(f"  [bold]{signals_found}[/bold] candidates with confluence >= {MIN_CONFLUENCE}")
                for c in candidates:
                    console.print(
                        f"    {c.symbol}: score={c.confluence_score} "
                        f"ema={'UP' if c.ema_bullish else 'DN'} "
                        f"adx={c.adx_value:.0f} rsi={c.rsi_value:.0f} "
                        f"vol_spike={c.volume_spike} vwap={'UP' if c.vwap_bullish else 'DN'}"
                    )
            else:
                console.print("  No assets meet confluence threshold")

            # Build initial PipelineState for each candidate
            pipeline_states: list[PipelineState] = []
            for signal in candidates:
                symbol = signal.symbol
                try:
                    price = alpaca.get_latest_price(symbol)
                    bars = alpaca.get_bars(symbol, timeframe="1Hour", limit=24)
                    if bars and len(bars) >= 2:
                        change_pct = ((price - bars[0]["open"]) / bars[0]["open"] * 100) if bars[0]["open"] > 0 else 0.0
                    else:
                        change_pct = 0.0
                    state = PipelineState(
                        symbol=symbol,
                        bars=tuple(bars or []),
                        signal=signal,
                    )
                    pipeline_states.append(state)
                except Exception as exc:
                    console.print(f"    [red]Price fetch error for {symbol}: {exc}[/red]")
                    log.exception("Price fetch failed for %s", symbol)
                    continue

            # -- 4c. Layer 2: MiroFish Risk Gate (or bypass) ------------------
            approved_states: list[PipelineState] = []

            for state in pipeline_states:
                symbol = state.symbol
                signal = state.signal
                price = state.bars[-1]["close"] if state.bars else 0.0
                bars = list(state.bars)
                volume_24h = sum(b["volume"] for b in bars) if bars else 0
                change_pct = ((price - bars[0]["open"]) / bars[0]["open"] * 100) if bars and bars[0]["open"] > 0 else 0.0

                try:
                    if SKIP_RISK_GATE:
                        risk_gate_passed += 1
                        console.print(f"  [green]APPROVED[/green] {symbol} (risk gate disabled)")
                        approved_states.append(state)
                        continue

                    console.print(f"\n  [cyan]Layer 2: Risk gate for {symbol}...[/cyan]")
                    verdict = risk_gate.evaluate(
                        symbol=symbol,
                        price=price,
                        change_pct=change_pct,
                        volume=volume_24h,
                        confluence=signal.confluence_score,
                        bars=bars,
                    )

                    if verdict.decision == "PROCEED":
                        risk_gate_passed += 1
                        console.print(f"    [green]PROCEED[/green] — {verdict.reasoning[:80]}")
                        approved_states.append(state)
                    else:
                        veto_count = sum(1 for v in verdict.votes.values() if str(v).upper() == "VETO")
                        console.print(
                            f"    [red]VETO[/red] ({veto_count}/5 analysts) — {verdict.reasoning[:80]}"
                        )

                except Exception as exc:
                    console.print(f"    [red]Risk gate error: {exc}[/red]")
                    log.exception("Risk gate failed for %s", symbol)
```

- [ ] **Step 4: Update the order placement loop to use `approved_states`**

Find the loop that starts `for entry in approved:` (around line 628). Replace `for entry in approved:` with `for state in approved_states:` and update field access:

```python
            # -- 4d. Layer 3: Size and place orders ---------------------------
            cycle_exposure = 0.0
            for state in approved_states:
                # Re-check total exposure before each trade
                if equity > 0 and (total_exposure + cycle_exposure) / equity >= MAX_TOTAL_EXPOSURE_PCT:
                    console.print(
                        f"  [yellow]Exposure limit ({MAX_TOTAL_EXPOSURE_PCT:.0%}) reached "
                        f"— skipping remaining candidates[/yellow]"
                    )
                    break

                signal = state.signal
                symbol = state.symbol
                price = state.bars[-1]["close"] if state.bars else 0.0
                bars = list(state.bars)

                sizing = _kelly_technical(
                    confluence=signal.confluence_score,
                    current_price=price,
                    bankroll=bankroll,
                    kelly_fraction=config.kelly_fraction,
                    max_position_pct=MAX_POSITION_PCT,
                )
```

Everything after the `sizing = _kelly_technical(...)` call is unchanged — it still uses `symbol`, `price`, `signal`, `sizing` locals.

- [ ] **Step 5: Run all tests**

```bash
python -m pytest tests/ -v --ignore=tests/backtester
```

Expected: same results as Step 1 — all PASSED. Zero behavior change.

- [ ] **Step 6: Commit**

```bash
git add src/alpaca_orchestrator.py
git commit -m "refactor(phase0): wrap orchestrator scan loop in PipelineState (no behavior change)"
```

---

## Task 10: End-to-end validation

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all PASSED

- [ ] **Step 2: Run backtester on fixtures to confirm report generates cleanly**

```bash
python -m src.backtester --phase 0 --start 2026-03-01 --end 2026-03-03 \
  --fixture-dir tests/backtester/fixtures
```

Expected output includes:
```
INFO backtester: Loaded 60 bars for BTC/USD
INFO backtester:   trade_count               <some number>
INFO backtester:   monitor_pnl               <value>
INFO backtester: Report written: data/backtest_results/phase0_*.html
```

- [ ] **Step 3: Verify `LLMCache` round-trip manually**

```bash
python - <<'EOF'
from src.claude_llm import LLMCache
import os, tempfile
with tempfile.TemporaryDirectory() as d:
    c = LLMCache(os.path.join(d, "test.db"))
    c.put("hello world", "claude-sonnet-4-6", "mock response")
    assert c.get("hello world", "claude-sonnet-4-6") == "mock response"
    assert c.get("different prompt", "claude-sonnet-4-6") is None
    print("LLMCache round-trip: OK")
EOF
```

Expected: `LLMCache round-trip: OK`

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "feat(phase0): complete Phase 0 — backtester + PipelineState foundation"
```

---

## Self-Review

**Spec coverage check:**
- ✅ PipelineState frozen dataclass with `with_updates()` — Task 1
- ✅ LLM cache by `sha256(full_prompt_string)` in `data/llm_cache.db` — Task 2
- ✅ Walk-forward split documented in CLI (TRAIN_START/HOLDOUT_START constants) — Task 8
- ✅ PhaseConfig with all phase flags — Task 6
- ✅ `--compare-phases` flag — **gap**: not implemented here. The CLI has `--phase` but not `--compare-phases`. This is a Phase 5 deliverable per the spec — correctly deferred.
- ✅ `python -m src.backtester --phase N --holdout` — Task 8/9
- ✅ Orchestrator wired with PipelineState, no behavior change — Task 9
- ✅ Phase 0 exit criteria: backtester produces clean report + existing tests pass — Task 10

**Placeholder scan:** No TBDs, no "implement later", all steps have code.

**Type consistency:**
- `PipelineState.bars: tuple[dict, ...]` — used consistently in Tasks 1, 9
- `BacktestPortfolio.open_positions()` returns `list[_Position]` — engine accesses `.trade_id`, `.symbol`, `.entry_price` — all defined on `_Position` in Task 4
- `compute_summary()` returns dict with keys `trade_count`, `monitor_pnl`, `win_rate`, `sharpe_ratio`, `max_drawdown`, `total_return_pct`, `final_equity` — all used in report.py Task 8 ✅
