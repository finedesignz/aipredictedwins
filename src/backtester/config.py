"""
PhaseConfig — feature flags for backtester phase comparisons.

Each phase preset represents the cumulative features active at that phase.
"""
from __future__ import annotations
import dataclasses


@dataclasses.dataclass(frozen=True)
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

    # Sizing params
    min_confluence: int = 3
    kelly_fraction: float = 0.25
    max_position_pct: float = 0.05
    starting_equity: float = 100_000.0


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
