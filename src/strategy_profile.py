"""
StrategyProfile — bundles every parameter that differs between trading styles.

A frozen value object (peer to ``Config``) that records the timeframe, scan
cadence, indicator periods, exit params, max-hold, sizing, and confluence
thresholds for a trading style. Presets are exposed as module constants and via
the ``PROFILES`` registry.

Phase 1 delivered the ``SWING`` preset, whose field values reproduce the
current swing-bot behavior byte-for-byte (PROFILE-02). Phase 2 adds the
``DAYTRADE`` preset (5-min intraday style) and registers it. The orchestrator sources
its style-constant *defaults* from the active profile while the existing
``os.environ.get`` layer continues to win — so bots A/B running with their
current Coolify env produce identical behavior.

This module is pure constants: it reads no environment and imports nothing from
the orchestrator (one-way dependency — the orchestrator imports the profile).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyProfile:
    """Immutable bundle of style-varying trading parameters."""

    name: str
    timeframe: str
    scan_interval_s: int
    bar_count: int
    htf_filter_timeframe: str
    ema_fast: int
    ema_slow: int
    rsi_period: int
    adx_period: int
    atr_period: int
    atr_mult_stop: float
    atr_mult_trail: float
    hard_stop_pct: float
    max_hold_hours: float | None  # None => overnight allowed
    kelly_fraction: float
    max_position_pct: float
    min_confluence: int
    min_short_confluence: int


# SWING reproduces the current swing-bot effective defaults (PROFILE-02 parity).
# atr_mult_* are Phase-4 placeholders, not parity-load-bearing in Phase 1.
SWING = StrategyProfile(
    name="swing",
    timeframe="1Hour",
    scan_interval_s=1800,
    bar_count=50,
    htf_filter_timeframe="4Hour",
    ema_fast=9,
    ema_slow=21,
    rsi_period=14,
    adx_period=14,
    atr_period=14,
    atr_mult_stop=2.0,
    atr_mult_trail=1.5,
    hard_stop_pct=-0.08,
    max_hold_hours=168.0,
    kelly_fraction=0.25,
    max_position_pct=0.05,
    min_confluence=4,
    min_short_confluence=3,
)

# DAYTRADE — 5-min intraday style (PROFILE-03). Same indicator periods as swing
# (now measuring 5-min bars), tighter hard stop, capped 6h hold. atr_mult_* are
# Phase-4 placeholders; periods/atr/max_hold are consumed in Phase 3/4, not here.
DAYTRADE = StrategyProfile(
    name="daytrade",
    timeframe="5Min",
    scan_interval_s=120,
    bar_count=100,
    htf_filter_timeframe="1Hour",
    ema_fast=9,
    ema_slow=21,
    rsi_period=14,
    adx_period=14,
    atr_period=14,
    atr_mult_stop=1.5,
    atr_mult_trail=2.0,
    hard_stop_pct=-0.04,
    max_hold_hours=6.0,
    kelly_fraction=0.25,
    max_position_pct=0.05,
    min_confluence=4,
    min_short_confluence=3,
)

# Registry keyed by name (Phase 2 selects via BOT_PROFILE).
PROFILES = {"swing": SWING, "daytrade": DAYTRADE}
