"""
Kelly Criterion position sizing for Kalshi event contract trading.

Uses fractional Kelly to determine optimal position sizes given
MiroFish probability estimates vs. current Kalshi market prices.
"""


def kelly_size(
    win_prob: float,
    kalshi_price: float,
    bankroll: float,
    kelly_fraction: float = 0.25,
    max_position_pct: float = 0.05,
) -> dict:
    """
    Calculate position size using fractional Kelly Criterion.

    Args:
        win_prob: MiroFish's estimated probability (0.0-1.0).
        kalshi_price: Current Kalshi YES price as probability (0.0-1.0).
        bankroll: Current available balance in dollars.
        kelly_fraction: Fraction of full Kelly to use (0.25 = quarter Kelly).
        max_position_pct: Maximum position as fraction of bankroll (0.05 = 5%).

    Returns:
        dict with keys: side, kelly_pct, adjusted_pct, dollar_amount,
        contracts, price_cents, capped.
    """
    # Guard: no edge when model agrees with the market
    if win_prob == kalshi_price:
        return {
            "side": "none",
            "kelly_pct": 0.0,
            "adjusted_pct": 0.0,
            "dollar_amount": 0.0,
            "contracts": 0,
            "price_cents": 0,
            "capped": False,
        }

    if win_prob > kalshi_price:
        # Model thinks YES is underpriced -- buy YES
        side = "yes"
        b = (1.0 - kalshi_price) / kalshi_price  # payout odds
        p = win_prob
        price_per_contract = kalshi_price
    else:
        # Model thinks YES is overpriced -- buy NO
        side = "no"
        b = kalshi_price / (1.0 - kalshi_price)  # payout odds
        p = 1.0 - win_prob
        price_per_contract = 1.0 - kalshi_price

    q = 1.0 - p
    kelly_pct = max(0.0, (b * p - q) / b)

    adjusted_pct = kelly_pct * kelly_fraction

    capped = adjusted_pct > max_position_pct
    if capped:
        adjusted_pct = max_position_pct

    dollar_amount = bankroll * adjusted_pct
    contracts = int(dollar_amount / price_per_contract)
    price_cents = round(price_per_contract * 100)

    return {
        "side": side,
        "kelly_pct": kelly_pct,
        "adjusted_pct": adjusted_pct,
        "dollar_amount": dollar_amount,
        "contracts": contracts,
        "price_cents": price_cents,
        "capped": capped,
    }
