# Phase 10: Verification + Backtest - Research

**Researched:** 2026-06-15
**Domain:** Python test coverage audit + deterministic signal-frequency backtest harness (pytest, alpaca-py, pure-function signal engine)
**Confidence:** HIGH (all findings verified by reading the actual repo source this session)

## Summary

Phase 10 is a validation-only milestone with two deliverables, both reusing existing code.
VERIFY-01 is a coverage AUDIT plus filling one known gap: the Phase-7 verifier flagged that the
learning veto/scale path tests (`test_veto_skips_candidate`, `test_adjustment_scales_size_in_path`,
`test_shadow_mode_no_effect`) assert against a `_advice_consume` **mirror helper defined inside
`tests/test_learning_wiring.py`** (lines 82-97), NOT the production candidate loop. The fix is a
real-loop integration test driving the actual entry path with a seeded `FakeTradeMemory`.

The cleanest seam for that test is **`BotThread._run_cycle(...)`** (`src/bot_thread.py:307`). It is an
instance method that takes every external dependency as an injected argument — `alpaca`, `logger`,
`risk_gate`, `memory` — and contains the real veto/scale wiring (long path lines 522-577, short path
722-777). The orchestrator's equivalent loop lives inline inside `main()` (`alpaca_orchestrator.py:570`),
is not parameterized, and is therefore NOT a viable unit seam — drive the bot_thread path and assert
parity via the already-green `test_orchestrator_bot_thread_parity` (both import the same `_kelly_technical`).

VERIFY-02 is a signal-FREQUENCY backtest (not P&L). A **P&L** backtester already exists at
`src/backtester/` (data_loader/engine/portfolio/metrics/cli). Reuse its `data_loader.py` for
fixture/cache/live bar loading, but the frequency harness is a NEW thin script that feeds bars through
`scan_assets(profile=DAYTRADE, fetch_4h=False)` via a stub client and counts candidates per window.

**Primary recommendation:** (1) Add `tests/test_learning_realloop.py` driving `BotThread._run_cycle`
with a stub Alpaca + seeded `FakeTradeMemory` to prove veto (should_trade=False) and scale
(adjustment<1) in enforce AND shadow modes against real production code. (2) Add
`scripts/backtest_signal_frequency.py` (committed 5Min fixture + optional `--live`) that replays bars
through `scan_assets(profile=DAYTRADE, fetch_4h=False)` and a thin `tests/test_signal_frequency.py`
asserting a sane candidate-count range so it doubles as a regression guard.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Coverage audit (map tests → surfaces) | Test suite (`tests/`) | — | Pure documentation + gap-fill, no runtime |
| Real-loop learning integration test | Test suite driving `src/bot_thread.py` | `src/trade_memory` (FakeTradeMemory stub) | `_run_cycle` is the injectable entry seam |
| Signal-frequency backtest harness | `scripts/` (CLI) + `tests/` (regression assert) | `src/technical_signals.scan_assets`, `src/backtester/data_loader` | Reuses pure signal engine on replayed bars |
| Historical bar loading | `src/backtester/data_loader.py` (existing) | Alpaca crypto data API | Already implements fixture→cache→live priority |

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Audit existing tests and map them to the VERIFY-01 surfaces; document the mapping. Only ADD what's missing — do not duplicate existing green tests.
- **D-02:** Add a real-loop learning integration test: construct the entry path (or the smallest real slice of it) with a fake/seeded TradeMemory returning should_trade=False / adjustment<1, and assert the ACTUAL code path vetoes/scales (not the mirror helper). Cover both enforce and shadow modes.
- **D-03:** New `scripts/backtest_signal_frequency.py` (or tests/ harness) that fetches historical 5-min bars for the daytrade universe (or accept a fixture/CSV for offline determinism), runs `scan_assets(profile=DAYTRADE, fetch_4h=False)` across a rolling window, and reports candidate frequency per symbol + totals.
- **D-04:** Must run deterministically in CI/test without live API where possible — prefer a fixture-driven test plus an optional live-fetch mode.
- **D-05:** Output a short human-readable report and assert a sane frequency range so it doubles as a regression guard (e.g. daytrade produces > 0 and not absurdly many candidates on the fixture).

### Claude's Discretion
- Backtest harness location (scripts/ vs tests/) and fixture vs live-fetch default — prefer deterministic fixture for the committed test + documented live mode.

### Deferred Ideas (OUT OF SCOPE)
- Full P&L backtest with fills/slippage — future.
- Live Bot D paper run — after the Phase 9 infra HALT is resolved.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| VERIFY-01 | Unit tests cover milestone critical surfaces (profile presets/SWING parity, ATR exit math, fee gate, learning veto/scale wiring, session VWAP); audit + fill the mirror-helper gap | Coverage Map below maps each surface to its green test file; gap is the path-level learning tests using `_advice_consume` mirror (test_learning_wiring.py:82-97). Fill via `tests/test_learning_realloop.py` driving `BotThread._run_cycle` (bot_thread.py:307). |
| VERIFY-02 | Backtest harness over historical 5-min bars validating daytrade signal FREQUENCY before live paper run; reuse `scan_assets(profile=DAYTRADE, fetch_4h=False)`; simple frequency/coverage report | `scan_assets` (technical_signals.py:469) is profile-aware; `fetch_4h=False` avoids HTF calls. Reuse `src/backtester/data_loader.py` for fixture/cache/live loading. Stub client replays bars. DAYTRADE.bar_count=100 (strategy_profile.py:78). |
</phase_requirements>

## Coverage Map

Maps each VERIFY-01 critical surface to its existing test(s) and verdict. Verified by reading the
test files and source this session.

| Surface (VERIFY-01) | Covered by | Real code or mirror? | Status |
|---------------------|-----------|----------------------|--------|
| Profile presets / SWING parity | `tests/test_strategy_profile.py`, `test_learning_wiring.py::test_orchestrator_bot_thread_parity` | Real (`_kelly_technical` identity + profile constants) | GREEN — keep |
| ATR exit math | `tests/test_atr_exits.py`, `conftest.py::test_make_bars_for_atr_matches_atr` | Real (`_atr` called directly; deterministic generator) | GREEN — keep |
| Fee gate | `tests/test_fee_gate.py` | Real (`clears_fee_hurdle`) | GREEN — keep |
| Session VWAP | `tests/test_technical_signals.py` (session_anchor path in `_vwap_bullish`) | Real | GREEN — keep (verify session_anchor case present; ADD if missing) |
| Learning sizing math (LEARN-02/03, hard cap, floor/ceiling, no-op) | `test_learning_wiring.py` math tests (lines 19-72, 151-194) | Real (`_kelly_technical` direct) | GREEN — keep |
| Learning veto wiring (LEARN-01) — enforce | `test_learning_wiring.py::test_veto_skips_candidate` | **MIRROR** (`_advice_consume`, lines 82-105) | **GAP — fill** |
| Learning scale wiring (LEARN-02) — enforce | `test_learning_wiring.py::test_adjustment_scales_size_in_path` | **MIRROR** (lines 109-119) | **GAP — fill** |
| Learning shadow-mode wiring (LEARN-06) | `test_learning_wiring.py::test_shadow_mode_no_effect` | **MIRROR** (lines 139-148) | **GAP — fill** |
| signal_type alignment (get_advice vs record) | `test_learning_wiring.py::test_signal_type_alignment` | Mirror-ish (calls FakeTradeMemory directly, not via loop) | Acceptable but ADD real-loop assertion of `record_trade_context` |
| Shadow gate count logic | `tests/test_shadow_gate.py`, `test_learning_wiring.py::test_*_imports_shadow_gate` | Real (`should_enforce_learning`) | GREEN — keep |
| Learning dimensions | `tests/test_learning_dimensions.py` | Real | GREEN — keep |

**The exact gap (confirms Phase-7 verifier finding):** Three path-level tests exercise
`_advice_consume(memory, ...)` — a contract re-implementation living in the test file
(`test_learning_wiring.py:82-97`) — instead of `BotThread._run_cycle`. They prove the contract LOGIC
is sound but would NOT catch a regression where the production loop drops the `if not advice["should_trade"]`
veto or the `adj = advice.get("confidence_adjustment")` scale. Fill: one integration test that drives the
real `_run_cycle`.

## Real-Loop Integration Test Design (D-02)

### The seam: `BotThread._run_cycle` (src/bot_thread.py:307)

```python
def _run_cycle(self, cfg, alpaca, logger, risk_gate, starting_bankroll,
               cycle_count, memory=None, learning_loop=None, universe=None) -> None:
```

Every dependency is injected — no globals to patch beyond a couple of module-level helpers. The real
veto/scale wiring is inside this method:
- **LONG advisory:** lines 522-577 — `memory.get_advice(...)` → `if not advice["should_trade"]: if enforce: continue` (veto) → `elif enforce: adj = advice.get("confidence_adjustment", 1.0)` (scale) → `_kelly_technical(..., confidence_adjustment=adj, ...)`.
- **SHORT advisory:** lines 722-777 — same structure.
- **enforce flag:** `enforce = should_enforce_learning(memory, bot_id)` (line 443), computed once per cycle.
- **Order placement:** `alpaca.place_market_order(...)` (line 592); `memory.record_trade_context(...)` (line 621).

### What to stub (no live Alpaca, no DB)

Build a stub Alpaca object (extend the existing `mock_alpaca` conftest fixture, or a small fake):
- `get_account()` → `{"buying_power": 100000.0, "equity": 100000.0}`
- `get_bars(symbol, timeframe, limit)` → return committed 5Min/1Hour fixture bars engineered to yield a confluence_score ≥ `cfg.min_confluence` (so a LONG candidate survives to the sizing stage). Reuse `tests/backtester/fixtures` or a small inline OHLCV generator.
- `get_latest_price(symbol)` → fixed float matching last bar close.
- `place_market_order(...)` → record the call; return `{"order_id": "X", "status": "accepted"}`.

Stub the `logger` (TradeLogger): `get_open_alpaca_positions()` → `[]`, `log_alpaca_trade(...)` →
returns a fake `trade_id`. Stub `risk_gate` with `cfg.skip_risk_gate = True` (line 469) to bypass the
LLM panel entirely — this is the simplest path to the sizing/order stage. Patch `_db` module functions
(`get_recent_loss_symbols` → `set()`, `persist_scan_signals` → no-op) via monkeypatch.

### Assertions (cover the 4 cases)

| Case | Memory seed | enforce | Expected on real loop |
|------|-------------|---------|------------------------|
| Veto enforce | `FakeTradeMemory(advice={should_trade:False,...}, closed_count=999)` + `LEARNING_ENFORCE` unset | True | `place_market_order` NOT called (candidate vetoed via `continue`) |
| Veto shadow | same advice, `monkeypatch.setenv("LEARNING_ENFORCE","0")` | False | `place_market_order` IS called (shadow logs but does not skip) |
| Scale enforce | `advice={should_trade:True, confidence_adjustment:0.5}` + closed_count=999 | True | order placed with qty corresponding to half-scaled `adjusted_pct` (capture qty arg, compare to `_kelly_technical(...,confidence_adjustment=1.0)` baseline × 0.5 pre-cap) |
| Scale shadow | same advice, ENFORCE=0 | False | order placed at UNSCALED size (adj stays 1.0) |

Force enforce=True deterministically by seeding `FakeTradeMemory(closed_count=999)` (the shadow gate
`should_enforce_learning` enforces once enough closed trades exist) and leaving `LEARNING_ENFORCE`
unset; force shadow via `monkeypatch.setenv("LEARNING_ENFORCE","0")` (proven by
`test_explicit_zero_forces_shadow_both_runtimes`). Capture the `place_market_order` `qty` kwarg to
assert scaling; assert call-count 0 vs 1 to assert veto.

**Parity note:** The orchestrator's loop is inline in `main()` (not unit-drivable). Rely on the
existing green `test_orchestrator_bot_thread_parity` (`_kelly_technical` is the same object in both)
plus code-reading parity (Phase-7 verified all 4 call sites). Do NOT attempt to drive
`alpaca_orchestrator.main()` in a unit test — out of proportion to value.

## Backtest Harness Design (VERIFY-02, D-03/04/05)

### How `get_bars` fetches 5Min bars (src/alpaca_client.py:217)

```python
def get_bars(self, symbol, timeframe="1Day", limit=30) -> list[dict]:
```
- `timeframe="5Min"` → `TimeFrame(5, TimeFrameUnit.Minute)` (tf_map line 238).
- Computes `start = now - (bar_hours * limit * 2 + 1)` hours; for 5Min/limit=100 that's ~17h lookback. `limit` max 10000.
- Crypto path uses `CryptoBarsRequest(symbol, timeframe, start, limit)` via `CryptoHistoricalDataClient.get_crypto_bars`.
- Returns `list[dict]` with keys `timestamp` (ISO str), `open/high/low/close/volume/vwap` (floats). vwap defaults to 0 if absent.

**Critical: `scan_assets` IGNORES its own `timeframe`/`bar_count` args** (technical_signals.py:502):
```python
bars = alpaca_client.get_bars(symbol, timeframe=profile.timeframe, limit=profile.bar_count)
```
It sources timeframe/limit from `profile`. So for DAYTRADE it requests `timeframe="5Min", limit=100`.
The harness's stub client must respond to `get_bars(symbol, timeframe="5Min", limit=100)`.

### Approach: committed fixture replay + optional live-fetch (D-04 deterministic default)

Reuse `src/backtester/data_loader.py` — it already implements fixture→cache→live priority and
`normalise_bar`. The frequency harness adds a **stub client** wrapping a pre-loaded bar list:

```python
class _ReplayClient:
    """Feeds a fixed bar list to scan_assets; ignores get_bars time args (scan_assets passes profile.*)."""
    def __init__(self, bars_by_symbol, window_end_idx):
        self._bars = bars_by_symbol; self._end = window_end_idx
    def get_bars(self, symbol, timeframe="5Min", limit=100):
        return self._bars[symbol][self._end - limit:self._end]  # rolling window slice
```

Harness loop: for each rolling window (slide the end index across the fixture), build a `_ReplayClient`,
call `scan_assets(client, symbols, fetch_4h=False, profile=DAYTRADE)`, count returned signals where
`confluence_score >= DAYTRADE.min_confluence` (4) and `short_score >= DAYTRADE.min_short_confluence` (3).
Aggregate candidates per symbol + totals.

### Fixture requirements (NEW — current fixture is insufficient)

The existing `tests/backtester/fixtures/BTC_USD.json` is **60 × 1Hour bars** — wrong timeframe AND
fewer than DAYTRADE.bar_count=100. The harness needs a NEW committed 5Min fixture:
- Per symbol: ≥ `100 + windows` 5Min bars (e.g. 200-300 bars to allow a rolling window). `_adx` needs `period*2+1 = 29` bars minimum; `analyze` early-returns if `len(bars) < 30`.
- Keys: `timestamp` (5-min spaced ISO), `open/high/low/close/volume/vwap`.
- Generate once from a live fetch (`--live` mode below) and commit, or synthesize deterministic OHLCV that produces a known candidate count. Prefer a real captured slice for realism; store under `tests/fixtures/daytrade_5min/` or extend `tests/backtester/fixtures/`.
- Symbols: subset of DAYTRADE universe (BTC/USD, ETH/USD, SOL/USD enough for the regression test; full 8 in live mode).

### Location (Claude's discretion → recommendation)

- **`scripts/backtest_signal_frequency.py`** — CLI: `--fixture-dir`, `--live` (uses `data_loader.load_bars_from_alpaca`), `--window`, `--symbols`. Prints human-readable report (D-05). Default = fixture.
- **`tests/test_signal_frequency.py`** — imports the harness's pure function, runs it on the committed fixture, asserts the sane range (regression guard). This keeps CI deterministic and offline (D-04).

### Sane frequency range assertion (D-05)

On the committed fixture, assert: `total_candidates > 0` (daytrade DOES produce signals — guards a
regression that silences scanning) AND `total_candidates <= len(windows) * len(symbols)` and not
absurdly high (e.g. `<= 0.8 * windows * symbols` — guards a regression where every bar becomes a
candidate, e.g. a broken min_confluence gate). Pin the EXACT count on the committed fixture
(`assert total == N`) once the fixture is finalized, so any signal-engine math change that shifts
frequency trips the test — that is the strongest regression guard. Document N in a comment with the
fixture hash/date.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Historical bar loading (fixture/cache/live) | New loader | `src/backtester/data_loader.py` (`load_bars`, `load_bars_from_alpaca`, `normalise_bar`) | Already handles slash-symbol filenames, vwap defaults, sorting, Alpaca crypto fetch |
| Signal computation on bars | Re-derive indicators | `scan_assets(..., profile=DAYTRADE, fetch_4h=False)` | The whole point of VERIFY-02 is exercising the REAL engine |
| In-memory TradeMemory stub | New fake | `tests/conftest.py::FakeTradeMemory` | Already supports `advice`, `thresholds`, `closed_count`, records calls |
| Stub Alpaca client | New mock from scratch | extend `conftest.py::mock_alpaca` fixture | Already stubs get_positions/get_latest_price/get_bars/close_position |

## Common Pitfalls

### Pitfall 1: scan_assets ignores passed timeframe/bar_count
**What goes wrong:** Test stubs `get_bars` for `timeframe="1Hour"` but DAYTRADE makes it call with `"5Min", limit=100`.
**How to avoid:** Stub `get_bars` to ignore time args (return the fixture slice regardless), OR honor `profile.timeframe`/`profile.bar_count`. Verified at technical_signals.py:502.

### Pitfall 2: Fixture too short for indicators
**What goes wrong:** `analyze` returns None if `< 30` bars; `_adx` returns None if `< 29` bars; DAYTRADE.bar_count requests 100. A 60-bar fixture under-feeds.
**How to avoid:** Commit ≥100 bars per symbol (more to allow rolling windows). The current 1Hour 60-bar fixture is NOT reusable.

### Pitfall 3: Non-determinism from `datetime.now()` in get_bars
**What goes wrong:** Real `get_bars` computes `start` from `now()`. Live mode is non-deterministic by nature.
**How to avoid:** Default to fixture replay (no network, no clock). Gate live fetch behind explicit `--live`; never run live in CI test.

### Pitfall 4: Orchestrator entry loop is not a unit seam
**What goes wrong:** Trying to drive `alpaca_orchestrator.main()` pulls in argparse, infinite loop, account polling.
**How to avoid:** Drive `BotThread._run_cycle` (parameterized) instead; rely on existing parity test for orchestrator equivalence.

### Pitfall 5: enforce flag not deterministic
**What goes wrong:** `should_enforce_learning` is count-based; a test expecting enforce=True may get shadow if closed_count low.
**How to avoid:** Seed `FakeTradeMemory(closed_count=999)` for enforce; `monkeypatch.setenv("LEARNING_ENFORCE","0")` for shadow (proven by existing test_explicit_zero test).

### Pitfall 6: `_db` module side effects in `_run_cycle`
**What goes wrong:** `_run_cycle` calls `_db.get_recent_loss_symbols` and `_db.persist_scan_signals` (lines 363, 395) — hit Postgres.
**How to avoid:** monkeypatch both on `src.bot_thread._db` to no-op/empty before driving the cycle.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (no pytest.ini/setup.cfg config detected — uses default discovery on `tests/`) |
| Config file | none — discovery via `tests/` dir + conftest.py |
| Quick run command | `python -m pytest tests/test_learning_realloop.py tests/test_signal_frequency.py -x -q` |
| Full suite command | `python -m pytest tests/ -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| VERIFY-01 | Real loop vetoes when should_trade=False (enforce) | integration | `pytest tests/test_learning_realloop.py::test_realloop_veto_enforce -x` | ❌ Wave 0 |
| VERIFY-01 | Real loop does NOT veto in shadow mode | integration | `pytest tests/test_learning_realloop.py::test_realloop_veto_shadow -x` | ❌ Wave 0 |
| VERIFY-01 | Real loop scales qty by adjustment (enforce) | integration | `pytest tests/test_learning_realloop.py::test_realloop_scale_enforce -x` | ❌ Wave 0 |
| VERIFY-01 | Real loop ignores adjustment in shadow | integration | `pytest tests/test_learning_realloop.py::test_realloop_scale_shadow -x` | ❌ Wave 0 |
| VERIFY-01 | Existing surface coverage (parity/ATR/fee/VWAP/math) | unit | `pytest tests/ -q` | ✅ (audit only; ADD session-VWAP case if missing) |
| VERIFY-02 | DAYTRADE produces a sane candidate count on fixture | integration | `pytest tests/test_signal_frequency.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_learning_realloop.py tests/test_signal_frequency.py -q`
- **Per wave merge:** `python -m pytest tests/ -q`
- **Phase gate:** Full suite green (≥272 expected, per CONTEXT) before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_learning_realloop.py` — covers VERIFY-01 real-loop veto/scale (enforce + shadow), drives `BotThread._run_cycle`.
- [ ] `tests/test_signal_frequency.py` — covers VERIFY-02 regression assert on committed fixture.
- [ ] `scripts/backtest_signal_frequency.py` — CLI harness (fixture default + `--live`).
- [ ] `tests/fixtures/daytrade_5min/*.json` (or extend `tests/backtester/fixtures/`) — ≥100 × 5Min bars per symbol. Current 1Hour 60-bar fixture is insufficient.
- [ ] Audit: confirm a session-VWAP (`session_anchor=True`) assertion exists in `tests/test_technical_signals.py`; ADD if missing.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pytest | all tests | ✓ (272 tests run per Phase-7) | — | — |
| alpaca-py | live backtest fetch only | ✓ (0.43.2 per CLAUDE.md) | 0.43.2 | Fixture replay (default, no network) |
| ALPACA_API_KEY/SECRET | `--live` mode only | env-dependent | — | Fixture replay (CI default) |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** live Alpaca creds — fixture replay is the deterministic default per D-04.

## Package Legitimacy Audit

> No new external packages required. Both deliverables reuse in-repo modules (`pytest`, `alpaca-py`
> already present). No install step → audit N/A.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Full suite is ~272 tests | Validation Architecture | Low — count is informational; CONTEXT states 272+ |
| A2 | Session-VWAP assertion may or may not exist in test_technical_signals.py (not opened this session) | Coverage Map | Low — audit task confirms; ADD if missing |
| A3 | A real captured 5Min fixture will yield a stable nonzero candidate count | Backtest Harness | Medium — pin exact N only after fixture finalized; until then assert range not equality |

## Sources

### Primary (HIGH confidence)
- `src/bot_thread.py:307-460,500-815` — `_run_cycle` seam, veto/scale wiring, enforce flag, `_db` calls.
- `src/technical_signals.py:256-527` — `analyze`/`scan_assets`, profile sourcing of timeframe/bar_count, session VWAP.
- `src/strategy_profile.py:49-95` — SWING/DAYTRADE constants (5Min, bar_count=100, min_confluence=4).
- `src/alpaca_client.py:217-292` — `get_bars` params, 5Min mapping, return dict shape.
- `src/backtester/data_loader.py` — existing fixture/cache/live loader.
- `tests/conftest.py` — `FakeTradeMemory`, `mock_alpaca`, ATR generators.
- `tests/test_learning_wiring.py:82-148` — the `_advice_consume` mirror helper (the gap).
- `.planning/phases/07-...-07-VERIFICATION.md` (Findings, line 68) — verifier's mirror-helper flag.

## Metadata

**Confidence breakdown:**
- Coverage map / gap: HIGH — read the exact mirror helper and verifier note.
- Integration-test seam: HIGH — `_run_cycle` signature and wiring read directly.
- Backtest reuse: HIGH — existing data_loader + scan_assets behavior verified.
- Fixture sizing: HIGH — bar-count minimums confirmed against `analyze`/`_adx`.

**Research date:** 2026-06-15
**Valid until:** 2026-07-15 (stable internal code; refresh if signal engine or _run_cycle signature changes)
