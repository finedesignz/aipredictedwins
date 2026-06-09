"""Parity tests for StrategyProfile / SWING preset (PROFILE-01, PROFILE-02)."""

import dataclasses
import importlib

import pytest

from src.strategy_profile import SWING, PROFILES


def test_swing_values_match_current_constants():
    """PROFILE-02: SWING field values equal today's effective constants."""
    assert SWING.timeframe == "1Hour"
    assert SWING.scan_interval_s == 1800
    assert SWING.bar_count == 50
    assert SWING.htf_filter_timeframe == "4Hour"
    assert (SWING.ema_fast, SWING.ema_slow) == (9, 21)
    assert SWING.rsi_period == 14 and SWING.adx_period == 14
    assert SWING.hard_stop_pct == -0.15
    assert SWING.max_hold_hours is None
    assert SWING.kelly_fraction == 0.25
    assert SWING.max_position_pct == 0.05
    assert SWING.min_confluence == 4 and SWING.min_short_confluence == 3


def test_profile_is_frozen():
    """PROFILE-01: profile is immutable — assigning a field raises."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        SWING.min_confluence = 2  # type: ignore[misc]


def test_profiles_registry():
    """PROFILE-01: PROFILES['swing'] resolves to the SWING preset."""
    assert PROFILES["swing"] is SWING


def test_env_override_wins_over_profile_default(monkeypatch):
    """PROFILE-02 / D-05: env override beats the profile default (env still wins)."""
    monkeypatch.setenv("MIN_CONFLUENCE", "2")
    import src.alpaca_orchestrator as o

    importlib.reload(o)
    try:
        assert o.MIN_CONFLUENCE == 2  # env beats profile default of 4
    finally:
        # Restore module to its env-free state for other tests.
        monkeypatch.delenv("MIN_CONFLUENCE", raising=False)
        importlib.reload(o)
