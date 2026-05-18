"""Close Bot C orphan equity positions (QQQ, AAPL) — leave BITX (trend strategy)."""
import json, urllib.request, urllib.error

with open(r'C:\Users\artic\.claude\secrets\services.json') as f:
    token = json.load(f)['coolify']['api_token']
req = urllib.request.Request(
    'https://coolify.titaniumlabs.us/api/v1/applications/zkkw8wocws84gg4woc8kcoc4/envs',
    headers={'Authorization': f'Bearer {token}'})
with urllib.request.urlopen(req) as r:
    envs = json.load(r)
ev = {e['key']: e['real_value'] for e in envs}
H = {'APCA-API-KEY-ID': ev['ALPACA_API_KEY_C'], 'APCA-API-SECRET-KEY': ev['ALPACA_SECRET_KEY_C']}
BASE = 'https://paper-api.alpaca.markets'

for sym in ('QQQ', 'AAPL'):
    rq = urllib.request.Request(f'{BASE}/v2/positions/{sym}', headers=H, method='DELETE')
    try:
        with urllib.request.urlopen(rq, timeout=30) as r:
            o = json.load(r)
            print(f"{sym}: close order submitted id={o.get('id')} qty={o.get('qty')} status={o.get('status')}")
    except urllib.error.HTTPError as e:
        print(f"{sym}: ERROR {e.code} {e.read()[:200]}")

# Re-show positions
rq = urllib.request.Request(f'{BASE}/v2/positions', headers=H)
with urllib.request.urlopen(rq, timeout=30) as r:
    pos = json.load(r)
print(f"\nRemaining positions ({len(pos)}):")
for p in pos:
    print(f"  {p['symbol']:8} qty={p['qty']:>12} mv=${float(p['market_value']):.2f} upl=${float(p['unrealized_pl']):+.2f}")
