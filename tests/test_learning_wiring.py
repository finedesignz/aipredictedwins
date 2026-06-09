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


@pytest.mark.skip(reason="wired in 07-02/07-03")
def test_veto_skips_candidate():
    ...


@pytest.mark.skip(reason="wired in 07-02/07-03")
def test_adjustment_scales_size_in_path():
    ...


@pytest.mark.skip(reason="wired in 07-02/07-03")
def test_signal_type_alignment():
    ...


@pytest.mark.skip(reason="wired in 07-02/07-03")
def test_shadow_mode_no_effect():
    ...
