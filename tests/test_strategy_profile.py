"""Parity tests for StrategyProfile / SWING preset (PROFILE-01, PROFILE-02)."""

import dataclasses
import importlib

import pytest

from src.strategy_profile import SWING, DAYTRADE, PROFILES


def test_daytrade_values_match_spec():
    """PROFILE-03: DAYTRADE field values equal the design spec (D-01..D-03)."""
    assert DAYTRADE.name == "daytrade"
    assert DAYTRADE.timeframe == "5Min"
    assert DAYTRADE.scan_interval_s == 120
    assert DAYTRADE.bar_count == 100
    assert DAYTRADE.htf_filter_timeframe == "1Hour"
    assert (DAYTRADE.ema_fast, DAYTRADE.ema_slow) == (9, 21)
    assert DAYTRADE.rsi_period == 14 and DAYTRADE.adx_period == 14
    assert DAYTRADE.atr_period == 14
    assert DAYTRADE.atr_mult_stop == 1.5
    assert DAYTRADE.atr_mult_trail == 2.0
    assert DAYTRADE.hard_stop_pct == -0.04
    assert DAYTRADE.max_hold_hours == 6.0
    assert DAYTRADE.kelly_fraction == 0.25
    assert DAYTRADE.max_position_pct == 0.05
    assert DAYTRADE.min_confluence == 4 and DAYTRADE.min_short_confluence == 3


def test_profiles_registry_keys():
    """PROFILE-03/D-04: PROFILES has exactly swing + daytrade."""
    assert set(PROFILES) == {"swing", "daytrade"}
    assert PROFILES["daytrade"] is DAYTRADE


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


def _reload_orchestrator():
    import src.alpaca_orchestrator as o

    return importlib.reload(o)


def test_bot_profile_selects_daytrade(monkeypatch):
    """PROFILE-04: BOT_PROFILE=daytrade selects the DAYTRADE preset."""
    monkeypatch.setenv("BOT_PROFILE", "daytrade")
    o = _reload_orchestrator()
    try:
        assert o.PROFILE.name == "daytrade"
        assert o.PROFILE is DAYTRADE
    finally:
        monkeypatch.delenv("BOT_PROFILE", raising=False)
        _reload_orchestrator()


def test_bot_profile_swing_and_unset_resolve_swing(monkeypatch):
    """PROFILE-04 parity: explicit swing and unset both resolve to SWING."""
    monkeypatch.setenv("BOT_PROFILE", "swing")
    o = _reload_orchestrator()
    assert o.PROFILE is SWING
    monkeypatch.delenv("BOT_PROFILE", raising=False)
    o = _reload_orchestrator()
    assert o.PROFILE is SWING


def test_bot_profile_case_insensitive(monkeypatch):
    """PROFILE-04: selection is case-insensitive (DAYTRADE resolves)."""
    monkeypatch.setenv("BOT_PROFILE", "DAYTRADE")
    o = _reload_orchestrator()
    try:
        assert o.PROFILE.name == "daytrade"
    finally:
        monkeypatch.delenv("BOT_PROFILE", raising=False)
        _reload_orchestrator()


def test_bot_profile_unknown_raises(monkeypatch):
    """T-02-01: unknown BOT_PROFILE fails fast with ValueError."""
    monkeypatch.setenv("BOT_PROFILE", "scalp")
    try:
        with pytest.raises(ValueError):
            _reload_orchestrator()
    finally:
        monkeypatch.delenv("BOT_PROFILE", raising=False)
        _reload_orchestrator()


def test_daytrade_import_does_not_crash(monkeypatch):
    """Smoke: selecting daytrade imports cleanly (no startup crash)."""
    monkeypatch.setenv("BOT_PROFILE", "daytrade")
    try:
        o = _reload_orchestrator()
        assert o.PROFILE.name == "daytrade"
    finally:
        monkeypatch.delenv("BOT_PROFILE", raising=False)
        _reload_orchestrator()


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
