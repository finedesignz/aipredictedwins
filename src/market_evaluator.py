"""
Market evaluator — ranks Kalshi markets by MiroFish simulation fit.

Categorizes markets into tiers based on how well swarm intelligence
can predict their outcomes, then scores and ranks them for simulation.
"""

import re
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# ── Tier Classification Keywords ─────────────────────────────────────

# Tier 1: Strong MiroFish fit — sentiment-driven, crowd behavior
TIER1_KEYWORDS = [
    "federal reserve", "fomc", "rate cut", "rate hike", "interest rate",
    "election", "presidential", "governor", "senate", "congress", "vote",
    "geopolitical", "war", "invasion", "sanction", "treaty", "ceasefire",
    "tariff", "trade war", "policy", "legislation", "bill pass",
    "impeach", "resign", "cabinet", "supreme court", "nomination",
    "pope", "nato", "un resolution", "diplomat",
]

# Tier 2: Moderate fit — partially sentiment-driven
TIER2_KEYWORDS = [
    "cpi", "inflation", "unemployment", "gdp", "jobs report", "economic",
    "tech", "ai", "launch", "ipo", "merger", "acquisition", "earnings",
    "apple", "google", "tesla", "spacex", "openai", "microsoft",
    "oscar", "emmy", "grammy", "award", "viral", "trending",
    "bitcoin", "crypto", "ethereum", "price above", "price below",
    "greenland", "territory", "colonize", "mars",
]

# Tier 3: Weak fit — physics/stats driven (deprioritize)
TIER3_KEYWORDS = [
    "weather", "temperature", "hurricane", "earthquake", "rainfall",
    "sports", "nfl", "nba", "mlb", "nhl", "soccer", "touchdown",
    "batting", "rushing yards", "points scored",
]


def classify_tier(title: str, subtitle: str = "", category: str = "") -> int:
    """Classify a market into tier 1, 2, or 3 based on keywords.

    Returns 1 (best fit), 2 (moderate), or 3 (weak fit).
    """
    text = f"{title} {subtitle} {category}".lower()

    for kw in TIER3_KEYWORDS:
        if kw in text:
            return 3

    for kw in TIER1_KEYWORDS:
        if kw in text:
            return 1

    for kw in TIER2_KEYWORDS:
        if kw in text:
            return 2

    # Default: tier 2 (unknown = moderate fit)
    return 2


def score_market(market: dict) -> dict:
    """Score a market for simulation priority.

    Returns the market dict with added fields:
        tier, score, days_to_close, evaluation
    """
    title = market.get("title", "")
    subtitle = market.get("subtitle", "")
    category = market.get("category", "")
    volume = market.get("volume", 0)
    yes_price = market.get("yes_price", 0.5)
    close_time = market.get("close_time", "")

    tier = classify_tier(title, subtitle, category)

    # Days to close
    days = _days_until_close(close_time)

    # Score components (higher = better for simulation)
    tier_score = {1: 100, 2: 60, 3: 20}[tier]

    # Volume score: log scale, capped at 30 points
    import math
    vol_score = min(30, math.log10(max(volume, 1)) * 5)

    # Price uncertainty score: markets near 50% are most interesting
    # (most room for MiroFish to disagree with the market)
    uncertainty = 1.0 - abs(yes_price - 0.50) * 2  # 1.0 at 50%, 0.0 at 0% or 100%
    uncertainty_score = uncertainty * 25

    # Time preference: strongly favor near-term for faster capital realization
    if days is None:
        time_score = 0
    elif 1 <= days <= 7:
        time_score = 40     # this week — best
    elif 7 < days <= 14:
        time_score = 35     # next week — great
    elif 14 < days <= 30:
        time_score = 25     # this month — good
    elif 30 < days <= 60:
        time_score = 10     # 1-2 months — acceptable
    else:
        time_score = -50    # 60+ days — heavily penalize, capital lockup

    total_score = tier_score + vol_score + uncertainty_score + time_score

    # Human-readable evaluation
    tier_labels = {1: "Strong fit", 2: "Moderate fit", 3: "Weak fit"}
    evaluation = (
        f"Tier {tier} ({tier_labels[tier]}) | "
        f"Vol=${volume:,.0f} | "
        f"Price={yes_price:.0%} | "
        f"{'~'+str(days)+'d' if days else '?d'} to close | "
        f"Score={total_score:.0f}"
    )

    return {
        **market,
        "tier": tier,
        "score": total_score,
        "days_to_close": days,
        "evaluation": evaluation,
    }


def evaluate_markets(markets: list[dict], max_results: int = 20) -> list[dict]:
    """Score and rank all markets, return the top candidates for simulation.

    Filters out:
    - Tier 3 markets (weak MiroFish fit)
    - Markets with YES price < 5% or > 95% (already near certainty)
    - Markets closing in < 12 hours

    Returns sorted by score descending.
    """
    scored = []
    for m in markets:
        s = score_market(m)

        # Filter out weak fits
        if s["tier"] == 3:
            continue

        # Filter near-certain markets (no edge possible)
        price = s.get("yes_price", 0.5)
        if price < 0.05 or price > 0.95:
            continue

        # Filter by time horizon — skip < 6h only (no upper cap)
        # Long-dated markets are fine — we can sell positions early when gaps narrow
        days = s.get("days_to_close")
        if days is not None and days < 0.25:
            continue

        scored.append(s)

    # Sort by score descending
    scored.sort(key=lambda m: m["score"], reverse=True)

    return scored[:max_results]


def print_evaluation(markets: list[dict]):
    """Pretty-print market evaluation results."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="Market Evaluation — MiroFish Fit Ranking")
    table.add_column("#", style="dim", width=3)
    table.add_column("Tier", width=4)
    table.add_column("Score", width=5)
    table.add_column("Ticker", style="cyan", width=30)
    table.add_column("Event", max_width=40)
    table.add_column("YES Price", width=9)
    table.add_column("Volume", width=12)
    table.add_column("Close", width=8)

    tier_colors = {1: "green", 2: "yellow", 3: "red"}

    for i, m in enumerate(markets, 1):
        tier = m["tier"]
        days = m.get("days_to_close")
        close_str = f"{days:.0f}d" if days else "?"
        table.add_row(
            str(i),
            f"[{tier_colors[tier]}]T{tier}[/{tier_colors[tier]}]",
            f"{m['score']:.0f}",
            m["ticker"][:30],
            m["title"][:40],
            f"${m['yes_price']:.2f}",
            f"${m['volume']:,.0f}",
            close_str,
        )

    console.print(table)


def _days_until_close(close_time) -> float | None:
    """Parse close_time and return days until close."""
    if not close_time:
        return None
    try:
        if isinstance(close_time, (int, float)):
            close_dt = datetime.fromtimestamp(close_time, tz=timezone.utc)
        else:
            # ISO format string
            close_str = str(close_time).replace("Z", "+00:00")
            close_dt = datetime.fromisoformat(close_str)
        now = datetime.now(timezone.utc)
        delta = close_dt - now
        return max(0, delta.total_seconds() / 86400)
    except (ValueError, OSError):
        return None
