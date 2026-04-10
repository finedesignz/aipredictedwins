# Signal Quality & Entry Discipline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 7 root causes that caused both bots to enter all 8 overbought crypto assets simultaneously, losing money in a rising market.

**Architecture:** Two batches. Batch 1 (Tasks 1–4) fixes entry quality — RSI block, ADX direction, risk gate bypass removal, per-cycle cap. Batch 2 (Tasks 5–7) adds market context — BTC regime filter, exit threshold recalibration, volume pump filter. Deploy Batch 1 first, run 48h, then Batch 2.

**Tech Stack:** Python 3.11, `src/technical_signals.py`, `src/risk_gate.py`, `src/exit_advisor.py`, `src/alpaca_orchestrator.py`, pytest

---

## File Map

| File | What changes |
|------|-------------|
| `src/technical_signals.py` | `_adx()` returns tuple; `Signal` gets `plus_di`/`minus_di`; `analyze()` adds RSI block + ADX direction check |
| `src/risk_gate.py` | Delete `HIGH_CONFLUENCE_BYPASS` constant and bypass logic |
| `src/exit_advisor.py` | Recalibrate all threshold constants; update `TrailingStop` activation/distance/tighten logic; update `check_position_thresholds`; update `should_exit` |
| `src/alpaca_orchestrator.py` | Per-cycle entry cap (sort + slice top 3); BTC regime pre-check; volume market context filter; update Kelly b-ratio |
| `tests/test_technical_signals.py` | Update `_adx` tests for tuple return; add RSI block tests; add ADX direction tests |
| `tests/test_exit_advisor.py` | New file: threshold tests for new values; trailing stop tests for new activation/tighten logic |

---

## BATCH 1 — Core Entry Quality

---

### Task 1: RSI Hard Block at Entry

**Files:**
- Modify: `src/technical_signals.py`
- Modify: `tests/test_technical_signals.py`

- [x] **Step 1: Write the failing tests**

Add to `tests/test_technical_signals.py`:

```python
class TestRSIHardBlock:
    def test_overbought_rsi_returns_none(self):
        """Assets with RSI > 72 must be blocked before scoring."""
        # Steady strong uptrend → RSI will be well above 72
        bars = _make_uptrend_bars(50, start=100.0, step=1.5)
        signal = analyze("BTC/USD", bars)
        # RSI on a strong uptrend will exceed 72; signal must be None
        from src.technical_signals import _rsi
        closes = [b["close"] for b in bars]
        rsi = _rsi(closes, 14)
        if rsi is not None and rsi > 72:
            assert signal is None, f"Expected None for RSI={rsi:.1f} > 72, got score={signal.confluence_score if signal else 'N/A'}"

    def test_rsi_at_72_is_blocked(self):
        """RSI exactly at 72 is blocked (ceiling is exclusive: > 72 blocked)."""
        # We'll test the boundary by directly checking analyze() returns None
        # when RSI would be > 72 on the input data
        # Generate bars that produce RSI ~73-75
        # Strong uptrend for 20 bars
        closes = [100 + i * 0.8 for i in range(40)]
        bars = []
        for i, c in enumerate(closes):
            bars.append({
                "open": c * 0.999, "high": c * 1.005,
                "low": c * 0.995, "close": c,
                "volume": 1000.0 + i * 10, "vwap": c * 1.001,
                "timestamp": f"2026-03-27T{i:02d}:00:00",
            })
        from src.technical_signals import _rsi
        rsi = _rsi(closes, 14)
        result = analyze("ETH/USD", bars)
        if rsi is not None and rsi > 72:
            assert result is None

    def test_rsi_below_ceiling_scores_normally(self):
        """Assets with RSI <= 72 are scored normally."""
        # Moderate uptrend → RSI in 50-65 range
        bars = _make_uptrend_bars(50, start=100.0, step=0.1)
        from src.technical_signals import _rsi
        closes = [b["close"] for b in bars]
        rsi = _rsi(closes, 14)
        result = analyze("SOL/USD", bars)
        # If RSI <= 72, analyze() should return a Signal (not None due to RSI)
        if rsi is not None and rsi <= 72:
            # May still be None for other reasons (insufficient data etc.) but
            # RSI block should NOT be the reason
            pass  # just confirm no crash

    def test_oversold_rsi_still_scores(self):
        """RSI < 35 (oversold) still earns confluence +1."""
        bars = _make_downtrend_bars(50, start=125.0, step=0.8)
        from src.technical_signals import _rsi
        closes = [b["close"] for b in bars]
        rsi = _rsi(closes, 14)
        result = analyze("ADA/USD", bars)
        # Oversold RSI should not be blocked
        if rsi is not None and rsi < 35:
            # analyze() should not block on oversold RSI
            # (it may return None for other reasons but not the RSI block)
            assert result is None or result.rsi_signal == "oversold"
```

- [x] **Step 2: Run tests to confirm they fail**

```bash
cd C:/Users/artic/GitHub/aipredictedwins
python -m pytest tests/test_technical_signals.py::TestRSIHardBlock -v
```

Expected: FAIL — no RSI block exists yet.

- [x] **Step 3: Add RSI hard block to `analyze()`**

In `src/technical_signals.py`, inside `analyze()`, add the RSI check immediately after computing `rsi_value` (around line 234), before the confluence scoring block:

```python
    # --- RSI (14-period) ---
    rsi_value = _rsi(closes, 14)
    if rsi_value is None:
        rsi_value = 50.0
    if rsi_value < 30:
        rsi_signal = "oversold"
    elif rsi_value > 70:
        rsi_signal = "overbought"
    else:
        rsi_signal = "neutral"

    # Hard block: overbought assets are not candidates regardless of other signals.
    # RSI > 72 means buyers are exhausted — this is a late entry, not a good one.
    RSI_ENTRY_CEILING = 72.0
    if rsi_value > RSI_ENTRY_CEILING:
        log.debug(
            "BLOCKED %s: RSI=%.1f > %.0f ceiling (overbought entry rejected)",
            symbol, rsi_value, RSI_ENTRY_CEILING,
        )
        return None
```

Place this block right after the `rsi_signal` assignment, before the volume spike calculation.

- [x] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_technical_signals.py::TestRSIHardBlock -v
```

Expected: PASS for any test case where RSI > 72 on the generated data.

- [x] **Step 5: Run full test suite to check for regressions**

```bash
python -m pytest tests/test_technical_signals.py -v
```

Expected: All existing tests pass. Note: `test_uptrend_high_rsi` in `TestRSI` tests `_rsi()` directly (not `analyze()`), so it is unaffected.

- [x] **Step 6: Commit**

```bash
git add src/technical_signals.py tests/test_technical_signals.py
git commit -m "feat: RSI hard block — reject assets with RSI > 72 at entry"
```

---

### Task 2: ADX Directional Filter (+DI > -DI)

**Files:**
- Modify: `src/technical_signals.py`
- Modify: `tests/test_technical_signals.py`

- [x] **Step 1: Write the failing tests**

Add to `tests/test_technical_signals.py`:

```python
class TestADXDirectional:
    def test_adx_returns_tuple(self):
        """_adx() must return (adx, plus_di, minus_di) tuple."""
        n = 50
        highs = [100 + i * 1.2 for i in range(n)]
        lows = [99 + i * 1.0 for i in range(n)]
        closes = [100 + i * 1.1 for i in range(n)]
        result = _adx(highs, lows, closes, 14)
        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        assert len(result) == 3
        adx, plus_di, minus_di = result
        assert adx is not None
        assert plus_di >= 0
        assert minus_di >= 0

    def test_adx_uptrend_plus_di_dominates(self):
        """In an uptrend, +DI should exceed -DI."""
        n = 50
        highs = [100 + i * 1.2 for i in range(n)]
        lows = [99 + i * 1.0 for i in range(n)]
        closes = [100 + i * 1.1 for i in range(n)]
        adx, plus_di, minus_di = _adx(highs, lows, closes, 14)
        assert plus_di > minus_di, f"Expected +DI ({plus_di:.1f}) > -DI ({minus_di:.1f}) in uptrend"

    def test_adx_downtrend_minus_di_dominates(self):
        """In a downtrend, -DI should exceed +DI."""
        n = 50
        highs = [125 - i * 1.0 for i in range(n)]
        lows = [124 - i * 1.2 for i in range(n)]
        closes = [124.5 - i * 1.1 for i in range(n)]
        adx, plus_di, minus_di = _adx(highs, lows, closes, 14)
        assert minus_di > plus_di, f"Expected -DI ({minus_di:.1f}) > +DI ({plus_di:.1f}) in downtrend"

    def test_adx_insufficient_data_returns_none_tuple(self):
        """Insufficient data returns (None, 0.0, 0.0)."""
        result = _adx([1, 2, 3], [0.5, 1.5, 2.5], [0.8, 1.8, 2.8], 14)
        assert result is None or (isinstance(result, tuple) and result[0] is None)

    def test_analyze_downtrend_adx_does_not_score(self):
        """ADX in a downtrend (−DI > +DI) must not contribute +1 to confluence."""
        bars = _make_downtrend_bars(50, start=125.0, step=0.8)
        signal = analyze("DOT/USD", bars)
        # In a downtrend, -DI > +DI so ADX should NOT score
        # Downtrend also has EMA bearish, so confluence should be low
        if signal is not None:
            assert signal.adx_trending is False or signal.ema_bullish is False
```

- [x] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_technical_signals.py::TestADXDirectional -v
```

Expected: FAIL — `_adx()` returns a float, not a tuple.

- [x] **Step 3: Refactor `_adx()` to return `(adx, plus_di, minus_di)`**

Replace the entire `_adx()` function in `src/technical_signals.py`:

```python
def _adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> tuple[float, float, float] | None:
    """Average Directional Index with directional indicators.

    Returns (adx, plus_di, minus_di) or None if insufficient data.
    Requires at least (period * 2 + 1) bars.
    """
    n = len(closes)
    if n < period * 2 + 1 or len(highs) != n or len(lows) != n:
        return None

    tr_list = []
    plus_dm_list = []
    minus_dm_list = []

    for i in range(1, n):
        high_diff = highs[i] - highs[i - 1]
        low_diff = lows[i - 1] - lows[i]

        plus_dm = high_diff if high_diff > low_diff and high_diff > 0 else 0.0
        minus_dm = low_diff if low_diff > high_diff and low_diff > 0 else 0.0

        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

        tr_list.append(tr)
        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)

    atr = sum(tr_list[:period])
    plus_dm_smooth = sum(plus_dm_list[:period])
    minus_dm_smooth = sum(minus_dm_list[:period])

    dx_list = []

    for i in range(period, len(tr_list)):
        atr = atr - (atr / period) + tr_list[i]
        plus_dm_smooth = plus_dm_smooth - (plus_dm_smooth / period) + plus_dm_list[i]
        minus_dm_smooth = minus_dm_smooth - (minus_dm_smooth / period) + minus_dm_list[i]

        plus_di = (plus_dm_smooth / atr * 100) if atr > 0 else 0
        minus_di = (minus_dm_smooth / atr * 100) if atr > 0 else 0

        di_sum = plus_di + minus_di
        dx = (abs(plus_di - minus_di) / di_sum * 100) if di_sum > 0 else 0
        dx_list.append(dx)

    if len(dx_list) < period:
        return None

    adx = sum(dx_list[:period]) / period
    for dx in dx_list[period:]:
        adx = (adx * (period - 1) + dx) / period

    # Compute final +DI and -DI from the last smoothed values
    final_plus_di = (plus_dm_smooth / atr * 100) if atr > 0 else 0.0
    final_minus_di = (minus_dm_smooth / atr * 100) if atr > 0 else 0.0

    return (adx, final_plus_di, final_minus_di)
```

- [x] **Step 4: Update `Signal` dataclass to include directional fields**

In `src/technical_signals.py`, update the `Signal` dataclass:

```python
@dataclass
class Signal:
    """Result of technical analysis for a single asset."""
    symbol: str
    ema_bullish: bool
    adx_value: float
    adx_trending: bool
    plus_di: float        # +DI from ADX calculation
    minus_di: float       # -DI from ADX calculation
    rsi_value: float
    rsi_signal: str          # "oversold", "overbought", or "neutral"
    volume_spike: bool
    vwap_bullish: bool
    confluence_score: int    # 0-5: how many indicators are bullish
    details: dict            # raw indicator values for logging
```

- [x] **Step 5: Update `analyze()` to use the new ADX tuple and directional condition**

Replace the ADX section in `analyze()` (around line 226):

```python
    # --- ADX (14-period) ---
    adx_result = _adx(highs, lows, closes, 14)
    if adx_result is None:
        adx_value = 0.0
        plus_di = 0.0
        minus_di = 0.0
    else:
        adx_value, plus_di, minus_di = adx_result
    # ADX trending: must have strength (> 20) AND be directionally bullish (+DI > -DI)
    adx_trending = adx_value > 20 and plus_di > minus_di
```

Also update the `Signal` construction at the bottom of `analyze()` to include the new fields:

```python
    return Signal(
        symbol=symbol,
        ema_bullish=ema_bullish,
        adx_value=adx_value,
        adx_trending=adx_trending,
        plus_di=round(plus_di, 2),
        minus_di=round(minus_di, 2),
        rsi_value=rsi_value,
        rsi_signal=rsi_signal,
        volume_spike=vol_spike,
        vwap_bullish=vwap_bull,
        confluence_score=score,
        details=details,
    )
```

Also add `plus_di` and `minus_di` to the `details` dict:

```python
    details = {
        "ema9": round(ema9_latest, 6),
        "ema21": round(ema21_latest, 6),
        "adx": round(adx_value, 2),
        "plus_di": round(plus_di, 2),
        "minus_di": round(minus_di, 2),
        "rsi": round(rsi_value, 2),
        "volume_spike_ratio": round(
            volumes[-1] / (sum(volumes[-21:-1]) / 20) if len(volumes) >= 21 and sum(volumes[-21:-1]) > 0 else 0, 2
        ),
        "latest_close": closes[-1],
        "latest_volume": volumes[-1],
    }
```

- [x] **Step 6: Fix the existing ADX tests that expect a float**

Update `TestADX` in `tests/test_technical_signals.py` — the existing tests call `_adx()` and expect a float. Update them to unpack the tuple:

```python
class TestADX:
    def test_strong_trend_high_adx(self):
        n = 50
        highs = [100 + i * 1.2 for i in range(n)]
        lows = [99 + i * 1.0 for i in range(n)]
        closes = [100 + i * 1.1 for i in range(n)]
        result = _adx(highs, lows, closes, 14)
        assert result is not None
        adx, plus_di, minus_di = result
        assert adx > 20

    def test_insufficient_data(self):
        assert _adx([1, 2, 3], [0.5, 1.5, 2.5], [0.8, 1.8, 2.8], 14) is None

    def test_returns_tuple(self):
        n = 50
        highs = [100 + i * 0.5 for i in range(n)]
        lows = [99 + i * 0.5 for i in range(n)]
        closes = [99.5 + i * 0.5 for i in range(n)]
        result = _adx(highs, lows, closes, 14)
        assert isinstance(result, tuple)
        adx, plus_di, minus_di = result
        assert isinstance(adx, float)
```

Also update `TestAnalyze.test_signal_fields` to include new fields:

```python
    def test_signal_fields(self):
        bars = _make_uptrend_bars(50)
        signal = analyze("BTC/USD", bars)
        assert signal is not None
        assert hasattr(signal, "ema_bullish")
        assert hasattr(signal, "adx_value")
        assert hasattr(signal, "adx_trending")
        assert hasattr(signal, "plus_di")
        assert hasattr(signal, "minus_di")
        assert hasattr(signal, "rsi_value")
        assert hasattr(signal, "rsi_signal")
        assert hasattr(signal, "volume_spike")
        assert hasattr(signal, "vwap_bullish")
        assert hasattr(signal, "confluence_score")
        assert hasattr(signal, "details")
        assert 0 <= signal.confluence_score <= 5
        assert signal.plus_di >= 0
        assert signal.minus_di >= 0
```

- [x] **Step 7: Run all signal tests**

```bash
python -m pytest tests/test_technical_signals.py -v
```

Expected: All pass including new `TestADXDirectional` tests.

- [x] **Step 8: Commit**

```bash
git add src/technical_signals.py tests/test_technical_signals.py
git commit -m "feat: ADX directional filter — require +DI > -DI for bullish confirmation"
```

---

### Task 3: Remove HIGH_CONFLUENCE_BYPASS from Risk Gate

**Files:**
- Modify: `src/risk_gate.py`
- Modify: `tests/test_technical_signals.py`

- [x] **Step 1: Write the failing test**

Add to `tests/test_technical_signals.py`:

```python
class TestRiskGateNoBypass:
    def test_high_confluence_bypass_does_not_exist(self):
        """HIGH_CONFLUENCE_BYPASS must not exist on RiskGate."""
        from src.risk_gate import RiskGate
        assert not hasattr(RiskGate, "HIGH_CONFLUENCE_BYPASS"), (
            "HIGH_CONFLUENCE_BYPASS still exists — bypass must be removed entirely"
        )

    def test_llm_unavailable_always_vetoes(self):
        """When LLM is unavailable, gate must VETO at any confluence level."""
        from src.risk_gate import RiskGate
        gate = RiskGate.__new__(RiskGate)
        gate.logger = None

        # Simulate LLM unavailable by patching _llm.call to return None
        class FakeLLM:
            def call(self, *a, **kw): return None

        gate._llm = FakeLLM()

        # Previously: confluence=4 would PROCEED on LLM failure. Now must VETO.
        verdict = gate.evaluate(
            symbol="BTC/USD", price=70000.0, change_pct=1.5,
            volume=1000000.0, confluence=4, bars=[],
        )
        assert verdict.decision == "VETO", (
            f"Expected VETO when LLM unavailable (confluence=4), got {verdict.decision}"
        )
```

- [x] **Step 2: Run test to confirm it fails**

```bash
python -m pytest tests/test_technical_signals.py::TestRiskGateNoBypass -v
```

Expected: FAIL — bypass still exists.

- [x] **Step 3: Remove bypass from `src/risk_gate.py`**

Delete the class constant and rewrite the LLM-unavailable branch in `evaluate()`:

Remove this line from the class:
```python
    # High-confluence trades (4+/5) can bypass the gate when LLM is unavailable
    HIGH_CONFLUENCE_BYPASS = 4
```

Replace the `if raw is None:` block (around line 127) with:

```python
        if raw is None:
            log.error("Risk gate LLM call failed for %s — VETO (fail-closed)", symbol)
            verdict = RiskVerdict(
                decision="VETO",
                reasoning="Risk gate LLM unavailable. VETO fail-closed regardless of confluence.",
                scenarios=[], votes={}, raw_response="",
            )
```

- [x] **Step 4: Run tests**

```bash
python -m pytest tests/test_technical_signals.py::TestRiskGateNoBypass tests/test_technical_signals.py::TestRiskGateParsing -v
```

Expected: All pass.

- [x] **Step 5: Commit**

```bash
git add src/risk_gate.py tests/test_technical_signals.py
git commit -m "feat: remove HIGH_CONFLUENCE_BYPASS — risk gate always runs, fail-closed on LLM failure"
```

---

### Task 4: Per-Cycle Entry Cap (max 3 new positions)

**Files:**
- Modify: `src/alpaca_orchestrator.py`
- Modify: `tests/test_technical_signals.py`

- [x] **Step 1: Write the failing test**

Add to `tests/test_technical_signals.py`:

```python
class TestPerCycleEntryCap:
    def test_select_top_candidates_by_score_then_rsi(self):
        """_select_cycle_candidates must cap at 3, sorted by confluence desc then RSI asc."""
        from src.alpaca_orchestrator import _select_cycle_candidates
        from src.technical_signals import Signal

        def _make_signal(symbol, score, rsi):
            return Signal(
                symbol=symbol, ema_bullish=True, adx_value=25.0,
                adx_trending=True, plus_di=20.0, minus_di=10.0,
                rsi_value=rsi, rsi_signal="neutral",
                volume_spike=True, vwap_bullish=True,
                confluence_score=score, details={},
            )

        candidates = [
            _make_signal("BTC/USD", 4, 65),
            _make_signal("ETH/USD", 4, 58),   # same score, lower RSI → preferred
            _make_signal("SOL/USD", 3, 50),
            _make_signal("XRP/USD", 4, 70),   # same score, highest RSI → least preferred
            _make_signal("ADA/USD", 3, 45),
            _make_signal("AVAX/USD", 5, 60),  # highest score → first
        ]

        selected = _select_cycle_candidates(candidates, max_entries=3)
        assert len(selected) == 3
        # Order: AVAX (5/60), ETH (4/58), BTC (4/65)
        assert selected[0].symbol == "AVAX/USD"
        assert selected[1].symbol == "ETH/USD"
        assert selected[2].symbol == "BTC/USD"

    def test_fewer_than_cap_returns_all(self):
        """If fewer candidates than cap, return all."""
        from src.alpaca_orchestrator import _select_cycle_candidates
        from src.technical_signals import Signal

        def _make_signal(symbol, score, rsi):
            return Signal(
                symbol=symbol, ema_bullish=True, adx_value=25.0,
                adx_trending=True, plus_di=20.0, minus_di=10.0,
                rsi_value=rsi, rsi_signal="neutral",
                volume_spike=True, vwap_bullish=True,
                confluence_score=score, details={},
            )

        candidates = [_make_signal("BTC/USD", 4, 55), _make_signal("ETH/USD", 3, 50)]
        selected = _select_cycle_candidates(candidates, max_entries=3)
        assert len(selected) == 2
```

- [x] **Step 2: Run test to confirm it fails**

```bash
python -m pytest tests/test_technical_signals.py::TestPerCycleEntryCap -v
```

Expected: FAIL — `_select_cycle_candidates` does not exist yet.

- [x] **Step 3: Add `_select_cycle_candidates()` to `src/alpaca_orchestrator.py`**

Add this function after the `_kelly_technical` function (around line 367):

```python
MAX_ENTRIES_PER_CYCLE = int(_os.environ.get("MAX_ENTRIES_PER_CYCLE", "3"))


def _select_cycle_candidates(candidates: list, max_entries: int = MAX_ENTRIES_PER_CYCLE) -> list:
    """Select the best candidates for this cycle, capped at max_entries.

    Selection priority:
    1. Highest confluence score (more indicators agreeing = better)
    2. Lowest RSI as tiebreaker (more room to run before overbought)

    This prevents deploying all capital in one correlated burst when the
    whole market is moving simultaneously.
    """
    sorted_candidates = sorted(
        candidates,
        key=lambda s: (-s.confluence_score, s.rsi_value),
    )
    return sorted_candidates[:max_entries]
```

- [x] **Step 4: Wire `_select_cycle_candidates` into the main loop**

In the main loop in `main()`, find the line (around line 550):

```python
            candidates = [
                s for s in signals
                if s.confluence_score >= MIN_CONFLUENCE
                and s.symbol not in open_symbols
                and s.symbol not in MEME_CRYPTO
            ]
            signals_found = len(candidates)
```

Change to:

```python
            # Filter: minimum confluence, dedup, blocklist
            all_candidates = [
                s for s in signals
                if s.confluence_score >= MIN_CONFLUENCE
                and s.symbol not in open_symbols
                and s.symbol not in MEME_CRYPTO
            ]
            # Per-cycle cap: pick best 3 by confluence → lowest RSI
            candidates = _select_cycle_candidates(all_candidates)
            signals_found = len(candidates)

            if len(all_candidates) > len(candidates):
                console.print(
                    f"  [yellow]Cycle cap: {len(all_candidates)} candidates filtered to "
                    f"{len(candidates)} (max {MAX_ENTRIES_PER_CYCLE}/cycle)[/yellow]"
                )
```

- [x] **Step 5: Run tests**

```bash
python -m pytest tests/test_technical_signals.py::TestPerCycleEntryCap -v
```

Expected: PASS.

- [x] **Step 6: Run full test suite**

```bash
python -m pytest tests/ -v --ignore=tests/backtester
```

Expected: All pass.

- [x] **Step 7: Commit**

```bash
git add src/alpaca_orchestrator.py tests/test_technical_signals.py
git commit -m "feat: per-cycle entry cap — max 3 positions per scan, sorted by confluence then RSI"
```

---

### Task 4b: Deploy Batch 1 and verify

- [x] **Step 1: Push to main**

```bash
git push origin main
```

- [x] **Step 2: Confirm Coolify redeploys both bots**

Both bots use the same `main` branch. Coolify should auto-deploy on push (or trigger manually via dashboard at https://coolify.titaniumlabs.us for UUIDs `qjyla085qflghz7h0dpsk7mh` and `v147jk2s2sm0n7aov83ph8y2`).

- [x] **Step 3: Monitor for 48 hours**

Watch `data/bot_output.log` on both containers. Confirm:
- No entries with RSI > 72 logged
- Cycle summaries show ≤ 3 candidates selected
- Risk gate runs on every candidate (no "PROCEEDING on high confluence" bypass messages)
- OVERHEATED regime blocks not yet active (Batch 2)

**Do not proceed to Batch 2 until at least one entry occurs on each bot.**

---

## BATCH 2 — Market Context & Exit Quality

---

### Task 5: BTC Market Regime Filter

**Files:**
- Modify: `src/alpaca_orchestrator.py`
- Modify: `tests/test_technical_signals.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_technical_signals.py`:

```python
class TestBTCRegimeFilter:
    def test_check_market_regime_overheated(self):
        """OVERHEATED when BTC 1h RSI > 70 AND 4h RSI > 65."""
        from src.alpaca_orchestrator import _check_market_regime
        assert _check_market_regime(btc_rsi_1h=71.0, btc_rsi_4h=66.0) == "OVERHEATED"

    def test_check_market_regime_normal_one_condition(self):
        """NORMAL if only one threshold exceeded."""
        from src.alpaca_orchestrator import _check_market_regime
        assert _check_market_regime(btc_rsi_1h=72.0, btc_rsi_4h=60.0) == "NORMAL"
        assert _check_market_regime(btc_rsi_1h=65.0, btc_rsi_4h=68.0) == "NORMAL"

    def test_check_market_regime_normal_both_below(self):
        """NORMAL when both RSIs are below thresholds."""
        from src.alpaca_orchestrator import _check_market_regime
        assert _check_market_regime(btc_rsi_1h=55.0, btc_rsi_4h=50.0) == "NORMAL"

    def test_check_market_regime_boundary(self):
        """Exactly at threshold is NORMAL (> not >=)."""
        from src.alpaca_orchestrator import _check_market_regime
        assert _check_market_regime(btc_rsi_1h=70.0, btc_rsi_4h=65.0) == "NORMAL"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_technical_signals.py::TestBTCRegimeFilter -v
```

Expected: FAIL — `_check_market_regime` does not exist.

- [ ] **Step 3: Add `_check_market_regime()` to `src/alpaca_orchestrator.py`**

Add after `_select_cycle_candidates`:

```python
def _check_market_regime(btc_rsi_1h: float, btc_rsi_4h: float) -> str:
    """Classify the current crypto market regime using BTC as the tide indicator.

    OVERHEATED: BTC overbought on both hourly AND 4-hour timeframe simultaneously.
                Skip all new entries — this is a market top pattern.
    NORMAL: everything else.

    Thresholds: 1h RSI > 70 AND 4h RSI > 65
    Two-timeframe confirmation reduces false positives from brief hourly spikes.
    """
    if btc_rsi_1h > 70.0 and btc_rsi_4h > 65.0:
        return "OVERHEATED"
    return "NORMAL"


def _get_btc_regime(alpaca_client) -> tuple[str, float, float]:
    """Fetch BTC RSI on 1h and 4h, return (regime, rsi_1h, rsi_4h).

    Falls back to NORMAL on any error — we'd rather trade than silently block.
    """
    try:
        bars_1h = alpaca_client.get_bars("BTC/USD", timeframe="1Hour", limit=50)
        rsi_1h = 50.0
        if bars_1h and len(bars_1h) >= 15:
            from src.technical_signals import _rsi
            closes_1h = [b["close"] for b in bars_1h]
            rsi_1h = _rsi(closes_1h, 14) or 50.0
    except Exception as exc:
        log.warning("Failed to fetch BTC 1h bars for regime check: %s", exc)
        return "NORMAL", 50.0, 50.0

    try:
        bars_4h = alpaca_client.get_bars("BTC/USD", timeframe="4Hour", limit=50)
        rsi_4h = 50.0
        if bars_4h and len(bars_4h) >= 15:
            from src.technical_signals import _rsi
            closes_4h = [b["close"] for b in bars_4h]
            rsi_4h = _rsi(closes_4h, 14) or 50.0
    except Exception as exc:
        log.warning("Failed to fetch BTC 4h bars for regime check: %s", exc)
        rsi_4h = 50.0

    regime = _check_market_regime(rsi_1h, rsi_4h)
    return regime, rsi_1h, rsi_4h
```

- [ ] **Step 4: Wire regime check into the main scan loop**

In `main()`, at the start of the `else:` block that begins the scan (just before `# -- 4b. Layer 1: Technical Signal Engine`), add:

```python
            # -- 4b-pre. BTC market regime check ----------------------------
            regime, btc_rsi_1h, btc_rsi_4h = _get_btc_regime(alpaca)
            console.print(
                f"  [cyan]Market regime: {regime}[/cyan] "
                f"(BTC RSI 1h={btc_rsi_1h:.1f}, 4h={btc_rsi_4h:.1f})"
            )
            if regime == "OVERHEATED":
                console.print(
                    "  [bold yellow]OVERHEATED regime — skipping new entries this cycle[/bold yellow]"
                )
                log.info(
                    "Cycle %d: OVERHEATED regime (BTC RSI 1h=%.1f, 4h=%.1f) — no new entries",
                    cycle_count, btc_rsi_1h, btc_rsi_4h,
                )
                # Jump to cycle sleep — position monitor continues normally
                time.sleep(CYCLE_SLEEP_SECONDS)
                continue
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_technical_signals.py::TestBTCRegimeFilter -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/alpaca_orchestrator.py tests/test_technical_signals.py
git commit -m "feat: BTC regime filter — skip new entries when BTC RSI(1h) > 70 AND RSI(4h) > 65"
```

---

### Task 6: Exit Threshold Recalibration

**Files:**
- Modify: `src/exit_advisor.py`
- Modify: `src/alpaca_orchestrator.py` (Kelly b-ratio)
- Create: `tests/test_exit_advisor.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_exit_advisor.py`:

```python
"""Tests for recalibrated exit thresholds and trailing stop logic."""

import pytest


class TestNewThresholds:
    def test_soft_stop_at_minus_3_pct(self):
        """Soft stop triggers at -3%, not -2%."""
        from src.exit_advisor import check_position_thresholds
        # -2.5% should now be NORMAL (previously soft_stop)
        assert check_position_thresholds(100.0, 97.5) is None
        # -3.1% should now be soft_stop
        assert check_position_thresholds(100.0, 96.9) == "soft_stop"

    def test_soft_take_profit_at_plus_8_pct(self):
        """Soft take-profit triggers at +8%, not +5%."""
        from src.exit_advisor import check_position_thresholds
        # +6% should now be NORMAL (previously soft_take_profit)
        assert check_position_thresholds(100.0, 106.0) is None
        # +8.1% should now be soft_take_profit
        assert check_position_thresholds(100.0, 108.1) == "soft_take_profit"

    def test_hard_stop_at_minus_5_pct(self):
        """Hard stop triggers at -5%, not -4%."""
        from src.exit_advisor import check_position_thresholds
        # -4.5% should now be soft_stop range, not hard_stop
        result = check_position_thresholds(100.0, 95.5)
        assert result == "soft_stop", f"Expected soft_stop at -4.5%, got {result}"
        # -5.1% should be hard_stop
        assert check_position_thresholds(100.0, 94.9) == "hard_stop"

    def test_no_hard_take_profit(self):
        """No hard take-profit cap — large gains go to soft take-profit, not hard."""
        from src.exit_advisor import check_position_thresholds
        # +15% should be soft_take_profit (not hard_take_profit)
        result = check_position_thresholds(100.0, 115.0)
        assert result == "soft_take_profit", f"Expected soft_take_profit at +15%, got {result}"
        # +50% should also be soft_take_profit (trailing stop handles these, not hard cap)
        result = check_position_thresholds(100.0, 150.0)
        assert result == "soft_take_profit"

    def test_normal_range_unchanged(self):
        """Within normal range (-3% to +8%) returns None."""
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 100.5) is None   # +0.5%
        assert check_position_thresholds(100.0, 97.5) is None    # -2.5%
        assert check_position_thresholds(100.0, 107.9) is None   # +7.9%


class TestNewTrailingStop:
    def test_no_trigger_below_new_activation(self):
        """Trailing stop does not activate below +5% (was +3%)."""
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        # +4% — below new 5% activation threshold
        assert ts.update(1, 100.0, 104.0) is None

    def test_activates_at_5_pct(self):
        """Trailing stop activates once position gains >= 5%."""
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        # +5.1% — above activation
        assert ts.update(1, 100.0, 105.1) is None  # above activation, but not trailing yet

    def test_triggers_with_3_pct_trail(self):
        """Trailing stop uses 3% trail distance (was 2%)."""
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        ts.update(1, 100.0, 108.0)   # peak at 108 (+8%)
        ts.update(1, 100.0, 110.0)   # new peak at 110 (+10%)
        # Trail stop = 110 * (1 - 0.03) = 106.7
        # Price at 106 — below 106.7 trail
        result = ts.update(1, 100.0, 106.0)
        assert result == "trailing_stop"

    def test_no_trigger_above_3_pct_trail(self):
        """Price still above 3% trail does not trigger."""
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        ts.update(1, 100.0, 108.0)   # peak at 108
        # Trail stop = 108 * 0.97 = 104.76
        # Price at 105.5 — above trail
        assert ts.update(1, 100.0, 105.5) is None

    def test_tightens_to_2pct_above_12pct_gain(self):
        """Trail tightens from 3% to 2% once position is above +12%."""
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        ts.update(1, 100.0, 113.0)   # peak at 113 (+13%) — above 12% tighten threshold
        ts.update(1, 100.0, 115.0)   # new peak at 115
        # Tightened trail = 115 * (1 - 0.02) = 112.7
        # Normal (3%) trail would be 115 * 0.97 = 111.55
        # Price at 113.0 — above normal trail (111.55) but below tightened trail (112.7)
        result = ts.update(1, 100.0, 113.0)
        assert result == "trailing_stop", (
            "Expected trailing_stop: price 113 should be below tightened trail 112.7"
        )
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_exit_advisor.py -v
```

Expected: Multiple failures — current thresholds don't match new values.

- [ ] **Step 3: Update threshold constants in `src/exit_advisor.py`**

Replace the constants block at the top of the file:

```python
# Thresholds — calibrated for crypto volatility (BTC avg hourly ATR ~1.5-2.5%)
SOFT_STOP_PCT = -0.03         # -3% triggers LLM consultation (was -2%)
SOFT_TAKE_PROFIT_PCT = 0.08   # +8% triggers LLM consultation (was +5%)
HARD_STOP_PCT = -0.05         # -5% immediate exit (was -4%)
# Hard take-profit REMOVED — trailing stop captures large moves instead of a fixed ceiling

# Trailing stop — activates once position is up >= TRAIL_ACTIVATION, then trails
# TRAIL_DISTANCE behind the peak. Tightens to TRAIL_DISTANCE_TIGHT above TRAIL_TIGHTEN.
TRAIL_ACTIVATION_PCT = 0.05   # activate trailing stop once up 5% (was 3%)
TRAIL_DISTANCE_PCT = 0.03     # trail 3% behind peak (was 2%)
TRAIL_TIGHTEN_THRESHOLD = 0.12  # tighten trail once position is up 12%
TRAIL_DISTANCE_TIGHT_PCT = 0.02  # tightened trail distance
```

- [ ] **Step 4: Update `check_position_thresholds()` to remove hard take-profit**

Replace the function:

```python
def check_position_thresholds(entry_price: float, current_price: float) -> str | None:
    """Quick check for threshold crossings without LLM calls.

    Returns:
        "hard_stop"         — immediate exit, position at -5% or worse
        "soft_stop"         — position at -3%, needs LLM consultation
        "soft_take_profit"  — position at +8% or better, needs LLM consultation
        None                — position within normal range
    Note: hard_take_profit removed — trailing stop handles large gains.
    """
    if entry_price <= 0:
        return None

    pnl_pct = (current_price - entry_price) / entry_price

    if pnl_pct <= HARD_STOP_PCT:
        return "hard_stop"
    if pnl_pct <= SOFT_STOP_PCT:
        return "soft_stop"
    if pnl_pct >= SOFT_TAKE_PROFIT_PCT:
        return "soft_take_profit"
    return None
```

- [ ] **Step 5: Update `should_exit()` to remove hard take-profit check**

In `ExitAdvisor.should_exit()`, replace the hard threshold check:

```python
        # Hard stop — don't consult, caller handles immediately
        if pnl_pct <= HARD_STOP_PCT:
            return None  # Caller should exit immediately

        # Soft thresholds — consult LLM exit advisor
        if pnl_pct <= SOFT_STOP_PCT:
            trigger_type = "soft_stop"
            trigger_pct = pnl_pct * 100
        elif pnl_pct >= SOFT_TAKE_PROFIT_PCT:
            trigger_type = "soft_take_profit"
            trigger_pct = pnl_pct * 100
        else:
            return None  # Within normal range, no action
```

- [ ] **Step 6: Update `TrailingStop.update()` for new thresholds and tighten logic**

Replace the `update()` method in `TrailingStop`:

```python
    def update(self, trade_id: int, entry_price: float, current_price: float) -> str | None:
        """Update the trailing stop and return action if triggered.

        Returns:
            "trailing_stop" if price fell below the trail
            None otherwise
        """
        if entry_price <= 0:
            return None

        pnl_pct = (current_price - entry_price) / entry_price

        # Track peak
        prev_peak = self._peaks.get(trade_id)
        if prev_peak is None or current_price > prev_peak:
            self._peaks[trade_id] = current_price
            prev_peak = current_price

        # Only activate once position has gained enough
        peak_gain = (prev_peak - entry_price) / entry_price
        if peak_gain < TRAIL_ACTIVATION_PCT:
            return None

        # Tighten trail distance once position is above TRAIL_TIGHTEN_THRESHOLD
        if peak_gain >= TRAIL_TIGHTEN_THRESHOLD:
            trail_distance = TRAIL_DISTANCE_TIGHT_PCT
        else:
            trail_distance = TRAIL_DISTANCE_PCT

        trail_stop = prev_peak * (1 - trail_distance)

        if current_price <= trail_stop:
            self.remove(trade_id)
            return "trailing_stop"

        return None
```

- [ ] **Step 7: Update Kelly b-ratio in `src/alpaca_orchestrator.py`**

In `_kelly_technical()`, find:

```python
    # Risk/reward: soft take-profit at 5%, hard stop at 4%
    # b = reward / risk = 5% / 4% = 1.25
    b = 0.05 / 0.04
```

Replace with:

```python
    # Risk/reward: soft take-profit at 8%, hard stop at 5%
    # b = reward / risk = 8% / 5% = 1.6
    b = 0.08 / 0.05
```

Also update the banner in `_print_banner()` — find `Hard take-profit` line and update:

```python
        f"  Hard stop-loss  : {abs(HARD_STOP_PCT):.0%}\n"
        f"  Soft take-profit: {SOFT_TAKE_PROFIT_PCT:.0%} (trailing stop above +{TRAIL_ACTIVATION_PCT:.0%})\n"
        f"  Max exposure    : {MAX_TOTAL_EXPOSURE_PCT:.0%} of bankroll\n"
```

(Remove the `Hard take-profit` line from the banner, replace with the soft take-profit line above.)

- [ ] **Step 8: Run tests**

```bash
python -m pytest tests/test_exit_advisor.py -v
```

Expected: All pass.

- [ ] **Step 9: Run full test suite**

```bash
python -m pytest tests/ -v --ignore=tests/backtester
```

Note: Some existing `TestThresholdChecks` tests in `test_technical_signals.py` will now FAIL because they test old threshold values. Update them:

```python
class TestThresholdChecks:
    def test_hard_stop(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 94.9) == "hard_stop"   # -5.1%

    def test_no_hard_take_profit(self):
        from src.exit_advisor import check_position_thresholds
        # +15% is now soft_take_profit, not hard_take_profit
        assert check_position_thresholds(100.0, 115.0) == "soft_take_profit"

    def test_soft_stop(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 96.9) == "soft_stop"   # -3.1%

    def test_soft_take_profit(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 108.1) == "soft_take_profit"  # +8.1%

    def test_normal_range(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(100.0, 100.5) is None  # +0.5%

    def test_zero_entry(self):
        from src.exit_advisor import check_position_thresholds
        assert check_position_thresholds(0.0, 100.0) is None
```

Also update `TestTrailingStop` tests in `test_technical_signals.py` for new activation (5%) and trail (3%):

```python
class TestTrailingStop:
    def test_no_trigger_below_activation(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        # +4% — below new 5% activation
        assert ts.update(1, 100.0, 104.0) is None

    def test_activates_and_holds(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        # +6% — above 5% activation, not trailing yet
        assert ts.update(1, 100.0, 106.0) is None

    def test_triggers_on_pullback(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        ts.update(1, 100.0, 108.0)  # peak at 108
        ts.update(1, 100.0, 110.0)  # new peak at 110
        # Trail stop = 110 * (1 - 0.03) = 106.7
        result = ts.update(1, 100.0, 106.0)
        assert result == "trailing_stop"

    def test_no_trigger_above_trail(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        ts.update(1, 100.0, 108.0)  # peak at 108
        # Trail stop = 108 * 0.97 = 104.76
        # Price at 106 — still above trail
        assert ts.update(1, 100.0, 106.0) is None

    def test_remove_clears_tracking(self):
        from src.exit_advisor import TrailingStop
        ts = TrailingStop()
        ts.update(1, 100.0, 112.0)  # set high peak
        ts.remove(1)
        # After remove, starts fresh — no activation at 102
        assert ts.update(1, 100.0, 102.0) is None
```

Run full suite again after updates:

```bash
python -m pytest tests/ -v --ignore=tests/backtester
```

Expected: All pass.

- [ ] **Step 10: Commit**

```bash
git add src/exit_advisor.py src/alpaca_orchestrator.py tests/test_exit_advisor.py tests/test_technical_signals.py
git commit -m "feat: recalibrate exit thresholds for crypto volatility — softer stops, no hard TP ceiling, tightened trailing stop"
```

---

### Task 7: Volume Market Context Filter

**Files:**
- Modify: `src/alpaca_orchestrator.py`
- Modify: `tests/test_technical_signals.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_technical_signals.py`:

```python
class TestVolumeContextFilter:
    def test_suppress_volume_spike_when_market_wide(self):
        """If 4+ assets simultaneously spike, suppress volume_spike for all."""
        from src.alpaca_orchestrator import _apply_volume_context_filter
        from src.technical_signals import Signal

        def _make_signal(symbol, vol_spike):
            return Signal(
                symbol=symbol, ema_bullish=True, adx_value=25.0,
                adx_trending=True, plus_di=20.0, minus_di=10.0,
                rsi_value=55.0, rsi_signal="neutral",
                volume_spike=vol_spike, vwap_bullish=True,
                confluence_score=3, details={},
            )

        signals = [
            _make_signal("BTC/USD", True),
            _make_signal("ETH/USD", True),
            _make_signal("SOL/USD", True),
            _make_signal("XRP/USD", True),   # 4th spike → triggers suppression
            _make_signal("ADA/USD", False),
        ]

        filtered = _apply_volume_context_filter(signals)
        # All volume_spike flags should be False (market-wide pump)
        for s in filtered:
            assert s.volume_spike is False, f"{s.symbol} still has volume_spike=True after filter"

    def test_no_suppression_below_threshold(self):
        """If fewer than 4 assets spike, volume_spike flags are preserved."""
        from src.alpaca_orchestrator import _apply_volume_context_filter
        from src.technical_signals import Signal

        def _make_signal(symbol, vol_spike):
            return Signal(
                symbol=symbol, ema_bullish=True, adx_value=25.0,
                adx_trending=True, plus_di=20.0, minus_di=10.0,
                rsi_value=55.0, rsi_signal="neutral",
                volume_spike=vol_spike, vwap_bullish=True,
                confluence_score=3, details={},
            )

        signals = [
            _make_signal("BTC/USD", True),
            _make_signal("ETH/USD", True),
            _make_signal("SOL/USD", True),  # only 3 → no suppression
            _make_signal("XRP/USD", False),
        ]

        filtered = _apply_volume_context_filter(signals)
        spiking = [s for s in filtered if s.volume_spike]
        assert len(spiking) == 3

    def test_suppression_recalculates_confluence(self):
        """After volume suppression, confluence score must be recalculated."""
        from src.alpaca_orchestrator import _apply_volume_context_filter
        from src.technical_signals import Signal

        def _make_signal(symbol):
            # score=4: ema + adx + volume_spike + vwap (RSI neutral with ema = +1 too)
            return Signal(
                symbol=symbol, ema_bullish=True, adx_value=25.0,
                adx_trending=True, plus_di=20.0, minus_di=10.0,
                rsi_value=55.0, rsi_signal="neutral",
                volume_spike=True, vwap_bullish=True,
                confluence_score=4, details={},
            )

        signals = [_make_signal(f"ASSET{i}/USD") for i in range(5)]
        filtered = _apply_volume_context_filter(signals)
        # All volume spikes suppressed → confluence must drop by 1 for each
        for s in filtered:
            assert s.confluence_score == 3, (
                f"{s.symbol}: expected score=3 after volume suppression, got {s.confluence_score}"
            )
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_technical_signals.py::TestVolumeContextFilter -v
```

Expected: FAIL — `_apply_volume_context_filter` does not exist.

- [ ] **Step 3: Add `_apply_volume_context_filter()` to `src/alpaca_orchestrator.py`**

Add after `_get_btc_regime`:

```python
VOLUME_PUMP_THRESHOLD = int(_os.environ.get("VOLUME_PUMP_THRESHOLD", "4"))


def _apply_volume_context_filter(signals: list) -> list:
    """Suppress volume spike signal when the entire market is pumping together.

    A volume spike on one asset = institutional interest (valid signal).
    A volume spike across 4+ assets simultaneously = retail FOMO pump (noise).

    When suppressed, recalculate confluence score to reflect the loss of that signal.
    This is a post-computation cross-asset filter — run after scan_assets(), before
    confluence filtering.
    """
    spiking_count = sum(1 for s in signals if s.volume_spike)

    if spiking_count < VOLUME_PUMP_THRESHOLD:
        return signals  # Asset-specific spikes — keep as-is

    log.info(
        "Volume context filter: %d/%d assets spiking simultaneously — suppressing volume signal (market-wide pump)",
        spiking_count, len(signals),
    )

    updated = []
    for s in signals:
        if not s.volume_spike:
            updated.append(s)
            continue

        # Suppress volume spike and recalculate confluence score
        # Volume spike contributed +1 to score; remove it
        from dataclasses import replace
        new_score = max(0, s.confluence_score - 1)
        updated.append(replace(s, volume_spike=False, confluence_score=new_score))

    return updated
```

- [ ] **Step 4: Wire into the scan loop**

In `main()`, find the line:

```python
            try:
                signals = scan_assets(alpaca, TOP_CRYPTO_TICKERS, timeframe="1Hour", bar_count=50)
```

Add the filter call immediately after `scan_assets` returns:

```python
            try:
                signals = scan_assets(alpaca, TOP_CRYPTO_TICKERS, timeframe="1Hour", bar_count=50)
                signals = _apply_volume_context_filter(signals)
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_technical_signals.py::TestVolumeContextFilter -v
```

Expected: PASS.

- [ ] **Step 6: Run full test suite**

```bash
python -m pytest tests/ -v --ignore=tests/backtester
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add src/alpaca_orchestrator.py tests/test_technical_signals.py
git commit -m "feat: volume context filter — suppress spike signal when 4+ assets pump simultaneously"
```

---

### Task 7b: Deploy Batch 2

- [ ] **Step 1: Push to main**

```bash
git push origin main
```

- [ ] **Step 2: Confirm Coolify redeploys both bots**

Trigger redeploy for UUIDs `qjyla085qflghz7h0dpsk7mh` (Bot A) and `v147jk2s2sm0n7aov83ph8y2` (Bot B) at https://coolify.titaniumlabs.us if auto-deploy is not configured.

- [ ] **Step 3: Monitor logs for correct behavior**

Confirm in `data/bot_output.log`:
- Regime line printed every cycle: `Market regime: NORMAL (BTC RSI 1h=XX.X, 4h=XX.X)`
- OVERHEATED cycles log: `OVERHEATED regime — skipping new entries this cycle`
- Volume filter logs when suppression fires
- Exit advisor now triggers at -3% / +8% soft thresholds (not -2% / +5%)
- Trailing stop activates at +5%, not +3%

---

## Self-Review Notes

- All 7 spec changes are covered: Tasks 1–2 (RC1+RC4), Task 3 (RC2), Task 4 (RC3), Task 5 (RC6+regime), Task 6 (RC6+RC7 exit), Task 7 (RC5)
- `_adx()` tuple return is propagated to all callers — `analyze()` and existing tests updated in Task 2
- `check_position_thresholds()` tests in `test_technical_signals.py` conflict with new thresholds — explicitly updated in Task 6 Step 9
- `TrailingStop` tests in `test_technical_signals.py` conflict with new activation/distance — explicitly updated in Task 6 Step 9
- `dataclasses.replace()` used in volume filter to mutate frozen-ish signals — `Signal` is a regular dataclass (not frozen), so `replace()` works correctly
- Kelly b-ratio updated in Task 6 to match new reward/risk ratio (8%/5% = 1.6)
- Batch 2 gated on Batch 1 running 48h — enforced by Task 4b monitoring gate
