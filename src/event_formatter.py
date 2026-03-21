"""
Formats Kalshi market data into seed material for MiroFish simulations.
"""


def format_event(market: dict) -> str:
    """Convert a Kalshi market dict into rich seed text for MiroFish.

    Parameters
    ----------
    market : dict
        Must contain: title, subtitle, category, close_time, event_ticker
        May contain: yes_price, volume
    """
    title = market.get("title", "Unknown Event")
    subtitle = market.get("subtitle", "")
    category = market.get("category", "")
    close_time = market.get("close_time", "Unknown")
    ticker = market.get("ticker", "")
    yes_price = market.get("yes_price", 0)
    volume = market.get("volume", 0)

    # Build the question from subtitle or title
    question = subtitle if subtitle else title

    seed = f"""EVENT: {title}
MARKET: {subtitle}
CATEGORY: {category}
TICKER: {ticker}

CURRENT MARKET PRICING: {yes_price}% probability (YES side)
TRADING VOLUME: ${volume:,} in contracts traded

KEY STAKEHOLDERS:
- Institutional investors and professional traders
- Retail prediction market participants
- Media commentators and analysts
- Policy experts and industry insiders
- General public following the event

PREDICTION QUESTION: {question}

RESOLUTION: This market resolves YES or NO based on the official outcome.
The market closes at: {close_time}

INSTRUCTIONS FOR SIMULATION:
Simulate a diverse population of agents with varying expertise levels,
information access, and cognitive biases. Include both informed experts
and general public participants. Run the simulation to determine the
crowd's converged probability estimate for this event.
"""
    return seed.strip()


def get_event_question(market: dict) -> str:
    """Extract the yes/no question from a market for probability extraction."""
    subtitle = market.get("subtitle", "")
    title = market.get("title", "")
    return subtitle if subtitle else title
