"""Check current positions and recent orders from Alpaca for both bots."""
import urllib.request, json

PAPER_BASE = "https://paper-api.alpaca.markets"

BOTS = {
    "A": ("PKIZ5BFZLCF5DUCEW3EZCUWJYH", "9FwBnPA9fJNx5EwTKEJo6Wi8GkCTiYrEtnQKAgyXZiZi"),
    "B": ("PKVKN5V5L43SRNASWIRXPYMUQO", "sj31s7qkLzV7AnTaJdPajDZfWP36qEdUpvskXJtC8zA"),
}

def get(bot, path):
    key, secret = BOTS[bot]
    req = urllib.request.Request(
        f"{PAPER_BASE}{path}",
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)

for bot in ("A", "B"):
    print(f"\n{'='*50}")
    print(f"BOT {bot}")
    print('='*50)

    # Account
    acct = get(bot, "/v2/account")
    print(f"Equity: ${float(acct['equity']):,.2f}  Cash: ${float(acct['cash']):,.2f}  Buying Power: ${float(acct['buying_power']):,.2f}")

    # Positions
    positions = get(bot, "/v2/positions")
    if positions:
        print(f"\nOpen positions ({len(positions)}):")
        for p in positions:
            pnl = float(p['unrealized_pl'])
            pnl_pct = float(p['unrealized_plpc']) * 100
            print(f"  {p['symbol']:<12} {p['side']:<5} qty={float(p['qty']):.4f}  entry=${float(p['avg_entry_price']):.2f}  now=${float(p['current_price']):.2f}  PnL=${pnl:+.2f} ({pnl_pct:+.1f}%)")
    else:
        print("\nNo open positions")

    # Recent orders (last 10)
    orders = get(bot, "/v2/orders?status=all&limit=10&direction=desc")
    print(f"\nRecent orders ({len(orders)}):")
    for o in orders[:10]:
        filled = o.get('filled_at','')[:16] if o.get('filled_at') else o.get('submitted_at','')[:16]
        qty = o.get('filled_qty') or o.get('qty', '?')
        price = o.get('filled_avg_price') or o.get('limit_price') or '-'
        price_str = f"${float(price):.2f}" if price != '-' else '-'
        print(f"  {o['symbol']:<12} {o['side']:<5} {o['type']:<8} qty={float(qty):.4f}  {price_str:<10} status={o['status']:<12} {filled}")
