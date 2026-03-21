"""
Gap detector for MiroFish vs Kalshi price discrepancies.

Compares MiroFish simulation probabilities to live Kalshi market prices
and identifies tradeable opportunities where the swarm intelligence
disagrees with the market by a meaningful margin.

Pure functions — no class, no state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gap Detection
# ---------------------------------------------------------------------------

def detect_gap(
    mirofish_prob: float,
    kalshi_price: float,
    min_gap: float = 0.15,
) -> dict:
    """Compare a MiroFish probability to a Kalshi market price.

    Parameters
    ----------
    mirofish_prob : float
        Probability (0.0-1.0) from MiroFish simulation.
    kalshi_price : float
        Current YES price (0.0-1.0) on Kalshi.
    min_gap : float
        Minimum absolute gap to consider the opportunity tradeable.

    Returns
    -------
    dict
        Signal dict with gap size, direction, tradeability, and confidence.
    """
    gap = mirofish_prob - kalshi_price
    abs_gap = abs(gap)

    # Direction: positive gap means MiroFish thinks YES is underpriced
    direction = "yes" if gap > 0 else "no"

    tradeable = abs_gap >= min_gap

    # Confidence buckets (round to avoid floating-point boundary issues)
    abs_gap_r = round(abs_gap, 4)
    if abs_gap_r > 0.30:
        confidence = "high"
    elif abs_gap_r >= 0.20:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "mirofish_prob": round(mirofish_prob, 4),
        "kalshi_price": round(kalshi_price, 4),
        "gap": round(gap, 4),
        "abs_gap": round(abs_gap, 4),
        "direction": direction,
        "tradeable": tradeable,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Opportunity Filtering & Ranking
# ---------------------------------------------------------------------------

def _days_until_close(market: dict) -> float | None:
    """Return days until market close, or None if unparseable."""
    close_time = market.get("close_time")
    if not close_time:
        return None

    try:
        if isinstance(close_time, str):
            # Handle ISO-8601 strings (with or without trailing Z)
            ct = close_time.replace("Z", "+00:00")
            close_dt = datetime.fromisoformat(ct)
        elif isinstance(close_time, (int, float)):
            close_dt = datetime.fromtimestamp(close_time, tz=timezone.utc)
        else:
            return None

        now = datetime.now(timezone.utc)
        delta = close_dt - now
        return max(delta.total_seconds() / 86400.0, 0.0)
    except (ValueError, TypeError, OSError):
        return None


def _correlated_count(event_ticker: str, open_positions: list[dict]) -> int:
    """Count how many open positions share the same event_ticker."""
    if not open_positions or not event_ticker:
        return 0
    return sum(
        1 for pos in open_positions
        if pos.get("event_ticker") == event_ticker
    )


def filter_opportunities(
    markets_with_signals: list[dict],
    open_positions: list[dict] | None = None,
    max_correlated: int = 3,
) -> list[dict]:
    """Filter and rank market opportunities by quality.

    Parameters
    ----------
    markets_with_signals : list[dict]
        Each element is ``{"market": {...}, "signal": {...}}`` where
        ``market`` matches the shape returned by
        ``KalshiClient.get_active_markets`` and ``signal`` matches the
        shape returned by ``detect_gap``.
    open_positions : list[dict] | None
        Currently open positions. Each dict should contain at least
        ``event_ticker`` for correlation checking.
    max_correlated : int
        Maximum number of positions allowed for the same event_ticker
        before skipping new entries.

    Returns
    -------
    list[dict]
        Filtered and ranked list (best opportunities first).
    """
    open_positions = open_positions or []
    candidates: list[dict] = []

    for entry in markets_with_signals:
        market = entry.get("market", {})
        signal = entry.get("signal", {})

        # --- Gate 1: must be tradeable ---
        if not signal.get("tradeable", False):
            continue

        # --- Gate 2: correlation limit ---
        event_ticker = market.get("event_ticker", "")
        if _correlated_count(event_ticker, open_positions) >= max_correlated:
            log.debug(
                "Skipping %s — already %d correlated positions for %s",
                market.get("ticker", "?"),
                max_correlated,
                event_ticker,
            )
            continue

        # --- Compute ranking score ---
        abs_gap = signal.get("abs_gap", 0.0)
        volume = market.get("volume", 0)
        days = _days_until_close(market)

        # Volume bonus: normalized log-ish boost (0.0 - 1.0 range)
        # Markets with 100k+ volume get full bonus
        volume_score = min(volume / 100_000, 1.0) if volume else 0.0

        # Resolution window preference: 1-14 days is ideal
        if days is not None and 1.0 <= days <= 14.0:
            window_score = 1.0
        elif days is not None and 14.0 < days <= 30.0:
            window_score = 0.5
        else:
            # Too short (<1 day), too long (>30 days), or unknown
            window_score = 0.2

        # Composite score: gap dominates, volume and window are tiebreakers
        score = (abs_gap * 10.0) + (volume_score * 1.0) + (window_score * 0.5)

        candidates.append({
            **entry,
            "_score": round(score, 4),
            "_days_to_close": round(days, 2) if days is not None else None,
        })

    # Sort by composite score descending
    candidates.sort(key=lambda c: c["_score"], reverse=True)

    log.info(
        "Filtered %d opportunities from %d markets",
        len(candidates),
        len(markets_with_signals),
    )

    return candidates
