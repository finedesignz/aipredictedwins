"""
Evaluates stocks and crypto for MiroFish simulation candidacy.

Scores assets based on sentiment-driven price behavior (crypto and meme stocks
score highest), formats seed material for MiroFish swarm simulations, and
generates yes/no probability questions for the simulation pipeline.
"""

import logging
from datetime import datetime, timezone

from src.alpaca_client import AlpacaClient

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Top tickers to scan when screener data is unavailable
# ---------------------------------------------------------------------------
TOP_STOCK_TICKERS = [
    "AAPL", "TSLA", "NVDA", "META", "AMZN",
    "GOOGL", "MSFT", "AMD", "COIN", "MSTR",
]

TOP_CRYPTO_TICKERS = [
    "BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD",
    "LINK/USD", "DOT/USD", "SHIB/USD", "PEPE/USD", "XRP/USD",
]

# ---------------------------------------------------------------------------
# Sentiment/simulation fitness tiers
# ---------------------------------------------------------------------------
# Assets driven by crowd sentiment are best suited for MiroFish swarm sims.
# Meme stocks and crypto rank highest; blue chips rank lowest.
MEME_STOCKS = {"TSLA", "COIN", "MSTR", "GME", "AMC", "PLTR", "RIVN", "SOFI"}
MEME_CRYPTO = {"DOGE/USD", "SHIB/USD", "PEPE/USD", "BONK/USD", "WIF/USD", "FLOKI/USD"}

TIER_SCORES = {
    "S": 95,  # Meme crypto — pure sentiment
    "A": 85,  # Other crypto — high sentiment component
    "B": 75,  # Meme stocks — retail-driven
    "C": 60,  # High-beta tech stocks
    "D": 40,  # Blue-chip / low-vol stocks
}


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def get_trending_crypto(client: AlpacaClient, top_n: int = 10) -> list[dict]:
    """Get the most volatile/active crypto in the last 24h.

    Returns sorted by 24h volume descending.  Each dict contains:
        symbol, price, change_pct_24h, volume_24h
    """
    results = []
    for symbol in TOP_CRYPTO_TICKERS:
        try:
            price = client.get_latest_price(symbol)
            bars = client.get_bars(symbol, timeframe="1Hour", limit=24)
            if not bars:
                continue

            volume_24h = sum(b["volume"] for b in bars)
            open_24h = bars[0]["open"]
            change_pct = ((price - open_24h) / open_24h * 100) if open_24h > 0 else 0.0

            results.append({
                "symbol": symbol,
                "price": price,
                "change_pct_24h": round(change_pct, 2),
                "volume_24h": volume_24h,
                "high_24h": max(b["high"] for b in bars),
                "low_24h": min(b["low"] for b in bars),
            })
        except Exception as exc:
            log.warning("Failed to fetch crypto data for %s: %s", symbol, exc)
            continue

    results.sort(key=lambda x: x["volume_24h"], reverse=True)
    log.info("Trending crypto: %d assets evaluated, returning top %d", len(results), top_n)
    return results[:top_n]


def get_trending_stocks(client: AlpacaClient, top_n: int = 10) -> list[dict]:
    """Get most active stocks by recent volume.

    Scans TOP_STOCK_TICKERS, fetches 1-day bars, and returns sorted by volume.
    Each dict contains: symbol, price, change_pct_24h, volume_24h
    """
    results = []
    for symbol in TOP_STOCK_TICKERS:
        try:
            price = client.get_latest_price(symbol)
            bars = client.get_bars(symbol, timeframe="1Day", limit=2)
            if not bars:
                continue

            latest_bar = bars[-1]
            prev_close = bars[-2]["close"] if len(bars) >= 2 else latest_bar["open"]
            change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

            results.append({
                "symbol": symbol,
                "price": price,
                "change_pct_24h": round(change_pct, 2),
                "volume_24h": latest_bar["volume"],
                "high_24h": latest_bar["high"],
                "low_24h": latest_bar["low"],
            })
        except Exception as exc:
            log.warning("Failed to fetch stock data for %s: %s", symbol, exc)
            continue

    results.sort(key=lambda x: x["volume_24h"], reverse=True)
    log.info("Trending stocks: %d assets evaluated, returning top %d", len(results), top_n)
    return results[:top_n]


def evaluate_for_simulation(assets: list[dict]) -> list[dict]:
    """Score each asset for MiroFish simulation fitness.

    Assets driven by crowd sentiment score highest because MiroFish swarm
    intelligence excels at modeling collective behavior.

    Adds to each asset dict:
        score (0-100), tier (S/A/B/C/D), evaluation (str reason)
    """
    scored = []
    for asset in assets:
        symbol = asset["symbol"]
        is_crypto = "/" in symbol

        # Determine tier
        if symbol in MEME_CRYPTO:
            tier = "S"
            evaluation = "Meme crypto — pure sentiment-driven, ideal for swarm simulation"
        elif is_crypto:
            tier = "A"
            evaluation = "Crypto asset — high sentiment component, strong swarm sim candidate"
        elif symbol in MEME_STOCKS:
            tier = "B"
            evaluation = "Meme/retail-driven stock — sentiment-heavy, good swarm sim candidate"
        elif symbol in {"NVDA", "AMD", "COIN", "MSTR"}:
            tier = "C"
            evaluation = "High-beta tech — moderate sentiment influence, decent sim candidate"
        else:
            tier = "D"
            evaluation = "Blue-chip stock — fundamentals-driven, lower swarm sim accuracy"

        base_score = TIER_SCORES[tier]

        # Bonus for volatility (higher absolute change = more interesting)
        vol_bonus = min(abs(asset.get("change_pct_24h", 0)) * 1.5, 10)

        # Bonus for high volume (market attention)
        volume = asset.get("volume_24h", 0)
        vol_threshold = 1_000_000 if is_crypto else 50_000_000
        volume_bonus = min((volume / vol_threshold) * 5, 5) if vol_threshold > 0 else 0

        final_score = min(round(base_score + vol_bonus + volume_bonus, 1), 100)

        scored_asset = {**asset}
        scored_asset["score"] = final_score
        scored_asset["tier"] = tier
        scored_asset["evaluation"] = evaluation
        scored.append(scored_asset)

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def format_asset_seed(asset: dict, bars: list[dict]) -> str:
    """Format an asset and its recent bars into seed material for MiroFish.

    Similar to event_formatter.format_event() but tailored for price predictions.
    """
    symbol = asset["symbol"]
    price = asset.get("price", 0)
    change_pct = asset.get("change_pct_24h", 0)
    volume = asset.get("volume_24h", 0)
    is_crypto = "/" in symbol

    asset_type = "Cryptocurrency" if is_crypto else "Stock"
    base_name = symbol.replace("/USD", "") if is_crypto else symbol

    # Build price history summary from bars
    price_history = ""
    if bars:
        recent = bars[-min(10, len(bars)):]
        price_points = [f"  {b['timestamp'][:16]}: O={b['open']:.2f} H={b['high']:.2f} L={b['low']:.2f} C={b['close']:.2f} V={b['volume']:,.0f}" for b in recent]
        price_history = "\n".join(price_points)

        # Calculate trend
        if len(bars) >= 2:
            first_close = bars[0]["close"]
            last_close = bars[-1]["close"]
            trend_pct = ((last_close - first_close) / first_close * 100) if first_close > 0 else 0
            trend_dir = "UPTREND" if trend_pct > 1 else "DOWNTREND" if trend_pct < -1 else "SIDEWAYS"
        else:
            trend_dir = "INSUFFICIENT DATA"
            trend_pct = 0
    else:
        trend_dir = "NO DATA"
        trend_pct = 0

    direction_emoji = "rising" if change_pct > 0 else "falling" if change_pct < 0 else "flat"

    seed = f"""ASSET: {base_name} ({asset_type})
SYMBOL: {symbol}
CURRENT PRICE: ${price:,.2f}
24H CHANGE: {change_pct:+.2f}% ({direction_emoji})
24H VOLUME: {volume:,.0f}
TREND: {trend_dir} ({trend_pct:+.1f}% over period)

RECENT PRICE HISTORY:
{price_history if price_history else "  No recent bar data available."}

KEY MARKET PARTICIPANTS:
- Institutional algorithmic traders
- Retail day traders and swing traders
- Market makers providing liquidity
- {"Crypto whales and DeFi protocols" if is_crypto else "Hedge funds and mutual funds"}
- Social media-driven retail sentiment

MARKET CONTEXT:
- {"24/7 crypto market with global participation" if is_crypto else "US equity market with regular trading hours"}
- {"High leverage and liquidation cascades common" if is_crypto else "Options flow and dark pool activity influence price"}
- Current momentum is {direction_emoji} with {"high" if abs(change_pct) > 3 else "moderate" if abs(change_pct) > 1 else "low"} volatility

INSTRUCTIONS FOR SIMULATION:
Simulate a diverse population of agents: institutional traders with quantitative models,
retail traders following social media sentiment, market makers adjusting spreads,
and contrarian value investors. Include both momentum followers and mean-reversion
traders. Run the simulation to determine the crowd's converged probability estimate
for the price target question below.
"""
    return seed.strip()


def get_asset_question(asset: dict, timeframe: str = "24h") -> str:
    """Generate a yes/no question for probability extraction.

    E.g. "Will BTC/USD close above $98,000 in the next 24 hours?"

    The threshold is set slightly above the current price for a directional bet.
    """
    symbol = asset["symbol"]
    price = asset.get("price", 0)
    change_pct = asset.get("change_pct_24h", 0)

    # Set threshold based on current momentum
    # If trending up, ask about continuation above a level
    # If trending down, ask about recovery above current price
    if change_pct > 0:
        # Bullish momentum: will it continue higher?
        threshold = price * 1.01  # 1% above current
    else:
        # Bearish or flat: will it hold / recover above current?
        threshold = price * 0.995  # just below current (slight edge for recovery)

    # Format threshold nicely
    if price >= 1000:
        threshold_str = f"${threshold:,.0f}"
    elif price >= 1:
        threshold_str = f"${threshold:,.2f}"
    else:
        threshold_str = f"${threshold:.4f}"

    timeframe_labels = {
        "1h": "the next 1 hour",
        "4h": "the next 4 hours",
        "24h": "the next 24 hours",
        "1d": "the next trading day",
        "1w": "the next 7 days",
    }
    tf_label = timeframe_labels.get(timeframe, f"the next {timeframe}")

    return f"Will {symbol} close above {threshold_str} in {tf_label}?"
