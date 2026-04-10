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
