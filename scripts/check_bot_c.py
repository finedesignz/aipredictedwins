"""Inspect Bot C Alpaca account — find orphan QQQ/AAPL equity positions."""
import json, urllib.request, urllib.error

with open(r'C:\Users\artic\.claude\secrets\services.json') as f:
    token = json.load(f)['coolify']['api_token']

req = urllib.request.Request(
    'https://coolify.titaniumlabs.us/api/v1/applications/zkkw8wocws84gg4woc8kcoc4/envs',
    headers={'Authorization': f'Bearer {token}'})
with urllib.request.urlopen(req) as r:
    envs = json.load(r)

ev = {e['key']: e['real_value'] for e in envs}
print("ALPACA-related env keys present:")
for k in sorted(ev):
    if 'ALPACA' in k:
        print(f"  {k} = {ev[k][:8]}...")

key = ev.get('ALPACA_API_KEY_C')
sec = ev.get('ALPACA_SECRET_KEY_C')
if not key:
    print("\nNo ALPACA_API_KEY_C env — Bot C creds only in bots table.")
    raise SystemExit(0)

H = {'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': sec}
BASE = 'https://paper-api.alpaca.markets'

def aget(path):
    rq = urllib.request.Request(BASE + path, headers=H)
    with urllib.request.urlopen(rq, timeout=30) as r:
        return json.load(r)

acct = aget('/v2/account')
print(f"\nBot C account: equity=${acct['equity']} cash=${acct['cash']} status={acct['status']}")
pos = aget('/v2/positions')
print(f"Positions ({len(pos)}):")
for p in pos:
    print(f"  {p['symbol']:8} qty={p['qty']:>10} side={p['side']:6} "
          f"mv=${float(p['market_value']):.2f} upl=${float(p['unrealized_pl']):+.2f}")
