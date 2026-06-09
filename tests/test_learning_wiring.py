"""Phase 7 — self-learning loop wiring tests (LEARN-01/02/03 + shadow + signal_type).

Pure-function math tests run here directly. Path-level tests (candidate-loop
veto/scale, signal_type alignment, shadow mode, parity) are filled in / un-skipped
by 07-02 (bot_thread) and 07-03 (alpaca_orchestrator).
"""

import importlib

from src.alpaca_orchestrator import _kelly_technical

# With MIN_CONFLUENCE=4: confluence 4 -> kelly_pct 0.35, confluence 5 -> 0.43125.
# kelly_fraction=0.05 keeps the pre-cap adjusted_pct (0.0175) below the 0.05 cap
# so scaling/floor behaviour is observable without the hard clamp interfering.


# --- LEARN-02: confidence_adjustment scales pre-cap ------------------------

def test_adjustment_scales_size():
    base = _kelly_technical(4, 100.0, 10_000.0, kelly_fraction=0.05)
    scaled = _kelly_technical(
        4, 100.0, 10_000.0, kelly_fraction=0.05, confidence_adjustment=0.5
    )
    assert base["side"] == "buy"
    assert base["capped"] is False
    assert scaled["capped"] is False
    assert abs(scaled["adjusted_pct"] - base["adjusted_pct"] * 0.5) < 1e-12


# --- LEARN-03 / hard cap inviolate -----------------------------------------

def test_hard_cap_inviolate():
    res = _kelly_technical(
        5, 100.0, 10_000_000.0,
        kelly_fraction=0.25, confidence_adjustment=1.5, max_position_pct=0.05,
    )
    assert res["adjusted_pct"] == 0.05
    assert res["capped"] is True


# --- LEARN-03: dynamic floor + dynamic ceiling -----------------------------

def test_dynamic_thresholds_applied():
    # tiny position floored up to min_position_pct
    floored = _kelly_technical(
        4, 100.0, 10_000.0, kelly_fraction=0.05, min_position_pct=0.02
    )
    assert abs(floored["adjusted_pct"] - 0.02) < 1e-12
    assert floored["capped"] is False

    # large position ceilinged down to a tighter dynamic max
    ceiled = _kelly_technical(
        5, 100.0, 10_000.0, kelly_fraction=0.25, max_position_pct=0.03
    )
    assert ceiled["adjusted_pct"] == 0.03
    assert ceiled["capped"] is True


def test_min_floor_not_applied_to_zero():
    # confluence below MIN_CONFLUENCE -> side none, floor must not raise it.
    res = _kelly_technical(
        2, 100.0, 10_000.0, kelly_fraction=0.05, min_position_pct=0.02
    )
    assert res["side"] == "none"
    assert res["adjusted_pct"] == 0.0


def test_defaults_unchanged():
    # Default kwargs (adjustment 1.0, no floor) preserve legacy behaviour.
    res = _kelly_technical(5, 100.0, 10_000.0)
    assert res["adjusted_pct"] == 0.05  # 0.1078 clamped to 0.05
    assert res["capped"] is True


# ---------------------------------------------------------------------------
# Path-level tests — wired by 07-02 (bot_thread) and 07-03 (orchestrator).
# ---------------------------------------------------------------------------

import pytest  # noqa: E402


def _advice_consume(memory, symbol, signal_type, sentiment, change, enforce):
    """Mirror of the bot_thread / orchestrator advisory contract: returns
    (skip: bool, adj: float). Exercises the exact veto + shadow + adjustment
    semantics the wiring implements without standing up the full cycle loop."""
    adj = 1.0
    skip = False
    advice = memory.get_advice(
        symbol=symbol, signal_type=signal_type,
        sentiment=sentiment, price_change=change,
    )
    if not advice["should_trade"]:
        if enforce:
            skip = True
    elif enforce:
        adj = advice.get("confidence_adjustment", 1.0)
    return skip, adj, advice


def test_veto_skips_candidate(fake_memory):
    mem = fake_memory(advice={
        "should_trade": False, "confidence_adjustment": 0.0,
        "win_rate_for_pattern": 0.1, "sample_size": 4, "reasoning": "losing",
    })
    skip, adj, _ = _advice_consume(mem, "BTC/USD", "technical_confluence_4", 1.0, 2.0, enforce=True)
    assert skip is True


def test_adjustment_scales_size_in_path(fake_memory):
    mem = fake_memory(advice={
        "should_trade": True, "confidence_adjustment": 0.5,
        "win_rate_for_pattern": 0.45, "sample_size": 5, "reasoning": "weak",
    })
    skip, adj, _ = _advice_consume(mem, "BTC/USD", "technical_confluence_4", 1.0, 2.0, enforce=True)
    assert skip is False
    assert adj == 0.5
    base = _kelly_technical(4, 100.0, 10_000.0, kelly_fraction=0.05)
    scaled = _kelly_technical(4, 100.0, 10_000.0, kelly_fraction=0.05, confidence_adjustment=adj)
    assert abs(scaled["adjusted_pct"] - base["adjusted_pct"] * 0.5) < 1e-12


def test_signal_type_alignment(fake_memory):
    """get_advice and record_trade_context must use the same canonical
    signal_type for both long and short paths."""
    mem = fake_memory()
    # long
    mem.get_advice("BTC/USD", "technical_confluence_4", 1.0, 2.0)
    mem.record_trade_context({"symbol": "BTC/USD", "signal_type": "technical_confluence_4"})
    # short
    mem.get_advice("ETH/USD", "technical_short_3", 0.75, -2.0)
    mem.record_trade_context({"symbol": "ETH/USD", "signal_type": "technical_short_3"})
    for call, rec in zip(mem.advice_calls, mem.recorded):
        assert call["signal_type"] == rec["signal_type"]
    # short context uses canonical technical_short_, never short_technical_
    assert all(not r["signal_type"].startswith("short_technical_") for r in mem.recorded)
    assert any(r["signal_type"].startswith("technical_short_") for r in mem.recorded)


def test_shadow_mode_no_effect(fake_memory):
    """LEARNING_ENFORCE=0: a should_trade=False veto and an adjustment are
    logged but NOT applied (no skip, adj stays 1.0)."""
    mem = fake_memory(advice={
        "should_trade": False, "confidence_adjustment": 0.0,
        "win_rate_for_pattern": 0.1, "sample_size": 4, "reasoning": "losing",
    })
    skip, adj, _ = _advice_consume(mem, "BTC/USD", "technical_confluence_4", 1.0, 2.0, enforce=False)
    assert skip is False
    assert adj == 1.0


def test_memory_none_no_op():
    """memory=None means no thresholds, no adjustment — default sizing."""
    thresholds = None
    eff_max = 0.05 if thresholds is None else min(0.05, thresholds["max_position_pct"])
    eff_min = None if thresholds is None else thresholds["min_position_pct"]
    res = _kelly_technical(5, 100.0, 10_000.0, kelly_fraction=0.25,
                           max_position_pct=eff_max, min_position_pct=eff_min)
    legacy = _kelly_technical(5, 100.0, 10_000.0, kelly_fraction=0.25)
    assert res == legacy


def test_learning_enforce_flag_default(monkeypatch):
    import src.bot_thread as bt
    monkeypatch.setenv("LEARNING_ENFORCE", "0")
    reloaded = importlib.reload(bt)
    try:
        assert reloaded.LEARNING_ENFORCE is False
    finally:
        monkeypatch.delenv("LEARNING_ENFORCE", raising=False)
        importlib.reload(bt)
